"""
perf_2018_21 - MoSPI IPMD "Review of Infrastructure Sector Performance" monthly
reports, Apr 2018 - Mar 2021 (folders Performance Monitoring/2018-19 and
Performance Monitoring/2020-21; the 2020-21 folder also holds FY 2019-20 months,
so fiscal_year always comes from the report month, never the folder).

Outputs (dataset/clean/_parts/perf_2018_21/):
  perf.csv         Annexure-A month + April-to-month cumulative rows (PERF_COLS)
  perf_detail.csv  Highlights, Areas of concern, Noteworthy performance and the
                   ~60 sector detail tables, one row per numeric cell
  manifest.csv     one row per PDF

Parsing is done on PyMuPDF word boxes: words -> lines (by baseline) -> value
columns (numbers clustered by horizontal overlap; Annexure columns mapped onto the
printed "(1) (2) .. (11)" column-number row) -> header text assigned to columns by
x-overlap, then normalised to Target / Achievement / Actual / % Variation labels with
the period carried in period_start/period_end. Areas-of-concern / Noteworthy rows are
kept only when their printed percentages agree with their own values.

Run from repo root:  python pipeline/extract/perf_2018_21.py
"""
import re
import sys
from collections import Counter
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (DATASET, MANIFEST_COLS, PERF_COLS, PERF_DETAIL_COLS,  # noqa: E402
                    fiscal_year, rel, to_num, to_ym, write_part)

FAMILY = "perf_2018_21"
SRC_DIRS = [DATASET / "Performance Monitoring" / "2018-19",
            DATASET / "Performance Monitoring" / "2020-21"]

# --------------------------------------------------------------------------
# words / lines
# --------------------------------------------------------------------------
_TR = str.maketrans({"‐": "-", "‑": "-", "–": "-", "—": "-",
                     "−": "-", "\xa0": " ", "’": "'", "‘": "'"})


class W:
    __slots__ = ("x0", "y0", "x1", "y1", "t")

    def __init__(self, x0, y0, x1, y1, t):
        self.x0, self.y0, self.x1, self.y1, self.t = x0, y0, x1, y1, t

    @property
    def cx(self):
        return (self.x0 + self.x1) / 2


class Line:
    def __init__(self, words):
        self.words = sorted(words, key=lambda w: w.x0)
        self.y = sum(w.y1 for w in words) / len(words)

    @property
    def text(self):
        return " ".join(w.t for w in self.words)


def page_lines(page, tol=2.5):
    ws = []
    for x0, y0, x1, y1, t, *_ in page.get_text("words"):
        t = t.translate(_TR).strip()
        if t:
            ws.append(W(x0, y0, x1, y1, t))
    ws.sort(key=lambda w: w.y1)
    lines, cur = [], []
    for w in ws:
        if cur and w.y1 - cur[0].y1 > tol:
            lines.append(Line(cur))
            cur = []
        cur.append(w)
    if cur:
        lines.append(Line(cur))
    return lines


NA_TOK = {"NA", "N.A.", "N.A", "Na", "na", "NN", "N/A", "-", "--", "*", "$", "NR", "N.R.", "Nil", "NIL", "..",
          "#DIV/0!", "#VALUE!", "#N/A", "#REF!", "#NUM!"}  # NN = typo for NA (Jun 2018 Table 18)
_NUM = re.compile(r"\(?[-+]?(?:\d[\d,]*)?\.?\d+\)?%?")


def is_value(t):
    # malformed numbers such as "281.3.5" are still value cells (to_num -> blank)
    return t in NA_TOK or bool(_NUM.fullmatch(t)) or bool(re.fullmatch(r"[-+(]?\d[\d.,]*\)?%?", t))


def split_line(ln):
    """(label_words, value_words): values are the trailing run of value tokens."""
    k = -1
    for i, w in enumerate(ln.words):
        if not is_value(w.t):
            k = i
    return ln.words[:k + 1], ln.words[k + 1:]


def norm_ws(s):
    return re.sub(r"\s+", " ", s or "").strip()


_ENUM = re.compile(r"^(?:\d{1,2}\s*\.?(?=\s|$)|\(?[ivx]{1,4}\s*\)|\(?[a-h]\s*\)|[A-H]\.(?=\s)|[IVX]{1,4}\.(?=\s))\s*")


def strip_enum(s):
    s = norm_ws(s)
    for _ in range(3):
        s2 = _ENUM.sub("", s, count=1)
        if s2 == s:
            break
        s = s2
    return s.lstrip(" -:.").rstrip(" -:")


def starts_enum(s):
    return bool(re.match(r"^\s*(?:\(?[ivx]{1,4}\s*\)|\(?[a-h]\s*\))", s or ""))


def starts_serial(s):
    return bool(re.match(r"^\s*\d{1,2}\s*\.?(?:\s|$)", s or ""))


# --------------------------------------------------------------------------
# periods
# --------------------------------------------------------------------------
_MON = (r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
        r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?(?![a-z])")  # not "Decrease"
_RANGE = re.compile(r"apr[a-z]*\.?\s*(?:(\d{4})\s*)?-\s*" + _MON + r"\s*(\d{4}|\d{2})\b", re.I)
_SINGLE = re.compile(r"\b" + _MON + r"\s*[-']?\s*(\d{4}|\d{2})\b", re.I)
_FY = re.compile(r"\b(20\d\d)\s*-\s*(20\d\d|\d\d)\b")


_MON_FULL = {n[1:]: n for n in ("January", "February", "March", "April", "June", "July", "August",
                                  "September", "October", "November", "December")}
_BROKEN_MON = re.compile(r"(?<![A-Za-z])(" + "|".join(_MON_FULL) + r")(?![a-z])", re.I)  # glyph dropped


_SPLIT_MON = re.compile(r"(?<![A-Za-z])(" + "|".join(
    r"\s?".join(n) for n in ("January", "February", "September", "October", "November", "December")) + r")(?![a-z])")


def _fix_months(t):
    """'2018November' -> '2018 November'; 'eptember 2019' -> 'September 2019';
    'Septembe r 2019' -> 'September 2019'."""
    t = re.sub(r"(\d)([A-Za-z])", r"\1 \2", t)
    t = _SPLIT_MON.sub(lambda m: m.group(1).replace(" ", ""), t)
    return _BROKEN_MON.sub(lambda m: _MON_FULL[m.group(1).lower()], t)


def fy_start_ym(ym):
    y, m = int(ym[:4]), int(ym[5:7])
    return f"{y if m >= 4 else y - 1}-04"


def shift_year(ym, dy):
    return f"{int(ym[:4]) + dy:04d}{ym[4:]}"


def find_periods(text):
    """All period mentions in text, in order: (kind, start, end)."""
    t = (text or "").translate(_TR).replace(",", " ")
    t = _fix_months(t)
    out, taken = [], []
    for m in _RANGE.finditer(t):
        end = to_ym(f"{m.group(2)} {m.group(3)}")
        if end:
            out.append((m.start(), "cumulative", fy_start_ym(end), end))
            taken.append((m.start(), m.end()))
    for m in _SINGLE.finditer(t):
        if any(a <= m.start() < b for a, b in taken):
            continue
        ym = to_ym(f"{m.group(1)} {m.group(2)}")
        if ym:
            out.append((m.start(), "month", ym, ym))
            taken.append((m.start(), m.end()))
    for m in _FY.finditer(t):
        if any(a <= m.start() < b for a, b in taken):
            continue
        y0 = int(m.group(1))
        y1 = int(m.group(2)) if len(m.group(2)) == 4 else 2000 + int(m.group(2))
        if y1 == y0 + 1:
            out.append((m.start(), "fy", f"{y0}-04", f"{y1}-03"))
    return [o[1:] for o in sorted(out)]


def fix_title_year(title, rm):
    """Year clipped at the page edge: 'April-November 20' / 'November 201' in the Nov 2018
    report -> report year ('20' alone would otherwise read as 2020)."""
    m = re.search(r"(\d{1,3})\s*$", title or "")
    if rm and m and rm[:4].startswith(m.group(1)) and re.search(_MON + r"[\s,]*$", title[:m.start()], re.I):
        return title[:m.start()] + rm[:4]
    return title


def month_from_filename(name):
    m = re.search(r"CompleteReviewReport([A-Za-z]+)(\d{4})", name)
    return to_ym(f"{m.group(1)} {m.group(2)}") if m else None


# --------------------------------------------------------------------------
# Annexure-A (PRIORITY 1)
# --------------------------------------------------------------------------
G_POW, G_COAL = "Power generation (BU)", "Coal Production (MT)"
G_STEEL = "Production of Finished Steel ('000 Tonnes)"
G_STEEL_MAIN = G_STEEL + " / Main Producer"
G_CEM, G_FERT = "Cement Production (MT)", "Fertilisers Production ('000 Tonnes)"
G_PET, G_ROAD = "Petroleum", "Roads (Kms.)"
G_NHAI = G_ROAD + " / NHAI"
G_SPWD = G_ROAD + " / State PWD and Border Road Organisation (BRO)"
G_CARGO = "Civil Aviation / Cargo handled at Airports (In Metric Tonnes)"
G_PAX = "Civil Aviation / Passenger Traffic Handled at (In Numbers)"

# section keyword -> (sector, [(indicator_group, indicator, unit, is_total, label regex)])
ANNEX = [
    ("power", "Power", [
        (G_POW, "Thermal Generation", "BU", False, r"thermal"),
        (G_POW, "Nuclear Generation", "BU", False, r"nuclear"),
        (G_POW, "Hydro Generation", "BU", False, r"hydro"),
        (G_POW, "Import from Bhutan", "BU", False, r"bhutan"),
        (G_POW, "Renewable Energy", "BU", False, r"renewable"),
        (G_POW, "Total", "BU", True, r"^total$")]),
    ("coal", "Coal", [
        (G_COAL, "Coal India Ltd.", "MT", False, r"coal india"),
        (G_COAL, "Singareni", "MT", False, r"singareni"),
        (G_COAL, "Others", "MT", False, r"^others"),
        (G_COAL, "Total", "MT", True, r"^total$")]),
    ("steel", "Steel", [
        (G_STEEL_MAIN, "SAIL", "'000 Tonnes", False, r"sail"),
        (G_STEEL_MAIN, "ESSAR", "'000 Tonnes", False, r"essar"),
        (G_STEEL_MAIN, "Tata Steet (TSL)", "'000 Tonnes", False, r"tata|tsl"),
        (G_STEEL_MAIN, "JSWL", "'000 Tonnes", False, r"jswl"),
        (G_STEEL_MAIN, "JSPL", "'000 Tonnes", False, r"jspl"),
        (G_STEEL_MAIN, "RINL (VSP)", "'000 Tonnes", False, r"rinl|vsp"),
        (G_STEEL_MAIN, "Total", "'000 Tonnes", True, r"^total$"),
        (G_STEEL, "Major (Secondary) Producer", "'000 Tonnes", False, r"secondary"),
        (G_STEEL, "Total (I + II)", "'000 Tonnes", True, r"total\s*\(i")]),
    ("cement", "Cement", [
        (G_CEM, "Cement Production(MT)", "MT", False, r"cement")]),
    ("fertili", "Fertilizers", [
        (G_FERT, "Nitrogen", "'000 Tonnes", False, r"nitrogen"),
        (G_FERT, "Phosphate", "'000 Tonnes", False, r"phosphate"),
        (G_FERT, "Total", "'000 Tonnes", True, r"^total$")]),
    ("petroleum", "Petroleum & Natural Gas", [
        (G_PET, "Crude Oil Prod. (MT)", "MT", False, r"crude"),
        (G_PET, "Refinery Prod. (MT)", "MT", False, r"refinery"),
        (G_PET, "Natural Gas Prod. (MCM)", "MCM", False, r"natural gas")]),
    ("roads", "Roads", [
        (G_NHAI, "Widening/ Strengthening/ existing weak pavement to four/six/eight lanes (Kms.)",
         "Kms", False, r"widening/\s*strengthening"),
        (G_SPWD, "Widening to four/six/eight lanes (Kms.)", "Kms", False, r"widening to four"),
        (G_SPWD, "Widening to two lanes (Kms.)", "Kms", False, r"two lanes"),
        (G_SPWD, "Strengthening of existing weak pavement (Kms.)", "Kms", False, r"^strengthening of"),
        (G_SPWD, "Total of (b)", "Kms", True, r"total of")]),
    ("railways", "Railways", [
        ("Railways", "Revenue earning goods Traffic (MT)", "MT", False, r"revenue|goods")]),
    ("shipping", "Shipping & Ports", [
        ("Shipping", "Cargo handled at major ports (MT)", "MT", False, r"cargo"),
        ("Shipping", "Coal handled at major ports (MT)", "MT", False, r"coal")]),
    ("civil aviation", "Civil Aviation", [
        (G_CARGO, "Export Cargo", "Tonnes", False, r"export"),
        (G_CARGO, "Import Cargo", "Tonnes", False, r"import"),
        (G_PAX, "International Terminals", "Numbers", False, r"international"),
        (G_PAX, "Domestic Terminals", "Numbers", False, r"domestic")]),
    ("telecom", "Telecommunications", [
        ("Telecommunications", "Net Addition in Switching Capacity (Fixed+WLL+GSM) ('000 Lines)",
         "'000 Lines", False, r"switching|fixed\+wll"),
        ("Telecommunications", "Net new wireline (Fixed) telephone connections provided ('000 Numbers)",
         "'000 Numbers", False, r"wireline|telephone"),
        ("Telecommunications", "Net (New) Wireless (WLL+GSM) connections provided ('000 Numbers)",
         "'000 Numbers", False, r"wireless|\(new\)"),
        ("Telecommunications", "Total connections (ii+iii) (in '000 Numbers)",
         "'000 Numbers", True, r"^total")]),
]
ANNEX_ROWS = sum(len(t) for _, _, t in ANNEX)  # 42


def find_annex_page(doc):
    for i, p in enumerate(doc):
        ws = {w[4] for w in p.get_text("words")}
        if {"Thermal", "(2)", "(3)"} <= ws and any(w.startswith("Telecommunications") for w in ws):
            return i
    return None


def parse_annexure(page):
    """-> (title, ncols, [ {section, label, vals{col:int->str}} ], issues)"""
    lines = page_lines(page)
    issues = []
    mk = None
    for ln in lines:
        m = [w for w in ln.words if re.fullmatch(r"\(\d{1,2}\)", w.t)]
        if len(m) >= 6:
            mk = ln
            cols = {int(w.t.strip("()")): w.cx for w in m}
            break
    if mk is None:
        return None, 0, [], ["annexure column-number row not found"]
    ncols = max(cols)
    title = norm_ws(" ".join(ln.text for ln in lines if ln.y < mk.y and "Performance during" in ln.text))
    c2, c3 = cols[2], cols[3]
    boundary = c2 - 0.6 * (c3 - c2)
    raw, pending, section = [], [], None
    for ln in lines:
        if ln.y <= mk.y + 1:
            continue
        txt = ln.text
        if re.match(r"^(BU|MT)\s*:", txt) or "Targets not provided" in txt:
            break
        vals = [w for w in ln.words if is_value(w.t) and w.cx >= boundary]
        labs = norm_ws(" ".join(w.t for w in ln.words if w not in vals))
        if not vals:
            m = re.match(r"^(\d{1,2})\.\s*(.*)$", labs)
            if m:
                section, pending = m.group(2), []
                continue
            if re.match(r"^(?:I\.|II\.|\([ab]\))\s", labs) or not labs:
                pending = []  # sub-group heading; groups are fixed in ANNEX
                continue
            pending.append(labs)
            continue
        raw.append((section, norm_ws(" ".join(pending + [labs])), ln, vals))
        pending = []
    vcols = cluster_columns([(ln, v) for _, _, ln, v in raw])
    want = sorted(k for k in cols if k >= 2)
    if len(vcols) == len(want):
        cmap = dict(enumerate(want))
    else:  # fall back to nearest column-number marker
        cmap = {i: min(want, key=lambda k: abs(cols[k] - c["cx"])) for i, c in enumerate(vcols)}
        issues.append(f"annexure: {len(vcols)} value columns vs {len(want)} headers")
        if len(set(cmap.values())) != len(cmap):
            return title, ncols, [], issues + ["annexure columns could not be aligned"]
    rows = []
    for section, label, ln, vals in raw:
        got = {}
        for w in vals:
            ci = col_of(w, vcols)
            if ci is None or cmap[ci] in got:
                issues.append(f"p{page.number + 1} y={ln.y:.0f} value '{w.t}' not aligned to a column")
                got = None
                break
            got[cmap[ci]] = w.t
        if got is not None:
            rows.append({"section": section or "", "label": label, "vals": got, "y": ln.y})
    return title, ncols, rows, issues


def map_annex(rows):
    """Map parsed rows onto ANNEX template. -> ([(tpl_entry, sector, row)], issues, restored)"""
    issues, restored, out = [], 0, []
    by_sec = {}
    for r in rows:
        key = next((k for k, _, _ in ANNEX if k in r["section"].lower()), None)
        if key is None:
            issues.append(f"unrecognised annexure section '{r['section']}' ({r['label']})")
            continue
        by_sec.setdefault(key, []).append(r)
    for key, sector, tpl in ANNEX:
        rs = by_sec.get(key, [])
        pats = [re.compile(t[4], re.I) for t in tpl]

        def lab(r):
            return strip_enum(r["label"]).lower()
        ok = len(rs) == len(tpl)
        if ok:
            for i, r in enumerate(rs):
                hit = [j for j, p in enumerate(pats) if p.search(lab(r))]
                if hit and i not in hit:
                    ok = False
                    break
        if ok:
            for i, r in enumerate(rs):
                if not pats[i].search(lab(r)):
                    restored += 1
                out.append((tpl[i], sector, r))
            continue
        issues.append(f"{sector}: {len(rs)} rows vs {len(tpl)} expected; matched by label")
        used = set()
        for r in rs:
            hit = [j for j, p in enumerate(pats) if p.search(lab(r)) and j not in used]
            if len(hit) >= 1:
                used.add(hit[0])
                out.append((tpl[hit[0]], sector, r))
            else:
                issues.append(f"{sector}: dropped unmatched row '{r['label']}'")
    return out, issues, restored


def annex_perf_rows(mapped, ncols, report_month, src, page_no, notes):
    fy = fiscal_year(report_month)
    out, overridden = [], set()
    for (grp, ind, unit, is_tot, _), sector, r in mapped:
        v = r["vals"]
        # a section heading may carry its own data month, e.g. Mar 2021
        # "11. Telecommunications** (February ,2021)" + "** Telecom data upto Feb 2021"
        pm = [p for p in find_periods(r["section"]) if p[0] == "month"]
        end = pm[0][2] if pm else report_month
        dq = None
        if end != report_month:
            overridden.add(f"{sector} data month {end} (per section heading)")
            dq = f"carried_forward:{end};source_says_previous_month_data"
        specs = [("month", end, end, 2)]
        if ncols >= 11:
            specs.append(("cumulative", fy_start_ym(end), end, 7))
        for ptype, ps, pe, c0 in specs:
            out.append({
                "report_month": report_month, "fiscal_year": fy, "source_file": src, "page": page_no,
                "sector": sector, "indicator_group": grp, "indicator": ind, "unit": unit,
                "is_total": is_tot, "period_type": ptype, "period_start": ps, "period_end": pe,
                "annual_target": None,
                "target": to_num(v.get(c0)), "actual": to_num(v.get(c0 + 1)),
                "prev_year_actual": to_num(v.get(c0 + 2)),
                "pct_var_target": to_num(v.get(c0 + 3)), "pct_var_prev_year": to_num(v.get(c0 + 4)),
                "pct_achievement": None, "dq_note": dq,
            })
    notes += sorted(overridden)
    return out


# --------------------------------------------------------------------------
# generic tables (PRIORITY 2)
# --------------------------------------------------------------------------
_HDR_WORDS = {"target", "actual", "achievement", "achievement(provisional)", "(provisional)", "provisional",
              "variation", "%", "%age", "annual", "growth", "percent", "more", "less", "short", "shortfall",
              "decrease", "increase", "over", "achieve-", "achievem-", "(actual)", "sl.", "no.", "fall",
              "throughput", "installed", "prorated"}
_TITLE_STOP = {"target", "actual", "achievement", "%", "%age", "sl.", "variation", "annual", "more", "less",
               "(provisional)", "short", "decrease"}
_TITLE_RE = re.compile(r"^Table\s*-?\s*(\d{1,2}\s*[A-Z]?)\s*:\s*(.*)$", re.I)
_SPECIAL = [(re.compile(r"^HIGHLIGHTS$", re.I), "Highlights", "bottom"),
            (re.compile(r"^Areas? of concern$", re.I), "Areas of concern", "block"),
            (re.compile(r"^Noteworthy Performance$", re.I), "Noteworthy Performance", "block")]
_FOOT = re.compile(r"^(?:BU|MT|MCM|KM|BRO|NA|MU)\s*:|^[#$*@]\s*:|^\*\s*:|^Note\b|^Source\b|"
                   r"Infrastructure Performance Report|^Ministry of Statistics|^\*\s*Targets|"
                   r"^\$\s*:|^#\s(?!\s*\()", re.I)  # but '# (Km)' is the tail of 'State PWD & BRO' (Jan 2019)
_SECTION = re.compile(r"^\d{1,2}\.\d{1,2}\s+[A-Za-z]|^\d{1,2}\.\s*[A-Z][A-Z &]{3,}$")
SECTOR_HEAD = [("POWER", "Power"), ("COAL", "Coal"), ("STEEL", "Steel"), ("CEMENT", "Cement"),
               ("FERTILI", "Fertilizers"), ("PETROLEUM", "Petroleum & Natural Gas"), ("ROADS", "Roads"),
               ("RAILWAYS", "Railways"), ("SHIPPING", "Shipping & Ports"),
               ("CIVIL AVIATION", "Civil Aviation"), ("TELECOM", "Telecommunications")]
_UNIT_MAP = [(r"billion units?", "BU"), (r"million units?", "MU"), (r"million tonnes?", "MT"),
             (r"thousand tonnes?", "'000 Tonnes"), (r"lakh tonnes?", "Lakh Tonnes"),
             (r"percentage|per ?cent", "%"), (r"rs\.? in crores?", "Rs crore"),
             (r"million cubic met", "MCM"), (r"\bmcm\b", "MCM"), (r"metric tonnes?|\btonnes?\b", "Tonnes"),
             (r"numbers?", "Numbers"), (r"lakh", "Lakh")]
_ROW_UNIT = [(r"\(\s*bu\s*\)", "BU"), (r"\(\s*mt\s*\)|\(mt\)|production\s*\(mt", "MT"),
             (r"\(\s*mcm\s*\)|gas\s*\(mcm", "MCM"), (r"\(\s*kms?\.?\s*\)|#\s*\(km", "Kms"),
             (r"\(\s*nos\.?\s*\)", "Numbers"), (r"\(\s*tonnes?\s*\)", "Tonnes"), (r"\(\s*lakh\s*\)", "Lakh"),
             (r"'000\s*lines", "'000 Lines"), (r"'000\s*no", "'000 Numbers"), (r"\(in lines\)", "Lines"),
             (r"\(in numbers\)", "Numbers"), (r"\(\s*mu\s*\)", "MU"), (r"rs\.? in crore", "Rs crore")]


def is_unit_line(txt):
    return bool(re.fullmatch(r"\((?:In\s+)?[^)]*\)", txt.strip(), re.I)) and unit_from(txt, True) is not None


def unit_from(text, table):
    t = (text or "").lower()
    for pat, u in (_UNIT_MAP if table else _ROW_UNIT):
        if re.search(pat, t):
            return u
    return None


_SECTOR_PATS = [  # order matters: airport cargo before ports, ports before coal ("Coal handled at major ports")
    (r"airport|passenger|civil aviation|(?:export|import)\s*cargo", "Civil Aviation"),
    (r"\bports?\b|shipping", "Shipping & Ports"),
    (r"telecom|switching|telephone|wireless|wireline|cell\)|connections", "Telecommunications"),
    (r"power|thermal|nuclear|hydro|plf|bhutan|renewable", "Power"),
    (r"coal", "Coal"), (r"steel", "Steel"), (r"cement", "Cement"), (r"fertili", "Fertilizers"),
    (r"crude|refinery|natural gas|petroleum", "Petroleum & Natural Gas"),
    (r"nhai|pwd|\bbro\b|road|highway", "Roads"), (r"railway|freight", "Railways")]


def sector_from_text(t):
    t = (t or "").lower()
    for pat, s in _SECTOR_PATS:
        if re.search(pat, t):
            return s
    return None


_MONTH_WORDS = {"jan", "january", "feb", "february", "mar", "march", "apr", "april", "may", "jun", "june",
                "jul", "july", "aug", "august", "sep", "sept", "september", "oct", "october", "nov",
                "november", "dec", "december"}


def is_header_line(ln):
    toks = [w.t for w in ln.words]
    low = [t.lower() for t in toks]
    if any(t in _HDR_WORDS for t in low):
        return True
    if any(t.strip("-,.()") in _MONTH_WORDS for t in low):
        return True
    if find_periods(ln.text):
        return True
    yrs = [t for t in toks if re.fullmatch(r"(19|20)\d\d", t)]
    if len(yrs) >= 3 and len(yrs) >= len(toks) - 2 and len(set(yrs)) >= 3:
        return True  # "Sl.No. Sector 2014 2015 2016 ..."
    if yrs and len(yrs) == len(toks) <= 2:
        return True  # stray header year on its own baseline
    yt = [t for t in toks if not re.fullmatch(r"[A-Za-z]", t)]
    if yt and all(re.fullmatch(r"\(?(19|20)\d\d\)?", t) for t in yt) and any("(" in t or ")" in t for t in yt):
        return True  # "2019)  2018)" wrapped header years
    nums = [t.strip("()") for t in toks]
    if all(n.isdigit() and int(n) <= 20 for n in nums) and len(nums) >= 3:
        return True  # column-number row  1 2 3 ... / (1) (2) ...
    return False


def cluster_columns(vlines):
    """Value columns from token boxes. Numbers cluster by horizontal overlap (works for
    right-aligned and centred cells); placeholders (-, NA, *, $) join the column they sit
    in, or form their own column when a whole column is placeholders."""
    toks = [w for _, vals in vlines for w in vals]
    cols = []
    for w in sorted((w for w in toks if w.t not in NA_TOK), key=lambda w: w.x0):
        if cols and w.x0 <= cols[-1]["x1"] + 2:
            c = cols[-1]
            c["x1"] = max(c["x1"], w.x1)
            c["n"] += 1
        else:
            cols.append({"x0": w.x0, "x1": w.x1, "n": 1})
    loose = sorted((w for w in toks if w.t in NA_TOK and col_of(w, cols, 10) is None), key=lambda w: w.cx)
    extra = []
    for w in loose:
        if extra and w.cx - extra[-1]["cxl"] <= 10:
            c = extra[-1]
            c["x0"], c["x1"], c["n"], c["cxl"] = min(c["x0"], w.x0), max(c["x1"], w.x1), c["n"] + 1, w.cx
        else:
            extra.append({"x0": w.x0, "x1": w.x1, "n": 1, "cxl": w.cx})
    for c in extra:
        c.pop("cxl")
        c["ph"] = True
    # a lone shifted placeholder (e.g. one "NA" printed 20pt left) joins the nearest column
    for c in [c for c in extra if c["n"] == 1]:
        others = [o for o in cols + extra if o is not c and o.get("n", 0) > 0]
        if others:
            o = min(others, key=lambda o: max(o["x0"] - c["x1"], c["x0"] - o["x1"], 0))
            if max(o["x0"] - c["x1"], c["x0"] - o["x1"], 0) <= 25:
                o["x0"], o["x1"], o["n"], c["n"] = min(o["x0"], c["x0"]), max(o["x1"], c["x1"]), o["n"] + 1, 0
    extra = [c for c in extra if c["n"] > 0]
    cols = sorted(cols + extra, key=lambda c: c["x0"])
    for c in cols:
        c["cx"] = (c["x0"] + c["x1"]) / 2
    return cols


def merge_disjoint(cols, vlines):
    """Merge a placeholder column into its neighbour when no row uses both: the "-" of
    that column is just printed off-centre (e.g. Nov 2020 cement % variation)."""
    while True:
        use = [set() for _ in cols]
        for ri, (_, vw) in enumerate(vlines):
            for w in vw:
                ci = col_of(w, cols)
                if ci is not None:
                    use[ci].add(ri)
        for i in range(len(cols) - 1):
            a, b = cols[i], cols[i + 1]
            if (a.get("ph") or b.get("ph")) and not (use[i] & use[i + 1]) and b["x0"] - a["x1"] <= 30:
                m = {"x0": min(a["x0"], b["x0"]), "x1": max(a["x1"], b["x1"]), "n": a["n"] + b["n"]}
                m["cx"] = (m["x0"] + m["x1"]) / 2
                if a.get("ph") and b.get("ph"):
                    m["ph"] = True
                cols = cols[:i] + [m] + cols[i + 2:]
                break
        else:
            return cols


def assign_row(vw, cols):
    """{column index: raw text} for one row, or None if two cells claim one column.
    Numbers go by overlap; placeholders (-, NA, *) take the nearest free column."""
    got = {}
    for w in (w for w in vw if w.t not in NA_TOK):
        ci = col_of(w, cols)
        if ci is None or ci in got:
            return None
        got[ci] = w.t
    for w in (w for w in vw if w.t in NA_TOK):
        d = sorted((max(c["x0"] - 4 - w.x1, w.x0 - c["x1"] - 4, 0), abs(c["cx"] - w.cx), i)
                   for i, c in enumerate(cols) if i not in got)
        if not d or d[0][0] > 12:
            return None
        got[d[0][2]] = w.t
    return got


def col_of(w, cols, far=12):
    """Index of the column a value token belongs to (None if ambiguous/too far)."""
    best, bov = None, 0.0
    for i, c in enumerate(cols):
        ov = min(w.x1, c["x1"] + 4) - max(w.x0, c["x0"] - 4)
        if ov > bov:
            best, bov = i, ov
    if best is not None or not far:
        return best
    d = [(max(c["x0"] - w.x1, w.x0 - c["x1"], 0), i) for i, c in enumerate(cols)]
    dist, i = min(d) if d else (1e9, None)
    return i if dist <= far else None




def header_labels(hlines, cols, label_right=None):
    """Assign header text to value columns by x-overlap with column cells."""
    if not cols:
        return []
    # cell = (previous cell's right edge, this column's right edge]; numbers are
    # right-aligned, placeholder-only columns (NA / - / *) are not, so their cell runs
    # halfway to the next column
    left = cols[0]["x0"] - 22
    if label_right and label_right + 2 < left:
        left = label_right + 2  # e.g. "Target" printed left of a narrow "NA" column
    cells = []
    for i, c in enumerate(cols):
        last = i == len(cols) - 1
        if c.get("ph") and not last:
            right = max(c["x1"] + 3, (c["cx"] + cols[i + 1]["x0"]) / 2)
        else:
            right = c["x1"] + (30 if last else 3)
        cells.append((left, right))
        left = right
    pieces = [[] for _ in cols]
    for ln in hlines:
        if all(re.fullmatch(r"\(?\d{1,2}\)?", w.t) for w in ln.words):
            continue  # column-number row
        phrases, cur = [], []
        for w in ln.words:
            new_period = (cur and re.fullmatch(r"\d{2,4}\)?", cur[-1].t)
                          and re.match(_MON, w.t, re.I))
            if cur and (w.x0 - cur[-1].x1 > 3.8 or w.t.startswith("(") or new_period):
                phrases.append(cur)
                cur = []
            cur.append(w)
        if cur:
            phrases.append(cur)
        units = []
        for ph in phrases:
            txt = " ".join(w.t for w in ph)
            units.append((ph[0].x0, ph[-1].x1, txt))
        for x0, x1, txt in units:
            wd = max(x1 - x0, 1)
            hit = []
            for i, (l, r) in enumerate(cells):
                ov = max(0.0, min(x1, r) - max(x0, l))
                if ov >= 0.4 * wd or ov >= 0.5 * (r - l):
                    hit.append(i)
            if not hit:
                cx = (x0 + x1) / 2
                hit = [i for i, (l, r) in enumerate(cells) if l <= cx <= r]
            for i in hit:
                pieces[i].append((ln.y, x0, txt))
    return [norm_ws(" ".join(t for _, _, t in sorted(p))) for p in pieces]


CANON_COLS = {
    "Areas of concern": ["Target", "Actual shortfall", "Shortfall (%)", "Achievement during corresponding period last year",
                         "Less achievement than corresponding period last year",
                         "Decrease over last year's achievement (%)"],
    "Noteworthy Performance": ["Target", "More achievement than the target", "Increase over the target (%)",
                               "Achievement during corresponding period last year",
                               "More achievement than corresponding period last year",
                               "Increase over last year's achievement (%)"],
}
_HEADING_WORDS = re.compile(r"^(physica|physical|financia|financial|nitrogen|phosphate)$", re.I)
_SECTOR_HEADING = re.compile(r"^(petroleum|roads|shipping\s*(and|&)\s*ports|civil aviation|"
                             r"telecommunications?)\b", re.I)


_FRAG = {"-ment", "ment", "ent", "achieve-", "achievem-", "(actual)", "actual", "year's", "last", "r"}


def is_heading(label_txt, words, first_col_x0):
    t = strip_enum(label_txt)
    raw = norm_ws(label_txt)
    if not t or all(x.lower() in _FRAG or x.lower() in _HDR_WORDS for x in t.split()):
        return False
    if re.search(r":\s*-?\s*(#|[ivx]+\s*\))?\s*$", raw) or re.search(r":\s*-?\s*#?$", raw):
        return True
    if _SECTOR_HEADING.match(t) and not re.search(r"\(\s*(mt|mcm|km|kms)", t, re.I):
        return True
    if _HEADING_WORDS.match(t) or re.fullmatch(r"[A-Z][A-Z &]{3,}", t):
        return True
    if re.match(r"^[A-H]\.\s", raw) or re.match(r"^(I|II|III|IV)\.\s", raw):
        return True
    if words and words[-1].x1 > first_col_x0 + 5:
        return True  # spans into the value area -> group title
    return False


def split_two_level(zone):
    """Detect a two-level stub column (outer label printed only on the first of its rows,
    inner label at a fixed indent). Returns (zone with inner labels only, [(y, outer)])."""
    starts = [(ln, lw) for ln, lw, vw in zone if vw and lw]
    if len(starts) < 4:
        return zone, []
    a = min(lw[0].x0 for _, lw in starts)
    later = Counter(round(lw[0].x0) for _, lw in starts if lw[0].x0 > a + 20)
    if not later:
        return zone, []
    b, nb = later.most_common(1)[0]
    at_a = [lw for _, lw in starts if lw[0].x0 < a + 3]
    with_b = [lw for lw in at_a if any(abs(w.x0 - b) <= 3 for w in lw)]
    if nb < 2 or len(with_b) < 2 or len(with_b) < 0.7 * len(at_a):
        return zone, []
    out, outers = [], []
    for ln, lw, vw in zone:
        if vw and lw and lw[0].x0 < a + 3:
            if any(abs(w.x0 - b) <= 3 for w in lw):
                outers.append((ln.y, norm_ws(" ".join(w.t for w in lw if w.x0 < b - 3))))
                lw = [w for w in lw if w.x0 >= b - 3]
            else:
                outers.append((ln.y, None))  # full-width label, e.g. "Total (International+Domestic)"
        out.append((ln, lw, vw))
    return out, outers


def assemble_rows(zone, cols, mode):
    """zone: list of (Line, label_words, value_words). -> list of (row_group, label, vals, y)."""
    first_x0 = cols[0]["x0"] if cols else 1e9
    rows = []
    if mode == "bottom":
        group, pending = None, []
        for ln, lw, vw in zone:
            ltxt = norm_ws(" ".join(w.t for w in lw))
            if not vw:
                if not ltxt or re.fullmatch(r"\d{1,2}\.?", ltxt):
                    continue
                if is_heading(ltxt, lw, first_x0):
                    group, pending = strip_enum(ltxt).rstrip(" :-#"), []
                    continue
                pending.append(ltxt)
                continue
            parts = pending + ([ltxt] if ltxt else [])
            pending = []
            k = max([i for i, p in enumerate(parts) if starts_enum(p)] or [0])
            if k > 0:  # lines before an enumerated label are a group title
                group = strip_enum(" ".join(parts[:k])).rstrip(" :-#")
                parts = parts[k:]
            elif parts and (starts_serial(parts[0]) or re.match(r"^[A-H]\.\s", parts[0])
                            or re.match(r"^All India", strip_enum(parts[0]), re.I)):
                group = None  # new top-level item ("8 Railway ...", "C. DGH (JVC/Private)", "All India Total")
            if strip_enum(" ".join(parts)):  # a value line with no label at all is dropped
                rows.append((group, strip_enum(" ".join(parts)), vw, ln.y))
        return rows
    raise ValueError(mode)  # block mode: assemble_blocks()


_UNIT_END = re.compile(r"\([^()]*\)\s*[#*@$]*$")


def line_cells(vw, cols):
    """{col: text} for one line's value tokens + count of numbers that found no column.
    Placeholders (-, NA) take the nearest free column; a surplus placeholder is dropped
    (Feb 2021 prints an extra '-' under a rotated, otherwise empty 'Actual' header)."""
    got, bad = {}, 0
    for w in (w for w in vw if w.t not in NA_TOK):
        ci = col_of(w, cols)
        if ci is None or ci in got:
            bad += 1
            continue
        got[ci] = (w.t, w)
    for w in (w for w in vw if w.t in NA_TOK):
        d = sorted((max(c["x0"] - 4 - w.x1, w.x0 - c["x1"] - 4, 0), abs(c["cx"] - w.cx), i)
                   for i, c in enumerate(cols) if i not in got)
        if d and d[0][0] <= 12:
            got[d[0][2]] = (w.t, w)
    return got, bad


def assemble_blocks(zone, cols, near=22):
    """Areas of concern / Noteworthy. Label cells wrap over 1-4 lines and value cells are
    vertically centred, so a row's numbers can sit above, inside or below its label, and
    are sometimes split over two lines. Build label blocks first (a block starts at an
    enumerator 'i)', a serial '3.', a capitalised line after a label that already ended
    with its unit '(MT)', or after a gap), then give each value cell to the nearest block
    still missing that column. -> ([(group, label, {col: text}, y, {col: [dq flags]})], unplaced
    numbers, re-joined numbers)"""
    first_x0 = cols[0]["x0"] if cols else 1e9
    group, blocks, cur, in_group, home = None, [], None, 0, {}
    for li, (ln, lw, vw) in enumerate(zone):
        words, serial = list(lw), False
        while words and re.fullmatch(r"\d{1,2}\.?|\.", words[0].t):
            words.pop(0)
            serial = True
        ltxt = re.sub(r"\s+\d{1,2}\.?$", "", norm_ws(" ".join(w.t for w in words))).strip()
        if not ltxt:
            continue
        if is_heading(ltxt, words, first_x0) and (not vw or ltxt.rstrip().endswith(":")
                                                   or _SECTOR_HEADING.match(strip_enum(ltxt))):
            # a heading may carry the first sub-item's values (Jan 2019 '5 Civil Aviation: 1185129 ...'
            # above 'i) Export cargo ...'): they are aligned like any bare value line below
            group, cur, in_group = strip_enum(re.sub(r"\s+[ivx]+\s*\)\s*$", "", ltxt)).rstrip(" :-#"), None, 0
            continue
        top = serial and bool(re.match(r"[A-Z]", ltxt))  # "3. Steel Production"
        cont = bool(re.match(r"[(#a-z]", ltxt))  # '#(Km)', '(MT)', 'at Airports (Tonne)'
        if (cur is None or starts_enum(ltxt) or top or ln.y - cur["y1"] > (24 if cont else 16)
                or (_UNIT_END.search(" ".join(cur["lab"])) and re.match(r"[A-Z][a-z]", ltxt))):
            if top or (group is not None and in_group > 0 and not starts_enum(ltxt)):
                group = None  # un-numbered item after a group's sub-items = new top-level item
            in_group += 1
            cur = {"g": group, "lab": [], "y0": ln.y, "y1": ln.y, "cells": {}, "src": {}}
            blocks.append(cur)
        cur["lab"].append(ltxt)
        cur["y1"] = ln.y
        home[li] = cur

    def dist(b, y):
        if b["y0"] - 2 <= y <= b["y1"] + 2:
            return 0.0, abs(y - (b["y0"] + b["y1"]) / 2)
        return min(abs(y - b["y0"]), abs(y - b["y1"])), abs(y - (b["y0"] + b["y1"]) / 2)

    # a number wrapped inside its cell: Aug 2019 '13.9' with its last digit '9' on the next
    # baseline, directly under it (touching, inside its x-range) -> '13.99'
    zone = [(ln, lw, list(vw)) for ln, lw, vw in zone]
    seen, wrapped, joined = [], 0, set()
    for ln, lw, vw in zone:
        for w2 in list(vw):
            if not re.fullmatch(r"\d{1,2}", w2.t):
                continue
            up = [w1 for w1 in seen if re.fullmatch(r"-?\d+\.\d*", w1.t) and abs(w2.y0 - w1.y1) <= 1.5
                  and w1.x0 + 3 < w2.x0 and w2.x1 < w1.x1 - 3]
            if len(up) == 1:
                up[0].t += w2.t
                joined.add(id(up[0]))
                vw.remove(w2)
                wrapped += 1
        seen += vw
    unplaced, loose, bare = 0, [], []
    for li, (ln, lw, vw) in enumerate(zone):
        if not vw:
            continue
        got, bad = line_cells(vw, cols)
        unplaced += bad
        hb = home.get(li)
        if hb is None:
            if (bare and ln.y - bare[-1][0][-1] <= 14 and not set(got) & set(bare[-1][1])
                    and len(bare[-1][1]) < len(cols)):
                bare[-1][0].append(ln.y)  # rest of a row whose cells are split over two lines
                bare[-1][1].update(got)
            else:
                bare.append(([ln.y], dict(got)))
            continue
        for ci, (t, w) in sorted(got.items()):
            if ci not in hb["cells"]:
                hb["cells"][ci], hb["src"][ci] = t, w
            else:
                loose.append((ln.y, ci, t, w))
    # bare value lines -> blocks: order-preserving alignment with least total distance. Values
    # may be centred, top- or bottom-aligned in their cell, so nearest-first is not enough
    # (Jan 2019 p18: International's values sit closer to the Domestic label below them).
    n, m, skip = len(bare), len(blocks), near + 1
    cost = [[min(dist(b, y)[0] for y in ys) for b in blocks] for ys, got in bare]
    cost = [[c if c <= near and not set(got) & set(b["cells"]) else None for c, b in zip(row, blocks)]
            for row, (ys, got) in zip(cost, bare)]
    f = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        f[i][0] = i * skip
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            c = cost[i - 1][j - 1]
            f[i][j] = min(f[i - 1][j] + skip, f[i][j - 1], f[i - 1][j - 1] + c if c is not None else 1e9)
    i, j, match = n, m, {}
    while i > 0:
        c = cost[i - 1][j - 1] if j > 0 else None
        if j > 0 and c is not None and f[i][j] == f[i - 1][j - 1] + c:
            match[i - 1], i, j = j - 1, i - 1, j - 1
        elif j > 0 and f[i][j] == f[i][j - 1]:
            j -= 1
        else:
            i -= 1
    for k, (ys, got) in enumerate(bare):
        y, hb = ys[0], blocks[match[k]] if k in match else None
        for ci, (t, w) in sorted(got.items()):
            if hb is not None and ci not in hb["cells"]:
                hb["cells"][ci], hb["src"][ci] = t, w
            else:
                loose.append((y, ci, t, w))
    for y, ci, t, w in loose:  # cell-level fallback, e.g. Sep 2020 '74.01' printed on the row above
        cand = sorted((dist(b, y), i) for i, b in enumerate(blocks) if ci not in b["cells"])
        if cand and cand[0][0][0] <= near:
            blocks[cand[0][1]]["cells"][ci], blocks[cand[0][1]]["src"][ci] = t, w
        elif t not in NA_TOK:
            unplaced += 1
    rows = []
    for b in blocks:
        lab, g = strip_enum(" ".join(b["lab"])), b["g"]
        gs, ls = sector_from_text(g), sector_from_text(lab)
        if gs and ls and gs != ls:
            g = None  # stale group: the section heading is missing in the source (May 2019 p18 Roads)
        if b["cells"] and lab and (ls or (g and gs)):
            rows.append((g, lab, b["cells"], b["y0"],
                         {ci: ["digits_rejoined"] for ci, w in b["src"].items() if id(w) in joined}))
        elif b["cells"] and any(to_num(t) is not None for t in b["cells"].values()):
            unplaced += 1  # values without an identifiable label
    return rows, unplaced, wrapped


def group_periods(labels):
    """Columns that repeat as k-column groups ([Capacity, Throughput, %] x 2), where
    each group names exactly one period, take that period for every column of the group."""
    base = [re.sub(r"\s+", "", re.sub(r"(?i)april\s*-\s*|april,?\d{4}\s*-\s*", "", _strip_periods(lab))).lower()
            for lab in labels]
    n = len(base)
    for k in range(2, n // 2 + 1):
        if n % k or any(base[i] != base[i % k] for i in range(n)):
            continue
        out = []
        for g in range(n // k):
            ps = {(p[1], p[2]) for l in labels[g * k:(g + 1) * k] for p in find_periods(l) if p[0] != "fy"}
            if len(ps) != 1:
                return None
            out += [ps.pop()] * k
        return out
    return None


def _strip_periods(t):
    t = _fix_months((t or "").translate(_TR).replace(",", " "))
    t = _RANGE.sub(" ", t)
    t = _SINGLE.sub(" ", t)
    return re.sub(r"(?i)\bapr[a-z]*\.?\s*-\s*" + _MON, " ", t)  # "April - October" without a year


_VAR = re.compile(r"variation|increase|decrease|short\s*fall|less achievement|more achievement", re.I)


def col_period(label, tbl_period, report_month):
    low = label.lower()
    ps = find_periods(label)
    if "annual" in low:
        fy = [p for p in ps if p[0] == "fy"]
        if fy:
            return fy[0][1], fy[0][2]
        s = fy_start_ym(report_month)
        return s, shift_year(s, 1)[:5] + "03"
    if "growth" not in low and _VAR.search(label) and tbl_period:
        return tbl_period[1], tbl_period[2]
    ps = [p for p in ps if p[0] != "fy"]
    if ps:
        return ps[0][1], ps[0][2]
    if tbl_period:
        # month name lost (broken glyphs, e.g. "Ja ua y 2020 Actual"): use the bare year
        yrs = re.findall(r"\b(20\d\d)\b", _FY.sub(" ", _strip_periods(label)))
        if yrs:
            dy = int(yrs[0]) - int(tbl_period[2][:4])
            if dy in (0, -1):
                return shift_year(tbl_period[1], dy), shift_year(tbl_period[2], dy)
            return None, None
        return tbl_period[1], tbl_period[2]
    return None, None


def half_ulp(t):
    """Half a unit in the last printed decimal place of a number as printed ('97.23' -> 0.005)."""
    t = str(t).strip("()%+-")
    return 0.5 * 10 ** -(len(t.split(".")[1]) if "." in t else 0)


SPECIAL_GROUPS = {6: [(0, 1, 2), (3, 4, 5)], 7: [(1, 2, 3), (4, 5, 6)], 5: [(0, 1, 2)]}


def group_ok(assign, g):
    """(base, diff, %) cells of an Areas/Noteworthy row agree: % = diff / base * 100 (+-2%)."""
    vals = [to_num(assign.get(i)) for i in g]
    if any(v is None for v in vals) or not vals[0]:
        return False
    calc, b = vals[1] / vals[0] * 100, abs(vals[0])
    rounding = 100 * (half_ulp(assign[g[1]]) / b + abs(vals[1]) * half_ulp(assign[g[0]]) / b ** 2)
    return abs(abs(calc) - abs(vals[2])) <= max(0.6, 0.02 * abs(vals[2]), rounding + half_ulp(assign[g[2]]))


def special_row_ok(label, assign, ncols):
    """Areas of concern / Noteworthy row: groups (base, diff, %) must be all blank or
    all numbers with % = diff / base * 100 (+-2%); label must be a real label."""
    if not re.search(r"[A-Za-z]{3,}", re.sub(r"\([^)]*\)", "", label or "")):
        return False
    groups = SPECIAL_GROUPS.get(ncols, [])
    if not any(to_num(v) is not None for v in assign.values()):
        return len(assign) >= ncols - 1  # a full row of "-" is fine; one stray "-" is a fragment
    verified = partial = 0
    for g in groups:
        vals = [to_num(assign.get(i)) for i in g]
        if all(v is None for v in vals):
            continue
        if vals[0] and assign.get(g[1]) in NA_TOK and assign.get(g[2]) in NA_TOK:
            partial += 1  # last year's figure printed, no shortfall/excess against it ('-', '-')
            continue
        if not group_ok(assign, g):
            return False
        verified += 1
    return verified > 0 or not partial  # a partial group is accepted only beside a verified one


def pin_bad_cell(label, assign, ncols, sign):
    """A row that fails special_row_ok because of ONE bad printed cell (Apr 2018 Railways prints
    'more than last year' 0.51 where 97.98 - 90.47 = 7.51 is implied). One (base, diff, %) group
    must verify on its own and give the actual (base + sign * diff; sign -1 for shortfalls, +1 for
    excesses); in the other group exactly one cell may then disagree while the other two agree with
    that actual. -> (column, implied value) or None."""
    if not re.search(r"[A-Za-z]{3,}", re.sub(r"\([^)]*\)", "", label or "")):
        return None
    groups = SPECIAL_GROUPS.get(ncols, [])
    good = [g for g in groups if group_ok(assign, g)]
    if len(groups) != 2 or len(good) != 1:
        return None
    gb, gd, _ = good[0]
    b0, d0 = to_num(assign[gb]), to_num(assign[gd])
    actual = b0 + sign * abs(d0)
    bi, di, pi = next(g for g in groups if g not in good)
    vb, vd, vp = (to_num(assign.get(i)) for i in (bi, di, pi))

    def close(x, y, *texts):
        return abs(x - y) <= max(0.005 * max(abs(x), abs(y)), 3 * sum(half_ulp(t) for t in texts))
    ref = (assign[gb], assign[gd])
    hits = []
    if vb and vp is not None and close(abs(actual - vb) / abs(vb) * 100, abs(vp), assign[pi], *ref):
        hits.append((di, abs(actual - vb)))  # base and % agree with the actual: diff is wrong
    if vb and vd is not None and close(abs(actual - vb), abs(vd), assign[di], assign[bi], *ref):
        hits.append((pi, abs(vd) / abs(vb) * 100))  # base and diff agree: % is wrong
    if vd is not None and vp:
        base = actual - sign * abs(vd)
        if base and close(abs(vd) / abs(base) * 100, abs(vp), assign[pi], *ref):
            hits.append((bi, base))  # diff and % agree: base is wrong
    return hits[0] if len(hits) == 1 else None


def is_std(labels):
    j = re.sub(r"\s+", "", " ".join(labels).lower())
    return sum(k in j for k in ("target", "achievem", "actual")) >= 2


_MON_WORD = re.compile(r"\b" + _MON, re.I)


def canon_label(raw, ci, labels, tbl):
    """Clean column label; the period itself lives in period_start/period_end."""
    sq = re.sub(r"\s+", "", raw.lower())
    t = _FY.sub(" ", _strip_periods(raw))
    t = re.sub(r"\b(19|20)\d\d\b|\(\s*\)", " ", t)
    t = _MON_WORD.sub(" ", t)
    t = norm_ws(re.sub(r"\s+(during|of|in)$", "", norm_ws(t).strip(" -,(")))
    if tbl["special"]:
        return t or raw
    std = is_std(labels)
    if "annua" in sq:
        return "Annual Target"
    if std and ("variation" in sq or (len(labels) >= 5 and ci >= len(labels) - 2
                                      and any("variation" in lab.lower() for lab in labels[-2:]))):
        tail = sq.split("variation")[-1]
        if "target" in tail:
            return "% Variation Over Target"
        if "actual" in tail or "ctua" in tail:
            return "% Variation Over Actual"
        return "% Variation Over Target" if ci == len(labels) - 2 else "% Variation Over Actual"
    if "achievem" in sq and ("actual" in sq or "ctua" in sq) and tbl["period"]:
        # header words of two columns merged: the one naming last year is the Actual column
        prev_year = str(int(tbl["period"][2][:4]) - 1)
        if prev_year in raw and tbl["period"][2][:4] not in raw:
            return "Actual"
    if "achievement" in sq or "achievem" in sq:
        return "Achievement (Provisional)" if "provision" in sq else "Achievement"
    for key, name in (("proratedinstalledcapacity", "Prorated Installed Capacity"),
                      ("crudethroughput", "Actual Crude Throughput"),
                      ("utilisationofinstalled", "% Utilisation of Installed Capacity"),
                      ("utilisati", "Capacity Utilisation (%)")):
        if key in sq:
            return name
    if "airport" in tbl["title"].lower():
        if "handled" in sq:
            return "Cargo handled"
        if "traffic" in sq:
            return "PAX Traffic"
    if std and "target" in sq:
        return "Target"
    if std and ("actual" in sq or "ctua" in sq):
        return "Actual"
    if not t:
        if re.search(r"utili", tbl["title"], re.I):
            return "Capacity Utilisation (%)"
        if re.search(r"plf", tbl["title"], re.I):
            return "PLF (%)"
        return raw or f"col{ci + 1}"
    return t


def column_meta(tbl, report_month):
    """-> [(label, (period_start, period_end))] per column."""
    labels, tp = tbl["labels"], tbl["period"]
    if tbl.get("colper"):
        return [(canon_label(lab, i, labels, tbl), tbl["colper"][i]) for i, lab in enumerate(labels)]
    std = is_std(labels) and not tbl["special"]
    out, seen = [], Counter()
    for i, lab in enumerate(labels):
        name = canon_label(lab, i, labels, tbl)
        per = col_period(lab, tp, report_month)
        if std and tp:
            # standard target tables: the column type fixes the period; header text is
            # only used to pick month vs cumulative (combined tables have tp=None)
            if name == "Annual Target":
                fs = fy_start_ym(tp[2])
                per = (fs, shift_year(fs, 1)[:5] + "03")
            elif name in ("Target", "Achievement (Provisional)", "Achievement") or name.startswith("% Variation"):
                per = (tp[1], tp[2])
            elif name == "Actual" or (name in ("Cargo handled", "PAX Traffic") and seen[name]):
                per = (shift_year(tp[1], -1), shift_year(tp[2], -1))
            elif name in ("Cargo handled", "PAX Traffic"):
                per = (tp[1], tp[2])
            elif name == lab and per == (shift_year(tp[1], -1), shift_year(tp[2], -1)):
                name = "Actual"  # header shows only the period, e.g. "April- October 2018"
        seen[name] += 1
        if per[0] is None:
            name = lab or f"col{i + 1}"  # keep printed header when the period is unknown
        out.append((name, per))
    return repair_dups(out)


def repair_dups(meta):
    """Two columns with the same label and period: when the table also has cumulative
    columns, the later month-period twin is the cumulative column whose 'April-' prefix
    was clipped (e.g. PLF 'September 2019 Actual' for April-September 2019). Anything still
    ambiguous is returned with label None (dropped by the caller)."""
    meta = [list(m) for m in meta]
    has_cum = any(p[0] and p[0] != p[1] and p[1] and int(p[1][:4]) * 12 + int(p[1][5:]) -
                  int(p[0][:4]) * 12 - int(p[0][5:]) < 12 for _, p in meta)
    for i, (n, p) in enumerate(meta):
        if p[0] and p[0] == p[1] and has_cum and any((n2, p2) == (n, p) for n2, p2 in meta[:i]):
            meta[i][1] = (fy_start_ym(p[1]), p[1])
    cnt = Counter((n, p) for n, p in meta)
    return [(n if cnt[(n, p)] == 1 else None, p) for n, p in meta]


def parse_tables(lines, page_no, state, report_month, stats):
    """Find and parse all tables on one page. Returns list of table dicts."""
    tables = []
    starts = []
    for i, ln in enumerate(lines):
        txt = ln.text
        m = _TITLE_RE.match(txt)
        if m:
            starts.append((i, f"Table {norm_ws(m.group(1))}: {norm_ws(m.group(2))}", "bottom"))
            continue
        for pat, name, mode in _SPECIAL:
            if pat.match(txt.strip()):
                starts.append((i, name, mode))
        mm = re.match(r"^\d{1,2}\.\s*([A-Z][A-Z &]+)$", txt.strip())
        if mm:
            for key, sec in SECTOR_HEAD:
                if mm.group(1).startswith(key):
                    state["sector"] = sec
                    starts.append((i, None, None))  # section marker (ends previous table)
    carry = None
    for n, (i, title, mode) in enumerate(starts):
        if title is None:
            continue
        end = starts[n + 1][0] if n + 1 < len(starts) else len(lines)
        t = parse_one(lines, i, end, title, mode, report_month, page_no, state, stats)
        if t:
            tables.append(t)
        elif end == len(lines) and title.startswith("Table"):
            carry = lines[i:]  # title/header at the page foot, rows on the next page
    return tables, carry


_PAGE_HEAD = re.compile(r"^(Ministry of Statistics|Infrastructure and Project Monitoring|\d{1,3}$)", re.I)


def join_carry(carry, lines):
    """Prepend a table start carried over from the previous page, re-based just above."""
    body = [ln for ln in lines if not _PAGE_HEAD.match(ln.text)]
    body = [ln for ln in body if not re.search(r"Infrastructure Performance Report", ln.text)]
    if not body:
        return lines
    carry = [ln for ln in carry if not _FOOT.search(ln.text) and not re.fullmatch(r"\d{1,3}", ln.text.strip())]
    if not carry:
        return lines
    dy = body[0].y - 12 - carry[-1].y
    moved = [Line([W(w.x0, w.y0 + dy, w.x1, w.y1 + dy, w.t) for w in ln.words]) for ln in carry]
    return moved + body


def resplit_zone(zone):
    """Value tokens left of (or inside) the label area are serial numbers / label parts.
    The label area ends before the value columns; a stray word printed inside a value
    column must not drag the boundary right (it would swallow real values)."""
    def numeric(w):  # real numbers, not placeholders or serials like "1." / "10"
        return w.t not in NA_TOK and not re.fullmatch(r"\d{1,2}\.?", w.t)
    firsts = sorted(min(w.x0 for w in vw if numeric(w)) for ln, lw, vw in zone if any(numeric(w) for w in vw))
    v0 = firsts[len(firsts) // 4] if firsts else 1e9
    label_right = max((w.x1 for ln, lw, vw in zone if vw for w in lw if not is_value(w.t) and w.x1 <= v0 + 2),
                      default=0)
    zone2 = []
    for ln, lw, vw in zone:
        allw = sorted(lw + vw, key=lambda w: w.x0)
        last_txt = max((w.x0 for w in allw if not is_value(w.t)), default=-1)
        val = [w for w in allw if is_value(w.t) and w.x1 > label_right and w.x0 > last_txt]
        zone2.append((ln, [w for w in allw if w not in val], val))
    zone = zone2
    return zone, label_right


def parse_one(lines, i, end, title, mode, report_month, page_no, state, stats):
    special = not title.startswith("Table")
    name = title
    j, prev_y = i + 1, lines[i].y
    unit = None
    # title continuation lines (stop at the unit line or the first column-header line)
    while j < end and lines[j].y - prev_y <= 16:
        txt = lines[j].text
        if is_unit_line(txt):
            unit = unit_from(txt, True)
            j += 1
            break
        low = {w.t.lower() for w in lines[j].words}
        if low & _TITLE_STOP:
            break
        lw, vw = split_line(lines[j])
        if vw and not find_periods(txt):
            break
        if not special and len(find_periods(txt)) > 1:
            break  # "December 2018  April-December 2018" group header
        title += " " + txt
        prev_y = lines[j].y
        j += 1
    # Areas of concern / Noteworthy keep their canonical name: the next line can be a rotated
    # header letter (Feb 2021 'Areas of concern A'); Highlights keeps its descriptive subtitle
    title = name if mode == "block" else norm_ws(title)
    # header zone until first data line
    k = j
    while k < end:
        ln = lines[k]
        if _FOOT.search(ln.text):
            return None
        lw, vw = split_line(ln)
        if vw and not is_header_line(ln):
            break
        k += 1
    if k >= end:
        return None
    # label-only lines after the last real header line belong to the data zone
    kh = k
    while kh > j and not is_header_line(lines[kh - 1]) and not is_unit_line(lines[kh - 1].text):
        kh -= 1
    hlines = []
    for ln in lines[j:kh]:
        if is_unit_line(ln.text):
            unit = unit_from(ln.text, True)
            continue
        hlines.append(ln)
    k = kh
    # data zone
    zone, last_y = [], None
    for ln in lines[k:end]:
        txt = ln.text
        if _FOOT.search(txt) or _SECTION.match(txt) or _TITLE_RE.match(txt):
            break
        if last_y is not None and ln.y - last_y > 60:
            break
        lw, vw = split_line(ln)
        if vw and not lw and len(vw) == 1 and ln.y > 730:
            break  # page number
        zone.append((ln, lw, vw))
        last_y = ln.y
    vlines = [(ln, vw) for ln, lw, vw in zone if vw]
    if not vlines:
        return None
    zone, label_right = resplit_zone(zone)
    vlines = [(ln, vw) for ln, lw, vw in zone if vw]
    if not vlines:
        return None
    cols = merge_disjoint(cluster_columns(vlines), vlines)
    for c in cols:
        c["n"] = 0
    for _, vw in vlines:
        for w in vw:
            ci = col_of(w, cols)
            if ci is not None:
                cols[ci]["n"] += 1
    if any(c["n"] < 2 for c in cols) and len(vlines) > 3:
        return {"skip": f"p{page_no} '{title}': sparse/misaligned value column"}
    labels = header_labels(hlines, cols, label_right)
    hdr_text = " ".join(ln.text for ln in hlines)
    if unit is None and re.search(r"rs\.?\s*in\s*crore", hdr_text, re.I):
        unit = "Rs crore"
    # table-level current period
    tbl_period = None
    if special:
        ps = [p for lab in labels for p in find_periods(lab) if p[0] != "fy"]
        if ps:
            latest = max(p[2] for p in ps)
            cand = [p for p in ps if p[2] == latest]
            tbl_period = next((p for p in cand if p[0] == "cumulative"), cand[0])
        if title.startswith(("Areas", "Noteworthy")):
            # these tables always cover FY-start .. report month; headers are only a cross-check
            # (Sep 2019 'Septembe r 2019' split glyphs, May 2020 header misprinted '(April 2020)')
            anchor = ("cumulative", fy_start_ym(report_month), report_month)
            if tbl_period and tbl_period[1:] != anchor[1:]:
                stats["notes"].append(f"p{page_no} {title}: header period {tbl_period[1]}..{tbl_period[2]} "
                                      f"!= report period; anchored to {anchor[1]}..{anchor[2]}")
            tbl_period = anchor
    else:
        tt = fix_title_year(title, report_month)
        if not find_periods(tt) and report_month:  # "... - November 201" (year cut off)
            tt = re.sub(r"(\d{1,3})\s*$", report_month[:4], tt)
        tp = [p for p in find_periods(tt) if p[0] != "fy"]
        if tp and tp[-1][2] != report_month:
            tp = [p for p in find_periods(title) if p[0] != "fy"]
        if len({(p[0], p[2]) for p in tp}) == 1:
            tbl_period = tp[0]
    if not special and len(labels) >= 5 and any("variation" in l.lower() for l in labels[-2:]):
        # the "% Variation Over" group header spans the last two columns
        labels = labels[:-2] + [l if "variation" in l.lower() else "% Variation Over " + l for l in labels[-2:]]
    colper = group_periods(labels) if not special else None
    if not special:
        # fixed layouts whose wrapped headers are too cramped to read column by column:
        # capacity utilisation = [M, M-1y, Apr..M, Apr..M-1y]; PLF = [T, A, prev] x (month, cum)
        tm = [p[2] for p in find_periods(fix_title_year(title, report_month)) if p[0] == "month"]
        m = max(tm) if tm else report_month  # latest: titles may name last year first
        cur, cum = (m, m), (fy_start_ym(m), m)
        prev, pcum = tuple(shift_year(x, -1) for x in cur), tuple(shift_year(x, -1) for x in cum)
        tl = title.lower()
        if "capacity utilisation" in tl and "refinery" not in tl and len(labels) == 4:
            labels, colper = ["Capacity Utilisation (%)"] * 4, [cur, prev, cum, pcum]
        elif "plf" in tl and len(labels) in (3, 6):
            labels = ["Target", "Achievement (Provisional)", "Actual"] * (len(labels) // 3)
            colper = [cur, cur, prev, cum, cum, pcum][:len(labels)]
    ckey = next((k for k in CANON_COLS if title.startswith(k)), None)
    if ckey and tbl_period and "target" in labels[0].lower() and len(labels) in (5, 6):
        cur = (tbl_period[1], tbl_period[2])
        prev = (shift_year(cur[0], -1), shift_year(cur[1], -1))
        if len(labels) == 6 and "achievement" in labels[3].lower():
            labels = list(CANON_COLS[ckey])
            colper = [cur, cur, cur, prev, cur, cur]
        elif len(labels) == 5 and re.search(r"less|more", labels[3], re.I):
            labels = [lab for i, lab in enumerate(CANON_COLS[ckey]) if i != 3]
            colper = [cur] * 5
    elif (ckey and tbl_period and len(labels) == 7 and labels[0].lower().startswith("actual")
          and "target" in labels[1].lower() and "achievement" in labels[4].lower()):
        # header of the 'Achievement' column repeats the current period, but the values are
        # last year's (e.g. Jan 2021: 1169.52 BU = Apr 2019-Jan 2020 power generation)
        cur = (tbl_period[1], tbl_period[2])
        prev = (shift_year(cur[0], -1), shift_year(cur[1], -1))
        labels = ["Actual"] + list(CANON_COLS[ckey])
        colper = [cur, cur, cur, cur, prev, cur, cur]
    if title.startswith("Highlights"):
        # 5 achievement columns then 4 growth columns under two group headers
        ga = [w for ln in hlines for w in ln.words if w.t.lower() in ("achievement", "growth")]
        if len(cols) == 9:
            kinds = ["Achievement"] * 5 + ["Growth percent"] * 4
        elif ga:
            kinds = ["Growth percent" if min(ga, key=lambda w: abs(w.cx - c["cx"])).t.lower() == "growth"
                     else "Achievement" for c in cols]
        else:
            kinds = [""] * len(cols)
        labels = [norm_ws(k + " " + re.sub(r"(?i)achievement|growth|percent", "", lab))
                  for k, lab in zip(kinds, labels)]
    outers = []
    if not special:
        zone, outers = split_two_level(zone)
    out = []
    if mode == "block":
        brows, unplaced, wrapped = assemble_blocks(zone, cols)
        if wrapped:
            stats["notes"].append(f"p{page_no} {title}: {wrapped} number(s) wrapped onto the next line inside "
                                  f"their cell re-joined (e.g. '13.9'+'9' -> 13.99; checked against the row's ratio)")
        if unplaced:
            stats["notes"].append(f"p{page_no} {title}: {unplaced} value cell(s) not attributable to a row, dropped")
        out = [(g, lab, cells, notes) for g, lab, cells, _, notes in brows]
    else:
        rows = assemble_rows(zone, cols, mode)
        if outers:  # e.g. airport name printed once for its Export / Import rows
            rows = [(norm_ws(" / ".join(x for x in (g, next((t for oy, t in reversed(outers) if oy <= y + 1), None))
                                       if x)) or None, lab, vw, y) for g, lab, vw, y in rows]
        for grp, label, vw, y in rows:
            assign = assign_row(vw, cols)
            if assign is None:
                return {"skip": f"p{page_no} '{title}': row '{label}' values not aligned to columns"}
            out.append((grp, label, assign, {}))
        restore_total_label(out, title)
    checked = 0
    if ckey:
        # Areas of concern / Noteworthy cells are vertically centred and wrap unevenly; keep a
        # row only if it is complete and its printed percentages agree with its own values, or if
        # exactly one printed cell contradicts an otherwise consistent row (that cell is blanked)
        if not colper:
            return {"skip": f"p{page_no} '{title}': unrecognised column layout ({len(labels)} columns)"}
        good, bad = [], []
        for r in out:
            if special_row_ok(r[1], r[2], len(labels)):
                good.append(r)
                continue
            pin = pin_bad_cell(r[1], r[2], len(labels), -1 if ckey == "Areas of concern" else 1)
            if pin:
                ci, implied = pin
                r[3].setdefault(ci, []).append(f"printed_value_inconsistent:implied={implied:.2f}")
                stats["notes"].append(f"p{page_no} {title}: row '{r[1]}' kept, printed '{labels[ci]}' "
                                      f"{r[2][ci]} contradicts the row (implied {implied:.2f}); value blanked")
                good.append(r)
            else:
                bad.append(r[1])
        checked = len(bad)
        if len(good) < 0.7 * len(out):
            return {"skip": f"p{page_no} '{title}': {checked}/{len(out)} rows failed consistency checks"}
        if bad:
            stats["notes"].append(f"p{page_no} {title}: row(s) dropped (incomplete or % inconsistent in more "
                                  f"than one cell): " + ", ".join(f"'{b}'" for b in bad))
        out = good
    out, dropped = dedupe_rows(out, title, (lambda lab, a: special_row_ok(lab, a, len(labels))) if ckey else None)
    dups = len(dropped)
    if dropped:
        stats["notes"].append(f"p{page_no} '{title}': row(s) dropped, same label repeated in the table: "
                              + ", ".join(dropped))
    if not out:
        return None
    stats["tables"] += 1
    return {"title": title, "unit": unit, "labels": labels, "cols": cols, "rows": out,
            "period": tbl_period, "colper": colper, "dups": dups, "checked": checked,
            "special": special, "sector": state.get("sector"), "page": page_no}


TELECOM_GROUPS = [
    (r"switching", "Net addition in switching capacity - wireline & wireless (WLL+GSM) (in Lines)"),
    (r"DELs|wireline\s*\(Fixed\)", "Provision of net new DELs Telephone connections wireline (Fixed) (in Numbers)"),
    (r"Wireless\s*\(Mobile\)", "Provision of net new Wireless (Mobile) connections (WLL+GSM) (in Numbers)")]


def dedupe_rows(out, title, check=None):
    """A repeated (group, label) means a group heading is missing in the source. Telecom Tables
    59/60 always print switching / wireline / wireless blocks of Public / Private / Total: when a
    block repeats and the next template heading is absent (May 2020 Table 59 omits the wireline
    heading) the block gets that heading back, flagged label_restored. With `check` (Areas /
    Noteworthy), a repeat whose numbers fill only the columns the first row left blank is the other
    half of a split row (Oct 2020 Noteworthy prints 'State PWD & BRO' once for the target and once
    for last year) and is merged if check(label, merged cells) holds. Other repeats are dropped.
    -> (rows, ['group / label' dropped])"""
    def tidx(g):
        return next((k for k, (p, _) in enumerate(TELECOM_GROUPS) if re.search(p, g or "", re.I)), None)

    def nums(a):
        return {ci for ci, t in a.items() if to_num(t) is not None}
    tel = "Telecommunication Sector" in title
    present = {tidx(r[0]) for r in out}
    pos, uniq, dropped, moved = {}, [], [], {}
    for g, lab, a, n in out:
        if g in moved or ((g, lab) in pos and tel and tidx(g) is not None
                          and tidx(g) + 1 < len(TELECOM_GROUPS) and tidx(g) + 1 not in present):
            if g not in moved:
                present.add(tidx(g) + 1)
                moved[g] = TELECOM_GROUPS[tidx(g) + 1][1]
            g = moved[g]
            n.setdefault(None, []).append("label_restored")
        if (g, lab) in pos:
            first = uniq[pos[(g, lab)]]
            merged = {**first[2], **{ci: a[ci] for ci in nums(a)}}
            if check and nums(a) and not nums(a) & nums(first[2]) and check(lab, merged):
                first[2].update(merged)
                first[3].setdefault(None, []).append("split_row_merged")
                continue
            dropped.append(f"{g or ''} / {lab}".strip(" /"))
            continue
        pos[(g, lab)] = len(uniq)
        uniq.append((g, lab, a, n))
    return uniq, dropped


def restore_total_label(out, title):
    """Airport tables: the grand-total label can print as mangled glyphs ('-6' in Feb 2021 Table 58).
    A row with no letters in its label whose values are the sum of the two rows above it (Total
    International + Total Domestic) is 'Total (International+Domestic)', flagged label_restored."""
    if "airport" not in title.lower():
        return
    for i in range(2, len(out)):
        g, lab, a, n = out[i]
        if re.search(r"[A-Za-z]", lab or ""):
            continue
        rows = (a, out[i - 1][2], out[i - 2][2])
        hits = [ci for ci in a if all(to_num(x.get(ci)) is not None for x in rows)
                and abs(to_num(a[ci]) - to_num(rows[1][ci]) - to_num(rows[2][ci])) <= 1]
        if len(hits) >= 2:
            n.setdefault(None, []).append("label_restored")
            out[i] = (None, "Total (International+Domestic)", a, n)


def clean_group(g):
    """Trailing footnote marks off; glyph-dropped 'Physica' / 'Financia' restored."""
    g = norm_ws(re.sub(r"[*#]+$", "", g or ""))
    return {"Physica": "Physical", "Financia": "Financial"}.get(g, g) or None


def detail_rows(tbl, report_month, src):
    fy = fiscal_year(report_month)
    out = []
    meta = column_meta(tbl, report_month)
    tbl["ambiguous_cols"] = sum(1 for n, _ in meta if n is None)
    for grp, label, assign, notes in tbl["rows"]:
        if not label:
            label = None
        # special tables: the section heading (row_group) decides, the row label only when there is none
        sector = tbl["sector"] if not tbl["special"] else (sector_from_text(grp) or sector_from_text(label))
        for ci, raw in assign.items():
            clab, (ps, pe) = meta[ci]
            if clab is None:
                continue  # column label/period ambiguous -> not emitted
            pct = bool(re.search(r"%|percent|variation|plf|utili[sz]ation", clab, re.I)) or tbl["unit"] == "%"
            unit = "%" if pct else (unit_from(f"{grp or ''} {label or ''}", False) or tbl["unit"])
            flags = tbl.get("dq", []) + notes.get(None, []) + notes.get(ci, [])
            bad = any(f.startswith("printed_value_inconsistent") for f in flags)  # blank beats wrong
            out.append({
                "report_month": report_month, "fiscal_year": fy, "source_file": src, "page": tbl["page"],
                "sector": sector, "table_title": tbl["title"], "row_group": clean_group(grp), "row_label": label,
                "column_label": clab, "period_start": ps, "period_end": pe,
                "value": None if bad else to_num(raw), "value_text": raw, "unit": unit,
                "dq_note": ";".join(flags) or None,
            })
    return out


def add_flag(r, flag):
    """Append a data-quality flag to a row's ';'-joined dq_note (no duplicates)."""
    cur = [f for f in (r.get("dq_note") or "").split(";") if f]
    if flag not in cur:
        r["dq_note"] = ";".join(cur + [flag])


def ym_add(ym, k):
    n = int(ym[:4]) * 12 + int(ym[5:7]) - 1 + k
    return f"{n // 12:04d}-{n % 12 + 1:02d}"


def ym_diff(a, b):
    return (int(a[:4]) - int(b[:4])) * 12 + int(a[5:7]) - int(b[5:7])


def telecom_lag(perf, detail, rm, notes):
    """Telecom data can lag the report (Sep-Nov 2020 reports carry July 2020, Feb 2021 carries
    Jan 2021, Mar 2021 carries Feb 2021). The data month is printed only in the telecom detail
    table titles (Table 59 'Performance of Telecommunication Sector - July 2020'). When the
    Annexure telecom actuals equal that table's totals, the Annexure rows and the Highlights /
    Areas / Noteworthy telecom cells are re-dated to the data month instead of the report month."""
    t59 = [r for r in detail if "Telecommunication Sector" in r["table_title"] and r["row_label"] == "Total"
           and r["column_label"].startswith("Achievement") and r["period_start"] == r["period_end"]
           and r["value"] is not None]
    if not rm or not t59:
        return
    tm = max(r["period_end"] for r in t59)
    k = ym_diff(rm, tm)
    if k <= 0:
        return
    cf = (f"carried_forward:{tm}", "source_says_previous_month_data")
    for r in detail:  # Tables 59/60 themselves: titled with the earlier data month
        if "Telecommunication Sector" in r["table_title"]:
            for f in cf:
                add_flag(r, f)
    want = {round(r["value"]) for r in t59 if r["period_end"] == tm}
    tel = [r for r in perf if r["sector"] == "Telecommunications"]
    if not tel:
        return  # no Annexure (Aug 2020); the detail tables carry their own titled period
    chk = [r for r in tel if r["period_type"] == "month" and not r["is_total"] and r["actual"] is not None]
    if not chk or any(round(r["actual"] * 1000) not in want for r in chk):
        notes.append(f"telecom detail tables are titled {tm} but Annexure telecom values do not match them; "
                     f"Annexure telecom rows kept under the report month")
        return
    changed = 0
    for r in tel:
        for f in cf:
            add_flag(r, f)
        per = (tm, tm) if r["period_type"] == "month" else (fy_start_ym(tm), tm)
        if (r["period_start"], r["period_end"]) != per:
            r["period_start"], r["period_end"] = per
            changed += 1
    cum = {round(r["actual"], 3) for r in tel if r["period_type"] == "cumulative" and r["actual"] is not None}
    cum |= {round(r["prev_year_actual"], 3) for r in tel
            if r["period_type"] == "cumulative" and r["prev_year_actual"] is not None}
    shifted = 0
    for title in {r["table_title"] for r in detail
                  if r["sector"] == "Telecommunications" and not r["table_title"].startswith("Table")}:
        cells = [r for r in detail if r["table_title"] == title and r["sector"] == "Telecommunications"]
        if not any(r["value"] is not None and round(r["value"], 3) in cum for r in cells):
            notes.append(f"telecom cells of '{title[:40]}' not re-dated (values do not match the lagged Annexure)")
            continue
        for r in cells:
            for f in cf:
                add_flag(r, f)
            if r["period_end"]:
                pe = ym_add(r["period_end"], -k)
                r["period_start"] = pe if r["period_start"] == r["period_end"] else fy_start_ym(pe)
                r["period_end"] = pe
                shifted += 1
    notes.append(f"telecom data month {tm} (per Table 59 title; Annexure telecom actuals equal its totals): "
                 f"{changed} Annexure rows and {shifted} Highlights/Areas/Noteworthy telecom cells dated {tm}")


# --------------------------------------------------------------------------
# pages without a text layer. Aug 2020 pp14-43 draw every glyph as a vector path and there is no
# OCR engine, so Annexure-A (p17) and Highlights (p14) were rendered with fitz (200 and 300 dpi)
# and transcribed by eye, cell by cell, exactly as printed. Nothing is emitted unless the
# transcription passes its own arithmetic (check_annex / check_highlights); main() then compares it
# with the neighbouring reports (corroborate). Rows carry dq_note transcribed_from_image. Not
# transcribed: Areas of concern / Noteworthy (pp15-16) and Tables 1-58 (pp18-43).
# --------------------------------------------------------------------------
TRANSCRIBED = {"CompleteReviewReportAug2020.pdf": {
    "annex_page": 17,
    "annex_title": "Infrastructure Sector Performance during August 2020 and April-August 2019 & April-August 2020",
    # label | cols (2)..(11): Aug 2020 Target, Actual, Aug 2019 Actual, % over Target, % over Actual,
    #         Apr-Aug 2020 Target, Actual, Apr-Aug 2019 Actual, % over Target, % over Actual
    "annex": """
1. Power generation (BU)
Thermal Generation | 89.594 79.034 80.782 -11.79 -2.16 492.284 387.328 455.875 -21.32 -15.04
Nuclear Generation | 4.065 3.591 4.302 -11.66 -16.53 17.345 18.372 19.806 5.92 -7.24
Hydro Generation | 19.033 18.950 19.928 -0.44 -4.91 72.189 78.036 75.203 8.10 3.77
Import from Bhutan | 0.896 1.561 1.187 74.22 31.51 4.029 5.358 2.981 32.99 79.74
Renewable Energy | - 15.766 14.922 - 5.66 - 67.316 67.344 - -0.04
Total | 113.588 118.902 121.121 4.68 -1.83 585.847 556.410 621.209 -5.02 -10.43
2. Coal Production (MT)
Coal India Ltd. | 45.980 37.160 34.700 -19.18 7.09 236.130 195.530 210.140 -17.19 -6.95
Singareni | 4.691 2.440 4.053 -47.99 -39.80 25.521 14.795 26.284 -42.03 -43.71
Others | 8.438 4.932 3.982 -41.55 23.86 42.190 23.815 23.287 -43.55 2.27
Total | 59.109 44.532 42.735 -24.66 4.20 303.841 234.140 259.711 -22.94 -9.85
3. Production of Finished Steel ('000 Tonnes)
i) SAIL | - 1031.0 1033.0 - -0.19 - 3398.0 5145.0 - -33.96
ii) ESSAR | - 573.0 577.0 - -0.69 - 2402.0 2991.0 - -19.69
iii) Tata Steet (TSL) | 871.0 1650.0 1516.0 89.44 8.84 3762.0 5676.0 7604.0 50.88 -25.36
iv) JSWL | - 1212.0 1140.0 - 6.32 - 4896.0 6309.0 - -22.40
v) JSPL | - 412.0 398.0 - 3.52 - 1293.0 1814.0 - -28.72
vi) RINL (VSP) | 356.0 164.0 248.0 -53.93 -33.87 781.0 465.0 1607.0 -40.46 -71.06
Total | 1227.0 5042.0 4912.0 310.92 2.65 NA 18130.0 25470.0 - -28.82
II. Major (Secondary) Producer | - 3039.0 3446.0 - -11.81 NA 11950.0 18046.0 - -33.78
Total (I + II) | 1227.0 8081.0 8358.0 558.60 -3.31 NA 30080.0 43516.0 - -30.88
4. Cement Production (MT)
Cement Production(MT) | - 20.85 24.45 - -14.72 - 98.20 138.60 - -29.15
5. Fertilisers Production ('000 Tonnes)
i) Nitrogen | 1308.8 1239.9 1193.7 -5.26 3.87 5948.5 5728.0 5445.8 -3.71 5.18
ii) Phosphate | 545.7 419.2 381.2 -23.18 9.97 2573.6 1884.4 1941.0 -26.78 -2.92
Total | 1854.5 1659.1 1574.9 -10.54 5.35 8522.1 7612.4 7386.8 -10.67 3.05
6. Petroleum
i) Crude Oil Prod. (MT) | 2.763 2.577 2.750 -6.73 -6.29 13.449 12.886 13.725 -4.19 -6.11
ii) Refinery Prod. (MT) | 21.705 16.150 21.953 -25.59 -26.43 102.836 82.459 106.313 -19.82 -22.44
iii) Natural Gas Prod. (MCM) | 2836 2432 2688 -14.24 -9.54 13259 11660 13437 -12.06 -13.22
7. Roads (Kms.)
Widening/ Strengthening/ existing weak pavement to four/six/eight lanes (Kms.) | 235.00 283.00 224.00 20.43 26.34 900.00 881.00 1323.00 -2.11 -33.41
Widening to four/six/eight lanes (Kms.) | 16.00 17.88 18.60 11.75 -3.87 36.00 56.00 109.47 55.56 -48.84
Widening to two lanes (Kms.) | 200.00 221.74 285.16 10.87 -22.24 750.00 1101.72 1555.00 46.90 -29.15
Strengthening of existing weak pavement (Kms.) | 100.00 97.88 58.55 -2.12 67.17 619.00 925.83 245.91 49.57 276.49
Total of (b) | 316.00 337.50 362.31 6.80 -6.85 1405.00 2083.55 1910.38 48.30 9.06
8. Railways
Revenue earning goods Traffic (MT) | 100.11 94.63 91.06 -5.47 3.92 200.22 431.39 498.32 115.46 -13.43
9. Shipping
i) Cargo handled at major ports (MT) | - 51.611 57.494 - -10.23 - 245.047 293.670 - -16.56
ii) Coal handled at major ports (MT) | - 9.075 10.402 - -12.76 - 45.782 63.525 - -27.93
10. Civil Aviation
i) Export Cargo | 57385 73973 101150 28.91 -26.87 236713 283288 522429 19.68 -45.77
ii) Import Cargo | 38615 54499 69969 41.13 -22.11 159291 191425 346369 20.17 -44.73
i) International Terminals | 1000000 586693 5718640 -41.33 -89.74 1675000 1691159 28285402 0.96 -94.02
ii) Domestic Terminals | 10850000 5576872 23063614 -48.60 -75.82 24937500 14044346 113940672 -43.68 -87.67
11. Telecommunications
i) Net Addition in Switching Capacity (Fixed+WLL+GSM) ('000 Lines) | - -489.364 246.170 - - - -689.897 2157.828 - -
ii) Net new wireline (Fixed) telephone connections provided ('000 Numbers) | - 9.867 -204.815 - - - 693.009 -731.229 - -
iii) Net (New) Wireless (WLL+GSM) connections provided ('000 Numbers) | - 3195.054 2956.225 - 8.08 - -11924.987 6603.901 - -
Total connections (ii+iii) (in '000 Numbers) | - 3204.921 2751.410 - 16.48 - -11231.978 5872.672 - -
""",
    "hl_page": 14,
    "hl_title": "Highlights Growth Achieved during the period April - August 2020 during Last Three Years "
                "(April - August)",
    # '@group' starts a row group ('@' alone clears it); label | Achievement April-August 2016..2020,
    # Growth percent April-August 2017..2020
    "hl": """
Power (BU) | 525.397 557.879 590.069 621.209 556.41 6.18 5.77 5.28 -10.43
Coal (MT) | 234.816 234.627 261.248 259.711 234.140 -0.08 11.35 -0.59 -9.85
Steel (Finished Steel) (MT) | 44.866 51.054 40.947 43.516 30.08 13.79 -19.80 6.27 -30.88
Cement (MT) | 121.16 117.18 136.77 138.60 98.2 -3.29 16.72 1.34 -29.15
Fertilizers (MT) | 7.3957 7.3952 7.357 7.387 7.612 -0.01 -0.51 0.40 3.05
@Petroleum
Crude Oil (MT) | 15.146 15.105 14.612 13.725 12.886 -0.27 -3.26 -6.07 -6.11
Refinery (MT) | 101.785 101.909 107.806 106.313 82.459 0.12 5.79 -1.39 -22.44
Natural Gas (MCM) | 13123 13690 13570 13437 11660 4.31 -0.87 -0.98 -13.22
@Widening & Strengthening of Highways
NHAI (KM) | 834.00 972.00 1079.00 1323.00 881 16.55 11.01 22.61 -33.41
State PWD & BRO (KM) | 919.99 1368.65 2009.04 1910.38 2083.55 48.77 46.79 -4.91 9.06
@
Railway Revenue Earning Freight Traffic (MT) | 445.97 467.72 494.47 498.32 431.39 4.88 5.72 0.78 -13.43
@Shipping & Ports
Cargo Handled at Major Ports (MT) | 265.307 274.319 288.467 293.670 245.04 3.40 5.16 1.80 -16.56
Coal handled at Major Ports(MT) | 63.581 55.556 66.282 63.525 45.78 -12.62 19.31 -4.16 -27.93
@Civil Aviation
Export Cargo handled (Tonnes) | 453938 525948 531588 522429 283288 15.86 1.07 -1.72 -45.77
Import Cargo handled (Tonnes) | 297520 366766 401882 346369 191425 23.27 9.57 -13.81 -44.73
Passengers handled at International Terminals (Lakh) | 240.612 262.973 283.222 282.854 16.911 9.29 7.70 -0.13 -94.02
Passengers handled at Domestic Terminal (Lakh) | 818.932 950.175 1134.433 1139.407 140.443 16.03 19.39 0.44 -87.67
@Telecommunications
Addition in Switching capacity (Fixed+WLL=GSM) ('000 lines) | 2039.822 -1109.759 1525.699 2157.828 -689.89 -154.40 -237.48 41.43 -
New net Fixed/wired Telephone connections ('000 No.) | -713.652 -648.598 -623.346 -731.229 693.009 - - - -
New net Cell phone (WLL+ GSM) connections ('000 No.) | -4760.788 15618.190 -22005.581 6603.901 -11924.98 - - - -
""",
}}
_TEL_TPL, _STEEL_TPL = ANNEX[-1][2], ANNEX[2][2]
SUM_PARTS = {  # totals that are not simply 'all other rows of the group'
    _STEEL_TPL[8][:2]: [_STEEL_TPL[6][:2], _STEEL_TPL[7][:2]],  # Total (I + II) = main Total + secondary
    _TEL_TPL[3][:2]: [_TEL_TPL[1][:2], _TEL_TPL[2][:2]]}  # connections = wireline + wireless


def pct_close(a_t, b_t, p_t):
    """Printed % change p = (a / b - 1) * 100 within print rounding (+0.02 for the source rounding
    from unrounded data). None when not checkable (a, b or p not a number, b = 0)."""
    a, b, p = to_num(a_t), to_num(b_t), to_num(p_t)
    if a is None or p is None or not b:
        return None
    tol = 100 * abs(a / b) * (half_ulp(a_t) / max(abs(a), 1e-9) + half_ulp(b_t) / abs(b)) + half_ulp(p_t) + 0.02
    return abs((a / b - 1) * 100 - p) <= tol


def read_transcription(text, nvals, hl=False):
    """Transcription block -> rows. Annexure: [{section, label, vals{2..11}}] like parse_annexure;
    Highlights: [(group, label, {0..8: text}, {})] like parse_one."""
    rows, head = [], None
    for ln in text.strip().splitlines():
        if "|" not in ln:
            head = ln.strip().lstrip("@") or None if hl else re.sub(r"^\d{1,2}\.\s*", "", ln.strip())
            continue
        lab, vals = (x.strip() for x in ln.split("|"))
        vals = vals.split()
        if len(vals) != nvals:
            raise ValueError(f"transcribed row '{lab}': {len(vals)} values, expected {nvals}")
        rows.append((head, lab, dict(enumerate(vals)), {}) if hl else
                    {"section": head, "label": lab, "vals": dict(enumerate(vals, 2))})
    return rows


def check_annex(mapped):
    """Transcribed Annexure: every printed % variation recomputes from its own columns and every
    total equals its components (a '-' component counts 0) within print rounding. -> problems"""
    probs, val = [], {}
    for (grp, ind, _, _, _), _, r in mapped:
        v = val[(grp, ind)] = r["vals"]
        for p, a, b in ((5, 3, 2), (6, 3, 4), (10, 8, 7), (11, 8, 9)):
            if to_num(v[p]) is not None and not pct_close(v[a], v[b], v[p]):
                probs.append(f"{ind}: col ({p}) {v[p]} != ({a}) {v[a]} vs ({b}) {v[b]}")
    for (grp, ind, _, tot, _), _, _ in mapped:
        if not tot:
            continue
        parts = SUM_PARTS.get((grp, ind)) or [(g, i) for (g, i, _, t, _), _, _ in mapped if g == grp and not t]
        for c in (2, 3, 4, 7, 8, 9):
            t, xs = val[(grp, ind)][c], [val[k][c] for k in parts]
            if to_num(t) is None or any(to_num(x) is None and x != "-" for x in xs):
                continue
            tol = half_ulp(t) + sum(half_ulp(x) for x in xs if x != "-") + 1e-9
            if abs(sum(to_num(x) or 0 for x in xs) - to_num(t)) > tol:
                probs.append(f"{grp} / {ind}: col ({c}) {t} != sum of components")
    return probs


def check_highlights(rows, perf):
    """Transcribed Highlights: each growth % recomputes from the achievement columns, and the last two
    achievements equal an Annexure cumulative actual / previous-year actual of the same sector (at
    scale 1, 1/1000 or 1/100000 = lakh; the source truncates, so within one last-place unit). -> problems"""
    probs = []
    cum = [r for r in perf if r["period_type"] == "cumulative"]
    for g, lab, a, _ in rows:
        for i in range(4):
            if to_num(a[5 + i]) is not None and not pct_close(a[i + 1], a[i], a[5 + i]):
                probs.append(f"{lab}: growth {a[5 + i]} != {a[i + 1]} vs {a[i]}")
        sec = sector_from_text(g) or sector_from_text(lab)

        def near(t, x):
            return x is not None and any(abs(x * s - to_num(t)) <= 2 * half_ulp(t) + 1e-9 for s in (1, 1e-3, 1e-5))
        if not any(r["sector"] == sec and near(a[4], r["actual"]) and near(a[3], r["prev_year_actual"]) for r in cum):
            probs.append(f"{lab}: {a[3]} / {a[4]} not found in the Annexure cumulative rows")
    return probs


def transcribed_tables(name, rm, src, notes):
    """-> (perf rows, detail rows, parser variants) for a report page transcribed from its image."""
    tr = TRANSCRIBED.get(name)
    if not tr:
        return [], [], []
    mapped, iss, _ = map_annex(read_transcription(tr["annex"], 10))
    probs = iss + check_annex(mapped) + ([] if len(mapped) == ANNEX_ROWS else [f"{len(mapped)} annexure rows"])
    if probs:
        notes.append(f"p{tr['annex_page']} Annexure-A transcription NOT emitted, checks failed: " + " | ".join(probs))
        return [], [], []
    perf = annex_perf_rows(mapped, 11, rm, src, tr["annex_page"], notes)
    for r in perf:
        add_flag(r, "transcribed_from_image")
    notes.append(f"p{tr['annex_page']} Annexure-A has no text layer: transcribed from a 300 dpi render "
                 f"({len(perf)} rows, dq_note transcribed_from_image); all printed % variations recompute and all "
                 f"totals equal their components")
    hl = read_transcription(tr["hl"], 9, hl=True)
    probs = check_highlights(hl, perf)
    if probs:
        notes.append(f"p{tr['hl_page']} Highlights transcription NOT emitted, checks failed: " + " | ".join(probs))
        return perf, [], ["annexA_transcribed"]
    ys = [(fy_start_ym(shift_year(rm, d)), shift_year(rm, d)) for d in range(-4, 1)]
    tbl = {"title": tr["hl_title"], "unit": None, "labels": ["Achievement"] * 5 + ["Growth percent"] * 4,
           "rows": hl, "period": None, "colper": ys + ys[1:], "special": True, "sector": None,
           "page": tr["hl_page"], "dq": ["transcribed_from_image"]}
    detail = detail_rows(tbl, rm, src)
    notes.append(f"p{tr['hl_page']} Highlights has no text layer: transcribed ({len(detail)} cells, dq_note "
                 f"transcribed_from_image); growth % recompute and the 2019/2020 columns equal the Annexure")
    return perf, detail, ["annexA_transcribed", "highlights_transcribed"]


# --------------------------------------------------------------------------
# per file
# --------------------------------------------------------------------------
def process(path):
    src = rel(path)
    rm = month_from_filename(path.name)
    doc = fitz.open(path)
    notes = []
    man = {"source_file": src, "report_type": "performance_review", "report_period": rm,
           "pages": len(doc), "rows_perf": 0, "rows_perf_detail": 0}
    perf, detail = [], []
    notext = [i + 1 for i, p in enumerate(doc) if not p.get_text("words") and p.get_drawings()]
    if notext:
        tr = TRANSCRIBED.get(path.name, {})
        done = f"pp{tr['hl_page']} and {tr['annex_page']} transcribed from images (below), the rest" if tr else "they are"
        notes.append(f"pages {notext[0]}-{notext[-1]} ({len(notext)}) have no text layer (glyphs drawn as vector "
                     f"paths): {done} not extracted (no OCR)")
    # title check (cover/summary pages)
    head = " ".join(doc[i].get_text() for i in range(min(4, len(doc)))).translate(_TR)
    tm = [p for p in find_periods(head) if p[0] == "month"]
    if rm and tm and rm not in {p[2] for p in tm}:
        notes.append(f"filename month {rm} not found in title pages")
    # annexure
    ai = find_annex_page(doc)
    variant = []
    if ai is None:
        perf, detail, variant = transcribed_tables(path.name, rm, src, notes)
        if not perf:
            notes.append("Annexure-A page not found")
    else:
        title, ncols, rows, iss = parse_annexure(doc[ai])
        tper = find_periods(title)
        if rm and tper and tper[0][2] != rm:
            notes.append(f"annexure title month {tper[0][2]} != filename month {rm}")
        mapped, iss2, restored = map_annex(rows)
        iss += iss2
        if restored:
            notes.append(f"{restored} clipped annexure labels restored from template")
        perf = annex_perf_rows(mapped, ncols, rm, src, ai + 1, notes)
        variant.append(f"annexA_{'month+cum' if ncols >= 11 else 'month_only'}")
        if ncols < 11:
            notes.append("April report: Annexure-A has the month table only (April-to-April = month); "
                         "no separate cumulative rows")
        if len(mapped) != ANNEX_ROWS:
            notes.append(f"annexure rows {len(mapped)}/{ANNEX_ROWS}")
        notes += iss[:5]
    # detail tables
    state, stats, skipped, carry = {"sector": None}, {"tables": 0, "notes": []}, [], None
    skipped_cols = []
    for pi, page in enumerate(doc):
        if ai is not None and pi == ai:
            continue
        lines = page_lines(page)
        if not lines:
            continue
        if carry:
            lines = join_carry(carry, lines)
        tables, carry = parse_tables(lines, pi + 1, state, rm, stats)
        for t in tables:
            if "skip" in t:
                skipped.append(t["skip"])
                continue
            detail += detail_rows(t, rm, src)
            if t.get("ambiguous_cols"):
                skipped_cols.append(f"p{t['page']} '{t['title']}': {t['ambiguous_cols']} ambiguous column(s) dropped")
    notes += stats["notes"]
    telecom_lag(perf, detail, rm, notes)
    ends = {}
    for r in detail:
        if re.search(r"capacity utili|\bplf\b", r["table_title"], re.I) and r["period_end"]:
            ends[r["table_title"]] = max(ends.get(r["table_title"], ""), r["period_end"])
    for t, e in sorted(ends.items()):
        if e != rm:
            notes.append(f"'{t[:60]}' latest period {e} != report month")
    skipped = skipped + skipped_cols
    variant.append("detail_generic")
    if skipped:
        notes.append(f"{len(skipped)} detail tables skipped/trimmed: " + " | ".join(skipped))
    man.update(rows_perf=len(perf), rows_perf_detail=len(detail), parser_variant="+".join(variant))
    exp = ANNEX_ROWS * (2 if rm and rm[5:] != "04" else 1)
    if len(perf) == exp and not notext:
        status = "ok"
    elif perf or detail:
        status = "partial"
    else:
        status = "failed"
    man["status"] = status
    man["notes"] = "; ".join(notes)
    doc.close()
    return perf, detail, man, skipped, stats["tables"]


def validate(perf):
    """Printed % variation vs target/actual and component sums vs printed totals. Values stay as
    printed; the offending rows get dq_note printed_pct_mismatch / components_sum_mismatch.
    -> [(source_file, message)]"""
    probs = []
    for r in perf:
        t, a, pv = r["target"], r["actual"], r["pct_var_target"]
        if t and a is not None and pv is not None and t > 0:
            calc = (a / t - 1) * 100
            if abs(calc - pv) > max(0.6, abs(pv) * 0.02):
                add_flag(r, "printed_pct_mismatch")
                probs.append((r["source_file"], f"{r['period_type']} {r['indicator']}: % var over target "
                                                     f"printed {pv}, target/actual imply {calc:.2f}"))
    # component sums (actual) for power / coal / fertiliser / steel-main / state-pwd
    groups = {}
    for r in perf:
        groups.setdefault((r["source_file"], r["period_type"], r["indicator_group"]), []).append(r)
    for (sf, pt, g), rs in groups.items():
        tot = [r for r in rs if r["is_total"]]
        comp = [r for r in rs if not r["is_total"]]
        if len(tot) != 1 or not comp or g in ("Railways", G_STEEL, "Telecommunications", G_CEM):
            continue
        s = [r["actual"] for r in comp]
        if None in s or tot[0]["actual"] is None:
            continue
        if abs(sum(s) - tot[0]["actual"]) > max(0.02 * abs(tot[0]["actual"]), 1.5):
            add_flag(tot[0], "components_sum_mismatch")
            probs.append((sf, f"{pt} {g}: components sum {sum(s):.3f} != printed total {tot[0]['actual']}"))
    return probs


def flag_stale(perf):
    """A value repeated from the previous month's report although the report's own cumulative
    contradicts it: Sep 2019 State PWD 'Strengthening' month (58.55 / 100.06) = Aug 2019's while
    Apr-Sep minus Apr-Aug is 22.29; Jan 2020 switching capacity month = Dec 2019's; or a cumulative
    that does not move although a fresh month value is not zero (Jul 2019 switching 2157.828).
    Kept as printed, flagged stale_repeat_of:<previous report month>. Rows dated to an earlier data
    month on purpose (telecom lag, dq_note carried_forward) are not compared. -> [(source_file, msg)]"""
    by = {(r["report_month"], r["indicator_group"], r["indicator"], r["period_type"]): r
          for r in perf if r["period_end"] == r["report_month"]}
    out = []
    for (rm, g, ind, pt), m1 in sorted(by.items()):
        pm = ym_add(rm, -1)
        m0, c0, c1 = (by.get(k) for k in ((pm, g, ind, "month"), (pm, g, ind, "cumulative"),
                                            (rm, g, ind, "cumulative")))
        if pt != "month" or rm[5:] == "04" or not (m0 and c0 and c1):
            continue
        for f, what in (("actual", "actual"), ("prev_year_actual", "previous-year actual")):
            v = m1[f]
            if v in (None, 0):
                continue
            step = None if None in (c1[f], c0[f]) else c1[f] - c0[f]
            if v == m0[f] and step is not None and abs(step - v) > max(0.02 * abs(v), 0.01):
                # the repeated month value is the stale one: when the cumulative did not move either,
                # the next report confirms the month was ~0 (Jan 2020 switching, Dec 2019 PWD last year)
                add_flag(m1, f"stale_repeat_of:{pm}")
                out.append((m1["source_file"], f"month {what} of '{ind}' = {v}, same as the {pm} report, but "
                                               f"the cumulative moved by {step:.3f}"))
            elif step == 0:
                add_flag(c1, f"stale_repeat_of:{pm}")
                out.append((m1["source_file"], f"cumulative {what} of '{ind}' = {c1[f]}, same as the {pm} "
                                               f"report, although the month value is {v}"))
    return out


def corroborate(perf, rm):
    """Transcribed Annexure rows of report rm against the text-layer reports: current-year values
    against the same period in other reports (lagged telecom) or the M-1 / M+1 cumulatives, previous-
    year values against the report 12 months earlier or the M+1 cumulative. Reports revise figures, so
    small differences are normal; an indicator whose current-year values are off by more than 25%
    from every neighbour would be a misread and is dropped. -> (perf, note)"""
    own = [r for r in perf if r["report_month"] == rm and "transcribed_from_image" in (r["dq_note"] or "")]
    idx = {}
    for r in perf:
        if r["report_month"] != rm:
            idx.setdefault((r["indicator_group"], r["indicator"], r["period_start"], r["period_end"]), []).append(r)
    ok = n = 0
    off, drop = [], set()
    for m in (r for r in own if r["period_type"] == "month"):
        key = (m["indicator_group"], m["indicator"])
        c = next(r for r in own if r["period_type"] == "cumulative" and (r["indicator_group"], r["indicator"]) == key)
        M, fy = m["period_end"], c["period_start"]

        def get(ps, pe):
            return idx.get(key + (ps, pe), [])
        nxt = {o["source_file"]: o for o in get(ym_add(M, 1), ym_add(M, 1))}
        pairs = [(o, nxt[o["source_file"]]) for o in get(fy, ym_add(M, 1)) if o["source_file"] in nxt]
        py, pfy = shift_year(M, -1), shift_year(fy, -1)
        cands = {
            ("month", "actual", m["actual"]): [o["actual"] for o in get(M, M)],
            ("cumulative", "actual", c["actual"]): [o["actual"] for o in get(fy, M)]
            + [o["actual"] + m["actual"] for o in get(fy, ym_add(M, -1)) if None not in (o["actual"], m["actual"])]
            + [oc["actual"] - om["actual"] for oc, om in pairs if None not in (oc["actual"], om["actual"])],
            ("month", "prev_year_actual", m["prev_year_actual"]): [o["actual"] for o in get(py, py)],
            ("cumulative", "prev_year_actual", c["prev_year_actual"]): [o["actual"] for o in get(pfy, py)]
            + [oc["prev_year_actual"] - om["prev_year_actual"] for oc, om in pairs
               if None not in (oc["prev_year_actual"], om["prev_year_actual"])]}
        cur_dev = []
        for (pt, f, x), ys in cands.items():
            ys = [y for y in ys if y is not None]
            if x is None or not ys:
                continue
            d = min(abs(x - y) / max(abs(y), 1e-9) for y in ys)
            n += 1
            ok += d <= 0.005
            if d > 0.005:
                off.append(f"{m['indicator'][:28]} {pt} {f} {x} ({100 * d:.1f}%)")
            if f == "actual":
                cur_dev.append(d)
        if cur_dev and min(cur_dev) > 0.25:
            drop.add(key)
    if not n:
        return perf, None
    note = (f"transcription vs neighbouring reports: {ok}/{n} values within 0.5% of another report; the rest "
            f"differ by revisions or source quirks and are kept as printed: " + "; ".join(off))
    if drop:
        note += f"; DROPPED as likely misreads (>25% off every neighbour): {sorted(drop)}"
    return [r for r in perf if r not in own or (r["indicator_group"], r["indicator"]) not in drop], note


def main():
    files = sorted(p for d in SRC_DIRS for p in d.glob("*.pdf"))
    perf, detail, manifest, known = [], [], [], []
    for f in files:
        try:
            p, d, m, skipped, ntab = process(f)
        except Exception as e:  # keep going; record failure
            manifest.append({"source_file": rel(f), "report_type": "performance_review",
                             "report_period": month_from_filename(f.name), "status": "failed",
                             "notes": f"exception: {e!r}"})
            print("FAILED", f.name, repr(e))
            continue
        perf += p
        detail += d
        manifest.append(m)
        known += [f"{f.name}: {s}" for s in skipped]
        print(f"{f.name}: perf={len(p)} detail={len(d)} tables={ntab} skipped={len(skipped)} "
              f"status={m['status']} {m['notes'][:150]}")
    extra = {}
    for name in TRANSCRIBED:
        src = next((m["source_file"] for m in manifest if m["source_file"].endswith("/" + name)), None)
        perf, note = corroborate(perf, month_from_filename(name))
        if note and src:
            extra[src] = [note]
    for m in manifest:  # after corroborate()
        if m.get("status") != "failed":
            m["rows_perf"] = sum(r["source_file"] == m["source_file"] for r in perf)
    seen = Counter((r["source_file"], r["indicator_group"], r["indicator"], r["period_type"]) for r in perf)
    dups = [k for k, v in seen.items() if v > 1]
    if dups:
        print("DUPLICATE perf keys:", dups[:5])
    probs, stale = validate(perf), flag_stale(perf)
    for m in manifest:
        sf = m["source_file"]
        bad = [msg for f, msg in probs if f == sf]
        rep = [msg for f, msg in stale if f == sf]
        m["notes"] = "; ".join(x for x in [m.get("notes")] + extra.get(sf, []) + (
            ["printed values inconsistent in source (kept as printed, dq_note printed_pct_mismatch / "
             "components_sum_mismatch): " + " | ".join(bad)] if bad else []) + (
            ["values repeated from the previous report although this report's own cumulative contradicts "
             "them (kept as printed, dq_note stale_repeat_of): " + " | ".join(rep)] if rep else []) if x)
    write_part(perf, FAMILY, "perf", PERF_COLS)
    write_part(detail, FAMILY, "perf_detail", PERF_DETAIL_COLS)
    write_part(manifest, FAMILY, "manifest", MANIFEST_COLS)
    print(f"TOTAL perf={len(perf)} detail={len(detail)} files={len(manifest)} validation_issues={len(probs)} "
          f"stale={len(stale)}")
    for sf, msg in (probs + stale)[:60]:
        print("  VALIDATION", sf, msg)
    for k in known[:60]:
        print("  SKIPPED", k)


def _selfcheck():
    # periods
    assert find_periods("April,2018-February 2019") == [("cumulative", "2018-04", "2019-02")]
    assert find_periods("April 2020 -Jan 2021)") == [("cumulative", "2020-04", "2021-01")]
    assert find_periods("% Variation Over Actual December 2017") == [("month", "2017-12", "2017-12")]
    assert find_periods("Annual Target 2018-2019")[0] == ("fy", "2018-04", "2019-03")
    assert find_periods("Dec-18") == [("month", "2018-12", "2018-12")]
    assert fix_title_year("Coking Coal despatch - April-November 20", "2018-11").endswith("November 2018")
    assert fix_title_year("Coal - November 201", "2018-11").endswith("November 2018")
    assert fix_title_year("Table 1: Power - Dec 18", "2018-12").endswith("Dec 18")
    assert month_from_filename("CompleteReviewReportMarch2020.pdf") == "2020-03"
    assert month_from_filename("CompleteReviewReportJuly2019.pdf") == "2019-07"
    # line split + label cleaning
    ln = Line([W(84, 0, 90, 9, "i)"), W(94, 0, 120, 9, "NHAI"), W(227, 0, 250, 9, "2863"),
               W(127, 0, 140, 9, "(Km)"), W(418, 0, 421, 9, "-")])
    lw, vw = split_line(ln)
    assert [w.t for w in lw] == ["i)", "NHAI", "(Km)"] and [w.t for w in vw] == ["2863", "-"]
    assert strip_enum("iii)Natural Gas (MCM)") == "Natural Gas (MCM)"
    assert strip_enum("2. Fertilizer Production (MT)") == "Fertilizer Production (MT)"
    assert strip_enum("Total - A") == "Total - A"
    # block assembly: value line printed above its enumerated label (centred cells)
    def L(y, *ws):
        return Line([W(x, y - 8, x + 6 * len(t), y, t) for x, t in ws])
    z = [L(285, (84, "Roads"), (119, ":")), L(297, (226, "500.0"), (294, "215")),
         L(301, (83, "i)"), (93, "NHAI"), (128, "(Km)")), L(315, (83, "ii)"), (96, "State"), (123, "PWD")),
         L(322, (226, "360.0"), (293, "0.45")), L(329, (83, "#(Km)"))]
    def blocks(z):
        zone, _ = resplit_zone([(ln,) + split_line(ln) for ln in z])
        cols = cluster_columns([(ln, vw) for ln, lw, vw in zone if vw])
        rows, bad, _ = assemble_blocks(zone, cols)
        return [(g, lab, [c for _, c in sorted(v.items())]) for g, lab, v, *_ in rows], bad
    assert blocks(z) == ([("Roads", "NHAI (Km)", ["500.0", "215"]), ("Roads", "State PWD #(Km)", ["360.0", "0.45"])],
                         0), blocks(z)
    # May 2019 p17: Natural Gas values printed on the line above its label, below Crude Oil's
    z = [L(216, (91, "Petroleum:")), L(229, (91, "i)"), (101, "Crude"), (131, "Oil"), (230, "5.63"), (290, "0.11")),
         L(241, (91, "Production(MT)")), L(253, (229, "5653"), (291, "258")), L(268, (91, "ii)"), (105, "Natural"),
         (144, "Gas")), L(281, (102, "Production"), (153, "(MCM)"))]
    assert blocks(z) == ([("Petroleum", "Crude Oil Production(MT)", ["5.63", "0.11"]),
                          ("Petroleum", "Natural Gas Production (MCM)", ["5653", "258"])], 0), blocks(z)
    # Jul 2020 p15: 'Fertilizer Production' starts a new row after 'Cement Production ((MT)';
    # May 2019 p18: State PWD under a stale 'Petroleum' group (Roads heading missing) loses the group
    z = [L(250, (48, "4."), (76, "Cement"), (116, "Production")), L(255, (225, "-"), (285, "-")),
         L(262, (76, "((MT)")), L(275, (76, "Fertilizer"), (123, "Production")), L(283, (53, "5.")),
         L(288, (76, "(MT)"), (215, "6.67"), (278, "0.72")), L(306, (51, "6."), (76, "Petroleum:")),
         L(319, (76, "i)"), (86, "Crude"), (215, "10.69"), (275, "0.38")), L(385, (63, "6.")),
         L(394, (81, "i)State"), (116, "PWD"), (215, "807"), (275, "173.98")), L(410, (84, "#(Km)"))]
    assert blocks(z)[0] == [(None, "Cement Production ((MT)", ["-", "-"]),
                            (None, "Fertilizer Production (MT)", ["6.67", "0.72"]),
                            ("Petroleum", "Crude", ["10.69", "0.38"]), (None, "State PWD #(Km)", ["807", "173.98"])],         blocks(z)
    # Sep 2020 p15: a cell of row ii) printed on the last label line of row i)
    z = [L(492, (89, "Shipping"), (133, "and"), (152, "Ports:")),
         L(504, (90, "i)"), (100, "Cargo"), (129, "handled"), (224, "-"), (397, "348.24"), (475, "49.68")),
         L(517, (65, "9."), (90, "ports"), (115, "(MT)"), (400, "74.01")),
         L(529, (90, "ii"), (99, ")"), (105, "Coal"), (128, "handled"), (227, "-"), (475, "18.52")),
         L(541, (90, "ports"), (115, "(MT)"))]
    assert blocks(z)[0] == [("Shipping and Ports", "Cargo handled ports (MT)", ["-", "348.24", "49.68"]),
                            ("Shipping and Ports", "Coal handled ports (MT)", ["-", "74.01", "18.52"])], blocks(z)
    # Jan 2019 p18: values printed below each label block (bottom-aligned)
    z = [L(449, (84, "Civil"), (110, "Aviation:")), L(513, (83, "vii)"), (120, "Passenger")), L(525, (97, "handled")),
         L(538, (97, "Terminal"), (140, "(Lakh)")), L(547, (410, "543.18"), (489, "36.67")),
         L(551, (83, "viii)"), (120, "Passenger")), L(563, (97, "Domestic")), L(576, (97, "Terminal"), (140, "(Lakh)")),
         L(589, (407, "1995.75"), (486, "314.26"))]
    assert blocks(z) == ([("Civil Aviation", "Passenger handled Terminal (Lakh)", ["543.18", "36.67"]),
                          ("Civil Aviation", "Passenger Domestic Terminal (Lakh)", ["1995.75", "314.26"])], 0), blocks(z)
    # Aug 2019 p17: '%' cell on its own line under the row's other cells; wrapped '13.9' + '9'
    z = [L(510, (83, "iii)"), (100, "Passenger")), L(522, (97, "International")),
         L(527, (234, "300.22"), (300, "17.37"), (401, "283.22")), L(535, (97, "(Lakh)")), L(540, (356, "5.78")),
         L(548, (83, "iv)"), (100, "Passenger")), L(552, (226, "1259.21"), (300, "119.8"), (401, "-")),
         L(560, (97, "Domestic")), L(565, (356, "9.51")), L(573, (97, "(Lakh)"))]
    assert blocks(z) == ([(None, "Passenger International (Lakh)", ["300.22", "17.37", "5.78", "283.22"]),
                          (None, "Passenger Domestic (Lakh)", ["1259.21", "119.8", "9.51", "-"])], 0), blocks(z)
    z = [L(160, (65, "1."), (84, "Coal"), (109, "(MT)"), (356, "13.9")), L(167, (233, "302.03"), (300, "42.24")),
         L(173.2, (363, "9"))]
    z[2].words[0].y0 = z[0].words[-1].y1  # the wrapped digit touches the line above
    assert blocks(z) == ([(None, "Coal (MT)", ["302.03", "42.24", "13.99"])], 0), blocks(z)
    z = [L(410, (42, "5"), (61, "Civil"), (87, "Aviation:"), (196, "1185129"), (263, "130189")),
         L(422, (61, "i)"), (73, "Export")), L(434, (73, "Airports"), (112, "(Tonne)")),
         L(447, (61, "ii)"), (73, "Import")), L(452, (197, "869356"), (263, "85989")), L(460, (73, "(Tonne)"))]
    assert blocks(z) == ([("Civil Aviation", "Export Airports (Tonne)", ["1185129", "130189"]),
                          ("Civil Aviation", "Import (Tonne)", ["869356", "85989"])], 0), blocks(z)
    # sector: airport cargo is Civil Aviation, not ports ('Export' contains 'port')
    assert sector_from_text("Export cargo handled at Airports (Tonne)") == "Civil Aviation"
    assert sector_from_text("Coal handled at major ports (MT)") == "Shipping & Ports"
    assert sector_from_text("Import from Bhutan") == "Power"
    assert find_periods("(April- Septembe r 2019)") == [("cumulative", "2019-04", "2019-09")]
    # bottom assembly: wrapped label, group line before enumerated row
    z = [L(264, (86, "7"), (97, "Roads")), L(274, (99, "Widening"), (140, "of")), L(283, (97, "Highways")),
         L(295, (97, "i)"), (103, "NHAI"), (216, "119.00")), L(322, (86, "8"), (97, "Railway")),
         L(335, (97, "Freight"), (146, "(MT)"), (220, "88.80"))]
    zone = [(ln,) + split_line(ln) for ln in z]
    cols = cluster_columns([(ln, vw) for ln, lw, vw in zone if vw])
    rows = assemble_rows(zone, cols, "bottom")
    assert [(g, lab) for g, lab, _, _ in rows] == [("Widening of Highways", "NHAI"),
                                                   (None, "Railway Freight (MT)")], rows
    # broken glyphs / merged words / month-like words
    assert find_periods("eptember 2019") == [("month", "2019-09", "2019-09")]
    assert [p[2] for p in find_periods("November 2018November 2017")] == ["2018-11", "2017-11"]
    assert find_periods("%age Decrease over last 12") == []
    # Areas of concern row check: % must equal diff / base
    assert special_row_ok("Coal Production (MT)", {0: "546.564", 1: "47.001", 2: "8.60", 3: "-", 4: "-", 5: "-"}, 6)
    assert not special_row_ok("Coal Production (MT)", {0: "546.564", 1: "47.001", 2: "18.60"}, 6)
    assert not special_row_ok("(MT)", {0: "1.2", 1: "0.1", 2: "8.33"}, 6)
    # rounding of 2-decimal inputs (April 2020: 0.35 / 0.86 = 40.7% printed 39.88) is tolerated
    assert special_row_ok("Passenger (Lakh)", {0: "0.86", 1: "0.35", 2: "39.88", 3: "-", 4: "-", 5: "-"}, 6)
    # Mar 2021 NHAI: last year printed, no shortfall against it; accepted only beside a verified group
    nhai = {0: "4218.00", 1: "4570.00", 2: "352.00", 3: "7.70", 4: "3277.00", 5: "-", 6: "-"}
    assert special_row_ok("NHAI (Km)", nhai, 7)
    assert not special_row_ok("NHAI (Km)", {**nhai, 2: "-", 3: "-"}, 7)
    # clipped "April-" on the last-year cumulative PLF column is recovered, true twins are dropped
    fixed = repair_dups([("Actual", ("2019-09", "2019-09")), ("Target", ("2020-04", "2020-09")),
                         ("Actual", ("2019-09", "2019-09"))])
    assert fixed[2] == ("Actual", ("2019-04", "2019-09")), fixed
    assert repair_dups([("A", ("2019-09", "2019-09")), ("A", ("2019-09", "2019-09"))])[1][0] is None
    # placeholders take the nearest free column
    cols = [{"x0": 190, "x1": 215, "cx": 202}, {"x0": 244, "x1": 270, "cx": 257}]
    assert assign_row([W(230, 0, 233, 9, "-"), W(250, 0, 270, 9, "12.5")], cols) == {1: "12.5", 0: "-"}
    # Apr 2018 Noteworthy Railways: only 'more than last year' 0.51 is wrong (97.23+0.75-90.47 = 7.51)
    rail = {0: "97.23", 1: "0.75", 2: "0.77", 3: "90.47", 4: "0.51", 5: "8.30"}
    assert not special_row_ok("Railways (MT)", rail, 6)
    ci, implied = pin_bad_cell("Railways (MT)", rail, 6, 1)
    assert ci == 4 and abs(implied - 7.51) < 1e-9
    assert pin_bad_cell("Railways (MT)", {**rail, 4: "0.51", 5: "0.50"}, 6, 1) is None  # two bad cells
    # Feb 2021 Table 58: grand-total label printed as '-6'; May 2020 Table 59: wireline heading missing
    rows = [("Total", "International", {0: "25000000", 1: "8518235", 2: "-58.95"}, {}),
            ("Total", "Domestic", {0: "175000000", 1: "89913758", 2: "-40.26"}, {}),
            (None, "6", {0: "200000000", 1: "98431993", 2: "-42.52"}, {})]
    restore_total_label(rows, "Table 58: Airport-wise Passenger Traffic handled")
    assert rows[2][1] == "Total (International+Domestic)" and rows[2][3] == {None: ["label_restored"]}
    sw = TELECOM_GROUPS[0][1] + " x"
    rows = [(sw, lab, {}, {}) for lab in ("Public Sector", "Private Sector", "Total")] * 2 + [
        (TELECOM_GROUPS[2][1], "Total", {}, {})]
    got, dropped = dedupe_rows(rows, "Table 59: Performance of Telecommunication Sector - May 2020")
    assert [g for g, *_ in got] == [sw] * 3 + [TELECOM_GROUPS[1][1]] * 3 + [TELECOM_GROUPS[2][1]] and not dropped
    assert dedupe_rows(rows[:4], "Table 12: Coal")[1] == [sw + " / Public Sector"]
    # Oct 2020 Noteworthy: 'State PWD & BRO' printed twice, target half and last-year half
    half = [("Roads", "State PWD", {0: "2391", 1: "585.28", 2: "24.48", 3: "-", 4: "-", 5: "-"}, {}),
            ("Roads", "State PWD", {0: "-", 1: "-", 2: "-", 3: "2743", 4: "232.92", 5: "8.49"}, {})]
    got, dropped = dedupe_rows(half, "Noteworthy Performance", lambda lab, a: special_row_ok(lab, a, 6))
    assert len(got) == 1 and not dropped and got[0][2][4] == "232.92" and got[0][2][0] == "2391", got
    # the Aug 2020 transcription passes its own arithmetic, a misread digit does not
    tr = TRANSCRIBED["CompleteReviewReportAug2020.pdf"]
    mapped = map_annex(read_transcription(tr["annex"], 10))[0]
    assert len(mapped) == ANNEX_ROWS and not check_annex(mapped), check_annex(mapped)
    mapped[0][2]["vals"][3] = "79.084"  # Thermal actual 79.034 misread
    assert len(check_annex(mapped)) >= 2  # % over target, % over actual and the power total all break
    # stale repeat: month equal to last report's while the cumulative moved by 22.29
    rs = [{"report_month": rm, "period_end": rm, "indicator_group": "g", "indicator": "i", "period_type": pt,
           "source_file": rm, "actual": a, "prev_year_actual": None, "dq_note": None}
          for rm, pt, a in (("2019-08", "month", 58.55), ("2019-08", "cumulative", 245.91),
                            ("2019-09", "month", 58.55), ("2019-09", "cumulative", 268.2))]
    assert len(flag_stale(rs)) == 1 and rs[2]["dq_note"] == "stale_repeat_of:2019-08" and not rs[3]["dq_note"]
    print("selfcheck ok")


if __name__ == "__main__":
    _selfcheck()
    main()
