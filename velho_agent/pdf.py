"""Hakemuksen liitteeksi tuleva yksisivuinen Velho-esittely (PDF)."""

from pathlib import Path

from fpdf import FPDF

from .config import PDF_DIR

FONT_DIR = Path("C:/Windows/Fonts")
INK = (30, 30, 40)
ACCENT = (90, 60, 200)
MUTED = (110, 110, 120)


def _fonts(pdf: FPDF) -> str:
    regular, bold = FONT_DIR / "arial.ttf", FONT_DIR / "arialbd.ttf"
    if regular.exists() and bold.exists():
        pdf.add_font("Body", "", str(regular))
        pdf.add_font("Body", "B", str(bold))
        return "Body"
    return "Helvetica"


def _txt(text: str, font: str) -> str:
    # Sisäänrakennetut fontit tukevat vain latin-1-merkkejä
    if font == "Helvetica":
        text = text.replace("€", "EUR").replace("–", "-").replace("’", "'").replace("•", "-")
        return text.encode("latin-1", "replace").decode("latin-1")
    return text


def build_proposal_pdf(job: dict, analysis: dict, application: dict, cfg: dict) -> Path:
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    # Esittely luvataan yksisivuiseksi: pienennetään kokoja, kunnes se mahtuu
    for k in (1.0, 0.94, 0.88, 0.82, 0.76):
        pdf = _render(job, analysis, application, cfg, k)
        if pdf.page == 1:
            break
    company = "".join(c for c in (job.get("company") or "yritys") if c.isascii() and c.isalnum())[:30]
    path = PDF_DIR / f"Velho_ehdotus_{job['id']}_{company}.pdf"
    pdf.output(str(path))
    return path


def _render(job: dict, analysis: dict, application: dict, cfg: dict, k: float) -> FPDF:
    pdf = FPDF(format="A4")
    pdf.set_margins(18, 18, 18)
    pdf.set_auto_page_break(True, margin=16)
    pdf.add_page()
    font = _fonts(pdf)
    t = lambda s: _txt(s, font)  # noqa: E731
    w = pdf.epw
    velho = cfg["velho"]

    def heading(text: str) -> None:
        pdf.set_font(font, "B", 12 * k)
        pdf.set_text_color(*INK)
        pdf.multi_cell(w, 6 * k, t(text), new_x="LMARGIN", new_y="NEXT", align="L")
        pdf.ln(1.5 * k)

    def body(text: str, color=INK, size=10.5) -> None:
        pdf.set_font(font, "", size * k)
        pdf.set_text_color(*color)
        pdf.multi_cell(w, 5.4 * k, t(text), new_x="LMARGIN", new_y="NEXT", align="L")

    # Otsikko
    pdf.set_font(font, "B", 10 * k)
    pdf.set_text_color(*ACCENT)
    pdf.cell(w, 6 * k, t("VELHO  ·  AUTOMAATIOEHDOTUS"), new_x="LMARGIN", new_y="NEXT", align="L")
    pdf.ln(2 * k)
    pdf.set_font(font, "B", 20 * k)
    pdf.set_text_color(*INK)
    pdf.multi_cell(w, 9 * k, t(application["ehdotus_otsikko"]), new_x="LMARGIN", new_y="NEXT", align="L")
    body(f"{job.get('company') or ''} – {job.get('title') or ''}", MUTED, 10)
    pdf.ln(6 * k)

    # Johdanto ja ilmoituksen rutiinitehtävät
    body(application["johdanto"])
    pdf.ln(3 * k)
    bullet = "•" if font != "Helvetica" else "-"
    for task in application["esimerkkitehtavat"]:
        pdf.set_font(font, "B", 10.5 * k)
        pdf.set_text_color(*ACCENT)
        pdf.cell(6 * k, 6 * k, t(bullet))
        pdf.set_text_color(*INK)
        pdf.multi_cell(0, 6 * k, t(task), new_x="LMARGIN", new_y="NEXT", align="L")
    pdf.ln(7 * k)

    # Velhon toimintatapa
    heading("Näin Velho työskentelee")
    for i, step in enumerate(velho.get("toimintatapa") or [], start=1):
        y = pdf.get_y()
        pdf.set_font(font, "B", 16 * k)
        pdf.set_text_color(*ACCENT)
        pdf.set_xy(pdf.l_margin, y)
        pdf.cell(12 * k, 7 * k, f"{i:02d}")
        pdf.set_xy(pdf.l_margin + 14 * k, y)
        pdf.set_font(font, "B", 11 * k)
        pdf.set_text_color(*INK)
        pdf.multi_cell(w - 14 * k, 6 * k, t(step["vaihe"]), new_x="LEFT", new_y="NEXT", align="L")
        pdf.set_font(font, "", 10 * k)
        pdf.set_text_color(*MUTED)
        pdf.multi_cell(w - 14 * k, 5 * k, t(step["kuvaus"]), new_x="LMARGIN", new_y="NEXT", align="L")
        pdf.ln(3.5 * k)
    pdf.ln(3 * k)

    # Säästöarvio ja yhteystiedot
    pdf.set_draw_color(*ACCENT)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + w, pdf.get_y())
    pdf.ln(5 * k)
    # Arvio pyöristetään tuhansiin, ettei se näytä tarkemmalta kuin on
    saasto = f"{round(analysis['vuosisaasto_eur'], -3):,}".replace(",", " ")
    heading(f"Arvioitu säästö: noin {saasto} € vuodessa")
    lahde = "ilmoituksen palkka" if analysis["palkka_lahde"] == "ilmoitus" else "arvioitu alan tyypillinen palkka"
    body(f"Arvio: {analysis['automatisoitava_osuus_pct']} % työajasta automatisoitavissa × työnantajan "
         f"kokonaiskustannus ({lahde} {analysis['palkka_kk_eur']} €/kk, sis. lomarahat ja sivukulut). "
         "Tarkka luku selviää kartoituksessa.", MUTED, 9)
    pdf.ln(5 * k)
    pdf.set_font(font, "B", 10.5 * k)
    pdf.set_text_color(*INK)
    pdf.multi_cell(w, 5.4 * k, t(application["seuraava_askel"]), new_x="LMARGIN", new_y="NEXT", align="L")
    pdf.ln(1.5 * k)
    hakija = cfg.get("hakija") or {}
    contact = " · ".join(x for x in [
        f"{hakija.get('etunimi', '')} {hakija.get('sukunimi', '')}".strip(),
        hakija.get("sahkoposti"), hakija.get("puhelin"), velho["verkkosivu"],
    ] if x)
    body(contact, MUTED, 9)
    return pdf
