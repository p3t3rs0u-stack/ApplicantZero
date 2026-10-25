from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
PDF_DIR = DATA_DIR / "liitteet"
DB_PATH = DATA_DIR / "velho.db"
BROWSER_PROFILE = DATA_DIR / "selainprofiili"

load_dotenv(ROOT / ".env")


def load_config() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def missing_applicant_fields(cfg: dict) -> list[str]:
    hakija = cfg.get("hakija") or {}
    return [k for k in ("etunimi", "sukunimi", "sahkoposti") if not hakija.get(k)]
