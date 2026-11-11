"""Database connection configuration from environment variables (no hardcoded credentials).

Variables: RSI_DB_HOST, RSI_DB_PORT, RSI_DB_NAME, RSI_DB_USER, RSI_DB_PASSWORD.
Values already present in the process environment take precedence; otherwise they are read
from the project's local `.env` file (simple KEY=VALUE lines; never commit or share it).
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ("RSI_DB_HOST", "RSI_DB_PORT", "RSI_DB_NAME", "RSI_DB_USER", "RSI_DB_PASSWORD")


def _load_dotenv(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def conninfo() -> dict:
    """Keyword arguments for psycopg.connect()."""
    _load_dotenv()
    missing = [k for k in REQUIRED if not os.environ.get(k)]
    if missing:
        raise RuntimeError(f"Missing database settings: {', '.join(missing)} (see .env.example)")
    return {
        "host": os.environ["RSI_DB_HOST"],
        "port": int(os.environ["RSI_DB_PORT"]),
        "dbname": os.environ["RSI_DB_NAME"],
        "user": os.environ["RSI_DB_USER"],
        "password": os.environ["RSI_DB_PASSWORD"],
        "application_name": "rsi_pipeline",
    }


def safe_description() -> str:
    """Connection description without the password (for logs/reports)."""
    c = conninfo()
    return f"postgresql://{c['user']}@{c['host']}:{c['port']}/{c['dbname']}"
