"""Project-name normalisation for entity resolution.

Goal: "Delhi-Mumbai Exp. Pkg-I" and "Delhi Mumbai Expressway Package 1"
produce the same token set. Extend ABBREV as you meet new spellings in
the reports; keep STOP small so rare words stay discriminative.
"""
from __future__ import annotations

import re
import unicodedata

ABBREV: dict[str, str] = {
    "pkg": "package", "pkgs": "package", "pack": "package",
    "exp": "expressway", "expy": "expressway", "expwy": "expressway",
    "rly": "railway", "rlys": "railway", "rail": "railway",
    "nh": "nh",  # keep as-is: "nh 44" is a real token
    "ph": "phase", "phs": "phase",
    "stn": "station", "jn": "junction", "jnc": "junction",
    "dt": "district", "dist": "district",
    "tpp": "thermalpower", "stpp": "superthermalpower", "tps": "thermalpower",
    "hep": "hydroelectric", "hpp": "hydropower", "hp": "hydropower",
    "govt": "government", "pvt": "", "ltd": "", "limited": "",
    "i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5", "vi": "6",
    "vii": "7", "viii": "8", "ix": "9", "x": "10",
    "km": "km", "kms": "km", "mw": "mw", "mtpa": "mtpa",
}

STOP: frozenset[str] = frozenset({
    "project", "projects", "of", "the", "and", "in", "for", "at", "to",
    "a", "an", "on", "by", "with", "new", "work", "works", "scheme",
    "construction", "development", "under", "via", "from", "between",
})

_NON_ALNUM = re.compile(r"[^a-z0-9 ]+")
_WS = re.compile(r"\s+")


def normalize_name(name: str | None) -> str:
    """Lower-case, strip accents/punctuation, expand abbreviations, drop stopwords."""
    if name is None:
        return ""
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    s = s.lower().replace("&", " and ").replace("-", " ").replace("/", " ")
    s = _NON_ALNUM.sub(" ", s)
    tokens = []
    for tok in _WS.split(s.strip()):
        if not tok:
            continue
        tok = ABBREV.get(tok, tok)
        if tok and tok not in STOP:
            tokens.append(tok)
    return " ".join(tokens)


def name_tokens(name: str | None) -> frozenset[str]:
    return frozenset(normalize_name(name).split())


def normalize_code(code: str | None) -> str | None:
    """Printed project codes: keep digits/letters only, upper-case; empty -> None."""
    if code is None:
        return None
    s = re.sub(r"[^A-Za-z0-9]", "", str(code)).upper()
    if not s or s in {"NA", "NAN", "NONE", "NIL", "0"}:
        return None
    return s
