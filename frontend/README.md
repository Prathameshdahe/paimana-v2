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

`src/lib/api.ts` exports `API_BASE`, read from `VITE_API_BASE` and defaulting to
`http://localhost:8000`. The variable is in the `.env` at the repo root because
`vite.config.ts` sets `envDir` to `..`.

The dashboard needs the backend running (see the root README); there is no
bundled project data. Every view reads the backend through
`src/lib/queries.ts` (TanStack Query hooks over the typed fetch helpers in
`src/lib/api.ts`; response types in `src/contracts/`, camelCase as served by
`backend/schemas.py`). A screen asks for an aggregate, one page, or one project,
never a full table. When the backend is down, the views and a banner under the
top bar say so and show the command to start it; nothing falls back to fake
data. The chat widget is keyword search over `/api/projects`.

Alerts are live: the top bar opens one `EventSource` on `/api/stream`
(`src/lib/useAlertStream.ts`), and each pushed alert refetches the bell, the
Home inbox and the live status. The Live strip on Home reads `/api/live/status`;
with `LIVE_JOBS=0` on the backend it says the loops are off.

## Where things are

Routes are in `src/App.tsx`: `/`, `/login`, `/command`, `/external`,
`/projects/:key`, `/audit`, `/workers` and `/approvals`. The `@` import alias
points to `src/`.

`src/mocks/audit.ts` holds the hardcoded Audit Suite numbers from the v1 model;
the Models page will replace them with `/api/models`. The role picker
behind `/login` is in `src/lib/auth/`.
