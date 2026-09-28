"""Typed settings of the backend, read once at import: the repo root's .env, then .env.db (both optional), then the
process environment, a later source winning. Every module reads its settings from here (llm/client.py keeps its own
load_dotenv of .env for the CLI tools). The env name of a field is its upper-case name (SECURE_COOKIES,
ALLOWED_ORIGINS ...); a list is comma-separated; a bool is 1/0, true/false, yes/no, on/off. `.env.example` documents
every variable.

database_url: inside the compose stack, where POSTGRES_HOST is set, it is built from POSTGRES_USER / POSTGRES_PASSWORD /
POSTGRES_HOST / POSTGRES_HOST_PORT (5432) / POSTGRES_DB, whatever DATABASE_URL says (that one is for tools on the host,
against the published port); otherwise DATABASE_URL, else Manamrit's DB_USER/DB_PASSWORD/DB_HOST/DB_PORT/DB_NAME,
else POSTGRES_USER/POSTGRES_PASSWORD/POSTGRES_PORT/POSTGRES_DB on localhost, else a password-less local default that
fails clearly. reload() rebuilds `settings` after the environment changed (the tests point DATABASE_URL at
paimana_test); modules read `settings` through this module (`from backend import settings as cfg; cfg.settings.x`),
not a copy.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib.parse import quote

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
ENV_FILES = (".env", ".env.db")
DEFAULT_ORIGINS = ("http://localhost:3000", "http://localhost:5173", "http://localhost:5174")
TRUE, FALSE = {"1", "true", "yes", "on"}, {"0", "false", "no", "off", ""}


@dataclass(frozen=True)
class Settings:
    database_url: str
    secure_cookies: bool = False
    allowed_origins: tuple[str, ...] = DEFAULT_ORIGINS
    allowed_hosts: tuple[str, ...] = ("*",)
    trusted_proxies: tuple[str, ...] = ()
    session_idle_h: int = 12
    session_max_d: int = 7
    duckdb_memory_limit: str = "2GB"
    duckdb_threads: int = 4
    live_jobs: bool = True
    llm_base_url: str = "http://localhost:1234/v1"
    llm_model: str = "qwen/qwen2.5-coder-14b"
    llm_chat_model: str = ""          # empty: llm_model (llm/client.py)
    llm_embed_model: str = "text-embedding-nomic-embed-text-v1.5"
    admin_email: str | None = None
    allowed_email_domains: tuple[str, ...] = ()
    api_docs: bool = True             # /docs, /redoc and /openapi.json (0 in production)

    @property
    def database_name(self) -> str:
        return self.database_url.rsplit("/", 1)[-1].split("?")[0]

    @property
    def database_host(self) -> str:
        """host:port/database, for messages (never the password)."""
        tail = self.database_url.split("@")[-1]
        return tail if "@" in self.database_url else tail.split("://")[-1]


def _bool(v: str | None, default: bool) -> bool:
    if v is None:
        return default
    s = v.strip().lower()
    if s in TRUE:
        return True
    if s in FALSE:
        return False
    raise ValueError(f"not a boolean: {v!r}")


def _int(v: str | None, default: int) -> int:
    return default if v is None or not v.strip() else int(v)


def _list(v: str | None, default: tuple[str, ...]) -> tuple[str, ...]:
    return default if v is None else tuple(x.strip() for x in v.split(",") if x.strip())


def _url(user: str, password: str | None, host: str, port: str | int, name: str) -> str:
    auth = quote(user, safe="") + (f":{quote(password, safe='')}" if password else "")
    return f"postgresql+psycopg://{auth}@{host}:{port}/{name}"


def _database_url(env: Mapping[str, str]) -> str:
    # inside the compose stack (POSTGRES_HOST=postgres) the URL is built from the .env.db credentials and the
    # service's own port, whatever DATABASE_URL says: that one points at the port published on the host
    if env.get("POSTGRES_HOST") and env.get("POSTGRES_USER") and env.get("POSTGRES_DB"):
        return _url(env["POSTGRES_USER"], env.get("POSTGRES_PASSWORD"), env["POSTGRES_HOST"],
                    env.get("POSTGRES_HOST_PORT") or 5432, env["POSTGRES_DB"])
    if env.get("DATABASE_URL"):
        return env["DATABASE_URL"]
    for user, password, host, port, name in (("DB_USER", "DB_PASSWORD", "DB_HOST", "DB_PORT", "DB_NAME"),
                                             ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_HOST", "POSTGRES_PORT",
                                              "POSTGRES_DB")):
        if env.get(user) and env.get(name):
            return _url(env[user], env.get(password), env.get(host) or "localhost", env.get(port) or 5432, env[name])
    return "postgresql+psycopg://paimana@localhost:5432/paimana"


def environment(root: Path = ROOT) -> dict[str, str]:
    """The merged environment: the env files under root in ENV_FILES order, then the process environment."""
    out: dict[str, str] = {}
    for name in ENV_FILES:
        out.update({k: v for k, v in dotenv_values(root / name).items() if v is not None})
    out.update(os.environ)
    return out


def load(env: Mapping[str, str] | None = None) -> Settings:
    e = environment() if env is None else env
    d = Settings.__dataclass_fields__
    return Settings(
        database_url=_database_url(e),
        secure_cookies=_bool(e.get("SECURE_COOKIES"), d["secure_cookies"].default),
        allowed_origins=_list(e.get("ALLOWED_ORIGINS"), DEFAULT_ORIGINS),
        allowed_hosts=_list(e.get("ALLOWED_HOSTS"), ("*",)),
        trusted_proxies=_list(e.get("TRUSTED_PROXIES"), ()),
        session_idle_h=_int(e.get("SESSION_IDLE_H"), d["session_idle_h"].default),
        session_max_d=_int(e.get("SESSION_MAX_D"), d["session_max_d"].default),
        duckdb_memory_limit=e.get("DUCKDB_MEMORY_LIMIT") or d["duckdb_memory_limit"].default,
        duckdb_threads=_int(e.get("DUCKDB_THREADS"), d["duckdb_threads"].default),
        live_jobs=_bool(e.get("LIVE_JOBS"), d["live_jobs"].default),
        llm_base_url=e.get("LLM_BASE_URL") or d["llm_base_url"].default,
        llm_model=e.get("LLM_MODEL") or d["llm_model"].default,
        llm_chat_model=e.get("LLM_CHAT_MODEL") or "",
        llm_embed_model=e.get("LLM_EMBED_MODEL") or d["llm_embed_model"].default,
        admin_email=e.get("ADMIN_EMAIL") or None,
        allowed_email_domains=_list(e.get("ALLOWED_EMAIL_DOMAINS"), ()),
        api_docs=_bool(e.get("API_DOCS"), d["api_docs"].default),
    )


settings = load()


def reload() -> Settings:
    """Rebuild `settings` from the environment as it is now; returns it."""
    global settings
    settings = load()
    return settings
