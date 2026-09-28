"""Sign-in, sessions, roles and the API's protections (SPEC9 section 2; docs/ACCESS_CONTROL.md, docs/SECURITY.md).

passwords.py  argon2id hashes and the password policy
sessions.py   the session cookie, current() (the viewer's session), guard() (Origin and CSRF on every write)
limits.py     the sign-in lock, the per-address sign-in and sign-up limits (kept in the database)
routes.py     /api/auth (signup, login, logout, me, password, reset) and /api/admin (sign-ups, accounts, audit)
middleware.py the HTTP hardening: proxy addresses, request ids, security headers, access log, CORS, Host, body
              limit, time limit, errors without tracebacks
bootstrap.py  python -m backend.auth.bootstrap: the first administrator and the hidden developer account
The SQL is backend/db/accounts.py; the viewer and the role table are backend/access.py.
"""
