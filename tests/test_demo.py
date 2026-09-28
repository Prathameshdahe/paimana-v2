"""The demo stack (docs/DEPLOYMENT.md, Demo): docker-compose.demo.yml, Dockerfile.demo and its ignore file,
deploy/nginx.demo.conf, deploy/demo-init.sh and scripts/demo-save.* are text, so these tests read them and check
what makes the demo safe to hand out: it binds to 127.0.0.1 only, the one-click sign-in stays out of production, no
secret enters the images, and the plain-http nginx keeps the production locations and headers."""
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def _text(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def demo():
    return yaml.safe_load(_text("docker-compose.demo.yml"))


def _locations(conf: str) -> set[str]:
    return {m.strip() for m in re.findall(r"^\s*location ([^{]+)\{", conf, re.M)}


def test_demo_services_and_exposure(demo):
    services = demo["services"]
    assert set(services) == {"postgres", "init", "api", "web"}
    assert demo["name"] == "paimana-demo"
    published = {name for name, s in services.items() if s.get("ports")}
    assert published == {"web"}
    assert all(p.startswith("127.0.0.1:") for p in services["web"]["ports"])


def test_demo_api_settings(demo):
    api, init = demo["services"]["api"], demo["services"]["init"]
    env = api["environment"]
    assert env["DEMO_LOGIN"] == "1" and env["SECURE_COOKIES"] == "0" and env["POSTGRES_HOST"] == "postgres"
    assert api["depends_on"]["init"]["condition"] == "service_completed_successfully"
    assert init["command"] == ["sh", "/app/deploy/demo-init.sh"] and init["restart"] == "no"
    assert init["environment"]["LIVE_JOBS"] == "0"
    for s in (api, init):
        assert s["build"]["dockerfile"] == "Dockerfile.demo" and s["build"]["target"] == "api"
        assert s["image"] == "paimana-demo-api"
    assert demo["services"]["web"]["build"]["target"] == "web"
    # the api must not mount the host's data over the copy in its image
    assert not api.get("volumes") and not api.get("env_file")


def test_one_click_sign_in_stays_out_of_production():
    for name in ("docker-compose.yml", "docker-compose.dev.yml"):
        assert "DEMO_LOGIN" not in _text(name)
    assert re.search(r"^DEMO_LOGIN=0$", _text(".env.production.example"), re.M)


def test_demo_dockerfile_targets():
    df = _text("Dockerfile.demo")
    targets = re.findall(r"^FROM \S+ AS (\w+)$", df, re.M)
    assert {"api", "web"} <= set(targets)
    assert "USER app" in df and "ENTRYPOINT [\"/app/deploy/api-entrypoint.sh\"]" in df
    assert "COPY deploy/nginx.demo.conf /etc/nginx/conf.d/paimana.conf" in df
    assert "/app/deploy/demo-init.sh" in df


def test_demo_dockerignore_keeps_secrets_out_and_lets_data_in():
    lines = {line.strip() for line in _text("Dockerfile.demo.dockerignore").splitlines()
             if line.strip() and not line.startswith("#")}
    assert {".git", ".env", ".env.*", "deploy/certs", "backups", "temp", "Dataset drive folder", "dataset.zip"} <= lines
    assert {"frontend/node_modules", "database/*.db"} <= lines
    assert not {"dataset", "model", "database/*.json"} & lines


def test_demo_nginx_keeps_the_production_locations_and_headers():
    demo_conf, prod = _text("deploy/nginx.demo.conf"), _text("deploy/nginx.conf.template")
    assert _locations(prod) <= _locations(demo_conf)
    assert "ssl" not in demo_conf and "Strict-Transport-Security" not in demo_conf
    assert "listen 80;" in demo_conf and "server_tokens off;" in demo_conf
    csp = re.search(r'add_header Content-Security-Policy "(.*?)" always;', prod)[1]
    assert csp in demo_conf
    for header in ("X-Content-Type-Options nosniff", "X-Frame-Options DENY",
                   "Referrer-Policy strict-origin-when-cross-origin"):
        assert header in demo_conf
    assert "token=[redacted]" in demo_conf and "try_files $uri $uri/ /index.html;" in demo_conf
    assert "${" not in demo_conf   # copied as it is: no template variables


def test_demo_init_and_save_scripts():
    init = _text("deploy/demo-init.sh")
    assert init.startswith("#!/bin/sh\n") and "set -eu" in init
    for step in ("CREATE EXTENSION IF NOT EXISTS vector", "CREATE EXTENSION IF NOT EXISTS citext",
                 "python -m alembic upgrade head", "python -m pipeline.run serve"):
        assert step in init
    for name in ("scripts/demo-save.sh", "scripts/demo-save.ps1"):
        text = _text(name)
        assert "docker-compose.demo.yml" in text and "paimana-demo-images.tar" in text
    assert "paimana-demo-images.tar*" in _text(".gitignore").splitlines()
    assert {"*.tar", "*.tar.gz"} <= set(_text(".dockerignore").splitlines())
