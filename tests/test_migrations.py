"""The migration chain builds the whole schema on an empty database, and every migration downgrades (upgrade head,
downgrade base, upgrade head on paimana_test; the schemas themselves stay, env.py creates them)."""
import sys
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import settings as cfg  # noqa: E402
from conftest import alembic_config  # noqa: E402

HANDOFF = ["001_core_identity", "84b98df29a61", "b704a78e671f", "004_model_artifact_checksum",
           "005_ingestion_staging"]   # Manamrit's chain, byte-identical files
OURS = ["1f3a9c2d7b40", "2c8d4e6f1a57", "3e5f7a9b2c68", "4a6b8c0d3e79", "5b7c9d1e4f80", "6c8e0a2b4d91"]
TABLES = {
    "ingest": {"source_documents", "load_runs", "staging_project_observations"},
    "core": {"projects", "project_keys", "project_timeline"},
    "ml": {"model_registry", "predictions", "risk_flags", "forecasts", "agency_stats"},
    "app": {"sources", "job_runs", "alerts", "watchlist", "signals", "signal_projects", "scouted", "audit_log",
            "briefs", "research_facts", "researched", "signal_judgements", "second_opinions", "users", "sessions",
            "signup_requests", "login_attempts", "rag_chunks", "rag_meta", "password_resets"},
}
SQL = """SELECT table_schema, table_name FROM information_schema.tables
         WHERE table_schema IN ('ingest', 'core', 'ml', 'app') AND table_type = 'BASE TABLE'"""


def tables(con) -> dict[str, set[str]]:
    out = {}
    for schema, name in con.execute(sa.text(SQL)):
        out.setdefault(schema, set()).add(name)
    return out


def test_chain_is_linear_and_ends_with_ours():
    script = ScriptDirectory.from_config(alembic_config())
    revs = [r.revision for r in script.walk_revisions()][::-1]   # base first
    assert revs == HANDOFF + OURS and script.get_heads() == [OURS[-1]]


def test_upgrade_downgrade_upgrade():
    c = alembic_config()
    e = sa.create_engine(cfg.settings.database_url)
    command.upgrade(c, "head")
    with e.connect() as con:
        assert tables(con) == TABLES
        assert con.execute(sa.text("SELECT version_num FROM alembic_version")).scalar() == OURS[-1]
        cols = {r[0] for r in con.execute(sa.text("SELECT column_name FROM information_schema.columns "
                                                  "WHERE table_schema = 'ml' AND table_name = 'predictions'"))}
        assert {"p_any_2q", "months_p95", "cost_pct_p05", "tier_rank_pct", "stagnation_override"} <= cols
        assert con.execute(sa.text("SELECT count(*) FROM pg_extension WHERE extname IN ('citext', 'vector')")).scalar() == 2
        idx = con.execute(sa.text("SELECT indexdef FROM pg_indexes WHERE schemaname = 'app' AND indexname = "
                                  "'rag_chunks_embedding'")).scalar()
        assert "hnsw" in idx and "vector_cosine_ops" in idx
        roles = con.execute(sa.text("SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                                    "WHERE conname = 'ck_users_role'")).scalar()
        assert "developer" in roles   # the hidden role (backend/access.py); sign-up requests keep three
        assert "developer" not in con.execute(sa.text("SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                                                      "WHERE conname = 'ck_signup_requests_role'")).scalar()
        one = con.execute(sa.text("SELECT indexdef FROM pg_indexes WHERE indexname = 'signup_requests_one_pending'"))
        assert "UNIQUE" in one.scalar()
    command.downgrade(c, "base")
    with e.connect() as con:
        assert tables(con) == {}
        assert con.execute(sa.text("SELECT count(*) FROM alembic_version")).scalar() == 0
    command.upgrade(c, "head")
    with e.connect() as con:
        assert tables(con) == TABLES
    e.dispose()


def test_app_constraints_hold():
    e = sa.create_engine(cfg.settings.database_url)
    with e.connect() as con:
        for sql in ("INSERT INTO app.alerts (created_at, kind, severity) VALUES (now(), 'nope', 2)",
                    "INSERT INTO app.alerts (created_at, kind, severity) VALUES (now(), 'signal', 4)",
                    "INSERT INTO app.users (email, password_hash, role) VALUES ('a@b.c', 'x', 'public')",
                    "INSERT INTO ml.model_registry (model_name, model_version, model_type, target_name, "
                    "feature_version, gold_version, is_champion) VALUES ('m', 'v1', 't', 'y', 'f', 'g', TRUE), "
                    "('m', 'v2', 't', 'y', 'f', 'g', TRUE)"):
            try:
                with con.begin_nested():
                    con.execute(sa.text(sql))
            except sa.exc.IntegrityError:
                continue
            raise AssertionError(f"accepted: {sql}")
        con.rollback()
    e.dispose()
