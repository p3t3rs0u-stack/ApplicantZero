"""Avaa hakemuslomakkeet näkyvään selaimeen omille välilehdilleen ja esitäyttää ne. Ei koskaan lähetä.

Ihminen kirjautuu tarvittaessa itse, hyväksyy evästeet/ehdot itse ja painaa Lähetä.
"""

import queue
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import Frame, sync_playwright

from . import db, llm, pipeline
from .config import BROWSER_PROFILE, ROOT, load_config, missing_applicant_fields

# Kerää näkyvät lomakekentät kaikista kehyksistä ja merkitsee ne data-velho-idx:llä
COLLECT_JS = """
(start) => {
  const out = [];
  let idx = start;
  // Hylätään pelkät tähdet yms. merkityksettömät labelit
  const useful = (t) => (t = (t || '').replace(/\\s+/g, ' ').trim()) && /[a-zåäö]{2}/i.test(t) ? t : '';
  const labelFor = (el) => {
    if (el.id) {
      const l = useful(document.querySelector(`label[for="${CSS.escape(el.id)}"]`)?.innerText);
      if (l) return l;
    }
    const direct = useful(el.closest('label')?.innerText)
      || useful(el.getAttribute('aria-label')) || useful(el.getAttribute('placeholder'));
    if (direct) return direct;
    // Lähin esivanhempi, jossa on tekstiä kentän ulkopuolella
    let node = el.parentElement;
    for (let i = 0; i < 4 && node; i++, node = node.parentElement) {
      const clone = node.cloneNode(true);
      clone.querySelectorAll('select, option, textarea, script, style').forEach(n => n.remove());
      const t = useful(clone.innerText);
      if (t) return t;
    }
    return '';
  };
  // Hakuvahti-, uutiskirje- ja hakukenttälomakkeet eivät ole hakemuksia
  const NOT_APPLICATION = /paikkavahti|hakuvahti|jobwatch|job.?alert|saved.?search|subscri|newsletter|uutiskirje|search/i;
  const NOT_APPLICATION_TEXT = /vinkkaamme|hakuvahti|paikkavahti|uutiskirje|tilaa ilmoitukset/i;
  const skipForm = (el) => {
    const form = el.closest('form');
    if (!form) return false;
    const attrs = [form.id, form.className, form.getAttribute('action') || ''].join(' ');
    return NOT_APPLICATION.test(attrs) || NOT_APPLICATION_TEXT.test(form.innerText.slice(0, 300));
  };
  // Evästebannerit ja bottiansat (honeypot) eivät kuulu hakemukseen
  const COOKIE = '#CybotCookiebotDialog, #onetrust-consent-sdk, #onetrust-pc-sdk, [id*=cookie i], [class*=cookie i], [aria-label*=cookie i], [aria-label*=eväste i]';
  const HONEYPOT = /honey|bot.?trap|^hp[_-]|leave.?(this|empty)|jätä tyhjäksi/i;
  const shown = (el) => {
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden';
  };
  // Mukautetuissa valintaruuduissa itse input on piilossa: näkyvä label riittää
  const visibleLabel = (el) => {
    const l = (el.id && document.querySelector(`label[for="${CSS.escape(el.id)}"]`)) || el.closest('label');
    return l && shown(l);
  };
  // Kentän kysymys/konteksti: fieldset-legend, ryhmän otsikko tai lähin ympäröivä teksti.
  // Tarvitaan esim. "Kyllä/Ei"-radioille ja "päivä/kuukausi/vuosi"-kentille.
  const question = (el, own) => {
    const group = el.closest('fieldset, [role=radiogroup], [role=group]');
    const legend = group && (group.querySelector('legend')?.innerText || group.getAttribute('aria-label')
      || (group.getAttribute('aria-labelledby') && document.getElementById(group.getAttribute('aria-labelledby'))?.innerText));
    if (useful(legend)) return useful(legend).slice(0, 200);
    let node = el.parentElement;
    for (let i = 0; i < 6 && node; i++, node = node.parentElement) {
      const clone = node.cloneNode(true);
      clone.querySelectorAll('input, select, option, textarea, label, script, style').forEach(n => n.remove());
      const t = useful(clone.innerText);
      if (t && t !== own) return t.length <= 150 ? t : '';  // pitkä teksti on sivun sisältöä, ei kysymys
    }
    return '';
  };
  for (const el of document.querySelectorAll('input, textarea, select')) {
    const type = (el.getAttribute('type') || el.tagName).toLowerCase();
    if (['hidden', 'submit', 'button', 'image', 'reset', 'password', 'search'].includes(type)) continue;
    if (el.disabled || (el.readOnly && type !== 'file')) continue;  // esim. "Merkkejä jäljellä" -laskurit
    if (skipForm(el) || el.closest(COOKIE)) continue;
    if (HONEYPOT.test([el.name, el.id, el.className, el.getAttribute('aria-label')].join(' '))) continue;
    const choice = ['checkbox', 'radio'].includes(type);
    if (!shown(el) && type !== 'file' && !(choice && visibleLabel(el))) continue;
    const label = labelFor(el);
    if (HONEYPOT.test(label)) continue;
    el.setAttribute('data-velho-idx', String(idx));
    out.push({
      idx, tyyppi: type, nimi: el.name || el.id || '',
      label: label.slice(0, 200),
      kysymys: (['checkbox', 'radio', 'file'].includes(type) || label.length < 20) ? question(el, label) || undefined : undefined,
      hyvaksyy: type === 'file' ? el.accept || undefined : undefined,  // esim. image/* = kuvakenttä
      pakollinen: el.required || el.getAttribute('aria-required') === 'true',
      arvo_nyt: el.tagName === 'SELECT' ? el.options[el.selectedIndex]?.text.trim()
        : ['checkbox', 'radio'].includes(type) ? (el.checked ? 'valittu' : 'ei valittu')
        : type === 'file' ? '' : (el.value || '').slice(0, 80),
      // Pitkistä listoista (maat, kielet) vain alku – Claude voi kirjoittaa tarkan vaihtoehdon
      vaihtoehdot: el.tagName === 'SELECT'
        ? (el.options.length > 40 ? [...[...el.options].slice(0, 10).map(o => o.text.trim()), `… yhteensä ${el.options.length}`]
                                  : [...el.options].map(o => o.text.trim()))
        : undefined,
    });
    idx++;
  }
  return out;
}
"""

HIGHLIGHT_JS = """
() => {
  const re = /lähetä|laheta|send|submit|hae paikkaa|lähetä hakemus|apply/i;
  for (const b of document.querySelectorAll('button, input[type=submit], a.btn')) {
    if (re.test(b.innerText || b.value || '')) {
      b.style.outline = '4px solid #e0245e';
      b.style.outlineOffset = '3px';
    }
  }
}
"""


def _collect(frames: list[Frame]) -> tuple[list[dict], dict[int, Frame]]:
    fields, owner = [], {}
    for frame in frames:
        try:
            found = frame.evaluate(COLLECT_JS, len(fields))
        except Exception:
            continue
        for f in found:
            owner[f["idx"]] = frame
        fields.extend(found)
    return fields, owner


# Profiilikuvakenttiin ladattava Velhon logo
LOGO_PATH = ROOT / "assets" / "velho-logo.png"


def _apply_fills(plan: dict, owner: dict[int, Frame], pdf_path: str) -> list[str]:
    errors = []
    for fill in plan["taytot"]:
        frame = owner.get(fill["idx"])
        if frame is None:
            continue
        loc = frame.locator(f'[data-velho-idx="{fill["idx"]}"]')
        try:
            if fill["toiminto"] == "kirjoita":
                loc.fill(fill["arvo"])
            elif fill["toiminto"] == "valitse":
                loc.select_option(label=fill["arvo"])
            elif fill["toiminto"] == "liite":
                loc.set_input_files(str(LOGO_PATH) if fill["arvo"] == "KUVA" else pdf_path)
            elif fill["toiminto"] == "rasti":
                try:
                    loc.check(timeout=3000)
                except Exception:
                    # Piilotettu mukautettu ruutu: klikataan inputia kuten label tekisi
                    loc.evaluate("el => { if (!el.checked) el.click(); }")
        except Exception as e:
            errors.append(f"kenttä {fill['idx']}: {e.__class__.__name__}")
    return errors


def _signature(field: dict) -> tuple:
    # Nimi on vakaa; label voi muuttua täytön jälkeen (esim. tiedostokentässä tiedoston nimi)
    if field["nimi"]:
        return (field["tyyppi"], field["nimi"])
    return (field["tyyppi"], field["label"], field.get("kysymys"))


class PrefillError(Exception):
    pass


class TargetClosedError(Exception):
    """Selainikkuna suljettiin kesken istunnon (sama nimi kuin Playwrightin virheellä)."""


# Kuinka kauan odotetaan lomakkeen ilmestymistä (esim. kirjautumisen ajan)
WAIT_FOR_FORM_S = 300
# Välilehden tilat, joissa työ on vielä kesken
BUSY = ("jonossa", "kirjoitetaan", "avataan", "odotetaan", "taytetaan")
# Tilat, joissa välilehti on poistunut istunnosta
GONE = ("suljettu", "lahetetty")


class Tab:
    """Yhden ilmoituksen välilehti istunnossa."""

    def __init__(self, job: dict):
        self.job_id = job["id"]
        self.title = f"{job['title']} – {job['company']}"
        self.state = "jonossa" if job["application"] else "kirjoitetaan"
        self.log: list[str] = []
        self.notes = ""
        self.page = None
        self.waiting_since = 0.0
        self.asked = False
        self.plan = None       # Future: Clauden täyttösuunnitelma
        self.fields = None     # (kentät, kehykset), joihin suunnitelma tehtiin
        self.draft = None      # Future: hakemuksen kirjoitus
        self.seen: set = set()  # jo täytettyjen kenttien tunnisteet (monivaiheiset lomakkeet)
        self.last_check = 0.0
        self.refills = 0

    def say(self, text: str) -> None:
        self.log.append(text)

    def as_dict(self) -> dict:
        return {"job_id": self.job_id, "title": self.title, "state": self.state, "log": self.log, "notes": self.notes}


class FillSession(threading.Thread):
    """Esitäyttöistunto: yksi selain, jokaiselle ilmoitukselle oma välilehti.

    Kaikki Playwright-kutsut tehdään tässä säikeessä (sync-API ei siedä säikeiden
    vaihtoa); Claude-kutsut (hakemuksen kirjoitus, täyttösuunnitelma) ajetaan
    rinnakkain säiepoolissa. Komennot tulevat jonosta muodossa (komento, job_id):
    "tayta", "lahetetty", "sulje" ja ("sulje_kaikki", None). Uudet ilmoitukset
    lisätään add()-metodilla, joka avaa niille välilehden seuraavalla kierroksella.
    Agentti ei koskaan paina Lähetä-nappia.
    """

    def __init__(self, job_ids: list[int]):
        super().__init__(daemon=True)
        missing = missing_applicant_fields(load_config())
        if missing:
            raise PrefillError(f"Täytä config.yaml → hakija: {', '.join(missing)}")
        if not job_ids:
            raise PrefillError("Valitse vähintään yksi ilmoitus.")
        self.tabs: dict[int, Tab] = {}
        self.state = "kaynnissa"
        self.log: list[str] = []
        self._commands: queue.Queue[tuple[str, int | None]] = queue.Queue()
        self._pool = ThreadPoolExecutor(max_workers=5)
        self._lock = threading.Lock()  # add() tulee web-säikeestä
        self.add(job_ids)

    # --- Rajapinta web-näkymälle (kutsutaan muista säikeistä) ---------------

    def send(self, command: str, job_id: int | None = None) -> None:
        self._commands.put((command, job_id))

    @property
    def alive(self) -> bool:
        return self.state == "kaynnissa"  # kaynnissa → suljetaan → suljettu / virhe

    def add(self, job_ids: list[int]) -> bool:
        """Lisää ilmoitukset istuntoon; False, jos istunto ehti jo päättyä."""
        conn = db.connect()
        with self._lock:
            if not self.alive:
                return False
            for job_id in job_ids:
                self._add(conn, job_id)
        return True

    def tab(self, job_id: int) -> Tab | None:
        tab = self.tabs.get(job_id)
        return tab if tab and self.alive and tab.state not in GONE else None

    def status(self) -> dict:
        return {"state": self.state, "log": self.log, "tabs": [t.as_dict() for t in list(self.tabs.values())]}

    # --- Istunnon säie ---------------------------------------------------------

    def _add(self, conn, job_id: int) -> None:
        if job_id in self.tabs and self.tabs[job_id].state not in GONE:
            return
        job = db.get(conn, job_id)
        if not job:
            return
        if job["application"] and not (job["pdf_path"] and Path(job["pdf_path"]).exists()):
            job["application"] = None  # PDF puuttuu: kirjoitetaan uudelleen
        tab = Tab(job)
        if tab.state == "kirjoitetaan":
            tab.say("Ei hakemusta – Claude kirjoittaa saatteen ja PDF:n…")
            tab.draft = self._pool.submit(pipeline.draft, job_id, load_config())
        self.tabs[job_id] = tab

    def run(self) -> None:
        conn = db.connect()  # SQLite-yhteys tälle säikeelle
        try:
            BROWSER_PROFILE.mkdir(parents=True, exist_ok=True)
            with sync_playwright() as p:
                ctx = p.chromium.launch_persistent_context(str(BROWSER_PROFILE), headless=False, no_viewport=True)
                blank = ctx.pages[0] if ctx.pages else None
                while True:
                    if self._handle_commands(conn, ctx):
                        break
                    for tab in list(self.tabs.values()):
                        self._step(conn, ctx, tab)
                    if blank and any(t.page for t in self.tabs.values()):
                        blank.close()  # profiilin oma tyhjä välilehti pois
                        blank = None
                    with self._lock:
                        if all(t.state in GONE for t in self.tabs.values()):
                            self.state = "suljetaan"  # add() ei enää lisää tähän istuntoon
                            break
                    if not ctx.pages:
                        raise TargetClosedError("Selainikkuna suljettiin")
                    ctx.pages[-1].wait_for_timeout(500)  # pyörittää Playwrightin tapahtumia
                ctx.close()
            self._finish("Selain suljettu.")
        except Exception as e:
            if e.__class__.__name__ == "TargetClosedError":  # käyttäjä sulki selainikkunan
                self._finish("Selainikkuna suljettiin.")
                return
            self.log.append(f"Virhe: {e.__class__.__name__}: {str(e).splitlines()[0][:200]}")
            self.state = "virhe"
        finally:
            self._pool.shutdown(wait=False, cancel_futures=True)

    def _finish(self, message: str) -> None:
        for tab in self.tabs.values():
            if tab.state not in GONE:
                tab.state = "suljettu"
        self.log.append(message)
        self.state = "suljettu"

    def _handle_commands(self, conn, ctx) -> bool:
        """Käsittelee jonon komennot; palauttaa True, jos koko istunto suljetaan."""
        while True:
            try:
                cmd, job_id = self._commands.get_nowait()
            except queue.Empty:
                return False
            if cmd == "sulje_kaikki":
                return True
            tab = self.tabs.get(job_id)
            if not tab or tab.state in GONE:
                continue
            if cmd == "tayta" and tab.page and tab.state not in ("taytetaan", "kirjoitetaan"):
                self._start_fill(conn, tab, force=True)
            elif cmd in ("lahetetty", "sulje"):
                if cmd == "lahetetty":
                    db.update(conn, job_id, status="lahetetty")
                    tab.say("Merkitty lähetetyksi.")
                if tab.page and not tab.page.is_closed():
                    tab.page.close()
                tab.state = "lahetetty" if cmd == "lahetetty" else "suljettu"

    def _step(self, conn, ctx, tab: Tab) -> None:
        if tab.state in GONE:
            return
        if tab.page and tab.page.is_closed():
            tab.say("Välilehti suljettiin.")
            tab.state = "suljettu"
            return
        try:
            if tab.state == "kirjoitetaan" and tab.draft.done():
                tab.draft.result()  # nostaa kirjoituksen virheen
                tab.say("Hakemus kirjoitettu.")
                tab.state = "jonossa"
            elif tab.state == "jonossa":
                self._open(conn, ctx, tab)
            elif tab.state == "odotetaan":
                self._start_fill(conn, tab)
            elif tab.state == "taytetaan" and tab.plan.done():
                self._apply(conn, tab)
            elif tab.state == "valmis":
                self._watch_next_step(conn, tab)
        except Exception as e:
            if e.__class__.__name__ == "TargetClosedError":
                raise
            tab.say(f"Virhe: {e.__class__.__name__}: {str(e).splitlines()[0][:200]}")
            tab.state = "virhe"

    def _open(self, conn, ctx, tab: Tab) -> None:
        tab.state = "avataan"
        page = ctx.new_page()
        page.goto(db.get(conn, tab.job_id)["url"])
        before = set(ctx.pages)
        _open_application(page)
        popups = [pg for pg in ctx.pages if pg not in before]
        if popups:  # hakujärjestelmä aukesi omaan välilehteensä: pidetään vain se
            page.close()
            page = popups[-1]
            page.wait_for_load_state()
        for _ in range(2):  # esim. Workable, Teamtailor: lomake vasta oman "Hae"-napin takana
            if _collect(page.frames)[0]:
                break
            page.wait_for_timeout(2000)
            if _collect(page.frames)[0]:
                break
            opened = _click_ats_apply(ctx, page)
            if opened is not page:
                page.close()
                page = opened
        tab.page = page
        tab.state = "odotetaan"
        tab.waiting_since = time.monotonic()

    def _start_fill(self, conn, tab: Tab, force: bool = False, only_new: bool = False) -> None:
        """Kerää kentät ja pyytää Claudelta täyttösuunnitelman taustalla."""
        try:
            fields, owner = _collect(tab.page.frames)
        except Exception:
            fields, owner = [], {}  # sivu latautuu tai vaihtuu
        if not fields:
            if force:
                tab.say("Lomakekenttiä ei löytynyt. Avaa hakulomake välilehdellä ja paina Täytä uudelleen.")
                tab.state = "valmis"
            elif not tab.asked and time.monotonic() - tab.waiting_since > 5:
                tab.say("Hakulomaketta ei näy vielä. Kirjaudu tai avaa lomake välilehdellä – täytän sen, kun kentät ilmestyvät.")
                tab.asked = True
            elif time.monotonic() - tab.waiting_since > WAIT_FOR_FORM_S:
                tab.say("Lomaketta ei löytynyt viidessä minuutissa. Paina Täytä uudelleen, kun lomake on näkyvissä.")
                tab.state = "valmis"
            return
        if not force:
            tab.page.wait_for_timeout(1500)  # annetaan lomakkeen latautua loppuun
            fields, owner = _collect(tab.page.frames)
        if only_new:  # jo täytettyihin ei kosketa (osa kentistä lisää tekstiä perään)
            fields = [f for f in fields if _signature(f) not in tab.seen and f["tyyppi"] != "file"]
            owner = {f["idx"]: owner[f["idx"]] for f in fields}
            if not fields:
                return
        job = db.get(conn, tab.job_id)  # hakemusta on voitu muokata istunnon aikana
        tab.say(f"Löytyi {len(fields)} kenttää, Claude suunnittelee täytön…")
        tab.fields = (fields, owner)
        tab.plan = self._pool.submit(llm.plan_form_fill, fields, job, job["application"], load_config())
        tab.state = "taytetaan"

    def _watch_next_step(self, conn, tab: Tab) -> None:
        """Monivaiheinen lomake: kun käyttäjä siirtyy seuraavaan vaiheeseen ja uusia
        tyhjiä kenttiä ilmestyy, ne täytetään automaattisesti (enintään 8 kertaa)."""
        if tab.refills >= 8 or time.monotonic() - tab.last_check < 3:
            return
        tab.last_check = time.monotonic()
        try:
            fields, _ = _collect(tab.page.frames)
        except Exception:
            return
        # Tiedostokentät eivät käynnistä täyttöä: ne ilmestyvät usein latausdialogeihin (esim. kuvan rajaus)
        new = [f for f in fields if _signature(f) not in tab.seen and not f["arvo_nyt"] and f["tyyppi"] != "file"]
        if new:
            tab.refills += 1
            tab.say("Uusia kenttiä ilmestyi – täytetään.")
            self._start_fill(conn, tab, force=True, only_new=True)

    def _apply(self, conn, tab: Tab) -> None:
        tab.state = "valmis"
        try:
            plan = tab.plan.result()
        except Exception as e:  # välilehti pysyy auki, vaikka Claude-kutsu epäonnistuu
            tab.say(f"Täyttö epäonnistui: {str(e)[:200]}. Voit täyttää käsin tai yrittää uudelleen.")
            return
        job = db.get(conn, tab.job_id)
        tab.seen |= {_signature(f) for f in tab.fields[0]}
        errors = _apply_fills(plan, tab.fields[1], job["pdf_path"])
        for frame in tab.page.frames:
            try:
                frame.evaluate(HIGHLIGHT_JS)
            except Exception:
                pass
        if job["status"] in ("arvioitu", "luonnos"):
            db.update(conn, tab.job_id, status="esitaytetty")
        tab.say(f"Täytetty {len(plan['taytot']) - len(errors)} kenttää. Tarkista lomake ja paina punaisella merkittyä Lähetä-nappia itse.")
        if errors:
            tab.say("Ei onnistunut: " + "; ".join(errors))
        tab.notes = plan["huomiot"]


def _open_application(page) -> None:
    apply = page.locator("a.apply--button").first
    if not apply.count():
        return
    # Klikataan kuten ihminen: toimii sekä Duunitorin omalle lomakkeelle
    # (suhteellinen tai #-linkki) että ulkoiseen hakujärjestelmään
    href = apply.get_attribute("href") or ""
    try:
        apply.click(timeout=10_000)
        page.wait_for_load_state()
        page.wait_for_timeout(1000)  # mahdollinen uusi välilehti ehtii aueta
    except Exception:
        if href and not href.startswith("#"):
            page.goto(urljoin(page.url, href))


# Hakujärjestelmän ilmoitussivun "Hae"-nappi, joka avaa lomakkeen. Klikataan vain,
# kun sivulla ei ole yhtään lomakekenttää – silloin ei ole mitään lähetettävää.
APPLY_TEXT = re.compile(r"^\s*(hae( paikkaa| nyt| työpaikkaa| tätä (työtä|paikkaa)| tähän (paikkaan|tehtävään))?|"
                        r"apply( now| for this job| here)?|täytä hakemus|jätä hakemus|aloita( hakemus| haku)?|"
                        r"siirry hakemaan|siirry hakulomakkeelle|hakemaan|sök( jobbet| nu)?|ansök)\s*[→›>]?\s*$", re.I)
NEVER_CLICK = re.compile(r"lähetä|laheta|send|submit|tallenna|save|vahvista|confirm|skicka|valmis|finish", re.I)
# Evästebannerista valitaan aina vain välttämättömät (yksityisyyttä suojaavin vaihtoehto)
COOKIE_DECLINE = re.compile(r"^\s*(vain välttämättömät|salli vain välttämättömät|käytä vain välttämättömiä|hyväksy vain välttämättömät|"
                            r"hylkää( kaikki)?|kieltäydy|en hyväksy|decline( all)?|reject( all)?|deny|only necessary|"
                            r"necessary (cookies )?only|use necessary cookies only|allow (only )?necessary|endast nödvändiga)\s*$", re.I)


def _visible_buttons(page):
    """Näkyvät napit ja linkit, sisältö ennen ylä-/alapalkkia."""
    items = []
    for el in page.locator("a, button, [role=button]").all()[:500]:
        try:
            if not el.is_visible():
                continue
            text = (el.inner_text(timeout=300) or el.get_attribute("aria-label") or "").strip()
            in_chrome = el.evaluate("e => !!e.closest('header, nav, footer, [role=navigation], [role=banner]')")
            items.append((in_chrome, text, el))
        except Exception:
            continue
    return [(text, el) for _, text, el in sorted(items, key=lambda x: x[0])]


def _dismiss_cookies(page) -> None:
    for frame in page.frames:
        for el in frame.locator("button, a, [role=button]").all()[:300]:
            try:
                if el.is_visible() and COOKIE_DECLINE.match(el.inner_text(timeout=300) or ""):
                    el.click(timeout=2000)
                    page.wait_for_timeout(500)
                    return
            except Exception:
                continue


def _click_ats_apply(ctx, page):
    """Klikkaa hakujärjestelmän omaa hakunappia; palauttaa sivun, jolla lomake on."""
    _dismiss_cookies(page)
    if _collect(page.frames)[0]:
        return page  # lomake näkyy jo: ei klikata mitään
    for text, el in _visible_buttons(page):
        try:
            if not APPLY_TEXT.match(text) or NEVER_CLICK.search(text):
                continue
            # Ei koskaan nappia lomakkeen sisällä, jossa on kenttiä (se olisi lähetysnappi)
            if el.evaluate("e => !!e.closest('form') && [...e.closest('form').querySelectorAll('input, textarea, select')]"
                           ".some(i => !['hidden', 'submit', 'button'].includes(i.type))"):
                continue
            before = set(ctx.pages)
            el.click(timeout=5000)
            page.wait_for_load_state()
            page.wait_for_timeout(2000)
            popups = [pg for pg in ctx.pages if pg not in before]
            opened = popups[-1] if popups else page
            _dismiss_cookies(opened)
            return opened
        except Exception:
            continue
    return page


def open_and_prefill(job_ids: list[int]) -> None:
    """Komentoriviversio: täyttää automaattisesti, Enter sulkee selaimen."""
    try:
        session = FillSession(job_ids)
    except PrefillError as e:
        raise SystemExit(str(e))
    session.start()
    shown: dict[int, int] = {}
    noted: set[int] = set()
    print("Esitäytetään. Lähetä hakemukset selaimessa ja sulje se, kun olet valmis.\n")
    while session.alive:
        for tab in list(session.tabs.values()):
            for line in tab.log[shown.get(tab.job_id, 0):]:
                print(f"#{tab.job_id}: {line}")
            if tab.notes and shown.get(tab.job_id, 0) < len(tab.log):
                print(f"#{tab.job_id} tarkista itse:\n{tab.notes}")
            shown[tab.job_id] = len(tab.log)
        time.sleep(0.5)
    print("\n".join(session.log))
