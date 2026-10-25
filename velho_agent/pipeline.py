"""Haku → arviointi → hakemusluonnos."""

from concurrent.futures import ThreadPoolExecutor, as_completed

from . import db, llm
from .duunitori import Blocked, DuunitoriClient
from .pdf import build_proposal_pdf


def search(cfg: dict, log=print) -> int:
    opts = cfg.get("duunitori") or {}
    pages = opts.get("sivuja_per_haku", 2)
    limit = opts.get("max_uusia_per_ajo", 100)
    dt = DuunitoriClient(delay_s=opts.get("viive_s", 10))
    conn = db.connect()
    new = 0
    try:
        for term in cfg["hakusanat"]:
            for page in range(1, pages + 1):
                results = dt.search(term, page)
                log(f"'{term}' sivu {page}: {len(results)} ilmoitusta")
                for r in results:
                    if db.exists(conn, r["ext_id"]):
                        continue
                    details = dt.fetch_job(r["url"])
                    # Hakutuloksen otsikko ja yritys ovat tarkempia kuin JSON-LD:n
                    job = {**{k: v for k, v in details.items() if v},
                           **{k: v for k, v in r.items() if v}, "search_term": term}
                    job.setdefault("location", None)
                    for key in ("posted", "valid_through", "description", "apply_url"):
                        job.setdefault(key, None)
                    if not db.insert_job(conn, job):
                        continue
                    new += 1
                    log(f"  + {job['title']} – {job.get('company')}")
                    if new >= limit:
                        log(f"Uusien ilmoitusten yläraja ({limit}) täynnä.")
                        return new
                if len(results) < 20:
                    break
    except Blocked as e:
        log(str(e))
    return new


def analyze_new(cfg: dict, log=print, workers: int = 5) -> int:
    conn = db.connect()
    min_score = cfg.get("min_pisteet", 55)
    count = 0
    jobs = db.list_jobs(conn, "uusi")
    log(f"Arvioidaan {len(jobs)} ilmoitusta…")

    def run(job):
        try:
            return job, llm.analyze(job), None
        except Exception as e:  # yksi epäonnistuminen ei kaada koko ajoa
            return job, None, e

    # Claude-kutsut rinnakkain, tietokantakirjoitukset pääsäikeessä
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = [pool.submit(run, job) for job in jobs]
        for future in as_completed(results):
            job, analysis, error = future.result()
            if error:
                log(f"  ! #{job['id']} arviointi epäonnistui: {error}")
                continue
            status = "arvioitu" if analysis["sopii"] and analysis["pisteet"] >= min_score else "ei_sovi"
            db.update(conn, job["id"], analysis=analysis, score=analysis["pisteet"], status=status)
            count += 1
            log(f"  {analysis['pisteet']:3d} p  {job['title']} – {job['company']}  → {db.STATUSES[status]}")
    return count


def draft(job_id: int, cfg: dict) -> dict:
    conn = db.connect()
    job = db.get(conn, job_id)
    if not job["analysis"]:
        job["analysis"] = llm.analyze(job)
        db.update(conn, job_id, analysis=job["analysis"], score=job["analysis"]["pisteet"])
    application = llm.write_application(job, job["analysis"], cfg)
    pdf_path = build_proposal_pdf(job, job["analysis"], application, cfg)
    db.update(conn, job_id, application=application, pdf_path=str(pdf_path), status="luonnos")
    return db.get(conn, job_id)


def rebuild_pdf(job_id: int, cfg: dict) -> None:
    conn = db.connect()
    job = db.get(conn, job_id)
    pdf_path = build_proposal_pdf(job, job["analysis"], job["application"], cfg)
    db.update(conn, job_id, pdf_path=str(pdf_path))
