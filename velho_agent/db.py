import json
import sqlite3
from datetime import datetime

from .config import DATA_DIR, DB_PATH

# Ilmoituksen elinkaari
STATUSES = {
    "uusi": "Uusi",
    "arvioitu": "Arvioitu",
    "ei_sovi": "Ei sovi",
    "luonnos": "Hakemus luonnosteltu",
    "esitaytetty": "Esitäytetty",
    "lahetetty": "Lähetetty",
    "vastasi": "Työnantaja vastasi",
    "hylatty": "Hylätty",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ext_id TEXT UNIQUE NOT NULL,
    url TEXT NOT NULL,
    title TEXT,
    company TEXT,
    location TEXT,
    posted TEXT,
    valid_through TEXT,
    description TEXT,
    apply_url TEXT,
    search_term TEXT,
    status TEXT NOT NULL DEFAULT 'uusi',
    score INTEGER,
    analysis TEXT,
    application TEXT,
    pdf_path TEXT,
    notes TEXT,
    found_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def exists(conn, ext_id: str) -> bool:
    return conn.execute("SELECT 1 FROM jobs WHERE ext_id = ?", (ext_id,)).fetchone() is not None


def insert_job(conn, job: dict) -> bool:
    """Palauttaa False, jos ilmoitus oli jo tallessa."""
    ts = now()
    cur = conn.execute(
        """INSERT OR IGNORE INTO jobs (ext_id, url, title, company, location, posted, valid_through,
                             description, apply_url, search_term, found_at, updated_at)
           VALUES (:ext_id, :url, :title, :company, :location, :posted, :valid_through,
                   :description, :apply_url, :search_term, :ts, :ts)""",
        {**job, "ts": ts},
    )
    conn.commit()
    return cur.rowcount > 0


def update(conn, job_id: int, **fields) -> None:
    for key in ("analysis", "application"):
        if key in fields and not isinstance(fields[key], (str, type(None))):
            fields[key] = json.dumps(fields[key], ensure_ascii=False)
    fields["updated_at"] = now()
    cols = ", ".join(f"{k} = :{k}" for k in fields)
    conn.execute(f"UPDATE jobs SET {cols} WHERE id = :id", {**fields, "id": job_id})
    conn.commit()


def get(conn, job_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _to_dict(row) if row else None


def list_jobs(conn, status: str | None = None) -> list[dict]:
    if status:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE status = ? ORDER BY score DESC NULLS LAST, found_at DESC", (status,)
        )
    else:
        rows = conn.execute("SELECT * FROM jobs ORDER BY score DESC NULLS LAST, found_at DESC")
    return [_to_dict(r) for r in rows]


def _to_dict(row) -> dict:
    d = dict(row)
    for key in ("analysis", "application"):
        d[key] = json.loads(d[key]) if d.get(key) else None
    return d
