# Security

What PAIMANA does about the items of the team's security plan (the 24-point checklist: data pipeline integrity,
identity, quarantine, the model, poisoning, report remarks, the LLM's place, SHAP, intervals, calibration, agency
names, the agency flag, PARIVESH, early notice, scenarios, the API boundary, roles, the agent, read-mostly AI, tests),
and what it does not. Each point names the code that holds it and the test that checks it. Nothing here is a
promise: where a control is missing it says so. The plan's own advice stands: layered and practical, no blockchain,
no encryption everywhere, no zero trust.

Sections: **Data** (the pipeline, identity, external sources), **Model** (the registry, the scores, what the LLM may
not touch), **AI** (the assistant, the second opinion, the jobs), **API** (sign-in, sessions, roles, what a request
must carry, the api's own protections) and **Deployment** (TLS, headers, rate limits, backups).

## Data

**Source integrity (plan 1).** Reports enter through `dataset/raw/inbox/` and `POST /api/jobs/ingest`
(`backend/live/watcher.py`). Every file is hashed (sha256) before anything reads it; the hash and the hash of the
pipeline and model code (`pipeline_version`) are recorded with the file's name, kind, period, row count, status and
error in the app database (`sources`; the database unit of this segment moves the record into
`ingest.source_documents` and the run into `ingest.load_runs`), and the same bytes are never processed twice by the
same code. A processed file is moved, not edited, into `dataset/raw/csv/<fiscal year>/` or `raw/pdf/<fiscal year>/`;
the raw layer is the archive and no step writes into it. An upload keeps only the base name of what the browser
sent, replaces every character outside a small set, accepts `.csv` and `.pdf` only, streams to a temporary file
under a 100 MB cap and renames it into the inbox (`save_upload`; `tests/test_input_validation.py`,
`tests/test_watcher.py`). Not done: the archive is not signed, so the hash says which bytes were ingested, not
whether they are the ministry's; a file tampered with before its first ingest is not detectable from the hash alone.
The place to add that is a manifest of the archive kept outside the server.

**Validation between layers (plan 1, 3).** `clean -> silver` runs typed parsing and the quarantine rules
(`pipeline/silver.py` `quarantine_rules`: expenditure anomalies, completion before sanction, placeholder dates,
negative money, duplicate key-periods). A row failing a rule goes to `silver/quarantine/<rule>.parquet` with the rule
named, and `summary.csv` counts them; the panel is built from the kept rows only. Quarantined rows never merge back:
the only way one re-enters is a changed rule or a corrected source and a rebuild, both of them commits. Per-quarter
coverage (`silver/coverage.parquet`) records the share of key fields present, so a quarter with thin data is visible
downstream (the backtest uses it to pick reliable cutoffs). `silver -> gold`: every feature is point-in-time and the
build asserts it (`pipeline/gold.py` `truncation_check` rebuilds the features on a truncated panel at four cutoffs
and requires identical frames; `tests/test_gold.py::test_features_at_t_same_on_truncated_panel`). Not done: the
quarantine decisions are not versioned per row with a reviewer; there is no reviewer yet (sign-in arrives in this
segment), so today a decision is a commit.

**Identity (plan 2, 11).** The PRJ- keys live in the identity map (`pipeline/identity/identity_map.py`): each
resolution keeps the original name, the source, the generated key, `match_score`, `match_method`, `review_status`
(`accepted` or `review`), `run_id` and `resolved_at`. Only accepted rows enter `silver/observations.parquet`; the
uncertain ones are kept apart in `observations_review.parquet` and the app shows them with a badge. Ambiguous pairs
are never forced into one identity (`tests/test_identity.py`, `tests/test_build_identity.py`). Agency names are
normalised to one canonical agency each (`gold/agency_map.csv`, `pipeline/agency.py`: NHAI and its long forms are one
agency), and every agency count, matrix point and scope uses the canonical name. Not done: no record of who approved
a manual resolution; the field to fill once there are users is the map's `run_id`/`resolved_at` pair.

**External sources (plan 5, 13).** Every external fact keeps its provenance: PARIVESH rows carry the proposal id,
stage, dates and the retrieval date, and the dashboard snapshots are archived per date (`pipeline/parivesh.py`,
`backend/live/portals.py`); the Bhoomi Rashi register keeps each pull's date; a web research fact carries source,
url, published and event date (with its precision), `researched_on`, the basis and, for the sweep, a second agent's
check (`pipeline/research.py`). Each checklist row shows its `evidence`, `source` and `as_of_date`
(`ml/risk_profile.py`), so the page says "environmental clearance reported as pending on PARIVESH at <date>", not
"the model established it". Web research and news are evidence next to the score, never a model input
(`dataset/raw/external/research/README.md` says why: hindsight, notoriety bias, no point-in-time history). The
synthetic mock data can never reach the pipeline (`tests/test_external_crosscheck.py::
test_mock_data_never_reaches_the_pipeline`: no module under `pipeline/`, `ml/` or `backend/` may name it and every
gold key is a PRJ- key). Not done: the external sources are not signed either; a wrong article gives a wrong fact,
which is why a fact is shown with its link and its date and flags a checklist row only when live, negative,
severity 2 or more and a high-confidence match, and never clears one.

**Privacy floor (plan 6, 13).** No private person is named anywhere the app shows or the model reads:
`pipeline/research.private_names` rejects a text with an honorific followed by a capitalised word unless it names an
organisation or a place; the sweep file is checked line by line (`tests/test_research_pipeline.py::
test_committed_sweep_names_no_private_person`), the research agent rejects such a headline before any LLM call and
its summaries after, the second opinion drops such a headline from its pack and rejects a reply that names a person,
and the search index never holds a research agent headline. PARIVESH keeps a proposal's name only for a government
body and stores no e-mail (`tests/test_parivesh.py`).

**Serving under failure (plan 1, 23).** The serving version file is written last by the profile step, so a
half-written data set is never picked up; the watcher pins the served version while a pipeline runs and a failed
step keeps the previous scores (`tests/test_watcher.py::test_failed_step_keeps_the_old_predictions`); a reload that
fails keeps serving the loaded version, raises one `pipeline_error` alert and retries later; DuckDB runs under a
memory and thread cap; every background job has a time limit and the LLM jobs a stop flag (`backend/serving.py`,
`backend/live/scheduler.py`; `tests/test_api.py`, `tests/test_live.py`). Not done: a pipeline step writes its own
output files in place, so a crash mid-step can leave that step's file truncated on disk; the running process keeps
the old version, but a restart would then fail to load until the step is rerun (`pipeline/run.py` says which files).

## Model

**Registry and versions (plan 4).** `model/registry.json` records every trained entry: `run_id`, `entry_id`, the
`gold_version` and `silver_version` it was trained on, `params`, `feature_list`, the metrics of every block
(validation, flash, test), the backtest windows, the artifact paths and `created_at`; `champions` names the served
entry per target and `decisions` logs every promotion with its reason. A challenger is promoted only when its PR-AUC
gain is not below zero on both blocks, above the seed noise on one, and its calibration error within a slack
(`ml/registry.py` `promote`; `tests/test_registry.py`). Served scores are produced by refitting the champion's
type, params and feature list on the labelled rows at scoring time (`ml/score.py`), so a served score is reproducible
from the registry entry and the gold version rather than trusted to a binary; `GET /api/models` shows the run, the
champion and the backtest. The code that turns a report into scores is hashed per ingest (`pipeline_version`). Not
done in this unit: a checksum of the model artifacts and their verification at load; the database unit of this
segment records each artifact's sha256 in `ml.model_registry` and `serving.state()` refuses a mismatch. The registry
holds no git commit; `run_id` and `pipeline_version` are the version marks.

**Poisoning (plan 5).** The model's inputs are the silver panel, the sector context and the report-remark events;
web research, news and the LLM's output are never features (`pipeline/gold.py` `FEATURE_GROUPS`,
`docs/EXTERNAL_RESEARCH_2026-09.md`). The point-in-time guard above keeps a later report from leaking into an earlier
row, and the agency context uses only outcomes realised by the row's date (`tests/test_gold.py::
test_agency_stats_count_only_realised_labels`).

**The LLM never changes a score (plan 7).** Tiers come from `ml/score.py` (rank by `p_any_2q`) and the checklist
from `ml/risk_profile.py`; no module under `llm/` writes a score, a tier, a checklist row, a user or a permission.
The second opinion stores its own `concern` and a computed `vs_model` next to the tier and cannot move it
(`llm/second_opinion.py`; `docs/SECOND_OPINION.md`); the worker cell's memos are drafts with status `pending` that
only the role they are addressed to can approve (`backend/store.py`, `tests/test_access.py::
test_memos_reach_the_official_they_are_addressed_to`).

**SHAP stays SHAP (plan 8).** Drivers are shown as the feature, its value and its contribution, in plain labels
(`backend/labels.py`, mirrored by the frontend); the chat's `explain_prediction` says "raises the risk" or "lowers
the risk" per driver and never turns a lag into a cause. Causes come from evidence with a source (events, PARIVESH,
research), listed separately.

**Intervals and calibration (plan 9, 10).** The served 5-95% bands are backtested on every train run
(`intervals.csv`: coverage, share below and above, width, pinball loss). The month bands cover about right in the
quarterly era and miss on the upper side in the flash era (9.9% of flash projects slipped past p95); the cost bands
over-cover (`docs/MODEL_UPGRADES_2026-09.md`, Interval honesty). The page and the prompts call the band a modelled
5-95% range with that caveat, not a validated confidence interval, and the public page gets the median only. The
probabilities are ranking scores: only the cost-revision target is Platt-calibrated (`ml/backtest.py` `CALIBRATED`),
the second-opinion pack and the chat say "ranking scores, not calibrated frequencies", and the tiers are rank
shares, not probability cut-offs.

**Agency flag (plan 12).** The matrix shows a historical indicator, not a verdict: the median schedule and cost bias
per canonical agency with IQR and a bootstrap 90% CI, agencies with fewer than 5 projects hidden, small agencies
shrunk toward their sector, the method printed with the data (`backend/serving.py` `AGENCY_METHOD`). Not done:
beyond the sector adjustment there is no control for project complexity, so a hard portfolio still reads as a
slower agency.

**Early notice (plan 14).** An early notice is a defined rule, not a feeling: a flagged external factor while the
CUF numbers show no slip yet. Each notice carries the flagged rows with their evidence, source and as-of date, and
`ml/risk_profile.py` `notice_backtest` measures how often past notices preceded a slip.

**Scenarios (plan 15).** The three curves are computed from analogues and the sector S-curve (`ml/analogues.py`);
the user supplies no input, so nothing out of range can reach the model, and every curve is labelled a modelled
scenario next to the forecast band.

## AI

**Read-only by construction (plan 17, 18, 19).** The assistant runs tools from a fixed catalogue (`llm/tools.py`);
every tool reads through `backend/serving.py` or the app database's read helpers and none writes. The viewer comes
from the server side of the request, never from the model, and each tool's arguments are validated by its pydantic
model with unknown fields and out-of-role tools refused; a planner call the role may not make is dropped before it
runs (`tests/test_chat_agent.py::test_injected_outside_text_cannot_add_a_call_or_change_scope`). The LLM cannot
delete anything, change a score, a model, a user or a permission: there is no tool for it. The two things an LLM
job does write are evidence, after checks: the research agent stores judged news items as cited facts and raises a
`signal` alert for a new live hold-up, and the second-opinion job stores opinions; neither touches a score.

**Untrusted text is data (plan 6).** Report remarks, PARIVESH lines, research summaries, headlines and the user's
own question go into prompts as quoted material between markers, with the marker characters and tags blanked so a
text cannot close the quote (`tools.quote`, `MARKERS`; `<<<DATA`, `<<<EVIDENCE`, `<<<ITEMS`), and every prompt says
quoted material is not instructions. The research judge must summarise its own item (shared words, numbers only from
the item), the second opinion may cite only listed ids, and a headline naming a person is rejected before any call
(`tests/test_research_agent.py`, `tests/test_second_opinion.py`).

**Every number is checked (plan 7, 8).** `backend/brief.validate` runs on the brief, on the chat's answer against
exactly the facts the writer saw, on the second opinion (each number in the items the claim cites, the concern level
inside what the evidence allows) and on the research agent's summaries; a reply that fails is asked again once with
the reasons, then replaced by a deterministic answer or stored as rejected (`docs/AI_ASSISTANT.md`,
`docs/SECOND_OPINION.md`).

**Disclosure (plan 16, 21).** The public gets the public tools and the public outputs only (`serving.public_*`);
the search index tags every chunk with a visibility and a project and filters both before ranking, so a public
question never retrieves an official chunk and an official never one outside their scope (`llm/rag.py`;
`tests/test_rag.py::test_public_never_sees_official_chunks`, `test_agency_scope_filters_project_chunks`). The model
runs locally in LM Studio; no text leaves the machine and the frontend holds no key. The research and second-opinion
runs record counts only in their job summaries (the projects they covered go to the log), and `GET /api/jobs` and
`GET /api/live/status` strip every per-project field for a viewer with a scope, so an official never learns of
another scope's projects from them (Segment 8 review finding [0];
`tests/test_access.py::test_job_summaries_never_show_a_scoped_official_another_scopes_project`).

**One model, fairly shared.** A single gate serialises generations; a chat request goes before any background take,
including ones already waiting; the worker cell, the brief, the research agent and the second opinion hold it per
call; a refused connection trips one shared breaker for 30 s; the chat is rate limited per client and role; every
job has a time limit and the LLM jobs a stop flag (`llm/client.py`, `backend/ratelimit.py`,
`backend/live/scheduler.py`).

**Tests (plan 22).** The plan's list maps to: unauthorised access `tests/test_access.py` (403 matrix, scoped 404s,
the public page redacted) and `tests/test_input_validation.py`; modified or duplicate input
`tests/test_watcher.py::test_ingest_runs_once_per_sha256`; invalid values `tests/test_silver.py` (quarantine) and
`tests/test_research_pipeline.py`; the LLM cannot change a score `tests/test_second_opinion.py`,
`tests/test_chat_tools.py`; RAG cannot retrieve an unauthorised document `tests/test_rag.py`; injected text is data
`tests/test_chat_agent.py`, `tests/test_research_agent.py`, `tests/test_second_opinion.py`; external data source
recorded `tests/test_parivesh.py`, `tests/test_research_pipeline.py`; quarantined rows stay out
`tests/test_silver.py`; model version verified before use: added with the checksum (above). Not done: the raw
archive's own hash manifest.

## API

What every request goes through, outermost first (`backend/auth/middleware.py`, `backend/auth/sessions.py`,
`backend/main.py`), and what the sign-in holds (`backend/auth/`, [ACCESS_CONTROL.md](ACCESS_CONTROL.md)).

**Who is asking (plan 17, 18).** Real accounts in `app.users` with argon2id password hashes (argon2-cffi defaults,
RFC 9106 low-memory profile). A session is a 256-bit random cookie token (`paimana_session`: HttpOnly, SameSite=Lax,
Secure in production); the database keeps only its sha256. Sessions end after 12 idle hours or 7 days, at sign-out,
when the account is disabled, and when the password changes. Roles and scope are read from the account on every
request, so a change or a disabled account takes effect at once; an open alert stream checks its session again
before it sends alerts and at every heartbeat, and ends when the session no longer holds or the account's role or
scope changed. The public is simply no cookie, and a cookie that
names no live session gets 401. The prototype's trusted role headers are gone from the backend, the frontend
and the tests. The administrator is an IPMD analyst with the admin flag. The developer account (every feature,
including raw model numbers, job controls and the audit log) is created only by the bootstrap from `.env.db` and is
invisible to administrators. Tests: `tests/test_auth.py`, `tests/test_access.py`, `tests/test_bootstrap.py`.

**What a write must carry.** Every non-GET request passes `sessions.guard`, an app-wide dependency. An `Origin`
header, when present, must be one of `ALLOWED_ORIGINS`. A request with a live session must carry the session's CSRF
token in `X-CSRF-Token`, compared in constant time. The token comes from `GET /api/auth/me`; SameSite=Lax is the
second line. Cookie-less writes (the public's chat, sign-in, sign-up, reset) carry no token.

**Guessing passwords.** One generic 401 covers an unknown email, a wrong password and a disabled account, with the
same argon2 cost. Five failures within 15 minutes lock the email for 15 minutes (423). Unknown emails lock too, so a
lock does not reveal an account. Twenty failures a minute from one address are refused (429). Sign-up allows three
requests an hour per address and one pending request per email, enforced by a unique index. A reset allows ten
attempts a minute per address. The password policy is at least 12 characters, not a common password, and not the
email's local part. A wrong current password on a password change counts toward the lock. Nothing writes a password
or a token to the audit log, the access log or a response other than the one that issued it.

**Audit (plan 20).** Every write records who did it: the account id, the email, the client address (`app.audit_log`),
role, action, target and detail. That covers alert acks, watchlist changes, memo decisions, job starts, uploads, the
worker trigger, sign-in, sign-out, password changes, resets, sign-up requests, approvals, rejections, account
changes, reset tokens and bootstrap runs. Failed sign-ins are recorded in `app.login_attempts`. The audit log is
read by the developer only (`GET /api/admin/audit`, newest first, filtered by date, account or action).

**Client address.** Behind nginx the api believes `X-Forwarded-For` and `X-Forwarded-Proto` only from a peer inside
`TRUSTED_PROXIES` (the compose network), and takes the right-most hop that is not a proxy. uvicorn runs with
`--no-proxy-headers`, so a client cannot choose its own address for the limits or the audit trail. The chat limit
keys on the account when signed in and on that address for the public.

**Hardening.** Security headers go on every api response: `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`,
`Permissions-Policy`, HSTS when `SECURE_COOKIES=1`, and `Cache-Control: no-store` on `/api/auth` and `/api/admin`.
CORS allows only `ALLOWED_ORIGINS`, with credentials. The Host header must match `ALLOWED_HOSTS`; `/healthz` and
`/readyz` answer for any host so the container probe works. JSON bodies are capped at 1 MiB and the report upload
at 110 MiB (413); the upload's allowance goes only to a request with a session cookie, and the upload route checks
the session and the developer's `jobs` feature before it reads the body, so nobody else can make the api spool a
file. Requests time out after 30 s (504); the streams, the upload and the routes that wait on the local
LLM or the web are exempt. A route's exception becomes `{"detail": "internal error", "requestId"}`, with the
traceback in the log under that request id and never in the response. A 422 names the field, never the value sent,
so an oversized password is not echoed back. Request bodies refuse unknown fields. Each request gets a request id
(nginx's `X-Request-ID` when it sent one) and one JSON access-log line, without the query strings of `/api/auth`
and `/api/admin`. `/docs` and `/openapi.json` are off in production (`API_DOCS=0`). On shutdown the research and
second-opinion jobs get their stop flags, including a run started from the API, and the process waits up to 30 s
for them.

**Not done.** No email verification and no email of any kind: an administrator checks a sign-up request by other
means and hands reset tokens over in person. No multi-factor sign-in, no single sign-on, no password expiry and no
breached-password lookup (the common-password list is short). Sessions are not bound to an address or a browser. An
administrator cannot end another account's sessions except by disabling it or issuing a reset. A signed-in session
can change its password with the current one, so a stolen live session plus the password is enough. The sign-up
answer (409) says that a request or an account exists for an email: rate-limited, but an enumeration signal. The
api's in-memory chat and reset limits reset when it restarts (the sign-in limits do not). The 30 s time limit
cannot stop a synchronous route's thread; the database's 15 s statement timeout bounds its queries. The watchlist
is still one list per role, cut to each viewer's scope.

## Deployment

The stack is `docker-compose.yml` ([DEPLOYMENT.md](DEPLOYMENT.md)).

**Network exposure.** The web container publishes 80 and 443 and nothing else does. The api (8000), postgres (5432)
and the backup container are reachable on the compose network only; `docker-compose.dev.yml` publishes postgres on
127.0.0.1:5434 for the laptop. LM Studio is reached from the api through the Docker host's bridge address and is
never published by the stack.

**TLS.** nginx 1.27 terminates TLS 1.2 and 1.3 (Mozilla's intermediate ciphers, session tickets off). Port 80 answers
the container's health probe and redirects everything else to https. HSTS is set for a year (no `includeSubDomains`,
no preload). The certificate is a file pair in `deploy/certs/`, git-ignored: self-signed on a laptop
(`scripts/gen-dev-cert.*`), from a CA on a server.

**Headers.** Every response through nginx carries `Content-Security-Policy` (`default-src 'self'`; images self and
`data:`; fonts self and fonts.gstatic.com; styles self, inline and fonts.googleapis.com; `connect-src 'self'`;
`frame-ancestors 'none'`; `base-uri 'self'`; `object-src 'none'`), `X-Content-Type-Options: nosniff`,
`X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy` (camera,
microphone, geolocation and payment off) and `Strict-Transport-Security`. nginx adds headers and never removes the
api's own. `server_tokens` is off.

**Rate limits, per client IP, 429 above them.** `/api/auth/*` 10 a minute (burst 5), `/api/chat` 10 a minute
(burst 3), everything else under `/api/` 60 a minute (burst 100). Request bodies: 1 MB everywhere except the report
upload (`/api/jobs/ingest`: 110 MB, streamed to the api, which enforces its own 100 MB). The chat and alert streams
and the upload may last 10 minutes; other calls 60 s at nginx (the api's own per-request timeout is shorter). The api
keeps its per-user limits behind these.

**Containers.** api: python 3.13-slim, a non-root user (uid 1000), read-only root filesystem, every Linux capability
dropped, `no-new-privileges`, a 4 GB memory limit, one worker. web: read-only root filesystem, capabilities cut to the
five nginx needs, 256 MB. migrate and backup: read-only, short-lived or idle. The writable bind mounts are `dataset/`,
`database/` and `temp/` for the api and `backups/` for postgres and backup; `model/` is read-only. Health checks:
`pg_isready`, the api's `/healthz`, nginx's `/healthz`.

**Secrets.** `.env` and `.env.db` are git-ignored and never enter an image (`.dockerignore`); the compose files pass
them through `env_file` only. `scripts/first-run.*` generates the database password (32 alphanumeric characters
from the OS random generator, file mode 600 on Linux). The administrator's password is typed at the bootstrap's
prompt and never written to a file, an argument or a log. The developer account's email and password live in
`.env.db` with the database credentials, and the api re-applies them at every start. Rotation of the database password: DEPLOYMENT.md.

**Backups.** A daily `pg_dump -Fc` with 14 days kept; on Linux the files belong to root with mode 600. They hold the
user rows (emails, argon2 hashes), sessions and the audit log, so `backups/` needs the same protection as the
database, and an off-machine copy.

**Updates.** `git pull`, `docker compose build`, `docker compose up -d` rebuilds from the pinned bases
(`python:3.13-slim`, `node:22-alpine`, `nginx:1.27-alpine`, `pgvector/pgvector:pg16`) and runs the migrations before
the new api starts; the bases move with their tags, so a monthly rebuild takes their fixes. The CI workflow
(`.github/workflows/check.yml`) runs the tests and the frontend checks on every push with read-only repository
permissions; it never builds images, deploys or pushes.

**Not done.** No web application firewall or intrusion detection. No automatic certificate renewal (a certbot cron is
described in DEPLOYMENT.md). The rate limits are per address, so an office behind one NAT shares one budget. No
egress filtering from the api container: it needs the news sources, PIB, PARIVESH, Bhoomi Rashi and LM Studio.
Docker Desktop on Windows is a demo host, not a hardened one. The postgres container keeps its default capabilities.
