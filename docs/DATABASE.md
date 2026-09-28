# The database

PAIMANA has two kinds of truth (Manamrit's principle, `database/postgres/README.md`):

- **Parquet through DuckDB is the analytical truth.** `backend/serving.py` reads `dataset/silver/` and
  `dataset/gold/` into an in-memory DuckDB and serves every number from there. The pipeline writes them
  (`python -m pipeline.run ...`). Nothing here changed in Segment 9.
- **PostgreSQL is the application truth.** Everything that used to live in SQLite (`database/paimana.db`), the
  users and sessions of the real sign-in, the assistant's search index, and a serving copy of the projects, timeline,
  scores, flags and forecasts in Manamrit's `ingest` / `core` / `ml` tables.

The server is PostgreSQL 16 with pgvector (the `pgvector/pgvector:pg16` image of the compose stack; in dev
`paimana-postgres-dev` on port 5433, because a native PostgreSQL holds 5432 on the team laptop). The credentials live
in `.env.db` (gitignored): `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_PORT` and `DATABASE_URL`
(`postgresql+psycopg://user:password@host:port/database`). `backend/settings.py` reads `.env`, then `.env.db`, then
the process environment; `DATABASE_URL` wins, else it is built from `POSTGRES_*` (or Manamrit's `DB_*`).

## Schemas

| Schema | Tables | Written by | Read by |
|---|---|---|---|
| `app` | `alerts`, `watchlist`, `signals`, `signal_projects`, `scouted`, `job_runs`, `sources`, `audit_log`, `briefs`, `research_facts`, `researched`, `signal_judgements`, `second_opinions` | `backend/db` (the API, the scheduler's jobs, the LLM modules) | the same, `llm/rag.py`, `pipeline/bottlenecks.py` |
| `app` | `users`, `sessions`, `signup_requests`, `login_attempts` | `backend/auth` (Segment 9 unit B) | `backend/access.py` |
| `app` | `rag_chunks` (pgvector, HNSW cosine index), `rag_meta` | the assistant's index builder | the assistant's search |
| `ingest` | `source_documents`, `load_runs`, `staging_project_observations` | the report watcher (a document and an INGEST run per accepted report), `pipeline/serve.py` (a SERVING run per load); staging is Manamrit's silver-CSV flow, unused by the app | lineage queries |
| `core` | `projects`, `project_keys`, `project_timeline` | `pipeline/serve.py` from silver | serving copies (the API keeps reading DuckDB) |
| `ml` | `model_registry`, `predictions`, `risk_flags`, `forecasts`, `agency_stats`, view `current_predictions` | `pipeline/serve.py` from gold and `model/registry.json` | serving copies |

`app` mirrors the Segment 8 SQLite tables column for column, with PostgreSQL types: `timestamptz` for every `*_at`,
`date` for `asof` and the fact dates, `boolean` for the 0/1 flags, `jsonb` for the JSON columns, `bigserial` ids.
`audit_log` has an id and the `user_id` / `email` / `ip` columns the authenticated routes fill.

The `backend/db` package is the only code that runs SQL against the database: `engine.py` (one pooled engine over
psycopg 3, `connect()` a transaction, `read()` autocommit, `healthy()` the readiness probe with a 2 s timeout),
`migrate.py` (Alembic from Python; `db.init()` at every backend start upgrades to the head and seeds the alert feed),
`app.py` (the helpers: every function of the old `backend/db.py` with the same name, signature and return shape,
plus the readers and writers the scout, the research agent, the assistant's index, the bottleneck step and the tests
use), `serve.py` (the loaders of `pipeline/serve.py`) and `migrate_sqlite.py` (below). Rows come back as dicts with
ISO-8601 timestamps (UTC, to the second), `YYYY-MM-DD` dates and ints for the flags, as they did from SQLite. A
viewer's project keys are one array parameter (`project_key = ANY(:keys)`).

## Migrations

`alembic.ini` sits at the repo root and points at `database/postgres/migrations`. Manamrit's five migrations are
byte-identical to his handoff (`001_core_identity` → `84b98df29a61` → `b704a78e671f` → `004_model_artifact_checksum`
→ `005_ingestion_staging`); PAIMANA's continue the chain: `1f3a9c2d7b40` (the app state tables), `2c8d4e6f1a57`
(users, sessions, sign-up requests, login attempts; `citext` for emails), `3e5f7a9b2c68` (`rag_chunks` with the
`vector` extension and its HNSW index, `rag_meta`), `4a6b8c0d3e79` (the served scores as columns of
`ml.predictions`, a CHECK on our tiers, `run_id` / `entry_id` / `feature_list_json` on `ml.model_registry`).
`migrations/env.py` creates the four schemas if missing and takes an advisory lock, so the compose `migrate` service
and the API's own `db.init()` can both run.

```
python -m alembic upgrade head        # build or update the whole schema on any database (empty included)
python -m alembic current             # the database's revision
python -m alembic downgrade -1        # undo the last migration (every migration downgrades)
python -m alembic revision -m "..."   # a new migration after the head; keep it idempotent-safe with a downgrade
```

The backend runs the upgrade itself at start (`db.init()`), so a fresh database needs nothing but the credentials.

## The one-time copy of the old SQLite state

A database from before Segment 9 (`database/paimana.db`: alerts, watchlists, news signals and links, scouted rows,
audit log, briefs, research facts and judgements, second opinions, job runs, ingested sources) is copied once with

```
python -m backend.db.migrate_sqlite database/paimana.db
```

Ids are kept (the alert stream and the signal links refer to them) and the sequences moved past them; every insert is
`ON CONFLICT DO NOTHING`, so a second run copies nothing and the counts per table are printed each time. The SQLite
file is not read by anything afterwards (`PAIMANA_DB` is gone).

## The serving tables

`python -m pipeline.run serve` (the report watcher runs it after `profile`, best-effort: a database outage does not
undo an ingested report, it is logged, alerted as `pipeline_error` and the next serve run catches up) loads,
idempotently:

- `core.projects` from silver `project_master.parquet` (every canonical key; `is_current` = in the latest report),
- `core.project_keys` from the identity aliases (`dataset/silver/identity/aliases.parquet`: each source key with its
  canonical key, match method and score and review status; `merged_into` when a key was merged),
- `core.project_timeline` from silver `observations.parquet` (one row per project and period, with the source
  document, page and silver version; the document is registered in `ingest.source_documents` with its sha256 when
  the raw file is present under `Dataset drive folder/Dataset`, else only `source_file` names it),
- `ml.model_registry` from `model/registry.json`: every champion entry (metrics, params, feature list, artifact path,
  the sha256 of the model file) and one row for the served combination of champions (`model_version` of
  `predictions_latest.json`), the champion of `target_name` `served`,
- `ml.predictions` from the served predictions parquet (our tier in `risk_tier`, the four probabilities and the
  quantiles as columns, SHAP and the rest in `prediction_payload`), `ml.risk_flags` from the flagged rows of the risk
  profile, `ml.forecasts` (scenarios, analogues and the completion band per project) and `ml.agency_stats`.

It prints the counts per table and writes an `ingest.load_runs` row (`run_type` SERVING). `backend/serving.py` keeps
reading DuckDB: these tables are the application-side copy Manamrit's contracts describe, for the dashboard queries
of the next segments and for anyone joining on `canonical_project_key`.

## Model integrity

`model/registry.json` records `artifact_sha256` for every entry (`python -m ml.registry seal` fills it for entries
registered before the field existed; a train run records it as it registers). `serving.state()` verifies the
champion model files against it every time a data version loads and refuses a mismatch: the old version stays served,
the failure is logged and a `pipeline_error` alert is raised. `GET /api/models` shows the sha256 next to each entry.

## Backups

`scripts/backup` runs `pg_dump -Fc` into `backups/` (the compose `backup` sidecar does it daily, 14-day retention;
`backups/` is gitignored) and `scripts/restore` loads one; `docs/DEPLOYMENT.md` has the procedure and the password
rotation. The Parquet data is rebuilt by the pipeline from `dataset/raw/`, which is never edited in place.

## Tests

The tests run against the database `paimana_test` on the same server (`tests/conftest.py` swaps the name in
`DATABASE_URL`; `TEST_DATABASE_URL` overrides it for the CI's Postgres service). The session fixture upgrades it to
the head once; every table of `app`, `ingest`, `core` and `ml` is emptied before each test module, and a test that
needs an empty database takes the `fresh_db` fixture. A PostgreSQL that cannot be reached fails every test with one
clear message; nothing is skipped. `tests/test_migrations.py` runs upgrade head → downgrade base → upgrade head.
