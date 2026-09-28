# Access control

Five roles see the same app cut to what they need: the public, an agency official, a ministry official, an IPMD
analyst and the hidden developer. An IPMD analyst whose account carries the admin flag is the **administrator**: they
approve sign-up requests and manage accounts.

## Sign-in and sessions

The public never signs in: a request without a session cookie is the public. An official signs in on `/login` with
an email and a password (`POST /api/auth/login`). The backend then sets the `paimana_session` cookie: 256 random
bits, `HttpOnly`, `SameSite=Lax`, `Path=/`, and `Secure` when `SECURE_COOKIES=1` (production, behind TLS). Only the
token's sha256 is stored (`app.sessions`), next to the session's CSRF token. A session ends after 12 idle hours
(`SESSION_IDLE_H`) or 7 days (`SESSION_MAX_D`), at sign-out, when the account is disabled, and when the account's
password changes (every session except the one that changed it). A new sign-in from the same browser ends the
session it replaces.

Every request with the cookie is read against `app.users`. The account's role, scope and admin flag take effect on
the next request after an administrator changes them, and a disabled account is out at once. A cookie that names no
live session (expired, revoked, forged) gets 401 and the cookie is cleared, so the browser falls back to the public.

**Writes.** A request that is not GET, HEAD or OPTIONS:
- must come from a trusted page: an `Origin` header, when sent, must be one of `ALLOWED_ORIGINS` (a browser always
  sends it on a cross-site write), otherwise 403;
- with a session cookie, must carry the session's CSRF token as `X-CSRF-Token`. `GET /api/auth/me` hands the token to
  the page. A missing or wrong token is 403. The public's cookie-less writes (the chat, sign-in, sign-up, reset)
  need no token.

**Passwords.** argon2id (argon2-cffi's defaults: 64 MiB, 3 passes, 4 lanes). A password must have at least 12
characters not counting whitespace at either end and at least 5 different characters (no blank or one-letter
password), must not be on the common-password list (checked with and without punctuation) and must not contain the
email's local part. `frontend/src/lib/auth/password.ts` checks the rules before sending (the distinct-character rule
is the backend's alone until the frontend adds it; the backend's 422 names it).

**Failed sign-ins.** One generic 401 covers an unknown email, a wrong password and a disabled account alike: "email
or password is wrong, or the account is locked or disabled". An unknown email costs the same argon2 time. Five
failures on one email within 15 minutes lock that email for 15 minutes from the last one: 423 with `Retry-After`,
even with the right password. Unknown emails lock the same way, so a lock tells nothing about an account. Twenty
failures from one client address within a minute hold back that address's sign-ins (429 with `Retry-After`). A
successful sign-in is never counted against its address. Both limits live in `app.login_attempts`, so a restart does
not clear them. A password reset lifts an account's lock. Code: `backend/auth/limits.py`.

**Sign-up.** `/signup` sends a request (`POST /api/auth/signup`): an email, a name, one of the three official roles,
the ministry or canonical agency for those roles (it must be one of `/api/scopes`), a justification of up to 500
characters and the account's password. Only the password's argon2 hash is kept. Limits: three requests an hour from
one address, and one pending request per email. A second request for the same email, or one for an email that
already has an account, gets 409. An administrator approves the request (the role and scope can be corrected first)
or rejects it with a note. After approval the person signs in with the password they chose. `ALLOWED_EMAIL_DOMAINS`
limits sign-up to official domains.

**Resets.** There is no email sending. An administrator issues a one-time reset token
(`POST /api/admin/users/{id}/reset-password`). The token is shown once and valid for 24 hours; only its sha256 is
stored, and a newer token replaces an older one. Issuing it ends every session of the account at once (an
account reset to lock someone out is signed out). The person sets a new password on `/reset`
(`POST /api/auth/reset`), which ends every session of the account again.

**The first administrator and the developer.** `python -m backend.auth.bootstrap --email <e> --name <n>` creates the
first administrator. The password comes from `PAIMANA_ADMIN_PASSWORD` or a hidden prompt, never from the command line.
The command refuses when an administrator already exists; `--force-reset` resets that account. The same command, and
the api container at every start (`--developer-only`, `deploy/api-entrypoint.sh`), creates or updates the developer
from `PAIMANA_DEVELOPER_EMAIL` / `PAIMANA_DEVELOPER_PASSWORD` in `.env.db`.

## Where the rules live

| Side | File | What it does |
|---|---|---|
| Backend | `backend/access.py` `POLICY` | Per role: its features and its scope. `viewer()` builds the `Viewer` from the session; routes take it as a dependency, answer 403 for a feature the role lacks, and cut every project row, alert, signal, memo and job summary to the scope. An out-of-scope project is 404. `FLAGGED` features (`admin`) also need the admin flag. |
| Backend | `backend/auth/` | Sessions, the Origin and CSRF checks (`sessions.guard`, on every route), the sign-in limits, the `/api/auth` and `/api/admin` routes, the bootstrap, the HTTP hardening |
| Frontend | `frontend/src/lib/auth/access.ts` | The same rules for display: `ROUTE_ROLES` (page to roles), `FEATURE_ROLES` (`canSeeDrivers`, `canSeeAlerts`, `canAck`, `canChat`, `canSeeLive`, `canSeeNews`, `canSeeSecondOpinion`, `canRunJobs`, `canSeePipelineErrors`, `canSeeModelVersion`, `canAdmin`) and `canAdmin(session)` (the role and the admin flag). `/admin` needs both. |

The two maps are kept by hand. The backend is the one that holds: a page shown by mistake still gets 403 or the
scoped rows. `tests/test_access.py` checks the backend matrix, `tests/test_auth.py` the sessions and
administration. Every test signs in real accounts through `tests/viewers.py`.

## Roles, scope and features

| Role | Account | Project rows |
|---|---|---|
| Public | none | every current project |
| Agency official | approved sign-up, scope a canonical agency (`gold/agency_map.csv`) | that agency's projects, under every printed name that maps to it |
| Ministry official | approved sign-up, scope a ministry | that ministry's projects |
| IPMD analyst | approved sign-up; the admin flag makes them the administrator | every project |
| Developer | the bootstrap only, one account | every project |

The developer is hidden. It is never listed to administrators, and `GET`/`POST /api/admin/users/{id}` and its reset
answer 404 for it. It is never a sign-up or approval choice, and its audit rows are shown to developers only.
`Me.role` is `developer` only in the developer's own `/api/auth/me`. An alert the developer acknowledges shows
`ackedAt` with no `ackedBy`, and a sign-up request it reviewed shows administrators no `reviewedBy`.

The scope applies to everything built from project rows: portfolio KPIs and tier counts, the map, the project list
and search, the project page (404 outside it), alerts and the live alert stream, bottleneck members (a cluster with
none in scope is hidden, the rest are recounted over their in-scope members), the External Factors counts and top
lists, the news feed and radar rollup (linked items only), the memos and the job summaries. Job summaries are
counts only, and every per-project field is removed for a scoped viewer; a failed run's error text reaches a scoped
viewer only as "the last run failed". The agency matrix shows a ministry official
the agencies of their ministry. It shows an agency official every agency, with their own flagged (`isSelf`) and
always shown, so they can compare with their peers. The watchlist is one list per role, cut to the viewer's scope.

## Pages and features

✓ shown, – hidden (backend 403). "Scoped" means cut to the role's projects as above.

| Page / feature | Public | Agency official | Ministry official | IPMD analyst | Developer |
|---|---|---|---|---|---|
| Home: map, KPIs, tier counts | ✓ | ✓ scoped | ✓ scoped | ✓ | ✓ |
| Home: early warning inbox | – | ✓ scoped | ✓ scoped | ✓ | ✓ |
| Project list and search (`/command`) | ✓ | ✓ scoped | ✓ scoped | ✓ | ✓ |
| Project page | simple: tier, progress, cost, completion, top 3 risks in plain words, progress history | ✓ full, scoped | ✓ full, scoped | ✓ full | ✓ full |
| Drivers, analogues, intervals, provenance, forecast, brief, project news, AI second opinion | – | ✓ | ✓ | ✓ | ✓ |
| Raw model numbers (probabilities, contributions, intervals, calibration; feature `numbers`) | – | – | – | – | ✓ |
| Web research (project page, External Factors) | facts without match reasons or the research agent's headlines | ✓ scoped | ✓ scoped | ✓ | ✓ |
| External Factors summary | counts, factors, map and measured delays; no evidence lines or PARIVESH lists | ✓ scoped | ✓ scoped | ✓ | ✓ |
| Bottlenecks, Agencies | – | ✓ scoped | ✓ scoped | ✓ | ✓ |
| Radar (signals feed, rollup) | – | ✓ linked, scoped | ✓ linked, scoped | ✓ linked | ✓ with the unlinked pool |
| Alert bell and live stream | – | ✓ scoped | ✓ scoped | ✓ with pipeline errors | ✓ with pipeline errors |
| Acknowledge an alert | – | – | ✓ scoped | ✓ | ✓ |
| AI assistant (chat) | ✓ public tools and public outputs only | ✓ scoped, every tool | ✓ scoped, every tool | ✓ every tool | ✓ every tool |
| Approvals | – | memos to agency officials, own projects | memos to ministry officials, own projects | every memo | every memo, view only |
| Live job status | – | ✓ counts | ✓ counts | ✓ | ✓ |
| Check inbox, run scout, upload a report, research, second-opinion job, portal pulls | – | – | – | – | ✓ |
| Models page, worker console and trigger | – | – | – | – | ✓ |
| Administration (`/admin`): sign-up requests, accounts, reset tokens | – | – | – | admin flag | ✓ |
| Audit log | – | – | – | – | ✓ |
| Model version in the top bar | – | ✓ | ✓ | ✓ | ✓ |

The public project page (`GET /api/projects/{key}` without a session) drops the SHAP drivers, the 5th and 95th
percentile intervals, the rank percentile, the identity review note and the provenance internals (model, gold and
silver versions, source document and page). It keeps the tier, the p50 estimates, the latest report's progress,
cost and completion, the risk checklist, and `topRisksPlain`: up to three flagged checklist rows as short sentences
("Land for the project is not fully acquired yet."). The timeline drops its source documents too. The external block
drops the PARIVESH link and proposals, the remark status and the measured hidden delay. The public External Factors
summary keeps the counts, the flagged factors per project, the land map and the measured priors; it drops every
evidence line and the per-project PARIVESH lists (open proposals, the proposals named in the remarks).

## API

| Endpoint | Public | Agency | Ministry | IPMD | Developer |
|---|---|---|---|---|---|
| `/api/meta`, `/api/scopes`, `/healthz`, `/readyz` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `/api/portfolio`, `/api/projects`, `/api/projects/{key}`, `.../timeline`, `/api/external/summary` | ✓ (detail redacted) | scoped | scoped | ✓ | ✓ |
| `.../research`, `/api/research/summary` | ✓ (redacted) | scoped | scoped | ✓ | ✓ |
| `.../forecast`, `.../brief`, `.../signals`, `.../second-opinion` | 403 | scoped | scoped | ✓ | ✓ |
| `/api/alerts`, `/api/stream` (the cookie; no query-string viewer) | 403 | scoped | scoped | ✓ | ✓ |
| `POST /api/alerts/{id}/ack` | 403 | 403 | scoped | ✓ | ✓ |
| `/api/watchlist` | 403 | scoped | scoped | ✓ | ✓ |
| `/api/bottlenecks`, `/api/agencies/matrix`, `/api/agencies/{a}/projects` | 403 | scoped | scoped | ✓ | ✓ |
| `/api/signals/feed`, `/api/radar/summary` | 403 | linked, scoped | linked, scoped | linked | ✓ |
| `/api/dispatch`, `POST /api/approvals` | 403 | addressed, scoped | addressed, scoped | ✓ | every memo to read; decides none (no memo is addressed to the developer, 403) |
| `/api/live/status`, `/api/jobs` | 403 | counts only | counts only | ✓ | ✓ |
| `POST /api/jobs/*` (ingest, watch, scout, research, second-opinion, parivesh-snapshot, bhoomi-pull) | 403 | 403 | 403 | 403 | ✓ |
| `/api/models`, `/api/worker-runs`, `POST /api/worker-runs/trigger` | 403 | 403 | 403 | 403 | ✓ |
| `POST /api/chat` | ✓ public tools, 6 a minute and 40 an hour per address | scoped, 20 a minute per account | scoped, 20 a minute | ✓, 20 a minute | ✓, 20 a minute |
| `POST /api/auth/signup`, `/login`, `/reset`; `POST /api/auth/logout`; `GET /api/auth/me` | ✓ (me: 401) | ✓ | ✓ | ✓ | ✓ |
| `POST /api/auth/password` | 401 | ✓ | ✓ | ✓ | ✓ |
| `/api/admin/signups` (list, approve, reject), `/api/admin/users` (list, update, reset-password) | 403 | 403 | 403 | admin flag | ✓ |
| `/api/admin/audit` | 403 | 403 | 403 | 403 | ✓ |

A `role` still sent in a request body or query (ack, watchlist, approvals) must match the signed-in role, or it is
403 (the developer may send `developer`). Every write records an `app.audit_log` row: role, action, target, detail, and the actor's account id, email and
client address.

**Request and response shapes** (camelCase; `frontend/src/contracts/auth.ts`, `backend/schemas.py`):
- `POST /api/auth/login {email, password}` → 200 `Me` and the cookie | 401 | 423 / 429 with `Retry-After`.
- `GET /api/auth/me` → `Me {userId, email, displayName, role, ministry, agency, isAdmin, csrfToken,
  sessionExpiresAt}` | 401. `sessionExpiresAt` is when the session ends if left idle from now.
- `POST /api/auth/logout` → 204. `POST /api/auth/password {current, new}` → 204 | 401 (wrong current password; it
  counts toward the lock) | 422.
- `POST /api/auth/signup {email, displayName, role, ministry?, agency?, justification, password}` → 202 `{id}` | 400
  (unknown scope) | 409 | 422 | 429.
- `POST /api/auth/reset {token, password}` → 204 | 400 (unknown, used or expired) | 422 | 429 (10 a minute per
  address).
- `GET /api/admin/signups?status=pending|approved|rejected` → `SignupRow[]`. `POST .../{id}/approve {note?, role?,
  ministry?, agency?}` → `User` | 400 | 404 | 409. `POST .../{id}/reject {note}` → `SignupRow`.
- `GET /api/admin/users?q=&page=&size=` → `{total, page, size, items: User[]}`. `POST /api/admin/users/{id} {status?,
  role?, ministry?, agency?, isAdmin?}` → `User`. An administrator cannot disable or demote their own account (403),
  and only an IPMD analyst can hold the admin flag (400). `POST /api/admin/users/{id}/reset-password` →
  `{token, expiresAt}`.
- `GET /api/admin/audit?since=&user=&action=&page=&size=` → `{total, page, size, items: [{id, at, userId, email,
  role, ip, action, target, detail}]}`, newest first. `user` is an account id, an email or a role.

Request bodies refuse unknown fields (422). A 422 names the field and the rule, never the value sent.

## AI assistant

`POST /api/chat` is open to every role (`chat` in every role's `POLICY`). What an answer may read is decided per tool
by the same viewer (`llm/tools.py`; full matrix in `docs/AI_ASSISTANT.md`):

| Tool | Public | Agency | Ministry | IPMD / developer |
|---|---|---|---|---|
| Project list, portfolio counts, project page, compare, search of help and records | ✓ public outputs | scoped | scoped | ✓ |
| Report history | timeline | + tier alerts, prediction log, scoped | + tier alerts, prediction log, scoped | ✓ full |
| Web research | facts without match reasons or agent headlines (the search index has none either) | + linked news, scoped | + linked news, scoped | ✓ + linked news |
| Outside factors | factor names and public evidence strings | + check evidence and PARIVESH detail, scoped | + check evidence and PARIVESH detail, scoped | ✓ full |
| Risk drivers and flagged checks with evidence | – | scoped | scoped | ✓ |
| Cached AI second opinion | – | scoped | scoped | ✓ |
| Agency scorecard | – | every agency, own by default; Critical / High counts only where every open project is in scope | their ministry's agencies, same rule | ✓ |
| Bottlenecks | – | scoped | scoped | ✓ |

The tools take the viewer from the request, never a scope from the model. They answer a project outside the scope
exactly like an unknown key. The public writer prompt never mentions model internals, and a public answer that
names one is rejected. The rate limit keys on the account when signed in and on the client address for the public
(`backend/ratelimit.py`). A refused request gets 429 before anything streams. Nothing about a question is stored or
logged.
