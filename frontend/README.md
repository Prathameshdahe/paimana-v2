# PAIMANA dashboard

Dashboard for PAIMANA Early Warning Radar. React 19, Vite 6, TypeScript,
Tailwind, TanStack Query and Recharts. Setup, the backend, the model and the
data pipeline are in the [root README](../README.md).

## Commands

From this folder:

```
npm install
npm run dev         # http://localhost:3000, fails if the port is taken
npm run lint
npm run typecheck   # tsc -b
npm run build       # tsc -b, then vite build into dist/
npm run preview     # serves dist/ on port 3000
```

## Backend

Requests go to `API_BASE + path` (`src/lib/api.ts`). `API_BASE` is `''` by
default, so every call is same-origin: the dev server proxies `/api` to
`http://localhost:8000` (`vite.config.ts`, `server.proxy` and `preview.proxy`)
and nginx does the same in production. `VITE_API_BASE` in the root `.env`
(`vite.config.ts` sets `envDir` to `..`) still overrides it for a backend on
another origin; then the backend's `ALLOWED_ORIGINS` must name the page's origin
and allow credentials, because every call sends `credentials: 'include'`. Leave
`VITE_API_BASE` empty for the proxy.

The dashboard needs the backend running; there is no bundled project data.
Every view reads the backend through `src/lib/queries.ts` (TanStack Query hooks
over the typed fetch helpers in `src/lib/api.ts`; response types in
`src/contracts/`, camelCase as served by `backend/schemas.py`). A screen asks
for an aggregate, one page, or one project, never a full table. When the
backend is down, the views and a banner under the top bar say so and show the
command to start it; nothing falls back to fake data.

Alerts are live: the top bar opens one `EventSource` on `/api/stream`
(`src/lib/useAlertStream.ts`), and each pushed alert refetches the bell, the
Home inbox and the live status. The assistant streams `POST /api/chat` as
server-sent events over fetch (`src/lib/chatStream.ts`).

## Sign-in and sessions

Officials sign in with an email and password (`/login`, `POST /api/auth/login`);
the backend sets an HttpOnly session cookie, and the page keeps nothing about
the viewer in the browser. On load `src/lib/auth/SessionContext.tsx` asks
`GET /api/auth/me`: the answer is the role, the scope (a ministry or an agency),
the admin flag and a CSRF token; 401 (or 404 from a backend without the sign-in
routes) is the public, who needs no account. The routes wait for that answer, so
an official never sees the public page first.

`src/lib/api.ts` sends the CSRF token as `X-CSRF-Token` on every non-GET
request while signed in (the chat stream too). A 401 on any later call clears
the session: an officials' page goes to `/login` with a "session expired"
notice; a public page shows the notice under the top bar. Signing in or out
clears the query cache, so no official's data stays in memory.

`src/lib/auth/access.ts` is the one map of which role opens which page and uses
which feature (`ROUTE_ROLES`, `FEATURE_ROLES`, `canOpen`, `can`, `canAdmin`);
`RequireRole.tsx` guards the routes with it. The backend enforces the same rules
(`backend/access.py`, `docs/ACCESS_CONTROL.md`); the map only decides what is
shown.

The other account pages: `/signup` (request access: email, name, role, the
searchable ministry or agency list, a justification, a password checked against
the policy in `src/lib/auth/password.ts` with a rules-only strength meter; an
IPMD administrator approves it), `/reset` (a new password with the one-time
token an administrator issued), and from the account menu in the top bar a
change-password dialog, Administration (admins) and Sign out. `/admin` has three
tabs over `/api/admin/*`: sign-up requests to approve (the role and scope can be
corrected first) or reject, users to search, edit, disable and reset (the token
shows once, with a copy button, and is never stored), and the paged audit log.

## Where things are

Routes are in `src/App.tsx`: `/`, `/login`, `/signup`, `/reset`, `/command`,
`/external`, `/bottlenecks`, `/agencies`, `/radar`, `/projects/:key`, `/models`
(`/audit` redirects there), `/workers`, `/approvals` and `/admin`. Every route
sits in one error boundary that offers Reload
(`src/components/common/ErrorBoundary.tsx`). The top bar
(`src/components/ui/navigation-menu-05.tsx`) shows the first five pages and the
rest under More. The `@` import alias points to `src/`.

Corners are sharp everywhere: every named radius in `tailwind.config.ts` is 0,
and `rounded-full` is for true circles only (dots, rings, avatars, the chat
launcher, spinner dots, the slider thumb, radio dots). The account pages
(`src/components/layout/AccountLayout.tsx`) animate nothing.

Models (`/models`) reads `/api/models`: live accuracy of the logged
predictions, the champion run's backtest, calibration, SHAP summary and
ablation tables, and the registry's champion decisions. Bottlenecks, Agencies
and Radar read `/api/bottlenecks`, `/api/agencies/matrix` and
`/api/signals/feed` + `/api/radar/summary`. The project page's Brief card calls
`/api/projects/{key}/brief` only when asked; 503 means LM Studio is not
running.

There is no test runner in this package; the behaviour checks for the api
client, the session, the password policy and the account, admin and error
pages are small esbuild + `react-dom/server` scripts kept outside the repo and
run before each change ships.
