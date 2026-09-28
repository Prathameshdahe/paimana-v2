"""Passwords (and the email check they lean on): argon2id hashes (argon2-cffi's defaults, RFC 9106's low-memory
profile: 64 MiB, 3 passes, 4 lanes, about 50 ms here) and the policy every new password passes: at least MIN_LENGTH
characters not counting whitespace at either end, at most MAX_LENGTH, at least MIN_DISTINCT different characters (no
run of one repeated character, no blank password), not a common password (COMMON, compared lower-cased with and
without its non-alphanumerics, as frontend/src/lib/auth/password.ts does), and not containing the email's local part
when that is 3 characters or more. The password itself is kept as typed (nothing is trimmed from it).

verify() never raises: a wrong password, a malformed hash or None is False. dummy_verify() spends the same time
on nothing, so a sign-in with an unknown email takes as long as one with a known email and a wrong password.
normal_email() trims an address and checks its shape (and settings.allowed_email_domains when set).
"""
from __future__ import annotations

import re
from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from backend import settings as cfg

MIN_LENGTH, MAX_LENGTH, MIN_DISTINCT = 12, 256, 5
EMAIL_MAX = 254
EMAIL_RX = re.compile(r"[^@\s]{1,64}@[^@\s]+\.[^@\s.]{2,}")
_hasher = PasswordHasher()

COMMON = frozenset("""
password password1 password12 password123 password1234 password12345 password123456 passw0rd p@ssw0rd password@123
password@1234 passw0rd123 passw0rd@123 pass@123 pass@1234 pass@12345 123456 12345678 123456789 1234567890
12345678910 123456789012 1234567890123 111111111111 000000000000 123123123123 qwerty qwerty123 qwerty12345
qwerty123456 qwertyuiop qwertyuiop12 qwertyuiop123 1q2w3e4r5t6y 1qaz2wsx3edc zaq12wsxcde3 asdfghjkl123 letmein
letmein12345 welcome welcome1 welcome123 welcome1234 welcome@123 welcome@1234 admin admin123 admin@123 admin@1234
admin@12345 admin123456 administrator administrator1 iloveyou iloveyou123 monkey dragon sunshine princess football
baseball abc123 abcd1234 abcdefgh abcdefghijkl abcdefgh1234 abc123456789 111111 000000 india123 india@123 india@1234
india@12345 bharat@123 bharat@1234 paimana paimana123 paimana@123 paimana@1234 paimanaradar changeme changeme123
changeme@123 secret secret123456 trustno1 mospi123 mospi@123 mospi@1234 ipmd@123 ipmd1234 ipmd@1234 government
government123 government@123 goi@123456 nic@123456 computer123 internet123 superman123 starwars123
""".split())


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify(password_hash: str | None, password: str | None) -> bool:
    if not password_hash or password is None:
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """True when the hash was made with other parameters than the current ones (rehash at the next sign-in)."""
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


@lru_cache(maxsize=1)
def _dummy() -> str:
    return _hasher.hash("an account that does not exist")


def dummy_verify(password: str | None) -> bool:
    """A verification against a hash no password matches: the unknown-email path's equal cost. Always False."""
    verify(_dummy(), (password or "") + "\x00")
    return False


def problems(password: str, email: str | None = None) -> list[str]:
    """What the policy rejects in password, in order (empty: it passes)."""
    out = []
    core, low = password.strip(), password.lower()
    if len(core) < MIN_LENGTH:
        out.append(f"at least {MIN_LENGTH} characters")
    if len(password) > MAX_LENGTH:
        out.append(f"at most {MAX_LENGTH} characters")
    if len(set(core)) < MIN_DISTINCT:
        out.append(f"at least {MIN_DISTINCT} different characters")
    if low in COMMON or "".join(c for c in low if c.isalnum()) in COMMON:
        out.append("not a common password")
    local = (email or "").split("@")[0].strip().lower()
    if len(local) >= 3 and local in low:
        out.append("not containing the name part of the email")
    return out


def check(password: str, email: str | None = None) -> None:
    """ValueError naming every rule the password breaks, else nothing."""
    bad = problems(password, email)
    if bad:
        raise ValueError("the password does not meet the rules: " + "; ".join(bad))


def normal_email(raw: str) -> str:
    """The address trimmed; ValueError when it does not look like one or its domain is not allowed."""
    out = (raw or "").strip()
    if len(out) > EMAIL_MAX or not EMAIL_RX.fullmatch(out):
        raise ValueError("that does not look like an email address")
    domains = {d.lower().lstrip("@") for d in cfg.settings.allowed_email_domains}
    if domains and out.rsplit("@", 1)[1].lower() not in domains:
        raise ValueError("accounts are for official email addresses of " + ", ".join(sorted(domains)))
    return out
