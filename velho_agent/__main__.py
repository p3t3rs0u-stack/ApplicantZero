import argparse
import sys

from . import db, pipeline
from .config import load_config


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="velho_agent", description="Velhon asiakashankinta-agentti")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("hae", help="hae uudet ilmoitukset Duunitorista")
    sub.add_parser("arvioi", help="arvioi uudet ilmoitukset Claudella")
    sub.add_parser("aja", help="hae + arvioi (ajastettava)")
    lista = sub.add_parser("lista", help="näytä ilmoitukset")
    lista.add_argument("--tila", choices=list(db.STATUSES))
    kirjoita = sub.add_parser("kirjoita", help="kirjoita hakemus ilmoitukseen")
    kirjoita.add_argument("id", type=int)
    tayta = sub.add_parser("tayta", help="avaa hakemuslomakkeet ja esitäytä (useampi id = useampi välilehti)")
    tayta.add_argument("id", type=int, nargs="+")
    web = sub.add_parser("web", help="käynnistä hyväksyntänäkymä")
    web.add_argument("--port", type=int, default=5050)
    args = parser.parse_args()

    cfg = load_config()
    if args.cmd in ("hae", "aja"):
        print(f"Uusia ilmoituksia: {pipeline.search(cfg)}")
    if args.cmd in ("arvioi", "aja"):
        print(f"Arvioitu: {pipeline.analyze_new(cfg)}")
    if args.cmd == "aja":
        input("\nValmis. Paina Enter sulkeaksesi.") if sys.stdin.isatty() else None
    elif args.cmd == "lista":
        for j in db.list_jobs(db.connect(), args.tila):
            score = j["score"] if j["score"] is not None else "–"
            print(f"#{j['id']:<4} {score:>3}  {db.STATUSES[j['status']]:<22} {j['title']} – {j['company']}")
    elif args.cmd == "kirjoita":
        job = pipeline.draft(args.id, cfg)
        print(job["application"]["saate"])
        print(f"\nLiite: {job['pdf_path']}")
    elif args.cmd == "tayta":
        from .filler import open_and_prefill
        open_and_prefill(args.id)
    elif args.cmd == "web":
        from .web import serve
        serve(args.port)


if __name__ == "__main__":
    main()
