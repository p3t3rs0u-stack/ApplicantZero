"""Duunitorin hakutulosten ja ilmoitusten luku.

Haku tehdään hitaasti, tunnistettavalla User-Agentilla, eikä estoja kierretä:
403/429 pysäyttää ajon.
"""

import html
import json
import re
import time
from urllib.parse import quote_plus, urljoin

import httpx
from bs4 import BeautifulSoup

BASE = "https://duunitori.fi"
USER_AGENT = "Mozilla/5.0 (compatible; VelhoAgent/0.1; +https://velho.io)"


class Blocked(Exception):
    pass


class DuunitoriClient:
    def __init__(self, delay_s: float = 10):
        self.delay_s = delay_s
        self._last = 0.0
        self.http = httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=30)

    def _get(self, url: str) -> str:
        wait = self._last + self.delay_s - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        resp = self.http.get(url)
        self._last = time.monotonic()
        if resp.status_code in (403, 429):
            raise Blocked(f"Duunitori vastasi {resp.status_code} – haku pysäytetään.")
        resp.raise_for_status()
        return resp.text

    def search(self, term: str, page: int = 1) -> list[dict]:
        """Palauttaa hakutulokset (ei 'Duunitori suosittelee' -nostoja)."""
        url = f"{BASE}/tyopaikat?haku={quote_plus(term)}"
        if page > 1:
            url += f"&sivu={page}"
        soup = BeautifulSoup(self._get(url), "html.parser")
        results = []
        for a in soup.select("a.job-box__hover.gtm-search-result"):
            results.append({
                "ext_id": "duunitori:" + a.get("data-id", a["href"]),
                "url": urljoin(BASE, a["href"]),
                "title": a.get_text(strip=True),
                "company": a.get("data-company"),
            })
        return results

    def fetch_job(self, url: str) -> dict:
        soup = BeautifulSoup(self._get(url), "html.parser")
        posting = {}
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict) and data.get("@type") == "JobPosting":
                posting = data
                break

        apply = soup.select_one("a.apply--button")
        apply_href = apply.get("href") if apply else None
        # '#...' tarkoittaa Duunitorin omaa "Hae helposti" -lomaketta ilmoitussivulla
        apply_url = url if not apply_href or apply_href.startswith("#") else urljoin(url, apply_href)

        return {
            "title": posting.get("title"),
            "company": (posting.get("hiringOrganization") or {}).get("name"),
            "location": _location(posting.get("jobLocation")),
            "posted": (posting.get("datePosted") or "")[:10] or None,
            "valid_through": (posting.get("validThrough") or "")[:10] or None,
            "description": _clean(posting.get("description") or _page_text(soup)),
            "apply_url": apply_url,
        }


def _location(loc) -> str | None:
    if isinstance(loc, list):
        loc = loc[0] if loc else None
    if not isinstance(loc, dict):
        return None
    return (loc.get("address") or {}).get("addressLocality")


def _clean(text: str) -> str:
    text = BeautifulSoup(html.unescape(text), "html.parser").get_text("\n")
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def _page_text(soup: BeautifulSoup) -> str:
    main = soup.select_one(".description, main") or soup
    return main.get_text("\n", strip=True)
