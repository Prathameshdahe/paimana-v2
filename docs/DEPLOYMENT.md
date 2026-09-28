# Deployment

How PAIMANA runs in production: one Docker Compose stack on a Linux server or, for a demo, on a Windows laptop with
Docker Desktop, with LM Studio on the host next to it. The security properties of the setup are in
[SECURITY.md](SECURITY.md) (Deployment); the database in [DATABASE.md](DATABASE.md); sign-in and roles in
[ACCESS_CONTROL.md](ACCESS_CONTROL.md).

## The stack

`docker-compose.yml` starts five containers on a private network (`10.201.0.0/24`):

| Container | Image | Role | Published |
|---|---|---|---|
| `web` | `paimana-web` (`Dockerfile.web`: node 22 build, nginx 1.27) | TLS, the dashboard, `/api/` proxied to the api, rate limits, security headers | 80 (redirects) and 443 |
| `api` | `paimana-api` (`Dockerfile.api`: python 3.13-slim) | FastAPI, one uvicorn worker, the background jobs, the LLM client | nothing |
| `migrate` | `paimana-api` | `python -m alembic upgrade head`, runs to completion before the api starts | nothing |
| `postgres` | `pgvector/pgvector:pg16` | application truth (volume `pgdata`) | nothing (dev override: 127.0.0.1:5434) |
| `backup` | `pgvector/pgvector:pg16` | `pg_dump -Fc` every day into `./backups/`, 14 days kept | nothing |

One api worker on purpose: the scheduler (`backend/live/scheduler.py`) and the LLM gate (`llm/client.py`) live in
the process, so a second worker would run every job twice and let two LLM calls collide. Give the container more
memory (`deploy.resources.limits.memory`, 4 GB) rather than more workers.

Bind mounts of the api: `dataset/` read-write (the report watcher's pipeline rewrites silver and gold, archives
reports under `raw/`, and the assistant's index lives in `rag/`), `model/` read-only, `database/` (the JSON stores;
`paimana.db` until it is migrated), `temp/`. Everything else in the container is read-only.

Files that never enter git or an image:

- `.env` — every setting; a copy of `.env.production.example`, which explains each one
- `.env.db` — the database credentials, written by `scripts/first-run.*`
- `deploy/certs/fullchain.pem` and `privkey.pem` — the TLS certificate
- `backups/` — database dumps

## Prerequisites

- Docker Engine 24+ with Compose v2 (Linux) or Docker Desktop (Windows). 8 GB of RAM for the stack; the model in LM
  Studio needs its own.
- LM Studio on the host with the models named in `.env` loaded and its server on port 1234. On Linux it must serve on
  `0.0.0.0` (Settings, Developer, "Serve on local network"): the api reaches it as `host.docker.internal`, the host's
  address on the Docker bridge, which a `127.0.0.1` listener refuses. On Docker Desktop the default works.
- The data: `dataset/` and `model/` from the team drive, as for a dev setup. The images contain code only.
- Git, to pull updates. Python and Node are not needed on the server: the images build the frontend and install the
  api.

## First run

Linux server:

```
git clone <repo> paimana && cd paimana
sh scripts/first-run.sh
```

Windows laptop demo (PowerShell) with the dev ports:

```
powershell -ExecutionPolicy Bypass -File scripts\first-run.ps1 -Dev
```

The script is idempotent; it skips what already exists. It writes `.env` from `.env.production.example` and
`.env.db` with a generated 32-character password, makes a self-signed certificate (`scripts/gen-dev-cert.*`) when
`deploy/certs/` is empty, runs `docker compose build`, starts postgres, runs `migrate`, starts the whole stack,
creates the first administrator (`python -m backend.auth.bootstrap` asks for the password itself), loads the
serving tables (`python -m pipeline.run serve`) and prints the URL. Options: `--dev` / `-Dev` (laptop ports),
`--skip-admin`, `--skip-serve`.

Before a real server's first run edit `.env`: `SERVER_NAME`, `ALLOWED_ORIGINS` (the exact https origin users
open), `ALLOWED_HOSTS`; and put a CA certificate in `deploy/certs/` (Real server, below). The stack serves https
only.

Laptop ports: `docker-compose.dev.yml` publishes the dashboard on https://localhost:8443 (http://localhost:8080
redirects there), postgres on 127.0.0.1:5434 (`psql`; `pytest` with the `DATABASE_URL` of `.env.db`) and creates a
`paimana_test` database. Nothing collides with the dev servers (8000/8010, 3000/5174, 5432/5433). Every compose
command then needs both files:

```
docker compose -f docker-compose.yml -f docker-compose.dev.yml <command>
```

or, once per shell, `export COMPOSE_FILE=docker-compose.yml:docker-compose.dev.yml` (PowerShell:
`$env:COMPOSE_FILE = 'docker-compose.yml;docker-compose.dev.yml'`), after which the plain `docker compose` commands
below and the scripts use the override too.

## One-off commands

The bootstrap, the serving-table load, an alembic command or a Python check run in a fresh container of the api
image with the stack's volumes and settings:

```
docker compose run --rm --no-deps api python -m backend.auth.bootstrap --email <e> --name <n>
docker compose run --rm --no-deps api python -m pipeline.run serve
docker compose run --rm --no-deps api python -m alembic current
```

`run` (not `exec`) on purpose: it starts the image's entrypoint (`deploy/api-entrypoint.sh`), which points
`DATABASE_URL` at the stack's postgres; `.env.db`'s own `DATABASE_URL` is the host-side one (the port
`docker-compose.dev.yml` publishes), for pytest and psql run on the host. `docker compose exec api ...` runs inside
the live api container without the entrypoint and is for looking around (`/readyz`, files, logs), not for database
work.

## Every day

- State: `docker compose ps`. The health column comes from `pg_isready` (postgres), `GET /healthz` (api: the
  process answers) and `GET /healthz` on port 80 (web). Readiness (data loaded, database reachable, LLM state) is
  `GET /readyz` on the api, inside the network only:
  `docker compose exec api python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/readyz').read().decode())"`.
- Logs, all to stdout: `docker compose logs -f api` (the access log carries a request id; nginx passes its own as
  `X-Request-ID`), `logs -f web`, `logs backup`, `logs migrate`.
- Restart one container: `docker compose restart api`. Stop everything: `docker compose down` (the data volume and
  the bind mounts stay); start again: `docker compose up -d`.
- New reports: drop them into `dataset/raw/inbox/` on the host or upload them from the dashboard; the watcher inside
  the api picks them up within `WATCH_INTERVAL_S`.

## Updates

```
git pull
docker compose build
docker compose up -d
```

`up -d` runs `migrate` (idempotent) before it replaces the api, and recreates only the containers whose image or
configuration changed. Check `docker compose ps` and `docker compose logs migrate api` afterwards. To go back:
`git checkout <previous commit>` and the same three commands; a migration without a downgrade needs a restore
(below). Rebuild at least monthly even without code changes, to take the base images' security fixes.

## Backups and restore

The backup container runs `pg_dump -Fc` at `BACKUP_HOUR` UTC (02:00) into `./backups/paimana-<UTC stamp>.dump` and
deletes dumps older than `BACKUP_KEEP_DAYS` (14). On Linux the files belong to root with mode 600. Copy `backups/`
off the machine (rsync, a drive): the container only writes locally.

- A dump now: `sh scripts/backup.sh` or `scripts\backup.ps1` (runs the same script through the backup container, so
  no client tools are needed on the host).
- Restore: `sh scripts/restore.sh backups/paimana-20260928-020000.dump` or `scripts\restore.ps1 -File ...`. It stops
  the api and backup containers, runs `pg_restore --clean --if-exists`, starts them again, and asks for a "yes"
  first.
- Not in the dumps: `dataset/`, `model/`, `database/*.json`, `.env`, `.env.db` and the certificate. Back those up as
  files.

## Rotating the database password

1. `docker compose exec postgres psql -U paimana -d paimana -c "ALTER USER paimana PASSWORD 'new-password'"`
   (alphanumeric, or URL-encode it in the `DATABASE_URL` line).
2. Put it in `.env.db`: `POSTGRES_PASSWORD` and the `DATABASE_URL` line.
3. `docker compose up -d`: api, migrate and backup are recreated with the new environment. postgres keeps running;
   its own `POSTGRES_PASSWORD` variable only matters when the volume is first created.

## Real server

- Domain: in `.env` set `SERVER_NAME=<domain>`, `ALLOWED_ORIGINS=https://<domain>`,
  `ALLOWED_HOSTS=<domain>,127.0.0.1` (the second is the container's own health probe).
- Certificate: `deploy/certs/fullchain.pem` and `privkey.pem` from a CA. With Let's Encrypt: `certbot certonly
  --standalone -d <domain>` while the stack is stopped (port 80 must be free), or a DNS challenge while it runs; copy
  the two files from `/etc/letsencrypt/live/<domain>/` and `docker compose restart web`. Renewals: a monthly cron
  with `certbot renew`, the copy, and the restart. Any replacement of the files needs `docker compose restart web`.
- `SECURE_COOKIES=1` stays: the stack never serves the dashboard over plain http. HSTS is on for a year without
  `includeSubDomains`, so other subdomains of the ministry are untouched.
- Ports: 80 and 443 only (`WEB_HTTP_PORT`, `WEB_HTTPS_PORT`). A firewall in front needs nothing else open.
- File ownership: the api runs as uid 1000. On Linux `dataset/`, `database/` and `temp/` must be writable by it:
  `sudo chown -R 1000:1000 dataset database temp`, or build with `docker compose build --build-arg APP_UID=$(id -u)
  --build-arg APP_GID=$(id -g) api`.
- LM Studio serves on `0.0.0.0` (Prerequisites); keep port 1234 closed to the outside in the host firewall. The
  stack reaches it through the Docker bridge, which the firewall should allow.
- Behind another proxy or load balancer: nginx's rate limits key on the address it sees; add `set_real_ip_from` /
  `real_ip_header` for the balancer's range to `deploy/nginx.conf.template`, and add the range to `TRUSTED_PROXIES`
  only if the balancer appends `X-Forwarded-For`.
- The compose network is `PAIMANA_SUBNET` (`10.201.0.0/24`); change it if the server routes that block, and change
  `TRUSTED_PROXIES` with it.
- The backup hour is UTC.

## Troubleshooting

- `api` unhealthy, or `docker compose logs api` says the database is unreachable: `docker compose ps postgres`; the
  password in `.env.db` must be the one the volume was created with (Rotating, above).
- The assistant says the LLM is unavailable: on the host `curl http://localhost:1234/v1/models`; from the container
  `docker compose exec api python -c "import urllib.request; print(urllib.request.urlopen('http://host.docker.internal:1234/v1/models', timeout=5).read()[:200])"`.
  On Linux the usual cause is LM Studio listening on 127.0.0.1 only.
- 429 from the dashboard: nginx's per-IP limits (`deploy/nginx.conf.template`: auth 10/min, api 60/min with a burst
  of 100, chat 10/min). Many users behind one NAT share one address; raise `rate=` for the api zone, then
  `docker compose build web && docker compose up -d web`.
- A browser warning about the certificate: the self-signed pair from `scripts/gen-dev-cert.*`. Expected on a laptop,
  wrong on a server.
- `migrate` fails and the api never starts: `docker compose logs migrate`; fix the cause and `docker compose up -d`
  again (`docker compose run --rm migrate` runs it alone).
- Windows: run the `.ps1` scripts from PowerShell (`-ExecutionPolicy Bypass` when the policy blocks them) or the
  `.sh` ones from Git Bash. `.gitattributes` keeps the shell scripts and everything under `deploy/` at LF, which the
  containers need.
