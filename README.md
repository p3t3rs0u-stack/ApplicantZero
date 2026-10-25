# Velho-agentti

Etsii Duunitorista rutiinitöitä sisältäviä työpaikkailmoituksia ja arvioi Claudella, kuinka suuren osan työstä Velho voisi automatisoida. Sen jälkeen se kirjoittaa poikkeavan "hakemuksen", joka on Velhon automaatioehdotus arvioidulla säästölaskelmalla, ja esitäyttää hakulomakkeen. **Ihminen tarkistaa ja painaa Lähetä itse.**

```
Duunitori ──hae──► SQLite ──arvioi (Claude)──► hyväksyntänäkymä
                                               │
                         kirjoita (Claude) ◄───┘
                         saate + PDF-ehdotus
                               │
                         esitäytä (Playwright + Claude)
                               │
                         ihminen tarkistaa ja lähettää
```

## Asennus

```bash
pip install -r requirements.txt
```

```bash
python -m playwright install chromium
```

1. Kopioi `.env.example` tiedostoksi `.env` ja lisää `ANTHROPIC_API_KEY` **tai** `OPENROUTER_API_KEY`. Jos OpenRouter-avain on asetettu, kutsut menevät OpenRouterin Anthropic-yhteensopivan rajapinnan kautta (malli `anthropic/claude-opus-5.5`, ilman Anthropicin palvelinpuolen varamallia).
2. Täytä `config.yaml` → `hakija` (nimi, sähköposti, puhelin, titteli). Hakemukset täytetään tämän henkilön nimissä.
3. Muokkaa tarvittaessa `hakusanat` ja `min_pisteet`.

## Käyttö

Tuplaklikkaa projektikansion **`Velho.pyw`**-tiedostoa. Agentti käynnistyy taustalle ilman komentoikkunaa ja avaa hyväksyntänäkymän selaimeen (http://localhost:5050). Jos agentti on jo käynnissä, tuplaklikkaus vain avaa näkymän. Sammutus tapahtuu yläkulman **Sammuta**-napista. Loki tallentuu tiedostoon `data/velho.log`.

Näkymässä:
- **Aja haku ja arviointi** hakee uudet ilmoitukset ja pisteyttää ne taustalla. Eteneminen näkyy etusivulla.
- Avaa ilmoitus → **Kirjoita hakemus** luo saatteen ja yksisivuisen PDF-ehdotuksen. Saatetta voi muokata.
- **Avaa ja esitäytä hakemus** avaa hakulomakkeen selaimeen ja täyttää sen automaattisesti heti, kun kentät näkyvät. Jos sivu vaatii kirjautumisen tai evästeiden hyväksynnän, tee se itse; agentti odottaa lomaketta enintään 5 minuuttia. Eteneminen ja tarkistettavat asiat näkyvät ilmoitussivulla.
- **Monta kerralla:** rastita etusivun listasta ilmoitukset ja paina **Esitäytä valitut**. Jokainen avautuu samaan selaimeen omalle välilehdelleen ja täytetään rinnakkain. Ilmoituksille, joilla ei vielä ole hakemusta, Claude kirjoittaa saatteen ja PDF:n ensin. Jos selain on jo auki, valitut lisätään siihen uusina välilehtinä.
- Tarkista lomake, hyväksy ehdot ja paina Lähetä itse. Paina sen jälkeen paneelissa **Lähetin hakemuksen**. Muut napit: **Täytä uudelleen**, **Sulje välilehti** ja **Sulje selain**.
- **Yhteydenotto johtoon:** Lähetetty-välilehdellä on **Ota yhteys johtoon**. Ilmoitussivun **Etsi johto** etsii verkosta (Claude + verkkohaku, noin 1–2 min) toimitusjohtajan, roolin johtajan ja ilmoituksen yhteyshenkilön sekä kirjoittaa kullekin sähköpostin ja LinkedIn-viestin (enintään 300 merkkiä). Sähköpostiosoitteita ei arvata: osoite näytetään vain, jos se löytyy sellaisenaan lähdesivulta (ohjelma tarkistaa sen). **Gmail-luonnos** avaa valmiin viestin Gmailiin, jossa se tallentuu Luonnoksiin. **LinkedIn** avaa profiilin ja kopioi viestin leikepöydälle. Lähetät itse ja merkitset lähetetyksi.

Komentoriviltä onnistuu myös (`python -m velho_agent web` käynnistää näkymän komentoikkunassa).

Samat toiminnot komentoriviltä:

```bash
python -m velho_agent aja
```

```bash
python -m velho_agent lista --tila arvioitu
```

```bash
python -m velho_agent kirjoita 12
```

```bash
python -m velho_agent tayta 12 26 63
```

## Ajastus (Windowsin tehtävien ajoitus)

Haku ja arviointi joka arkiaamu klo 7:

```bash
schtasks /Create /TN "Velho-agentti" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 07:00 /TR "cmd /c cd /d \"C:\polku\projektiin\" && python -m velho_agent aja"
```

## Huomioita

- **Kohtelias haku:** agentti hakee Duunitorilta hitaasti (10 s pyyntöjen välissä, enintään 100 uutta ilmoitusta per ajo) ja tunnistettavalla User-Agentilla. Estoja ei kierretä: jos Duunitori vastaa 403/429, ajo pysähtyy.
- **Ei automaattista lähetystä:** agentti ei koskaan paina Lähetä-nappia. Se täyttää kaikki kentät, joihin on vastaus, ja rastittaa käyttöehdot ja suostumukset. Viralliset kortit, passit ja luvat jäävät rastittamatta. Vastaukset (palkkatoive, kielitaito, aloitus…) ovat `config.yaml` → `lomakevastaukset`. Profiilikuvaksi ladataan `assets/velho-logo.png`.
- **Hakujärjestelmät:** jos lomake on hakujärjestelmän oman "Hae"-napin takana (esim. Workable, Rekrytointi.com, Teamtailor), agentti klikkaa sitä vain, kun sivulla ei ole yhtään lomakekenttää. Evästebannerista valitaan vain välttämättömät. Monivaiheisissa lomakkeissa uudet kentät täytetään, kun siirryt seuraavaan vaiheeseen. Kirjautumista vaativiin järjestelmiin (Duunitorin oma lomake, Academic Work, Workday) kirjaudutaan kerran itse agentin selaimessa.
- **Säästölaskelma** on arvio: kk-palkka × 12,5 (lomaraha) × 1,25 (sivukulut) × automatisoitava osuus. Jos ilmoituksessa ei ole palkkaa, Claude arvioi sen. Arvio on merkitty sellaiseksi myös hakemukseen.
- **Kustannukset:** arviointi käyttää mallia Claude Opus 5.5 matalalla effort-tasolla. Se tehdään vain uusille ilmoituksille, noin 1–2 senttiä per ilmoitus.
- **Tietosuoja:** tietokantaan (`data/velho.db`) tallennetaan vain ilmoitusten tiedot.

## Rakenne

| Tiedosto | Tehtävä |
|---|---|
| `velho_agent/duunitori.py` | hakutulokset ja ilmoitukset (JSON-LD JobPosting) |
| `velho_agent/llm.py` | Claude: arviointi, hakemus, lomakkeen täyttösuunnitelma |
| `velho_agent/pdf.py` | yksisivuinen automaatioehdotus |
| `velho_agent/filler.py` | Playwright-esitäyttö, ei lähetystä |
| `velho_agent/web.py` | hyväksyntänäkymä, taustahaku ja esitäytön ohjaus |
| `Velho.pyw` | tuplaklikattava käynnistin |
| `velho_agent/pipeline.py` | haku → arviointi → luonnos |
