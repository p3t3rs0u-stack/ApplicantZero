"""Hyväksyntänäkymä: http://localhost:5050

Kaikki ohjataan selaimesta: haku ja arviointi pyörivät taustasäikeessä ja
esitäyttö omassa istunnossaan, joiden etenemistä sivut kysyvät JSON-rajapinnasta.
"""

import os
import threading
from urllib.parse import urlparse

from flask import Flask, abort, jsonify, redirect, render_template_string, request, send_file, url_for

from . import db, pipeline
from .config import load_config
from .filler import FillSession, PrefillError

app = Flask(__name__)


@app.template_filter("source")
def source(url: str) -> str:
    """Ilmoituksen lähde URL:sta, esim. https://duunitori.fi/... → duunitori."""
    host = urlparse(url or "").netloc.removeprefix("www.")
    return host.split(".")[0] if host else "–"

BASE = """<!doctype html>
<html lang="fi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Velho-agentti</title>
<style>
:root{--bg:#f7f7fb;--card:#fff;--ink:#1e1e28;--muted:#6e6e78;--accent:#5a3cc8;--line:#e4e4ee;--good:#1d8a5b;--bad:#b3334a}
*{box-sizing:border-box}[hidden]{display:none!important}body{margin:0;font:15px/1.5 system-ui,Segoe UI,sans-serif;background:var(--bg);color:var(--ink)}
header{background:var(--ink);color:#fff;padding:14px 24px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
header a{color:#fff;text-decoration:none;font-weight:600}header .right{margin-left:auto;display:flex;gap:8px}
main{max-width:1100px;margin:0 auto;padding:20px 16px}
.tabs{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:14px}.tabs a{padding:5px 12px;border-radius:99px;background:var(--card);border:1px solid var(--line);color:var(--ink);text-decoration:none;font-size:13px}
.tabs a.on{background:var(--accent);color:#fff;border-color:var(--accent)}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{padding:9px 12px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{font-size:12px;color:var(--muted);text-transform:uppercase}
td a{color:var(--accent);text-decoration:none;font-weight:600}
.score{font-weight:700;font-variant-numeric:tabular-nums}.muted{color:var(--muted);font-size:13px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:18px;margin-bottom:16px}
.card.live{border-color:var(--accent);box-shadow:0 0 0 3px rgba(90,60,200,.12)}
h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:0 0 10px}
.btn{display:inline-block;padding:8px 14px;border-radius:8px;border:1px solid var(--accent);background:var(--accent);color:#fff;font:inherit;cursor:pointer;text-decoration:none}
.btn.ghost{background:transparent;color:var(--accent)}.btn.good{background:var(--good);border-color:var(--good)}
.btn.dim{background:transparent;border-color:#555;color:#ccc}.btn:disabled{opacity:.5;cursor:default}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
textarea{width:100%;min-height:260px;font:inherit;padding:10px;border:1px solid var(--line);border-radius:8px}
.task{padding:8px 0;border-bottom:1px solid var(--line)}.task:last-child{border:0}
.pill{font-size:12px;padding:1px 8px;border-radius:99px;background:#eee}.korkea{background:#d9f2e6;color:var(--good)}.matala{background:#f6dde2;color:var(--bad)}
pre{white-space:pre-wrap;font:inherit;max-height:400px;overflow:auto}
.flash{background:#fff7d6;border:1px solid #eedc8a;padding:10px 14px;border-radius:8px;margin-bottom:14px}
.log{list-style:none;margin:8px 0;padding:0;max-height:240px;overflow:auto}.log li{padding:3px 0;border-bottom:1px dashed var(--line);font-size:14px}
.notes{background:#fff7d6;border:1px solid #eedc8a;border-radius:8px;padding:10px 14px;white-space:pre-wrap;font-size:14px}
.spin{display:inline-block;width:12px;height:12px;border:2px solid var(--accent);border-right-color:transparent;border-radius:50%;animation:s 1s linear infinite;vertical-align:-1px;margin-right:6px}
@keyframes s{to{transform:rotate(360deg)}}
</style>
<script>
// Yhteinen pollaus: päivittää elävän paneelin ja lataa sivun uudelleen, kun työ päättyy
function poll(url, render, doneStates) {
  const tick = async () => {
    try {
      const s = await (await fetch(url)).json();
      render(s);
      if (doneStates.includes(s.state)) { setTimeout(() => location.reload(), 1200); return; }
    } catch (e) {}
    setTimeout(tick, 1500);
  };
  tick();
}
const esc = t => t.replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
</script>
</head><body>
<header><a href="{{ url_for('index') }}">Velho-agentti</a>
<div class="right">
<form method="post" action="{{ url_for('run_search') }}"><button class="btn" {{ 'disabled' if search_running }}>Aja haku ja arviointi</button></form>
<form method="post" action="{{ url_for('shutdown') }}" onsubmit="return confirm('Sammutetaanko Velho-agentti?')"><button class="btn dim">Sammuta</button></form>
</div></header>
<main>{% if msg %}<div class="flash">{{ msg }}</div>{% endif %}{{ body|safe }}</main>
</body></html>"""

FILL_PANEL = """
<div class="card live" id="fill">
  <div class="row"><h2 style="margin:0">Esitäyttö</h2><span class="muted" id="fill-count"></span>
    <button class="btn ghost" style="margin-left:auto" onclick="fillCmd('{{ url_for('fill_close_all') }}')">Sulje selain</button></div>
  <div id="fill-tabs"></div>
  <p class="muted">Jokainen ilmoitus on omalla välilehdellään. Agentti ei koskaan paina Lähetä-nappia – tarkista lomakkeet, hyväksy ehdot ja lähetä itse.</p>
</div>
<script>
const FILL_TITLES = {kirjoitetaan: 'Kirjoitetaan hakemusta…', jonossa: 'Jonossa…', avataan: 'Avataan hakulomaketta…',
  odotetaan: 'Odotetaan hakulomaketta…', taytetaan: 'Täytetään lomaketta…', valmis: 'Täytetty – tarkista ja lähetä',
  suljettu: 'Välilehti suljettu', lahetetty: 'Lähetetty', virhe: 'Keskeytyi'};
const FILL_BUSY = ['kirjoitetaan', 'jonossa', 'avataan', 'odotetaan', 'taytetaan'];
const FILL_ONLY = {{ only|tojson }};
const fillCmd = url => fetch(url, {method: 'POST'});
const fillUrl = (id, cmd) => "{{ url_for('fill_command', job_id=0, cmd='CMD') }}".replace('/0/', '/' + id + '/').replace('CMD', cmd);
poll("{{ url_for('fill_status') }}", s => {
  const tabs = s.tabs.filter(t => FILL_ONLY === null || t.job_id === FILL_ONLY);
  const open = s.tabs.filter(t => !['suljettu', 'lahetetty'].includes(t.state)).length;
  document.getElementById('fill-count').textContent = open + ' välilehteä auki';
  document.getElementById('fill-tabs').innerHTML = tabs.map(t => {
    const gone = ['suljettu', 'lahetetty'].includes(t.state);
    const busy = FILL_BUSY.includes(t.state);
    return '<div class="task"><div class="row">' + (busy ? '<span class="spin"></span>' : '') +
      '<b><a href="/job/' + t.job_id + '">' + esc(t.title) + '</a></b><span class="pill">' + (FILL_TITLES[t.state] || t.state) + '</span></div>' +
      '<ul class="log">' + t.log.slice(-3).map(l => '<li>' + esc(l) + '</li>').join('') + '</ul>' +
      (gone ? '' : '<div class="row" style="margin-top:8px">' +
        '<button class="btn ghost" ' + (busy && t.state !== 'odotetaan' ? 'disabled' : '') + ' onclick="fillCmd(fillUrl(' + t.job_id + ',&quot;tayta&quot;))">Täytä uudelleen</button>' +
        '<button class="btn good" onclick="fillCmd(fillUrl(' + t.job_id + ',&quot;lahetetty&quot;))">Lähetin hakemuksen</button>' +
        '<button class="btn ghost" onclick="fillCmd(fillUrl(' + t.job_id + ',&quot;sulje&quot;))">Sulje välilehti</button>' +
        (t.state === 'kirjoitetaan' ? '' : '<a class="btn ghost" href="/job/' + t.job_id + '/pdf" target="_blank">Liite-PDF ↗</a>') + '</div>') + '</div>';
  }).join('');
}, ['suljettu', 'virhe']);
</script>"""

INDEX = """
{% if search %}
<div class="card live" id="search">
  <h2><span class="spin"></span><span id="search-title">Haku ja arviointi käynnissä</span></h2>
  <ul class="log" id="search-log"></ul>
</div>
<script>
poll("{{ url_for('search_status') }}", s => {
  document.getElementById('search-title').textContent = s.title;
  const log = document.getElementById('search-log');
  log.innerHTML = s.log.slice(-12).reverse().map(l => '<li>' + esc(l) + '</li>').join('');
}, ['valmis', 'virhe']);
</script>
{% endif %}
{% if fill %}{{ fill_panel|safe }}{% endif %}
<div class="tabs">
  <a href="{{ url_for('index') }}" class="{{ 'on' if not status }}">Kaikki ({{ counts.values()|sum }})</a>
  {% for key, (label, keys) in filters.items() %}
  <a href="{{ url_for('index', tila=key) }}" class="{{ 'on' if status == key }}">{{ label }} ({{ filter_counts[key] }})</a>
  {% endfor %}
</div>
<form method="post" action="{{ url_for('prefill_many') }}" id="multi">
<div class="row" style="margin-bottom:10px">
  {% if status == "lahetetty" %}
  <button type="button" class="btn multi-act" data-label="Ota yhteyttä sähköpostilla" onclick="contact('Sähköposti')" disabled>Ota yhteyttä sähköpostilla</button>
  <button type="button" class="btn multi-act" data-label="Ota yhteyttä LinkedInissä" onclick="contact('LinkedIn')" disabled>Ota yhteyttä LinkedInissä</button>
  <span class="muted">Jokaiselle yritykselle aukeaa oma ikkuna parhaalle päättäjälle. Salli ponnahdusikkunat tälle sivulle, jos vain yksi aukeaa.</span>
  {% else %}
  <button class="btn multi-act" data-label="Esitäytä valitut" disabled>Esitäytä valitut</button>
  <span class="muted">Valitut avautuvat samaan selaimeen omille välilehdilleen. Puuttuvat hakemukset kirjoitetaan ensin.</span>
  {% endif %}
</div>
<div class="card live" id="contacts" hidden>
  <div class="row"><h2 style="margin:0">Avatut yhteydenotot</h2>
    <span class="muted">Lähetä viestit avautuneissa ikkunoissa ja merkitse ne tähän.</span></div>
  <div id="contact-rows"></div>
</div>
<table>
<tr><th><input type="checkbox" id="all" title="Valitse kaikki"></th><th>Pisteet</th><th>Ilmoitus</th><th>Lähde</th><th>Haku päättyy</th><th>Tila</th>{% if status == "lahetetty" %}<th>Johto</th>{% endif %}</tr>
{% for j in jobs %}
<tr>
  <td><input type="checkbox" name="job" value="{{ j.id }}" data-company="{{ j.company }}" data-outreach="{{ j.outreach|tojson|forceescape }}"></td>
  <td class="score">{{ j.score if j.score is not none else '–' }}</td>
  <td><a href="{{ url_for('job', job_id=j.id) }}">{{ j.title }}</a><div class="muted">{{ j.company }} · {{ j.location or '' }}</div></td>
  <td><a href="{{ j.url }}" target="_blank">{{ j.url|source }}</a></td>
  <td class="muted">{{ j.valid_through or '' }}</td>
  <td class="muted">{{ statuses[j.status] }}</td>
  {% if status == "lahetetty" %}<td>
    {% if j.outreach %}{% set sent = j.outreach.henkilot|map(attribute='lahetetty')|sum(start=[]) %}
    <a href="{{ url_for('job', job_id=j.id) }}#johto">{{ j.outreach.henkilot|length }} päättäjää</a>
    <div class="muted">{{ sent|length }} viestiä lähetetty</div>
    {% else %}<a class="btn ghost" href="{{ url_for('job', job_id=j.id) }}#johto">Ota yhteys johtoon</a>{% endif %}
  </td>{% endif %}
</tr>
{% else %}<tr><td colspan="6" class="muted">Ei ilmoituksia. Aja haku yläkulmasta.</td></tr>{% endfor %}
</table>
</form>
<script>
const boxes = [...document.querySelectorAll('#multi input[name=job]')];
const refresh = () => {
  const n = boxes.filter(b => b.checked).length;
  document.querySelectorAll('.multi-act').forEach(b => {
    b.disabled = !n;
    b.textContent = b.dataset.label + (n ? ' (' + n + ')' : '');
  });
};

// Yhteydenotto valituille: ikkunat avataan suoraan klikkauksesta (muuten selain estää ne)
const gmailUrl = (p) => 'https://mail.google.com/mail/?view=cm&fs=1&to=' + encodeURIComponent(p.sahkoposti)
  + '&su=' + encodeURIComponent(p.viesti.sposti_otsikko) + '&body=' + encodeURIComponent(p.viesti.sposti_teksti);
const liUrl = (p, company) => p.linkedin_url
  || 'https://www.linkedin.com/search/results/people/?keywords=' + encodeURIComponent(p.nimi + ' ' + company);
function contact(kanava) {
  const rows = [], missing = [], skipped = [];
  for (const b of boxes.filter(b => b.checked)) {
    const o = JSON.parse(b.dataset.outreach);
    if (!o) { missing.push(b); continue; }
    // Henkilöt ovat paremmuusjärjestyksessä: valitaan paras, jolle tämä kanava on käytettävissä
    const usable = (p) => p.viesti && (kanava === 'Sähköposti' ? p.sahkoposti : p.linkedin_url);
    let i = o.henkilot.findIndex(usable);
    if (i < 0 && kanava === 'LinkedIn') i = o.henkilot.findIndex(p => p.viesti);  // profiilia ei löytynyt: LinkedIn-haku
    if (i < 0) { skipped.push(b.dataset.company); continue; }
    rows.push({job: b.value, company: b.dataset.company, i, p: o.henkilot[i]});
  }
  rows.forEach(r => window.open(kanava === 'Sähköposti' ? gmailUrl(r.p) : liUrl(r.p, r.company), '_blank'));
  if (kanava === 'LinkedIn' && rows.length) navigator.clipboard.writeText(rows[0].p.viesti.linkedin_viesti).catch(() => {});
  missing.forEach(b => fetch('/job/' + b.value + '/johto', {method: 'POST'}));

  const panel = document.getElementById('contacts');
  panel.hidden = false;
  document.getElementById('contact-rows').innerHTML =
    rows.map((r, n) => '<div class="task row" data-n="' + n + '"><b>' + esc(r.company) + '</b> ' + esc(r.p.nimi)
      + ' <span class="muted">' + esc(r.p.rooli) + (kanava === 'Sähköposti' ? ' · ' + esc(r.p.sahkoposti) : '') + '</span>'
      + '<span style="margin-left:auto" class="row">'
      + (kanava === 'LinkedIn' ? '<button type="button" class="btn ghost copy">' + (n === 0 ? 'Kopioitu ✓' : 'Kopioi viesti') + '</button>' : '')
      + '<button type="button" class="btn good mark">Merkitse lähetetyksi</button></span></div>').join('')
    + (skipped.length ? '<p class="muted">' + (kanava === 'Sähköposti' ? 'Ei julkista sähköpostia (käytä LinkedIniä): ' : 'Ei päättäjiä: ')
       + esc(skipped.join(', ')) + '</p>' : '')
    + (missing.length ? '<p class="muted"><span class="spin"></span>Johtoa haetaan: ' + esc(missing.map(b => b.dataset.company).join(', '))
       + ' – paina nappia uudelleen, kun haku on valmis (noin 1–2 min, sivu päivittyy).</p>' : '')
    + (!rows.length && !missing.length ? '<p class="muted">Ei avattavia yhteydenottoja.</p>' : '');
  document.querySelectorAll('#contact-rows .task').forEach(el => {
    const r = rows[el.dataset.n];
    const copy = el.querySelector('.copy');
    if (copy) copy.onclick = async () => { await navigator.clipboard.writeText(r.p.viesti.linkedin_viesti); copy.textContent = 'Kopioitu ✓'; };
    el.querySelector('.mark').onclick = async (e) => {
      await fetch('/job/' + r.job + '/johto/' + r.i + '/lahetetty', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({kanava, otsikko: kanava === 'LinkedIn' ? '' : r.p.viesti.sposti_otsikko,
                              teksti: kanava === 'LinkedIn' ? r.p.viesti.linkedin_viesti : r.p.viesti.sposti_teksti})});
      e.target.textContent = 'Lähetetty ✓'; e.target.disabled = true;
    };
  });
  if (missing.length) {
    const wait = setInterval(async () => {
      const states = await Promise.all(missing.map(b => fetch('/job/' + b.value + '/johto/tila').then(r => r.json())));
      if (states.every(s => s.state !== 'kaynnissa')) { clearInterval(wait); location.reload(); }
    }, 5000);
  }
}
boxes.forEach(b => b.onchange = refresh);
document.getElementById('all').onchange = e => { boxes.forEach(b => b.checked = e.target.checked); refresh(); };
</script>"""

JOB = """
<p><a href="{{ url_for('index') }}">← Takaisin</a></p>
{% if outreach_error %}<div class="flash">{{ outreach_error }}</div>{% endif %}
<div class="card">
  <h1>{{ j.title }}</h1>
  <div class="muted">{{ j.company }} · {{ j.location or '' }} · julkaistu {{ j.posted or '?' }} · päättyy {{ j.valid_through or '?' }} · <a href="{{ j.url }}" target="_blank">Duunitori ↗</a></div>
  <div class="row" style="margin-top:12px">
    <span class="pill">{{ statuses[j.status] }}</span>
  </div>
</div>

{% if fill %}{{ fill_panel|safe }}{% endif %}

{% if a %}
<div class="card">
  <h2>Arvio: {{ a.pisteet }} / 100 · {{ a.automatisoitava_osuus_pct }} % automatisoitavissa · säästö n. {{ '{:,}'.format(a.vuosisaasto_eur).replace(',', ' ') }} €/v</h2>
  <p class="muted">{{ a.perustelu }}<br>Palkka {{ a.palkka_kk_eur }} €/kk ({{ a.palkka_lahde }}), työnantajan kustannus n. {{ '{:,}'.format(a.vuosikustannus_eur).replace(',', ' ') }} €/v.</p>
  {% for t in a.tehtavat %}<div class="task"><span class="pill {{ t.automatisoitavuus }}">{{ t.automatisoitavuus }}</span> <b>{{ t.tehtava }}</b><div class="muted">{{ t.miten }}</div></div>{% endfor %}
</div>
{% endif %}

<div class="card">
  <h2>Hakemus</h2>
  {% if app %}
  <form method="post" action="{{ url_for('save', job_id=j.id) }}">
    <textarea name="saate">{{ app.saate }}</textarea>
    <div class="row" style="margin-top:10px">
      <button class="btn ghost">Tallenna muutokset</button>
      <a class="btn ghost" href="{{ url_for('pdf', job_id=j.id) }}" target="_blank">Liite-PDF ↗</a>
    </div>
  </form>
  <div class="row" style="margin-top:14px">
    {% if not fill %}
    <form method="post" action="{{ url_for('prefill', job_id=j.id) }}"><button class="btn">{{ 'Avaa uuteen välilehteen' if busy else 'Avaa ja esitäytä hakemus' }}</button></form>
    {% endif %}
    <form method="post" action="{{ url_for('draft', job_id=j.id) }}" onsubmit="this.querySelector('button').innerHTML='<span class=spin></span>Kirjoitetaan…'"><button class="btn ghost">Kirjoita uudelleen</button></form>
  </div>
  {% else %}
  <form method="post" action="{{ url_for('draft', job_id=j.id) }}" onsubmit="this.querySelector('button').innerHTML='<span class=spin></span>Kirjoitetaan…'"><button class="btn">Kirjoita hakemus</button></form>
  <p class="muted">Claude kirjoittaa saatteen ja yksisivuisen esittelyn (PDF-liite). Kestää noin minuutin.</p>
  {% endif %}
</div>


{% if show_outreach %}
<div class="card" id="johto">
  <h2>Yhteydenotto johtoon</h2>
  {% if outreach_running %}
  <p><span class="spin"></span>Claude etsii päättäjiä verkosta ja kirjoittaa viestejä… (noin 1–2 min)</p>
  <script>poll("{{ url_for('outreach_status', job_id=j.id) }}", s => {}, ['valmis', 'virhe']);</script>
  {% elif o %}
  <p class="muted">Haettu {{ o.haettu[:16].replace('T', ' ') }}. Sähköposti näytetään vain, jos se löytyi julkisesta lähteestä.</p>
  {% for p in o.henkilot %}
  <div class="task" data-i="{{ loop.index0 }}">
    <div class="row"><b>{{ p.nimi }}</b><span class="muted">{{ p.rooli }}</span>{% if loop.first %}<span class="pill korkea">Paras</span>{% endif %}
      {% for l in p.lahetetty %}<span class="pill korkea">{{ l.kanava }} {{ l.aika[8:10] }}.{{ l.aika[5:7] }}.</span>{% endfor %}</div>
    <div class="muted">{{ p.peruste }}</div>
    <div class="muted">Lähde: {% for u in p.lahde.split(';') if u.strip() %}<a href="{{ u.strip() }}" target="_blank">{{ u.strip()|source }}</a> {% endfor %}
      {% if p.sahkoposti %}· {{ p.sahkoposti }}{% endif %}</div>
    {% if p.viesti %}
    <details style="margin-top:8px"><summary>Viestit (muokattavissa)</summary>
      <label class="muted">Sähköpostin otsikko</label>
      <input class="subj" value="{{ p.viesti.sposti_otsikko }}" style="width:100%;padding:6px;border:1px solid var(--line);border-radius:6px">
      <label class="muted">Sähköposti</label><textarea class="body" style="min-height:200px">{{ p.viesti.sposti_teksti }}</textarea>
      <label class="muted">LinkedIn (<span class="licount"></span>/300 merkkiä)</label><textarea class="li" style="min-height:90px">{{ p.viesti.linkedin_viesti }}</textarea>
    </details>
    {% endif %}
    <div class="row" style="margin-top:8px">
      <button class="btn" onclick="gmail(this)" data-to="{{ p.sahkoposti }}"
        {% if not p.sahkoposti %}disabled title="Ei julkista sähköpostiosoitetta"{% endif %}>Gmail-luonnos</button>
      <button class="btn" onclick="linkedin(this)"
        data-url="{{ p.linkedin_url or 'https://www.linkedin.com/search/results/people/?keywords=' ~ (p.nimi ~ ' ' ~ j.company)|urlencode }}">
        LinkedIn{{ '' if p.linkedin_url else ' (haku)' }}</button>
      <button class="btn ghost" onclick="sent(this, 'Sähköposti')">Merkitse: sähköposti lähetetty</button>
      <button class="btn ghost" onclick="sent(this, 'LinkedIn')">Merkitse: LinkedIn lähetetty</button>
    </div>
  </div>
  {% else %}<p class="muted">Päättäjiä ei löytynyt.</p>{% endfor %}
  <form method="post" action="{{ url_for('outreach_start', job_id=j.id) }}" style="margin-top:10px"><button class="btn ghost">Etsi uudelleen</button></form>
  {% else %}
  <p class="muted">Claude etsii verkosta toimitusjohtajan, roolin johtajan ja ilmoituksen yhteyshenkilön sekä kirjoittaa heille sähköposti- ja LinkedIn-viestit. Sinä lähetät.</p>
  <form method="post" action="{{ url_for('outreach_start', job_id=j.id) }}"><button class="btn">Etsi johto</button></form>
  {% endif %}
</div>
<script>
const row = b => b.closest('.task');
const val = (b, cls) => row(b).querySelector('.' + cls)?.value || '';
// Gmailin kirjoitusikkuna tallentuu automaattisesti Luonnoksiin
function gmail(b) {
  window.open('https://mail.google.com/mail/?view=cm&fs=1&to=' + encodeURIComponent(b.dataset.to)
    + '&su=' + encodeURIComponent(val(b, 'subj')) + '&body=' + encodeURIComponent(val(b, 'body')), '_blank');
}
async function linkedin(b) {
  try { await navigator.clipboard.writeText(val(b, 'li')); b.textContent = 'Viesti kopioitu ✓'; } catch (e) {}
  window.open(b.dataset.url, '_blank');
}
async function sent(b, kanava) {
  await fetch("{{ url_for('outreach_sent', job_id=j.id, i=0) }}".replace('/0/', '/' + row(b).dataset.i + '/'),
    {method: 'POST', headers: {'Content-Type': 'application/json'},
     body: JSON.stringify({kanava, otsikko: kanava === 'LinkedIn' ? '' : val(b, 'subj'),
                           teksti: kanava === 'LinkedIn' ? val(b, 'li') : val(b, 'body')})});
  location.reload();
}
document.querySelectorAll('#johto .li').forEach(t => {
  const c = () => t.closest('.task').querySelector('.licount').textContent = t.value.length;
  t.oninput = c; c();
});
</script>
{% endif %}

<div class="card"><h2>Ilmoitusteksti</h2><pre>{{ j.description }}</pre></div>"""

# Listan suodattimet: tunniste → (otsikko, tilat)
FILTERS = {
    "sopivat": ("Sopivat", ["arvioitu", "luonnos", "esitaytetty", "lahetetty", "vastasi"]),
    "ei_sopivat": ("Ei sopivat", ["ei_sovi", "hylatty"]),
    "lahetetty": ("Lähetetty", ["lahetetty", "vastasi"]),
    "ei_lahetetty": ("Ei lähetetty", ["arvioitu", "luonnos", "esitaytetty"]),
}


# --- Taustatyöt --------------------------------------------------------------

class SearchRun(threading.Thread):
    """Haku + arviointi taustalla; loki näytetään etusivulla."""

    def __init__(self):
        super().__init__(daemon=True)
        self.state = "kaynnissa"
        self.title = "Haetaan ilmoituksia Duunitorista…"
        self.log: list[str] = []

    def run(self):
        cfg = load_config()
        try:
            new = pipeline.search(cfg, log=self.log.append)
            self.title = f"Löytyi {new} uutta ilmoitusta – arvioidaan…"
            done = pipeline.analyze_new(cfg, log=self.log.append)
            self.title = f"Valmis: {new} uutta, {done} arvioitu"
            self.state = "valmis"
        except Exception as e:
            self.title = f"Haku keskeytyi: {e}"
            self.state = "virhe"


_search: SearchRun | None = None
_fill: FillSession | None = None


def _search_running() -> bool:
    return bool(_search and _search.state == "kaynnissa")


def _fill_alive() -> bool:
    return bool(_fill and _fill.alive)


def page(template: str, only: int | None = None, **ctx):
    """only: näytetäänkö esitäyttöpaneelissa vain tämän ilmoituksen välilehti."""
    fill_panel = render_template_string(FILL_PANEL, only=only) if ctx.get("fill") else ""
    body = render_template_string(template, statuses=db.STATUSES, fill_panel=fill_panel, **ctx)
    return render_template_string(BASE, body=body, msg=request.args.get("msg"), search_running=_search_running())


# --- Sivut -------------------------------------------------------------------

@app.get("/")
def index():
    conn = db.connect()
    status = request.args.get("tila")
    counts = dict(conn.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status").fetchall())
    all_jobs = db.list_jobs(conn)
    jobs = [j for j in all_jobs if j["status"] in FILTERS[status][1]] if status in FILTERS else all_jobs
    filter_counts = {key: sum(counts.get(k, 0) for k in keys) for key, (_, keys) in FILTERS.items()}
    return page(INDEX, jobs=jobs, status=status, counts=counts, filters=FILTERS,
                filter_counts=filter_counts, search=_search_running(), fill=_fill_alive())


@app.get("/job/<int:job_id>")
def job(job_id):
    j = db.get(db.connect(), job_id) or abort(404)
    busy = _fill_alive()
    fill = busy and _fill.tab(job_id) is not None
    run = _outreach.get(job_id)
    outreach_error = f"Johdon haku epäonnistui: {run.error}" if run and run.state == "virhe" else None
    show = j["status"] in ("lahetetty", "vastasi") or bool(j["outreach"]) or _outreach_running(job_id)
    return page(JOB, only=job_id, j=j, a=j["analysis"], app=j["application"], fill=fill, busy=busy,
                o=j["outreach"], show_outreach=show, outreach_running=_outreach_running(job_id),
                outreach_error=outreach_error)


@app.post("/job/<int:job_id>/kirjoita")
def draft(job_id):
    pipeline.draft(job_id, load_config())
    return redirect(url_for("job", job_id=job_id, msg="Hakemus kirjoitettu."))


@app.post("/job/<int:job_id>/tallenna")
def save(job_id):
    conn = db.connect()
    j = db.get(conn, job_id) or abort(404)
    application = {**j["application"], "saate": request.form["saate"]}
    db.update(conn, job_id, application=application)
    pipeline.rebuild_pdf(job_id, load_config())
    return redirect(url_for("job", job_id=job_id, msg="Tallennettu."))


# --- Yhteydenotto johtoon ------------------------------------------------------

class OutreachRun(threading.Thread):
    """Päättäjien haku ja viestien kirjoitus taustalla (noin 1–2 min)."""

    def __init__(self, job_id: int):
        super().__init__(daemon=True)
        self.job_id = job_id
        self.state = "kaynnissa"
        self.error = ""

    def run(self):
        try:
            pipeline.outreach(self.job_id, load_config())
            self.state = "valmis"
        except Exception as e:
            self.error = f"{e.__class__.__name__}: {str(e)[:200]}"
            self.state = "virhe"


_outreach: dict[int, OutreachRun] = {}


def _outreach_running(job_id: int) -> bool:
    run = _outreach.get(job_id)
    return bool(run and run.state == "kaynnissa")


@app.post("/job/<int:job_id>/johto")
def outreach_start(job_id):
    if not _outreach_running(job_id):
        _outreach[job_id] = OutreachRun(job_id)
        _outreach[job_id].start()
    return redirect(url_for("job", job_id=job_id) + "#johto")


@app.get("/job/<int:job_id>/johto/tila")
def outreach_status(job_id):
    run = _outreach.get(job_id)
    return jsonify(state=run.state if run else "valmis", error=run.error if run else "")


@app.post("/job/<int:job_id>/johto/<int:i>/lahetetty")
def outreach_sent(job_id, i):
    conn = db.connect()
    j = db.get(conn, job_id) or abort(404)
    data = j["outreach"]
    data["henkilot"][i]["lahetetty"].append({**request.get_json(), "aika": db.now()})
    db.update(conn, job_id, outreach=data)
    return ("", 204)


@app.get("/job/<int:job_id>/pdf")
def pdf(job_id):
    j = db.get(db.connect(), job_id) or abort(404)
    if not j["pdf_path"]:
        abort(404)
    return send_file(j["pdf_path"])


# --- Esitäyttö ---------------------------------------------------------------

def _start_fill(job_ids: list[int]) -> str | None:
    """Avaa ilmoitukset esitäyttöön: käynnissä olevaan selaimeen uusina välilehtinä
    tai uuteen istuntoon. Palauttaa virheviestin tai None."""
    global _fill
    if _fill_alive() and _fill.add(job_ids):
        return None
    try:
        _fill = FillSession(job_ids)
    except PrefillError as e:
        return str(e)
    _fill.start()
    return None


@app.post("/job/<int:job_id>/esitayta")
def prefill(job_id):
    error = _start_fill([job_id])
    return redirect(url_for("job", job_id=job_id, msg=error))


@app.post("/esitayta")
def prefill_many():
    job_ids = [int(i) for i in request.form.getlist("job")]
    error = _start_fill(job_ids)
    return redirect(url_for("index", msg=error or f"Esitäytetään {len(job_ids)} ilmoitusta omille välilehdilleen."))


@app.get("/esitaytto/tila")
def fill_status():
    if not _fill:
        return jsonify(state="suljettu", log=[], tabs=[])
    return jsonify(_fill.status())


@app.post("/esitaytto/<int:job_id>/<cmd>")
def fill_command(job_id, cmd):
    if cmd not in ("tayta", "lahetetty", "sulje") or not _fill_alive():
        abort(400)
    _fill.send(cmd, job_id)
    return ("", 204)


@app.post("/esitaytto/sulje")
def fill_close_all():
    if _fill_alive():
        _fill.send("sulje_kaikki")
    return ("", 204)


# --- Haku --------------------------------------------------------------------

@app.post("/aja")
def run_search():
    global _search
    if not _search_running():
        _search = SearchRun()
        _search.start()
    return redirect(url_for("index"))


@app.get("/aja/tila")
def search_status():
    if not _search:
        return jsonify(state="valmis", title="", log=[])
    return jsonify(state=_search.state, title=_search.title, log=_search.log)


@app.post("/sammuta")
def shutdown():
    if _fill_alive():
        _fill.send("sulje_kaikki")
    threading.Timer(1.0, lambda: os._exit(0)).start()
    return "<p style='font:16px system-ui;padding:40px'>Velho-agentti sammutettu. Voit sulkea tämän välilehden.</p>"


def serve(port: int = 5050) -> None:
    print(f"Hyväksyntänäkymä: http://localhost:{port}")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
