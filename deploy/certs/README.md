# deploy/certs

The web container mounts this folder read-only as `/etc/nginx/certs` and expects two files
(Let's Encrypt's names, so a certbot output can be copied in as is):

- `fullchain.pem` — the server certificate followed by its chain
- `privkey.pem` — the private key (mode 600 on Linux)

Everything here except this README is git-ignored. `scripts/gen-dev-cert.ps1` / `.sh` writes a self-signed pair for
a laptop or LAN demo; a real server needs a certificate from a CA (docs/DEPLOYMENT.md, Real server). After replacing
the files run `docker compose restart web`.
