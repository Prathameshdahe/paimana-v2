"""Manamrit's engine factory for the loader and check scripts under database/postgres/ (his handoff, 2026-09-28).

Adopted into PAIMANA: the URL now comes from backend/settings.py (DATABASE_URL, with his DB_USER/DB_PASSWORD/
DB_HOST/DB_PORT/DB_NAME as the fallback), so the scripts and the backend read the same .env / .env.db. The backend
itself does not use this: it has one pooled engine in backend/db/engine.py.
"""
import sys
from pathlib import Path

from sqlalchemy import create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend import settings as cfg  # noqa: E402


def get_engine():
    return create_engine(cfg.settings.database_url)
