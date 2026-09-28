# Access control

Four roles see the same app cut to what they need: the public, an agency official,
a ministry official and an IPMD analyst.

**This is a prototype. There is no authentication.** The sign-in page stores a role
and, for a ministry or agency official, a scope in the browser. `frontend/src/lib/api.ts`
sends them with every request as `X-Paimana-Role`, `X-Paimana-Ministry` and
`X-Paimana-Agency` (URI-encoded), and the backend trusts them. Anyone can send any
header, so this separates views; it does not protect data. A real deployment would
build the same viewer from a verified session (SSO or signed tokens) in
`backend/access.py` `viewer()` and drop the headers. Nothing else would change.

A request with no headers is the public.

## Where the rules live

| Side | File | What it does |
|---|---|---|
| Backend | `backend/access.py` `POLICY` | Per role: its features and its scope. Routes take the viewer as a dependency, answer 403 for a feature the role lacks and cut every project row, alert, signal and memo to the scope. An out-of-scope project is 404. |
| Frontend | `frontend/src/lib/auth/access.ts` | The same rules for display: `ROUTE_ROLES` (page to roles) and `FEATURE_ROLES` (`canSeeDrivers`, `canSeeAlerts`, `canAck`, `canChat`, `canSeeLive`, `canSeeNews`, `canRunJobs`, `canSeeModelVersion`). Routes, nav, bell, chat, live controls and the project page read it. |

The two maps are kept by hand. The backend is the one that holds: a page shown by
mistake still gets 403 or the scoped rows. `tests/test_access.py` checks the
backend side.

## Scope

| Role | Signs in with | Project rows |
|---|---|---|
| Public | nothing (or "Continue as public") | every current project |
| Agency official | a canonical agency (`gold/agency_map.csv`, picked from `GET /api/scopes`) | that agency's projects, under every printed name that maps to it |
| Ministry official | a ministry (picked from `GET /api/scopes`) | that ministry's projects |
| IPMD analyst | nothing | every project |

The scope applies to everything built from project rows: portfolio KPIs and tier
counts, the map, the project list and search, the project page (404 outside it),
alerts and the live alert stream, bottleneck members (a cluster with none in scope
is hidden, the rest are recounted over their in-scope members), the External
Factors counts and top lists, the news feed and radar rollup (linked items only),
and the memos. The agency matrix shows a ministry official the agencies of their
ministry, and an agency official every agency with their own flagged (`isSelf`)
and always shown, so they can compare with their peers. The watchlist is still one
list per role, cut to the scope; it becomes per person once there is real sign-in.

## Pages and features

✓ shown, – hidden (backend 403). "Scoped" means cut to the role's projects as above.

| Page / feature | Public | Agency official | Ministry official | IPMD analyst |
|---|---|---|---|---|
| Home: map, KPIs, tier counts | ✓ | ✓ scoped | ✓ scoped | ✓ |
| Home: early warning inbox | – | ✓ scoped | ✓ scoped | ✓ |
| Project list and search (`/command`) | ✓ | ✓ scoped | ✓ scoped | ✓ |
| Project page | simple: tier, progress, cost, completion, top 3 risks in plain words, progress history | ✓ full, scoped | ✓ full, scoped | ✓ full |
| SHAP drivers, analogues, quantile intervals, provenance, forecast, brief, project news | – | ✓ | ✓ | ✓ |
| External Factors summary | counts, factors, map and measured delays; no evidence lines or PARIVESH lists | ✓ scoped | ✓ scoped | ✓ |
| External Factors news feed | – | ✓ scoped | ✓ scoped | ✓ |
| Bottlenecks | – | ✓ scoped | ✓ scoped | ✓ |
| Agencies | – | ✓ all agencies, own highlighted | ✓ their ministry's agencies | ✓ |
| Radar (signals feed, rollup) | – | ✓ linked, scoped | ✓ linked, scoped | ✓ with the unlinked pool |
| Alert bell and live stream | – | ✓ scoped | ✓ scoped | ✓ with pipeline errors |
| Acknowledge an alert | – | – | ✓ scoped | ✓ |
| Project assistant (chat) | – | – | ✓ scoped | ✓ |
| Approvals | – | memos addressed to agency officials, own projects | memos addressed to ministry officials, own projects | every memo |
| Decide a memo | – | only its addressee | only its addressee | only its addressee |
| Live job status | – | ✓ | ✓ | ✓ |
| Check inbox, run scout, upload a report | – | – | – | ✓ |
| Models page | – | – | ✓ read-only | ✓ |
| Workers (console, trigger) | – | – | – | ✓ |
| Model version in the top bar | – | ✓ | ✓ | ✓ |

The public project page (`GET /api/projects/{key}` without headers) drops the SHAP
drivers, the 5th and 95th percentile intervals, the rank percentile, the identity
review note and the provenance internals (model, gold and silver versions, source
document and page). It keeps the tier, the p50 estimates, the latest report's
progress, cost and completion, the risk checklist and `topRisksPlain`: up to three
flagged checklist rows as short sentences ("Land for the project is not fully
acquired yet."). The timeline drops its source documents too, and the external block drops the PARIVESH link
and proposals, the remark status and the measured hidden delay. The public External Factors summary keeps the
counts, the flagged factors per project, the land map and the measured priors; it drops every evidence line and
the per-project PARIVESH lists (open proposals, the proposals named in the remarks).

## API

| Endpoint | Public | Agency | Ministry | IPMD |
|---|---|---|---|---|
| `/api/meta`, `/api/scopes` | ✓ | ✓ | ✓ | ✓ |
| `/api/portfolio`, `/api/projects`, `/api/projects/{key}`, `.../timeline`, `/api/external/summary` | ✓ (detail redacted) | scoped | scoped | ✓ |
| `.../forecast`, `.../brief`, `.../signals` | 403 | scoped | scoped | ✓ |
| `/api/alerts`, `/api/stream` | 403 | scoped | scoped | ✓ |
| `POST /api/alerts/{id}/ack` | 403 | 403 | scoped | ✓ |
| `/api/watchlist` | 403 | scoped | scoped | ✓ |
| `/api/bottlenecks`, `/api/agencies/matrix`, `/api/agencies/{a}/projects` | 403 | scoped | scoped | ✓ |
| `/api/signals/feed`, `/api/radar/summary` | 403 | linked, scoped | linked, scoped | ✓ |
| `/api/dispatch`, `POST /api/approvals` | 403 | addressed, scoped | addressed, scoped | ✓ |
| `/api/live/status`, `/api/jobs` | 403 | ✓ | ✓ | ✓ |
| `POST /api/jobs/*` | 403 | 403 | 403 | ✓ |
| `/api/models` | 403 | 403 | ✓ | ✓ |
| `/api/worker-runs`, `POST /api/worker-runs/trigger` | 403 | 403 | 403 | ✓ |

An unknown role, or a ministry or agency role without a known scope, is 400.
`EventSource` cannot send headers, so `/api/stream` takes the same three values as
`?role=&ministry=&agency=`. A `role` still sent in a request body or query (ack,
watchlist, approvals) must match the header role, or it is 403; the action is
recorded in the audit log under the header role.
