"""Claude-kutsut: ilmoituksen arviointi, hakemuksen kirjoitus ja lomakkeen kenttien täyttö."""

import json
import os
from typing import Literal

import anthropic
from pydantic import BaseModel

from . import config  # noqa: F401 – lataa .env ennen avainten lukua

# OpenRouter tarjoaa Anthropic-yhteensopivan rajapinnan: jos .env:ssä on
# OPENROUTER_API_KEY, kutsut menevät sen kautta (eri mallinimi, ei Anthropicin betoja)
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = "https://openrouter.ai/api"
MODEL = "anthropic/claude-opus-5.5" if OPENROUTER_KEY else "claude-opus-5-5"
# Lomakkeen täyttö on suoraviivaista kenttien yhdistämistä: Sonnet tekee saman
# suunnitelman kuin Opus noin puolessa ajassa (Haiku jätti liitteen pois)
FILL_MODEL = "anthropic/claude-sonnet-5.5" if OPENROUTER_KEY else "claude-sonnet-5-5"
# Palvelinpuolen varamalli, jos turvaluokitin hylkää pyynnön (vain Anthropicin rajapinta)
FALLBACK_BETA = "server-side-fallback-2026-07-01"

# Työnantajan kokonaiskustannus ≈ kk-palkka × 12,5 (lomaraha) × 1,25 (sivukulut)
EMPLOYER_COST_FACTOR = 12.5 * 1.25

_client: anthropic.Anthropic | None = None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        if OPENROUTER_KEY:
            # api_key=None, ettei mahdollinen ANTHROPIC_API_KEY lähde OpenRouterille
            _client = anthropic.Anthropic(base_url=OPENROUTER_BASE_URL, auth_token=OPENROUTER_KEY, api_key=None)
        else:
            _client = anthropic.Anthropic()
    return _client


class RefusedError(Exception):
    pass


def _parse(model_cls, system: str, user: str, effort: str, max_tokens: int = 16000, model: str = MODEL):
    params = dict(
        model=model,
        max_tokens=max_tokens,
        output_config={"effort": effort},
        system=system,
        messages=[{"role": "user", "content": user}],
        output_format=model_cls,
    )
    if OPENROUTER_KEY or model != MODEL:  # varamalli vain oletusmallille
        response = client().messages.parse(**params)
    else:
        response = client().beta.messages.parse(betas=[FALLBACK_BETA], fallbacks="default", **params)
    if response.stop_reason == "refusal":
        raise RefusedError(str(response.stop_details))
    if response.parsed_output is None:
        raise RuntimeError(f"Claude ei palauttanut jäsennettävää vastausta (stop_reason={response.stop_reason})")
    return response.parsed_output


# --- 1. Arviointi -----------------------------------------------------------

class Tehtava(BaseModel):
    tehtava: str
    automatisoitavuus: Literal["korkea", "keskitaso", "matala"]
    miten: str


class Analyysi(BaseModel):
    pisteet: int
    sopii: bool
    perustelu: str
    tehtavat: list[Tehtava]
    automatisoitava_osuus_pct: int
    palkka_kk_eur: int
    palkka_lahde: Literal["ilmoitus", "arvio"]


ANALYZE_SYSTEM = """Arvioit suomalaisia työpaikkailmoituksia Velholle. Velho automatisoi yritysten
rutiinityötä (tiedonsiirrot järjestelmien välillä, laskutus, raportointi, tilausten ja
pyyntöjen käsittely, sähköpostien luokittelu ja luonnostelu, tarkistukset, dashboardit).

Tehtäväsi: päättele, kuinka suuri osa ilmoituksen työnkuvasta on rutiinia, jonka
automaatio tai tekoäly voisi hoitaa. Ole realistinen ja kriittinen:
- Ihmissuhde-, hoiva-, käsi-, kenttä- ja asiantuntijatyö (esim. hoitaja, myyjä kentällä,
  asentaja, lääkäri, opettaja) saa matalat pisteet.
- Korkeat pisteet saavat roolit, joissa on paljon toistuvaa tiedon käsittelyä
  (toimistoavustaja, laskuttaja, reskontra, tilausten käsittely, back office, data entry).
- Julkisen sektorin palkkatuetut työt ja harjoittelut eivät sovi (sopii=false).

pisteet = 0–100 kuinka hyvä myyntimahdollisuus Velholle tämä on.
automatisoitava_osuus_pct = arvio 0–100 % työajasta, jonka automaatio voisi viedä.
palkka_kk_eur: käytä ilmoituksen palkkaa jos se on mainittu (palkka_lahde="ilmoitus"),
muuten arvioi suomalainen tyypillinen kuukausipalkka roolille (palkka_lahde="arvio").
tehtavat: luettele ilmoituksessa mainitut konkreettiset tehtävät ja kerro lyhyesti miten
Velho voisi automatisoida kunkin. Vastaa suomeksi."""


def analyze(job: dict) -> dict:
    user = _job_block(job)
    result: Analyysi = _parse(Analyysi, ANALYZE_SYSTEM, user, effort="low")
    data = result.model_dump()
    data["pisteet"] = max(0, min(100, data["pisteet"]))
    data["automatisoitava_osuus_pct"] = max(0, min(100, data["automatisoitava_osuus_pct"]))
    data["vuosikustannus_eur"] = round(data["palkka_kk_eur"] * EMPLOYER_COST_FACTOR)
    data["vuosisaasto_eur"] = round(data["vuosikustannus_eur"] * data["automatisoitava_osuus_pct"] / 100)
    return data


# --- 2. Hakemus -------------------------------------------------------------

class Hakemus(BaseModel):
    saate: str
    ehdotus_otsikko: str
    johdanto: str
    esimerkkitehtavat: list[str]
    seuraava_askel: str


WRITE_SYSTEM = """Kirjoitat poikkeuksellisen työhakemuksen Velhon puolesta. Hakija ei ole ihminen
hakemassa paikkaa, vaan Velho, joka ehdottaa, että osa ilmoitetun roolin rutiinitehtävistä
automatisoidaan. Tavoite: rekrytoija tai esihenkilö hämmästyy, hymyilee ja ottaa yhteyttä.

Sävy ja rakenne (saate, 120–200 sanaa, suomeksi, sinuttelematta, "te"-muoto):
- Avaa rehellisesti ja oivaltavasti: tämä ei ole tavallinen hakemus, ja sen sanoo heti.
- Viittaa konkreettisesti ilmoituksen omiin tehtäviin – lukijan pitää nähdä, että ilmoitus on luettu.
- Kerro selvästi MITEN: Velho rakentaa tekoälyagentteja ja automaatioita, jotka tekevät
  rutiinin. Kuvaa 1–2 esimerkillä mekanismi arkikielellä, esim. "tekoälyagentti lukee
  saapuvat edelleenlaskutuspyynnöt sähköpostista, poimii niistä summan ja kohteen ja tekee
  laskuluonnoksen D365:een – ihminen vain hyväksyy". Lukijan pitää ymmärtää, mitä agentti
  konkreettisesti tekee, mistä se lukee ja mihin kirjoittaa, ja missä kohtaa ihminen tarkistaa.
- Kehystä hyöty kunnioittavasti: ei "älkää palkatko ketään", vaan esim. että uusi työntekijä
  pääsee tekemään arvokkaampaa työtä tai rooli voi olla kevyempi, ja säästö on X €/v.
- Säästöluku on arvio – sano se arvioksi ja kerro mihin se perustuu.
- Lopuksi helppo seuraava askel (30 min esittelypuhelu, linkki) ja maininta, että
  jos ette ole kiinnostuneita, tähän ei tarvitse vastata.
- Ei liioittelua, ei tekoälyhypeä, ei lupauksia joita ei voi pitää. Ei markdownia saatteessa.

Liitteeksi tehdään yksisivuinen, tarkoituksella yleisluontoinen esittely (ei toteutusten
yksityiskohtia – Velhon toimintatapa lisätään siihen automaattisesti). Kirjoita sitä varten:
- ehdotus_otsikko: lyhyt, esim. "Vähemmän rutiinia, enemmän aikaa olennaiseen".
- johdanto: 2–3 lausetta. Velho automatisoi rutiinitehtäviä tekoälyagenttien ja
  automaatioiden avulla, jotta yritys säästää aikaa ja ihmiset pääsevät keskittymään
  olennaiseen. Sitten: "Teillä [yritys]:ssä/llä näitä voisivat olla esimerkiksi…"
- esimerkkitehtavat: 3–6 ilmoituksen rutiinitehtävää lyhyinä nimityksinä
  (esim. "Kuukausittainen laskutus"), ei selityksiä.
- seuraava_askel: 1–2 lausetta kutsu 30 minuutin esittelypuheluun linkin kera."""


def write_application(job: dict, analysis: dict, cfg: dict) -> dict:
    velho = cfg["velho"]
    hakija = cfg.get("hakija") or {}
    saasto = f"{round(analysis['vuosisaasto_eur'], -3):,}".replace(",", " ")
    user = f"""{_job_block(job)}

<arvio>
{json.dumps(analysis, ensure_ascii=False, indent=2)}
</arvio>
Käytä säästöstä pyöristettyä lukua "noin {saasto} €/v" – sama luku on liitteessä.

<velho>
{velho['kuvaus']}
Verkkosivu: {velho['verkkosivu']}
Varaa esittelypuhelu: {velho['varaa_aika']}
</velho>

<allekirjoittaja>
{hakija.get('etunimi', '')} {hakija.get('sukunimi', '')}, {hakija.get('titteli', '')}, Velho
{hakija.get('sahkoposti', '')} {hakija.get('puhelin', '')}
</allekirjoittaja>"""
    result: Hakemus = _parse(Hakemus, WRITE_SYSTEM, user, effort="high")
    return result.model_dump()


# --- 3. Lomakkeen kentät ----------------------------------------------------

class Taytto(BaseModel):
    idx: int
    toiminto: Literal["kirjoita", "valitse", "liite", "rasti"]
    arvo: str


class Tayttosuunnitelma(BaseModel):
    taytot: list[Taytto]
    huomiot: str


FILL_SYSTEM = """Täytät työhakemuslomaketta Velhon puolesta. Velho on tekoäly- ja automaatioyritys,
joka "hakee" paikkaa ehdottaakseen rutiinitöiden automatisointia. Saat listan lomakkeen kentistä
(idx, tyyppi, nimi, label, kysymys, pakollinen, arvo_nyt, vaihtoehdot), hakijan tiedot,
lomakevastaukset ja hakemuksen saatteen.

Täytä KAIKKI kentät, joihin on järkevä vastaus – myös vapaaehtoiset. Toiminnot:
- "kirjoita": teksti-, numero-, päivämäärä- ja textarea-kentät. Saatekirje/hakemus/motivaatio/
  vapaa kuvaus/"kerro itsestäsi" -kenttiin arvoksi täsmälleen "{SAATE}" – ohjelma vaihtaa sen
  saatteeseen (älä kopioi saatetta itse). Muihin avoimiin kysymyksiin lyhyt vastaus Velhon näkökulmasta.
  "Vahvista sähköposti" -kenttiin sama sähköposti.
- "valitse": select-kentät, arvo = yksi annetuista vaihtoehdoista täsmälleen (lähin lomakevastausta vastaava).
- "liite": CV/resume/hakemus/liite-tiedostokentät → arvo "PDF" (vain ensimmäiseen liitekenttään, jos niitä on monta);
  profiilikuva/valokuva/photo-kentät → arvo "KUVA". Tunnista kenttä labelista, kysymyksestä ja hyvaksyy-
  tiedostotyypeistä (image/* = kuva). Pakollinen CV/resume-kenttä täytetään aina PDF:llä.
- "rasti": valintaruudut ja radionapit. Rastita kaikki käyttöehtojen, tietosuojan, suostumusten,
  palautteen ja yhteydenottojen ruudut. Radioryhmästä (sama kysymys/nimi) valitse yksi vaihtoehto.
  Kielitaidoissa valitse aina korkein taso (erinomainen/äidinkieli/C2), osaamisissa korkein taso.
Jätä täyttämättä vain kentät, jotka on jo täytetty oikein (arvo_nyt), sekä kentät, joihin lomakevastaukset
käskevät jättää tyhjäksi. huomiot = yksi lyhyt lause tai tyhjä."""


def plan_form_fill(fields: list[dict], job: dict, application: dict, cfg: dict) -> dict:
    hakija = cfg.get("hakija") or {}
    user = f"""<kentat>
{json.dumps(fields, ensure_ascii=False, indent=1)}
</kentat>

<hakija>
{json.dumps(hakija, ensure_ascii=False, indent=1)}
Yritys: Velho ({cfg['velho']['verkkosivu']})
</hakija>

<lomakevastaukset>
{json.dumps(cfg.get('lomakevastaukset') or {}, ensure_ascii=False, indent=1)}
</lomakevastaukset>

<ilmoitus>{job.get('title')} – {job.get('company')}</ilmoitus>

<saate>
{application['saate']}
</saate>"""
    result: Tayttosuunnitelma = _parse(Tayttosuunnitelma, FILL_SYSTEM, user, effort="low", model=FILL_MODEL)
    plan = result.model_dump()
    for t in plan["taytot"]:
        t["arvo"] = t["arvo"].replace("{SAATE}", application["saate"])
    return plan


def _job_block(job: dict) -> str:
    return f"""<ilmoitus>
Otsikko: {job.get('title')}
Yritys: {job.get('company')}
Sijainti: {job.get('location')}
Julkaistu: {job.get('posted')}  Haku päättyy: {job.get('valid_through')}
URL: {job.get('url')}

{job.get('description') or ''}
</ilmoitus>"""
