"""The ops files (docs/DEPLOYMENT.md): docker-compose.yml, docker-compose.dev.yml, the Dockerfiles,
deploy/nginx.conf.template, the scripts and the CI workflow are text, so these tests read them and check what the
deployment relies on: what is published, what is read-only, the limits, the headers, the line endings, and that every
variable the stack reads is documented in .env.production.example. They need no Docker."""
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


class _Loader(yaml.SafeLoader):
    """Compose's !override and !reset tags: keep the tagged value."""


def _tagged(loader, _suffix, node):
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return loader.construct_scalar(node)


_Loader.add_multi_constructor("!", _tagged)


def _text(name):
    return (ROOT / name).read_text(encoding="utf-8")


def _yaml(name):
    return yaml.load(_text(name), Loader=_Loader)


@pytest.fixture(scope="module")
def prod():
    return _yaml("docker-compose.yml")["services"]


@pytest.fixture(scope="module")
def dev():
    return _yaml("docker-compose.dev.yml")["services"]


@pytest.fixture(scope="module")
def nginx():
    return _text("deploy/nginx.conf.template")


def test_compose_services_and_exposure(prod):
    assert set(prod) == {"postgres", "migrate", "api", "web", "backup"}
    for hidden in ("postgres", "migrate", "api", "backup"):
        assert "ports" not in prod[hidden], hidden
    assert prod["web"]["ports"] == ["${WEB_HTTP_PORT:-80}:80", "${WEB_HTTPS_PORT:-443}:443"]
    assert prod["postgres"]["image"] == "pgvector/pgvector:pg16" == prod["backup"]["image"]
    assert prod["postgres"]["healthcheck"]["test"][1].startswith("pg_isready")
    assert prod["postgres"]["shm_size"]
    assert "pgdata:/var/lib/postgresql/data" in prod["postgres"]["volumes"]
    assert prod["postgres"]["env_file"] == [".env.db"]


def test_compose_migrate_runs_alembic_once_after_postgres(prod):
    m = prod["migrate"]
    assert m["command"] == ["python", "-m", "alembic", "upgrade", "head"]
    assert m["depends_on"]["postgres"]["condition"] == "service_healthy"
    assert m["restart"] == "no"
    assert prod["api"]["depends_on"]["migrate"]["condition"] == "service_completed_successfully"


def test_compose_api_hardening(prod):
    a = prod["api"]
    assert a["read_only"] is True and a["cap_drop"] == ["ALL"]
    assert a["deploy"]["resources"]["limits"]["memory"] == "4g"
    assert a["restart"] == "unless-stopped"
    assert a["extra_hosts"] == ["host.docker.internal:host-gateway"]
    env = a["environment"]
    assert env["POSTGRES_HOST"] == "postgres"
    assert "host.docker.internal:1234/v1" in env["LLM_BASE_URL"]
    assert env["LIVE_JOBS"] == "${LIVE_JOBS:-1}"
    assert set(a["env_file"]) == {".env", ".env.db"}
    assert "./model:/app/model:ro" in a["volumes"]
    for rw in ("./dataset:/app/dataset", "./database:/app/database", "./temp:/app/temp"):
        assert rw in a["volumes"], rw


def test_compose_web_and_backup(prod):
    w = prod["web"]
    assert w["read_only"] is True and "./deploy/certs:/etc/nginx/certs:ro" in w["volumes"]
    assert w["depends_on"]["api"]["condition"] == "service_started"
    b = prod["backup"]
    assert b["entrypoint"] == ["bash", "/backup.sh"] and b["command"] == ["loop"]
    assert "./backups:/backups" in b["volumes"] and "./deploy/backup.sh:/backup.sh:ro" in b["volumes"]


def test_dev_override_ports_avoid_the_dev_servers(dev):
    assert dev["postgres"]["ports"] == ["127.0.0.1:5434:5432"]
    assert dev["web"]["ports"] == ["127.0.0.1:8080:80", "127.0.0.1:8443:443"]
    assert dev["web"]["environment"]["PAIMANA_HTTPS_SUFFIX"] == ":8443"
    assert dev["postgres"]["environment"]["PAIMANA_TEST_DB"] == "paimana_test"
    assert "ports: !override" in _text("docker-compose.dev.yml")  # replaces the production ports, never adds to them


def test_nginx_policy(nginx):
    csp = ("default-src 'self'; img-src 'self' data:; font-src 'self' https://fonts.gstatic.com; "
           "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; connect-src 'self'")
    assert csp in nginx
    assert "Strict-Transport-Security" in nginx and "X-Frame-Options DENY" in nginx
    assert "X-Content-Type-Options nosniff" in nginx and "Referrer-Policy strict-origin-when-cross-origin" in nginx
    assert "ssl_protocols TLSv1.2 TLSv1.3;" in nginx and "server_tokens off;" in nginx
    zones = dict(re.findall(r"limit_req_zone \$binary_remote_addr zone=(\w+):\w+ rate=(\d+r/m);", nginx))
    assert zones == {"auth": "10r/m", "api": "60r/m", "chat": "10r/m"}
    assert "limit_req_status 429;" in nginx and "limit_req_log_level warn;" in nginx
    assert "return 301 https://$host${PAIMANA_HTTPS_SUFFIX}$request_uri;" in nginx
    assert "try_files $uri $uri/ /index.html;" in nginx
    assert "access_log /dev/stdout" in nginx and "gzip on;" in nginx


def _block(nginx, header):
    """The first location block whose header line contains `header`, up to its closing brace."""
    start = nginx.index(header)
    return nginx[start:nginx.index("\n    }", start)]


def test_nginx_locations(nginx):
    assert nginx.count("client_max_body_size 110m;") == 1
    assert "client_max_body_size 110m;" in _block(nginx, "location = /api/jobs/ingest")
    for loc in ("location = /api/chat", "location = /api/stream"):
        body = _block(nginx, loc)
        assert "proxy_buffering off;" in body and "proxy_read_timeout 600s;" in body, loc
    assert "limit_req zone=auth" in _block(nginx, "location /api/auth/")
    assert "limit_req zone=chat" in _block(nginx, "location = /api/chat")
    assert "limit_req zone=api" in _block(nginx, "location /api/ ")
    # envsubst may only touch PAIMANA_* variables: any other ${...} would be blanked when the image starts
    assert set(re.findall(r"\$\{(\w+)\}", nginx)) <= {"PAIMANA_SERVER_NAME", "PAIMANA_HTTPS_SUFFIX"}


def test_dockerfiles():
    api = _text("Dockerfile.api")
    assert "FROM python:3.13-slim" in api and "\nUSER app\n" in api
    assert '"--workers", "1"' in api and "--timeout-graceful-shutdown" in api
    assert "/healthz" in api and 'ENTRYPOINT ["/app/deploy/api-entrypoint.sh"]' in api
    web = _text("Dockerfile.web")
    assert "FROM node:22-alpine AS build" in web and "FROM nginx:1.27-alpine" in web
    assert "npm ci" in web and "npm run build" in web
    assert "NGINX_ENVSUBST_FILTER=^PAIMANA_" in web
    # the base config replaces the image's, so its access_log does not double every line of the paimana one
    assert "COPY deploy/nginx.conf /etc/nginx/nginx.conf" in web
    base = _text("deploy/nginx.conf")
    assert not re.search(r"^\s*access_log\b", base, re.M) and "include /etc/nginx/conf.d/*.conf;" in base


def test_dockerignore_keeps_secrets_and_data_out():
    lines = _text(".dockerignore").splitlines()
    for p in (".env", ".env.*", "deploy/certs", "backups", "frontend/node_modules", "dataset", "model", ".git"):
        assert p in lines, p


def test_shell_scripts_are_lf_and_paired():
    attrs = _text(".gitattributes")
    assert "*.sh text eol=lf" in attrs and "deploy/** text eol=lf" in attrs
    shs = sorted((ROOT / "scripts").glob("*.sh")) + sorted((ROOT / "deploy").rglob("*.sh"))
    assert shs
    for sh in shs:
        raw = sh.read_bytes()
        assert b"\r" not in raw, f"{sh} has CRLF line endings"
        assert raw.startswith(b"#!/"), f"{sh} has no shebang"
    for sh in (ROOT / "scripts").glob("*.sh"):
        assert sh.with_suffix(".ps1").exists(), f"{sh.name} has no PowerShell twin"
    for name in ("Dockerfile.api", "Dockerfile.web", "deploy/nginx.conf", "deploy/nginx.conf.template"):
        assert b"\r" not in (ROOT / name).read_bytes(), name


def _env_names(name):
    return {m.group(1) for m in re.finditer(r"^#?\s?([A-Z][A-Z0-9_]+)=", _text(name), re.M)}


def test_env_production_example_documents_every_variable():
    documented = _env_names(".env.production.example")
    compose = _text("docker-compose.yml") + _text("docker-compose.dev.yml")
    interpolated = set(re.findall(r"\$\{([A-Z][A-Z0-9_]+)", compose))
    assert interpolated <= documented, interpolated - documented
    # the app settings of .env.example, minus the ones the stack sets itself or that only the dev servers use
    app = _env_names(".env.example") - {"VITE_API_BASE", "LLM_BASE_URL", "PAIMANA_DB"}
    assert app <= documented, app - documented
    # the database credentials live in .env.db, never here
    assert not {"POSTGRES_PASSWORD", "DATABASE_URL"} & documented


def test_gitignore_keeps_local_state_out():
    ignored = _text(".gitignore").splitlines()
    for p in ("backups/", "deploy/certs/*", "!deploy/certs/README.md", "!.env.production.example"):
        assert p in ignored, p


def test_ci_workflow_only_checks():
    wf = _yaml(".github/workflows/check.yml")
    assert wf["permissions"] == {"contents": "read"}
    text = _text(".github/workflows/check.yml")
    assert "git push" not in text and "docker push" not in text and "secrets." not in text
    jobs = wf["jobs"]
    assert jobs["backend"]["services"]["postgres"]["image"] == "pgvector/pgvector:pg16"
    backend = " ".join(s.get("run", "") for s in jobs["backend"]["steps"])
    assert "python -m pytest -q" in backend
    frontend = " ".join(s.get("run", "") for s in jobs["frontend"]["steps"])
    assert "npm run lint" in frontend and "npm run typecheck" in frontend and "npm run build" in frontend
