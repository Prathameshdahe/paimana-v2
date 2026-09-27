"""
Extractor for MoSPI "Review of Infrastructure Sector Performance" monthly
reports, FY 2015-16 .. 2017-18 (Performance Monitoring/2015-16, 2016-17, 2017-18).

Outputs (dataset/clean/_parts/perf_2015_18/):
  perf.csv         Annexure-A: month + cumulative (April..month) rows
  perf_detail.csv  Highlights table and sector-wise "Table - N" detail tables, long form
  manifest.csv     one row per source PDF

All tables in this family are ruled (drawn cell borders), so column boundaries
come from the vertical rules on the page, and rows from word y-positions
(PyMuPDF). Run from repo root:  python pipeline/extract/perf_2015_18.py
(--selfcheck runs only the built-in asserts).

Not extracted: 'Areas of concern' / 'Noteworthy performance' (free-form cells,
restating Annexure-A) and the April 2015 Highlights (no column rules).
"""
import re
import sys
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (PERF_COLS, PERF_DETAIL_COLS, MANIFEST_COLS, DATASET,  # noqa: E402
                    to_num, fiscal_year, rel, write_part, MONTHS)

FAMILY = "perf_2015_18"
FOLDERS = ["2015-16", "2016-17", "2017-18"]

SECTORS = [  # keyword in heading -> normalized sector
    ("power", "Power"), ("coal", "Coal"), ("steel", "Steel"), ("cement", "Cement"),
    ("fertili", "Fertilizers"), ("petroleum", "Petroleum & Natural Gas"),
    ("natural gas", "Petroleum & Natural Gas"), ("crude", "Petroleum & Natural Gas"),
    ("refiner", "Petroleum & Natural Gas"), ("road", "Roads"), ("nhai", "Roads"),
    ("railway", "Railways"), ("shipping", "Shipping & Ports"), ("port", "Shipping & Ports"),
    ("civil aviation", "Civil Aviation"), ("airport", "Civil Aviation"),
    ("telecom", "Telecommunications"),
]

UNITS = [  # regex on a parenthetical -> unit
    (r"^\(bu\)$|billion units?", "BU"),
    (r"million units?", "MU"),
    (r"^\(mt\)$|million tonnes?", "MT"),
    (r"'?\s*000\s*'?\s*tonnes|thousand tonnes", "'000 Tonnes"),
    (r"lakh\s*tonnes?", "Lakh Tonnes"),
    (r"^\(mcm\)$|million cubic", "MCM"),
    (r"^\(kms?\.?\)$", "Kms"),
    (r"metric tonnes|^\(tonnes?\)$", "Tonnes"),
    (r"'?\s*000\s*'?\s*lines", "'000 Lines"),
    (r"'?\s*000\s*'?\s*n(o|umbers)", "'000 Numbers"),
    (r"in numbers|^\(nos?\.?\)$", "Numbers"),
    (r"in lines", "Lines"),
    (r"^\(lakh\)$", "Lakh"),
    (r"percentage|^\(%\)$", "%"),
    (r"rs\.? in crore|crore", "Rs crore"),
]

NUM_RE = re.compile(r"^[-+]?\(?\d[\d,]*\.?\d*\)?%?$|^[-+]?\.\d+%?$")
BLANK_TOK = {"-", "--", "*", "na", "nr", "n.a.", "n.r.", "nil", "..", "#", "@", "$", "**"}
L1_RE = re.compile(r"^(\d{1,2})\s*\.\s*(\S.*)$")                       # "1. Power generation (BU)"
L2_RE = re.compile(r"^(?:(I{1,3}|IV|V|VI)\s*\.|\(([a-h])\))\s*(\S.*)$")  # "I. Main Producer", "(a) NHAI"
ENUM_RE = re.compile(r"^(?:\(?[ivx]{1,4}\)|\(?[a-h]\)|[IVX]{1,4}\s*\.|\d{1,2}\s*\.)\s*")
MONTH_WORD = r"(jan(?:uary)?|feb(?:ruary)?|fev|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"


def clean(s):
    s = (s or "").replace("\xa0", " ").replace("‐", "-").replace("‑", "-") \
        .replace("–", "-").replace("−", "-").replace("’", "'").replace("‘", "'")
    return " ".join(s.split())


def is_blank_tok(t):
    """Printed placeholders for 'no value': NA, NR, -, *, Excel errors like #DIV/0!."""
    t = t.strip()
    return t.lower() in BLANK_TOK or bool(re.fullmatch(r"#(DIV/0!|VALUE!|REF!|N/A|NAME\?|NUM!)", t, re.I))


def is_num_tok(t):
    t = t.strip()
    return bool(NUM_RE.match(t)) or is_blank_tok(t)


def is_colnum_row(toks):
    """'1 2 3 ...' / '(1) (2) ...' column-number rows (typos like '1 3 4 5 6 6' allowed)."""
    t = [x.strip("()") for x in toks]
    return len(t) >= 3 and all(x.isdigit() and int(x) <= 40 for x in t)


def month_from_name(name):
    """'CompleteReviewReportFev2018.pdf' -> '2018-02'."""
    m = re.search(r"Report([A-Za-z]+?)[\s_-]*(\d{4})", name)
    mon = m[1].lower()
    mo = MONTHS.get(mon) or MONTHS[mon[:3]]
    return f"{int(m[2]):04d}-{mo:02d}"


def ym_in_text(t):
    """All 'Month YYYY' occurrences in text -> list of 'YYYY-MM'."""
    out = []
    for m in re.finditer(r"\b" + MONTH_WORD + r"[\s.,'-]*(\d{4})", t, re.I):
        mon = m[1].lower()
        mo = MONTHS.get(mon) or MONTHS[mon[:3]]
        out.append(f"{int(m[2]):04d}-{mo:02d}")
    return out


def sector_of(text):
    t = text.lower()
    for k, v in SECTORS:
        if k in t:
            return v
    return None


def unit_of(*texts):
    for t in texts:
        t = re.sub(r"\(([^()]*)$", r"(\1)", t or "")      # unclosed '(MT' at the end
        for par in reversed(re.findall(r"\([^()]*\)", t)):
            p = par.lower()
            for rx, u in UNITS:
                if re.search(rx, p):
                    return u
    return None


# ---------------------------------------------------------------- page geometry
def page_words(page):
    """Words as dicts {x0,x1,y0,y1,cx,cy,t,bold}, built from characters.

    Some pages print every cell twice on top of itself, each copy missing a
    glyph ('-0 72' over '0.72'). Characters at the same position are merged
    (a visible glyph beats a space) before words are formed, which rebuilds
    '-0.72' and drops the doubled labels."""
    chars = []
    for b in page.get_text("rawdict")["blocks"]:
        for ln in b.get("lines", []):
            if ln.get("dir", (1, 0))[0] < 0.9:        # skip rotated text
                continue
            for s in ln["spans"]:
                bold = "bold" in s["font"].lower() or bool(s["flags"] & 16)
                for c in s["chars"]:
                    x0, y0, x1, y1 = c["bbox"]
                    chars.append(dict(c=clean(c["c"]) or " ", x0=x0, x1=x1, y0=y0, y1=y1, cy=(y0 + y1) / 2,
                                      cx=(x0 + x1) / 2, bold=bold, size=s["size"]))
    kept = {}                                          # y bucket -> chars, x-sorted
    for ch in sorted(chars, key=lambda c: c["x0"]):
        bucket = round(ch["cy"])
        dup = None
        for bk in (bucket - 1, bucket, bucket + 1):
            for k in reversed(kept.get(bk, [])[-6:]):
                if abs(k["x0"] - ch["x0"]) < 0.8 and abs(k["cy"] - ch["cy"]) < 1.5:
                    dup = k
                    break
            if dup:
                break
        if dup is None:
            kept.setdefault(bucket, []).append(ch)
        elif dup["c"] == " " and ch["c"] != " ":
            dup.update(c=ch["c"], x1=ch["x1"])
    words = []
    for ln in group_lines([c for v in kept.values() for c in v]):
        cur = []
        for ch in ln["w"]:
            gap = ch["x0"] - cur[-1]["x1"] if cur else 0
            if ch["c"] == " " or (cur and gap > 0.2 * max(ch["size"], 4)):
                if cur:
                    words.append(cur)
                cur = [] if ch["c"] == " " else [ch]
            else:
                cur.append(ch)
        if cur:
            words.append(cur)
    out = []
    for cs in words:
        x0, x1 = min(c["x0"] for c in cs), max(c["x1"] for c in cs)
        y0, y1 = min(c["y0"] for c in cs), max(c["y1"] for c in cs)
        out.append(dict(x0=x0, x1=x1, y0=y0, y1=y1, cx=(x0 + x1) / 2, cy=(y0 + y1) / 2,
                        t="".join(c["c"] for c in cs), bold=sum(c["bold"] for c in cs) * 2 > len(cs)))
    return out


def group_lines(words, tol=3.0):
    """Cluster words (or chars) into text lines by vertical centre."""
    lines = []
    for w in sorted(words, key=lambda w: w["cy"]):
        if lines and w["cy"] - lines[-1]["cy0"] <= tol:
            lines[-1]["w"].append(w)
        else:
            lines.append({"cy0": w["cy"], "w": [w]})
    for ln in lines:
        ln["w"].sort(key=lambda w: w["x0"])
        ln["cy"] = sum(w["cy"] for w in ln["w"]) / len(ln["w"])
        if all("t" in w for w in ln["w"]):
            ln["text"] = " ".join(w["t"] for w in ln["w"])
    return lines


def fix_wrapped_signs(lines, hsegs=()):
    """A negative number too wide for its cell wraps after its minus sign: '-' alone on
    one text line, the digits right-aligned under it on the next ('-' / '193.93').
    Glue the sign onto the number. A '-' on a line that also holds numbers or
    placeholders, or on a placeholder row above a data row ('ESSAR - -' / 'Tata 143 148'),
    is a 'no value' mark and is left alone; so is a '-' with a rule between it and the number."""
    for ln, nx in zip(lines, lines[1:]):
        dashes = [w for w in ln["w"] if w["t"] == "-"]
        if not dashes or nx["cy"] - ln["cy"] > 14 or \
                any(is_num_tok(w["t"]) for w in ln["w"] if w["t"] != "-"):
            continue
        nums = [w for w in nx["w"] if NUM_RE.match(w["t"])]
        if len(dashes) >= len(nums) and any(not is_num_tok(w["t"]) for w in nx["w"]):
            continue
        for d in dashes:
            below = [w for w in nums if re.fullmatch(r"\d[\d,]*\.?\d*", w["t"]) and abs(w["x1"] - d["x1"]) < 1.5]
            if len(below) != 1 or any(ln["cy"] < y < nx["cy"] and x0 < below[0]["x1"] and x1 > below[0]["x0"]
                                      for y, x0, x1 in hsegs):
                continue
            b = below[0]
            b.update(t="-" + b["t"], x0=min(b["x0"], d["x0"]))
            ln["w"].remove(d)
    for ln in lines:
        ln["text"] = " ".join(w["t"] for w in ln["w"])
    return [ln for ln in lines if ln["w"]]


def text_lines(page, hsegs=()):
    return fix_wrapped_signs(group_lines(page_words(page)), hsegs)


def _merge(segs):
    """Merge collinear, touching segments (pos, a0, a1)."""
    merged = []
    for p, a0, a1 in sorted(segs):
        for m in merged:
            if abs(m[0] - p) < 1.5 and a0 <= m[2] + 2 and a1 >= m[1] - 2:
                m[1], m[2] = min(m[1], a0), max(m[2], a1)
                break
        else:
            merged.append([p, a0, a1])
    return merged


def page_rules(page):
    """Table rules: vertical as [x, y0, y1], horizontal as [y, x0, x1]."""
    v, h = [], []
    for d in page.get_drawings():
        paint = d.get("color") if d.get("type") == "s" else (d.get("fill") or d.get("color"))
        if paint is None or max(paint) >= 0.5:
            continue                                   # grey spreadsheet gridlines, blue page frames
        for it in d["items"]:
            if it[0] == "l":
                a, b = it[1], it[2]
                if abs(a.x - b.x) < 1 and abs(a.y - b.y) > 2:
                    v.append(((a.x + b.x) / 2, min(a.y, b.y), max(a.y, b.y)))
                elif abs(a.y - b.y) < 1 and abs(a.x - b.x) > 2:
                    h.append(((a.y + b.y) / 2, min(a.x, b.x), max(a.x, b.x)))
            elif it[0] == "re":
                r = it[1]
                if r.width < 2.5 and r.height > 2:
                    v.append(((r.x0 + r.x1) / 2, r.y0, r.y1))
                elif r.height < 2.5 and r.width > 2:
                    h.append(((r.y0 + r.y1) / 2, r.x0, r.x1))
                elif d.get("color") is not None and not d.get("fill"):
                    # stroked cell rectangle: its edges are rules
                    v += [(r.x0, r.y0, r.y1), (r.x1, r.y0, r.y1)]
                    h += [(r.y0, r.x0, r.x1), (r.y1, r.x0, r.x1)]
    return _merge(v), _merge(h)


def rules_at(segs, y, pad=1.0):
    """Sorted, de-duplicated x of vertical rules crossing height y."""
    xs = sorted(x for x, y0, y1 in segs if y0 - pad <= y <= y1 + pad)
    out = []
    for x in xs:
        if not out or x - out[-1] > 3:
            out.append(x)
    return out


def strip_marks(s):
    """Drop trailing footnote marks: 'Traffic (MT) **' -> 'Traffic (MT)'."""
    return re.sub(r"(\s*[*#@$^]+)+$", "", clean(s)).strip()


def merge_wrapped_numbers(recs):
    """A number too wide for its cell wraps onto the next text line ('155.6' / '0').
    Detect a line whose few values all continue as 1-3 digit fragments in the same
    columns of the next line and glue them ('155.60'); its label joins the next one."""
    out = []
    i = 0
    while i < len(recs):
        a = recs[i]
        b = recs[i + 1] if i + 1 < len(recs) else None
        if (b and a["cells"] and b["cells"] and len(a["cells"]) < len(b["cells"])
                and set(a["cells"]) <= set(b["cells"]) and b["y"] - a["y"] < 12
                and all(re.fullmatch(r"\d{1,3}%?", b["cells"][k]) and re.search(r"[\d.]$", a["cells"][k])
                        for k in a["cells"])
                and not L1_RE.match(b["label"]) and not L2_RE.match(b["label"])):
            cells = dict(b["cells"])
            for k, v in a["cells"].items():
                cells[k] = v + cells[k]
            out.append(dict(b, label=clean(a["label"] + " " + b["label"]), cells=cells))
            i += 2
            continue
        out.append(a)
        i += 1
    return out


# ---------------------------------------------------------------- Annexure-A
def find_annexure_page(doc):
    for i in range(doc.page_count):
        t = clean(doc[i].get_text())
        if re.search(r"Power\s+generation\s*\(BU\)", t, re.I) and "(6)" in t and "(2)" in t:
            return i
    return None


def parse_annexure(page):
    """Return (rows, info). rows: dicts with group/subgroup/label/cells{colno: text}."""
    segs, hsegs = page_rules(page)
    lines = text_lines(page, hsegs)
    # column-number marker line "(1) (2) ... (n)"
    mk = None
    for ln in lines:
        nums = [w for w in ln["w"] if re.fullmatch(r"\(\d{1,2}\)", w["t"])]
        if len(nums) >= 6:
            mk = ln
            break
    if mk is None:
        raise ValueError("Annexure column-number row not found")
    centers = {int(w["t"][1:-1]): w["cx"] for w in mk["w"] if re.fullmatch(r"\(\d{1,2}\)", w["t"])}
    ncol = max(centers)
    assert sorted(centers) == list(range(1, ncol + 1)), centers
    body = [ln for ln in lines if ln["cy"] > mk["cy"] + 2]
    ybody = body[len(body) // 2]["cy"] if body else mk["cy"] + 50
    # boundary between column k and k+1: a vertical rule between the marker centres
    bounds = []
    for k in range(1, ncol):
        a, b = centers[k], centers[k + 1]
        cand = [x for x, y0, y1 in segs if a < x < b and y1 > mk["cy"] + 20 and y0 < ybody]
        if cand:  # the one closest to the midpoint
            bounds.append(min(cand, key=lambda x: abs(x - (a + b) / 2)))
        else:
            bounds.append((a + b) / 2)
    used_rules = sum(1 for k in range(1, ncol)
                     if any(abs(x - bounds[k - 1]) < 0.01 for x, *_ in segs))

    def col_of(x):
        for k, bx in enumerate(bounds, start=1):
            if x < bx:
                return k
        return ncol

    header_text = " ".join(ln["text"] for ln in lines if ln["cy"] <= mk["cy"])
    col_head = {k: [] for k in range(2, ncol + 1)}          # header words per value column
    for ln in lines:
        if mk["cy"] - 45 < ln["cy"] < mk["cy"] - 2:
            for w in ln["w"]:
                if w["cx"] >= bounds[0]:
                    col_head[col_of(w["cx"])].append(w["t"])
    recs = []
    for ln in body:
        if re.match(r"^(BU|MT)\s*:", ln["text"]) or re.match(r"^\*\s*:", ln["text"]):
            break
        lab = [w for w in ln["w"] if w["cx"] < bounds[0]]
        dat = [w for w in ln["w"] if w["cx"] >= bounds[0]]
        if dat and not all(is_num_tok(w["t"]) for w in dat):
            lab, dat = ln["w"], []           # heading overflowing into the number columns
        cells = {}
        for w in dat:
            k = col_of(w["cx"])
            cells[k] = (cells[k] + " " + w["t"]) if k in cells else w["t"]
        ltxt = strip_marks(" ".join(w["t"] for w in lab))
        if not ltxt and all(is_blank_tok(v) for v in cells.values()):
            continue                          # stray footnote marks ('#') on their own line
        recs.append(dict(label=ltxt, cells=cells, bold=any(w["bold"] for w in lab), y=ln["cy"]))
    recs = merge_wrapped_numbers(recs)
    rows, group, subgroup, pending = [], None, None, []
    for rc in recs:
        ltxt, cells = rc["label"], rc["cells"]
        if not cells:
            m1, m2 = L1_RE.match(ltxt), L2_RE.match(ltxt)
            if m1 and not pending:
                group, subgroup = clean(m1[2]), None
            elif m2 and not pending:
                subgroup = clean(m2[3])
            else:
                pending.append(ltxt)
            continue
        label = clean(" ".join(pending + [ltxt]))
        pending, restored = [], False
        if re.match(r"^\(in '000 Numbers\)$", label) and group and "telecom" in group.lower():
            # Nov 2017: the first label line of the bold total row is clipped in the source
            label, restored = "Total connections (ii+iii) " + label, True
        if not label:
            raise ValueError(f"values without a row label at y={rc['y']:.0f}: {cells}")
        m1 = L1_RE.match(label)
        if m1 and not re.match(r"^\d+\.\d", label):   # single-row sector printed on its heading line
            group, subgroup, label = clean(m1[2]), None, clean(m1[2])
        elif L2_RE.match(label):                       # level-2 row with values ends the sub-group
            subgroup = None
        rows.append(dict(group=group, subgroup=subgroup, label=label, cells=cells,
                         bold=rc["bold"], y=rc["y"], restored=restored))
    if pending:
        raise ValueError(f"dangling label text at end of Annexure: {pending}")
    return rows, dict(ncol=ncol, header=header_text, rules_used=used_rules, bounds=bounds,
                      col_head={k: " ".join(v) for k, v in col_head.items()})


def annexure_to_perf(rows, ncol, ym, src, pageno):
    fy = fiscal_year(ym)
    cum_start = f"{fy[:4]}-04"
    out = []
    for r in rows:
        group = r["group"] or ""
        label = ENUM_RE.sub("", r["label"]).strip()
        sub = ENUM_RE.sub("", r["subgroup"]).strip() if r["subgroup"] else None
        indicator = f"{sub}: {label}" if sub else label
        sector = sector_of(group) or sector_of(label)
        unit = unit_of(r["label"], r["subgroup"], group)
        is_total = bool(re.match(r"^(total|all india)", label, re.I))
        c = r["cells"]
        spans = [("month", 2, ym)] + ([("cumulative", 7, cum_start)] if ncol >= 11 else [])
        for ptype, k0, pstart in spans:
            vals = [c.get(k) for k in range(k0, k0 + 5)]
            if all(v is None for v in vals):
                continue
            t, a, p, pvt, pvp = map(to_num, vals)
            flags = ["label_restored"] if r.get("restored") else []
            flags += [f"printed_pct_mismatch:{name}" for base, pv, name in
                      ((t, pvt, "pct_var_target"), (p, pvp, "pct_var_prev_year")) if pct_differs(a, base, pv)]
            out.append(dict(
                report_month=ym, fiscal_year=fy, source_file=src, page=pageno,
                sector=sector, indicator_group=group, indicator=indicator, unit=unit,
                is_total=is_total, period_type=ptype, period_start=pstart, period_end=ym,
                annual_target=None, target=t, actual=a, prev_year_actual=p, pct_var_target=pvt,
                pct_var_prev_year=pvp, pct_achievement=None, dq_note=";".join(flags) or None))
    return out


def pct_differs(a, b, printed):
    """True when a printed % variation disagrees with (a / b - 1) * 100 beyond rounding."""
    if a is None or b in (None, 0) or printed is None:
        return False
    calc = (a / b - 1) * 100
    return abs(calc - printed) > 0.06 + 0.002 * abs(calc)


def add_flag(row, flag):
    have = (row.get("dq_note") or "").split(";")
    if flag not in have:
        row["dq_note"] = ";".join([f for f in have if f] + [flag])


# ---------------------------------------------------------------- sector detail tables
TITLE_RE = re.compile(r"^Table\s*[-–]?\s*\d+\s*[:.]?\s*\S", re.I)
UNITLINE_RE = re.compile(r"^\((?:in\s|rs\.?\s|percentage|%)[^)]*\)$", re.I)
FOOTNOTE_RE = re.compile(r"^[A-Za-z$*#@^]{1,4}\s*:\s")
SLNO_RE = re.compile(r"^s\.?[li1]?\.?no\.?$", re.I)


def period_of(text, ym):
    """Period named in a header/title: cumulative 'April-Dec 2017', FY '2017-2018',
    or a single month. Returns (start, end) or None."""
    t = re.sub(r"\b(20)\s+(\d)\s*(\d)\b", r"\1\2\3", clean(text).lower())   # 'April,20 16-' wrapped in the cell
    m = re.search(r"apr(?:il)?\s*[,']?\s*(\d{4})?\s*[-]\s*" + MONTH_WORD + r"[\s.,'-]*(\d{4})", t)
    if m:
        end = ym_in_text(t[m.start(2):])[0]
        return f"{fiscal_year(end)[:4]}-04", end
    m = re.search(r"\b(20\d\d)\s*-\s*(20\d\d|\d\d)\b", t)
    if m and (int(m[2][-2:]) - int(m[1][-2:])) % 100 == 1:
        return f"{m[1]}-04", f"{int(m[1]) + 1}-03"
    yms = ym_in_text(t)
    if yms:
        return yms[-1], yms[-1]
    return None


def shift_year(p, n):
    return tuple(f"{int(x[:4]) + n}-{x[5:]}" for x in p)


def title_lines(lines):
    return [i for i, ln in enumerate(lines)
            if TITLE_RE.match(ln["text"]) or re.fullmatch(r"HIGHLIGHTS", ln["text"].strip())]


def grid_in(vsegs, hsegs, y_from, y_to):
    """The ruled grid between two heights: extent, vertical and horizontal rules."""
    vs = [s for s in vsegs if s[1] > y_from and s[2] < y_to + 3 and s[2] - s[1] > 5]
    if len(vs) < 3:
        return None
    top, bot = min(s[1] for s in vs), max(s[2] for s in vs)
    left, right = min(s[0] for s in vs), max(s[0] for s in vs)
    return dict(top=top, bot=bot, left=left, right=right, vs=vs,
                hs=[s for s in hsegs if top - 2 <= s[0] <= bot + 2 and s[2] > left - 2 and s[1] < right + 2])


def find_tables(lines, vsegs, hsegs, page_h):
    """Ruled tables under a 'Table - N:' title (or a HIGHLIGHTS heading)."""
    heads = title_lines(lines)
    out = []
    for n, i in enumerate(heads):
        y_to = lines[heads[n + 1]]["cy"] - 3 if n + 1 < len(heads) else page_h
        g = grid_in(vsegs, hsegs, lines[i]["cy"], y_to)
        if g is None:
            out.append(dict(title=lines[i]["text"], error="no ruled grid under title"))
            continue
        title, unit = [lines[i]["text"]], None
        for ln in lines[i + 1:]:
            if ln["cy"] >= g["top"] - 1:
                break
            if UNITLINE_RE.match(ln["text"].strip()):
                unit = ln["text"].strip()
            elif not re.fullmatch(r"[*\s]+", ln["text"]):
                title.append(ln["text"])
        out.append(dict(g, title=clean(" ".join(title)), unit=unit))
    return out


def _is_data_line(ln):
    """A text line with at least two numbers that are not years or a column-number row."""
    if is_colnum_row([w["t"] for w in ln["w"]]):
        return False
    toks = [w["t"] for w in ln["w"] if NUM_RE.match(w["t"])]
    if sum(1 for t in toks if not re.fullmatch(r"(19|20)\d\d", t)) >= 2:
        return True
    # a row of placeholders only ('CCI NR * * - -'), but not a header line with footnote marks
    marks = [w["t"] for w in ln["w"] if is_blank_tok(w["t"]) and w["t"] not in ("-", "--")]
    return len(marks) >= 2 and not re.search(r"target|actual|achiev|variation|provisional|annual|\b"
                                             + MONTH_WORD, ln["text"], re.I)


def _is_num_cell(v):
    return all(is_num_tok(t) for t in v.split())


def _covered(iv, lo, hi):
    """Length of [lo, hi] covered by the union of intervals."""
    tot, cur = 0.0, lo
    for a, b in sorted(iv):
        a, b = max(a, cur), min(b, hi)
        if b > a:
            tot, cur = tot + b - a, b
    return tot


def parse_grid(tb, lines, cont=None):
    """Parse one ruled table -> (rows, {col: header label}, error).
    cont: the table this grid continues from the previous page (a grid printed above the
    page's first title, with no header of its own): its column geometry supplies the
    header labels, and its last row group carries on."""
    top, bot, left, right = tb["top"], tb["bot"], tb["left"], tb["right"]
    width = right - left
    full = []                                         # full-width rules, possibly drawn in pieces
    for y, x0, x1 in sorted(tb["hs"]):
        if not top + 3 < y < bot - 3:
            continue
        if full and y - full[-1][0] <= 2.5:
            full[-1][1].append((x0, x1))
        else:
            full.append([y, [(x0, x1)]])
    full = [y for y, iv in full if _covered(iv, left, right) >= 0.9 * width]
    tl = [ln for ln in lines if top < ln["cy"] < bot]
    first = next((ln["cy"] for ln in tl if _is_data_line(ln)), None)
    sep = max((y for y in full if first is not None and y < first and any(ln["cy"] < y for ln in tl)),
              default=None)
    if cont:
        sep = top if first is not None else None      # no header: every line is body
    if sep is None:
        return None, None, "no header separator rule"
    body = [ln for ln in tl if ln["cy"] > sep]
    head = [ln for ln in tl if ln["cy"] < sep]
    if not body:
        return None, None, "empty body"
    b0, b1 = body[0]["cy"], body[-1]["cy"]
    if b1 - b0 < 1:                                   # one-line body (a lone 'Total' row carried over)
        b0, b1 = b0 - 2, b1 + 2
    hgt = max(b1 - b0, 1)
    cover = []                                        # [x, covered length within the body]
    for x, y0, y1 in sorted(tb["vs"]):
        ov = max(0.0, min(y1, b1) - max(y0, b0))
        if cover and x - cover[-1][0] <= 3:
            cover[-1][1] += ov
        else:
            cover.append([x, ov])
    bnd = [x for x, ov in cover if ov >= 0.4 * hgt]
    if len(bnd) < 3:
        return None, None, "fewer than 2 body columns"
    cols = list(zip(bnd[:-1], bnd[1:]))
    ncols = len(cols)

    def col_of(x):
        for k, (a, b) in enumerate(cols):
            if a - 1 <= x < b + 1:
                return k
        return None

    # header label per body column (a merged header cell applies to every column it spans)
    hl = [[] for _ in cols]
    for ln in head:
        if is_colnum_row([w["t"] for w in ln["w"]]):
            continue                                  # column-number row '1 2 3 ...'
        cells = rules_at(tb["vs"], ln["cy"])
        for w in ln["w"]:
            lo = max([x for x in cells if x <= w["cx"]], default=left)
            hi = min([x for x in cells if x > w["cx"]], default=right)
            for k, (a, b) in enumerate(cols):
                if lo - 1 <= (a + b) / 2 <= hi + 1:
                    hl[k].append(w["t"])
    labels = [strip_marks(" ".join(h)) for h in hl]
    if cont:
        labels = []
        for a, b in cols:
            same = [lab for (a2, b2), lab in zip(cont["cols"], cont["all_labels"]) if abs(a - a2) <= 3 and abs(b - b2) <= 3]
            if not same:
                return None, None, "continuation columns do not match the previous table"
            labels.append(same[0])
    tb["cols"], tb["all_labels"] = cols, labels
    recs = []
    for ln in body:
        cells = {}
        for w in ln["w"]:
            k = col_of(w["cx"])
            if k is None:
                continue
            cells[k] = (cells[k] + " " + w["t"]) if k in cells else w["t"]
        if cells and not all(is_blank_tok(v) for v in cells.values()):   # stray '*' / '#' lines
            txt_w = [w for w in ln["w"] if not is_num_tok(w["t"])] or ln["w"]   # bold of the label text
            recs.append(dict(cells=cells, y=ln["cy"], bold=sum(w["bold"] for w in txt_w) * 2 > len(txt_w)))
    # value columns: mostly numeric cells; skip a leading 'Sl. No.' column
    numeric = []
    for k in range(ncols):
        vals = [r["cells"][k] for r in recs if k in r["cells"]]
        numeric.append(bool(vals) and sum(map(_is_num_cell, vals)) >= 0.6 * len(vals))
    skip = {k for k in range(ncols) if SLNO_RE.match(re.sub(r"\s", "", labels[k] or ""))
            or not any(k in r["cells"] for r in recs)}           # Sl. No. and empty spacer columns
    valcols = [k for k in range(ncols) if numeric[k] and k not in skip]
    if not valcols:
        return None, None, "no numeric columns"
    labcols = [k for k in range(valcols[0]) if k not in skip]
    if not labcols or any(not numeric[k] for k in range(valcols[0], ncols) if k not in skip):
        return None, None, "label/value columns interleaved: " + str([(labels[k], numeric[k]) for k in range(ncols)])
    for r in recs:
        r["slno"] = any(r["cells"].get(k) for k in skip)       # a new numbered item (Highlights)
        r["label"] = [strip_marks(r["cells"].get(k, "")) for k in labcols]
        present = rules_at(tb["vs"], r["y"])
        for j in range(len(labcols) - 1, 0, -1):
            if not any(abs(x - cols[labcols[j]][0]) < 2 for x in present):
                # label cell merged across label columns: 'Total (International+Domestic)'
                r["label"][j - 1] = clean(r["label"][j - 1] + " " + r["label"][j])
                r["label"][j] = ""
        r["vals"] = {k: r["cells"][k] for k in valcols if k in r["cells"]}
        bad = {k: v for k, v in r["vals"].items() if not _is_num_cell(v)}
        if bad:
            if len(bad) == len(r["vals"]) and not any(r["label"][1:]):
                # heading text overflowing into the value columns
                r["label"][0] = clean(" ".join([r["label"][0]] + [r["vals"][k] for k in sorted(r["vals"])]))
                r["vals"] = {}
            else:
                return None, None, f"text in value columns: {bad}"
        split = {k: v for k, v in r["vals"].items() if len(v.split()) > 1}
        if split:
            # e.g. '34118 90': a decimal point missing from the text layer -> ambiguous, drop cells
            tb.setdefault("bad_cells", []).append(split)
            r["vals"] = {k: v for k, v in r["vals"].items() if k not in split}
            r["void"] = True
        if (r["vals"] and any(r["label"]) and all(is_blank_tok(v) for v in r["vals"].values())
                and len(r["vals"]) < 0.3 * len(valcols)):
            r["vals"] = {}      # a lone '-' on the first line of a wrapped label: a label line
    # glue numbers wrapped onto the next text line
    tmp = merge_wrapped_numbers([dict(label=" ".join(x for x in r["label"] if x), cells=r["vals"],
                                      y=r["y"], r=r) for r in recs])
    if len(tmp) != len(recs):
        recs = [dict(t["r"], vals=t["cells"],
                     label=t["r"]["label"] if t["label"] == " ".join(x for x in t["r"]["label"] if x)
                     else [t["label"]] + [""] * (len(labcols) - 1)) for t in tmp]
    # rows: bottom-aligned wrapped labels, sub-headings, forward-filled first label column
    rows, pending, group, ff, heads, prev_group, dropped, ff_line = [], [], None, None, [], None, [], None
    if cont and cont["rows"]:
        group = prev_group = cont["rows"][-1]["row_group"]
    orphans = []
    is_val = [bool(r["vals"]) or bool(r.get("void")) for r in recs]
    for i, r in enumerate(recs):
        lab = r["label"]
        if not is_val[i] and re.fullmatch(r"[:\-\s]+", " ".join(lab)):
            continue                                   # ':-' left over from a wrapped heading
        if r.get("slno"):
            group = prev_group = None                  # numbered top-level item
            if pending:
                orphans.append(" ".join(pending))      # a row printed without any values
                pending = []
        if not is_val[i]:
            txt = clean(" ".join(x for x in lab if x))
            if not txt:
                continue
            if len(lab) > 1 and lab[0] and not any(lab[1:]):
                ff_line = clean((ff_line or "") + " " + lab[0])
                ff = ff_line
                continue
            if (txt.startswith("(") and not re.match(r"^\([a-z]\)", txt) and not pending and not heads
                    and i + 1 < len(recs) and is_val[i + 1] and any(recs[i + 1]["label"])):
                # top-aligned cell: 'V.O.Chidambaranar' (values) / '(Tuticorin)' / next row;
                # on a continuation page the cell's first line is on the previous page
                last = rows[-1] if rows and i > 0 and is_val[i - 1] else \
                    cont["rows"][-1] if cont and cont["rows"] and not rows and i == 0 else None
                if last:
                    last["row_label"] = clean(last["row_label"] + " " + txt)
                    continue
            heading = r["bold"] or re.match(r"^[A-Z]\s*\.\s", txt) or re.search(r":-?$", txt)
            if heading and pending:
                orphans.append(" ".join(pending))      # a row printed without any values
                pending = []
            if heading:
                if not heads:
                    prev_group = group
                heads.append(txt)
                group = " ".join(heads)
            else:
                pending.append(txt)
            continue
        first = next((x for x in lab if x), "")
        pending = [t for t in pending if not FOOTNOTE_RE.match(t)]
        if FOOTNOTE_RE.match(first) and len(r["vals"]) <= 1:
            continue                     # footnote 'NR: Not reported.' + page number inside the grid
        if not first and not pending and len(r["vals"]) <= 1 and i > 0 and not is_val[i - 1] \
                and FOOTNOTE_RE.match(clean(" ".join(recs[i - 1]["label"]))):
            continue                     # page number under a footnote line
        if heads and not pending and (not first or (len(lab) == 1 and (first.startswith("(") or (
                r["bold"] and not re.match(r"^[A-Z]\s*\.\s", heads[-1]) and not re.search(r":-?$", heads[-1]))))):
            # bold wrapped label sitting above its values: 'Others' / '(TISCO,IISCO,DVC)';
            # a bold item row is a top-level item
            pending, group = heads, (None if r["bold"] else prev_group)
        heads = []
        if not pending and not any(lab) and len(r["vals"]) < 0.3 * len(valcols):
            dropped.append(dict(r["vals"]))            # stray spreadsheet cell under a row
            continue
        if len(lab) > 1:
            if lab[0] and not any(lab[1:]) and ff_line:
                # label cell spanning the label columns and wrapped: 'Total' / 'Domestic)'
                ff = clean(ff_line + " " + lab[0])
            elif lab[0]:
                ff = lab[0]
            main = clean(" ".join(pending + [x for x in lab[1:] if x]))
            label, rgroup = (main, ff) if main else (ff, group)
        else:
            label, rgroup = clean(" ".join(pending + [lab[0]])), group
            if re.match(r"^([A-Z]\s*\.\s|All India)", label):
                rgroup = group = None        # 'C. DGH (JVC/Private)', 'All India Total': top level again
        pending, ff_line = [], None
        label = re.sub(r"^(?:[gjpqy] ){2,}|^\([A-Za-z]?\s*\)\s+", "", label)   # clipped glyph debris
        if not label:
            return None, None, f"values without a row label: {r['vals']}"
        rows.append(dict(row_group=rgroup, row_label=label, vals=r["vals"], y=r["y"]))
    pending = [t for t in pending if not re.search(r"\S\s*:\s", t)]   # footnotes inside the grid
    if pending:
        orphans.append(" ".join(pending))
    # a repeated (group, label) means a group heading is missing in the source (Telecom Table 60,
    # May 2016): the repeated block cannot be attributed, so it is dropped
    seen, keep = set(), []
    for rw in rows:
        key = (rw["row_group"], rw["row_label"])
        if key in seen:
            tb.setdefault("dup_rows", []).append(rw["row_label"])
            continue
        seen.add(key)
        keep.append(rw)
    rows = keep
    tb["dropped"], tb["orphans"] = dropped, orphans
    tb["label_header"] = " ".join(labels[k] for k in labcols)
    return rows, {k: labels[k] for k in valcols}, None


def months_between(a, b):
    return (int(b[:4]) - int(a[:4])) * 12 + int(b[5:7]) - int(a[5:7])


def col_period(label, table_period, ym, cum_table=False):
    """(period_start, period_end) for one value column.
    cum_table: the title names only an April-to-month period and the table has an
    annual-target column, so every column is cumulative even where its header names a
    single month ('July 2015 Target' in the Jul 2015 April-July freight table)."""
    lab = label.lower()
    per = period_of(label, ym)
    if per is None:
        return table_period
    if "variation" in lab and months_between(per[1], table_period[1]) >= 9:
        per = shift_year(per, 1)        # '% variation over (Actual) <last year>' measures this year
    if cum_table and per[0] == per[1] and not re.search(r"annua", lab):
        per = (f"{fiscal_year(per[1])[:4]}-04", per[1])
    return per


def col_role(label):
    """target | actual | prev | var_target | var_prev | None, for consistency checks."""
    lab = label.lower()
    if "variation" in lab:
        tail = lab.split("variation", 1)[1]
        return "var_target" if "target" in tail else "var_prev" if "actual" in tail else None
    if "annual" in lab or (re.search(r"\b20\d\d\s*-\s*(?:20)?\d\d\b", lab)
                           and not re.search(r"\b" + MONTH_WORD, lab)):
        return None                     # annual target ('Target 2015-2016')
    if "target" in lab:
        return "target"
    if "achievement" in lab:
        return "actual"
    if "actual" in lab:
        return "prev"
    return None


def pct_check(rows, labels):
    """Printed % variation vs computed from the same row.
    Returns (cells checked, cells differing, rows checked, rows where every check differs);
    a row that passes at least one check is aligned, the other difference is in the source."""
    roles = {}
    for k, lab in labels.items():
        r = col_role(lab)
        if r and r not in roles:
            roles[r] = k
    checked = bad = rows_chk = rows_bad = 0
    for row in rows:
        v = {r: to_num(row["vals"].get(k)) for r, k in roles.items()}
        res = []
        for base, var in (("target", "var_target"), ("prev", "var_prev")):
            a, b, pv = v.get("actual"), v.get(base), v.get(var)
            if a is None or b in (None, 0) or pv is None:
                continue
            res.append(not pct_differs(a, b, pv))
            if not res[-1]:
                row.setdefault("pct_bad", set()).add(roles[var])
        checked += len(res)
        bad += res.count(False)
        if res:
            rows_chk += 1
            rows_bad += not any(res)
    return checked, bad, rows_chk, rows_bad


def detail_rows(tb, rows, labels, ym, src, pageno, sector_ctx):
    title = tb["title"]
    is_high = title.upper().startswith("HIGHLIGHTS")
    tper = period_of(re.sub(r"^HIGHLIGHTS", "", title), ym) or (ym, ym)
    tunit = unit_of(tb.get("unit"), tb.get("label_header"))
    cum_table = (not is_high and tper[0] != tper[1] and not re.search(r"\b(and|&)\b", title, re.I)
                 and any("annua" in lab.lower() for lab in labels.values()))
    out = []
    for r in rows:
        rgroup, rlabel = r["row_group"], r["row_label"]
        if is_high:
            sector = sector_of(rgroup or "") or sector_of(rlabel)
        else:
            sector = sector_ctx or sector_of(title)
        runit = unit_of(rlabel, rgroup)
        for k, text in sorted(r["vals"].items()):
            val = to_num(text)
            if val is None:
                continue                  # NA / NR / - / * : not printed as a number
            cl = labels[k]
            ps, pe = col_period(cl, tper, ym, cum_table)
            low = cl.lower()
            if re.search(r"variation|growth|%|utili[sz]ation|\bplf\b", low):
                unit = "%"
            else:
                unit = runit or tunit
            out.append(dict(report_month=ym, fiscal_year=fiscal_year(ym), source_file=src, page=pageno,
                            sector=sector, table_title=title, row_group=rgroup, row_label=rlabel,
                            column_label=cl, period_start=ps, period_end=pe, value=val,
                            value_text=text, unit=unit,
                            dq_note="printed_pct_mismatch" if k in r.get("pct_bad", ()) else None))
    return out


# ---------------------------------------------------------------- driver
STALE_RE = re.compile(r"(?:M/o|Ministry\s+of)\s+([^.*]{3,80}?)\s+ha(?:ve|s)\s+not\s+provided\s+the\s+updated\s+data"
                      r"[^.]*\.\s*Therefore,?\s+the\s+data\s+for\s+the\s+month\s+of\s+(\w+[\s,]*\d{4})\s+has\s+been\s+used",
                      re.I)


def stale_month_sectors(doc):
    """{(sector, 'YYYY-MM' of the data actually used)} from 'data for the month of X has been used' footnotes."""
    out = set()
    for pg in doc:
        for m in STALE_RE.finditer(clean(pg.get_text())):
            if sector_of(m[1]) and ym_in_text(m[2]):
                out.add((sector_of(m[1]), ym_in_text(m[2])[0]))
    return out


def report_files():
    base = DATASET / "Performance Monitoring"
    return sorted(p for fy in FOLDERS for p in (base / fy).glob("*.pdf"))


def process_file(path):
    src = rel(path)
    ym = month_from_name(path.name)
    doc = fitz.open(path)
    notes, perf, detail = [], [], []
    status = "ok"
    # period stated inside the report (cover / summary title)
    stated = None
    for i in range(min(3, doc.page_count)):
        t = clean(doc[i].get_text())
        m = re.search(r"INFRASTRUCTURE SECTORS? PERFORMANCE\s*\(([^)]*)\)", t, re.I) or \
            re.search(r"PERFORMANCE OF INFRASTRUCTURE SECTORS\s*\(([^)]*)\)", t, re.I)
        if m and ym_in_text(m[1]):
            stated = ym_in_text(m[1])[-1]
            break
    if stated is None:
        notes.append("report period not found on cover/summary page")
    elif stated != ym:
        notes.append(f"cover/summary says {stated}, filename says {ym}")
    # Annexure-A
    ai = find_annexure_page(doc)
    variant = "failed"
    if ai is None:
        notes.append("Annexure-A page not found")
        status = "partial"
    else:
        rows, info = parse_annexure(doc[ai])
        at = re.search(r"Performance\s+during\s+(.{0,70}?)(?:\*|\(Figures|$)", info["header"])
        atp = period_of(at[1], ym) if at else None
        if not at or ym_in_text(at[1])[:1] != [ym] and (atp is None or atp[1] != ym):
            notes.append(f"Annexure-A title period '{at[1].strip() if at else '?'}' does not match {ym} "
                         f"(column headers used)")
        hdr_yms = set(ym_in_text(info["header"]))
        if ym not in hdr_yms:
            notes.append(f"Annexure-A column headers do not name {ym}")
            status = "partial"
        want = ["target", "actual", "actual", "target", "actual"] * (2 if info["ncol"] >= 11 else 1)
        # % variation columns sometimes name only the period ('April 2015- Jan. 2016')
        wrong = {k: info["col_head"][k] for k, role in zip(range(2, info["ncol"] + 1), want)
                 if role not in info["col_head"][k].lower()
                 and not (k in (5, 6, 10, 11) and re.search(r"\b(19|20)\d\d\b", info["col_head"][k]))}
        if wrong:
            notes.append(f"Annexure-A column headers unexpected: {wrong}")
            status = "partial"
        odd = [(r["label"], v) for r in rows for v in r["cells"].values() if not is_num_tok(v)]
        if odd:     # e.g. '34118 90' (decimal point missing): left blank by to_num
            notes.append(f"Annexure-A unreadable cells left blank: {odd}")
            status = "partial"
        perf = annexure_to_perf(rows, info["ncol"], ym, src, ai + 1)
        variant = f"annexA-{info['ncol']}col"
        if info["rules_used"] < info["ncol"] - 1:
            notes.append(f"Annexure-A: {info['ncol'] - 1 - info['rules_used']} column boundaries guessed")
    # sector detail tables + highlights
    sector_ctx, skipped, nt, parsed, last = None, [], 0, [], None

    def accept(tb, rows, labels, where):
        """Table-level checks; notes; False if the table is skipped."""
        nonlocal status
        chk, bad, rchk, rbad = pct_check(rows, labels)
        if rchk and rbad > max(1, 0.25 * rchk):
            skipped.append(f"{where}: {rbad}/{rchk} rows fail every % variation check (misaligned?)")
            return False
        if bad:
            notes.append(f"{where}: {bad}/{chk} printed % variations differ from computed "
                         f"(kept as printed, dq_note printed_pct_mismatch)")
        if tb.get("dropped"):
            notes.append(f"{where}: dropped stray unlabelled cells {tb['dropped']}")
        if tb.get("dup_rows"):
            notes.append(f"{where}: dropped rows repeating an earlier "
                         f"(group, label) - group heading missing in source: {tb['dup_rows']}")
            status = "partial"
        if tb.get("orphans"):
            notes.append(f"{where}: label lines without values {tb['orphans']}")
        if tb.get("bad_cells"):
            notes.append(f"{where}: dropped ambiguous cells (decimal point "
                         f"missing in text layer) {tb['bad_cells']}")
            status = "partial"
        return True

    for i in range(doc.page_count):
        if i == ai:
            last = None
            continue
        page = doc[i]
        v, h = page_rules(page)
        lines = text_lines(page, h)
        heads = title_lines(lines)
        # rows of the previous page's last table, printed above this page's first title
        y_title = lines[heads[0]]["cy"] - 3 if heads else page.rect.height
        g = grid_in(v, h, 0, y_title)
        if g and any(re.match(r"(areas of concern|noteworthy)", ln["text"], re.I) for ln in lines if ln["cy"] < g["top"]):
            g = last = None             # its own (not extracted) table, not a continuation
        if g and not last and any(_is_data_line(ln) for ln in lines if g["top"] < ln["cy"] < g["bot"]):
            # chart pages (axis labels inside drawn frames); logged for review, nothing to attach to
            print(f"  {src} p{i + 1}: ruled lines with numbers above the first title, no table on the previous page")
        elif g and any(_is_data_line(ln) for ln in lines if g["top"] < ln["cy"] < g["bot"]):
            where = f"p{i + 1} continuation of '{last['tb']['title'][:50]}'"
            rows, labels, err = parse_grid(g, lines, cont=dict(last["tb"], rows=last["rows"]))
            if err:
                skipped.append(f"{where}: {err[:90]}")
            elif accept(g, rows, labels, where):
                notes.append(f"{where}: {len(rows)} rows parsed")
                g["title"], g["unit"], g["label_header"] = last["tb"]["title"], last["tb"].get("unit"), \
                    last["tb"].get("label_header")
                last = dict(last, tb=g, rows=rows, labels=labels, page=i + 1)
                parsed.append(last)
        elif not heads:
            last = None
        for ln in lines:
            m = re.match(r"^\d{1,2}\s*\.\s*([A-Z][A-Z &]+)$", ln["text"].strip())
            if m and sector_of(m[1]) and ln["text"].strip().upper() == ln["text"].strip():
                sector_ctx = sector_of(m[1])
                break
        for tb in find_tables(lines, v, h, page.rect.height):
            nt += 1
            last = None
            where = f"p{i + 1} '{tb['title'][:50]}'"
            if "error" in tb:
                skipped.append(f"{where}: {tb['error']}")
                continue
            rows, labels, err = parse_grid(tb, lines)
            if err:
                skipped.append(f"{where}: {err[:90]}")
                continue
            if accept(tb, rows, labels, where):
                last = dict(tb=tb, rows=rows, labels=labels, page=i + 1, sector=sector_ctx)
                parsed.append(last)
    for e in parsed:
        detail += detail_rows(e["tb"], e["rows"], e["labels"], ym, src, e["page"], e["sector"])
    # footnote: a ministry sent no data for the report month, so last month's figures are
    # reprinted as this month's (Apr 2016 Roads). Values kept as printed, flagged.
    for sec, used in sorted(stale_month_sectors(doc)):
        flag = f"source_says_previous_month_data:{used}"
        hit = [r for r in perf + detail if r["sector"] == sec and r["period_end"] == ym]
        for r in hit:
            add_flag(r, flag)
        notes.append(f"{sec}: source footnote says {used} data reprinted as {ym}; {len(hit)} rows flagged ({flag})")
    if skipped:
        notes.append(f"skipped {len(skipped)}/{nt} detail tables: " + "; ".join(skipped))
        status = "partial"
    notes.append("Areas of concern / Noteworthy performance tables not extracted "
                 "(derived from Annexure-A, free-form cells)")
    man = dict(source_file=src, report_type="performance_review", report_period=ym, pages=doc.page_count,
               parser_variant=f"{variant}+ruled-tables", rows_perf=len(perf), rows_perf_detail=len(detail),
               status=status if perf else "failed", notes=" | ".join(notes))
    return perf, detail, man


def perf_sum_checks(perf):
    """Component rows vs printed Total rows in Annexure-A. Returns list of messages."""
    import pandas as pd
    df = pd.DataFrame(perf)
    msgs = []
    for (src, pt, grp), g in df.groupby(["source_file", "period_type", "indicator_group"], sort=False):
        g = g.reset_index(drop=True)
        start = 0
        for i, r in g.iterrows():
            if not r["is_total"]:
                continue
            pre = r["indicator"].split(": ")[0] if ": " in r["indicator"] else None
            comp = g.iloc[start:i]
            comp = comp[(comp["unit"] == r["unit"]) & ~comp["indicator"].str.contains("Switching")]
            if pre:
                comp = comp[comp["indicator"].str.startswith(pre + ": ") & ~comp["is_total"]]
            else:   # 'Total (I + II)': sub-totals plus un-prefixed rows since the last total
                comp = comp[comp["is_total"] | ~comp["indicator"].str.contains(": ")]
                if comp["is_total"].any():
                    comp = comp[comp["is_total"] | (comp.index > comp[comp["is_total"]].index.max())]
            start = i + 1
            if len(comp) < 2:
                continue
            for col in ("actual", "prev_year_actual"):
                if comp[col].isna().any() or pd.isna(r[col]):
                    continue
                s = comp[col].sum()
                if abs(s - r[col]) > 0.02 + 0.002 * abs(r[col]):
                    msgs.append(f"{src} {pt} {grp} '{r['indicator']}' {col}: printed {r[col]} vs sum {s:.3f}")
    return msgs


def main():
    files = report_files()
    all_perf, all_detail, manifest, failed = [], [], [], []
    for path in files:
        try:
            perf, detail, man = process_file(path)
        except Exception as e:  # keep going; the file is reported as failed
            failed.append((rel(path), repr(e)))
            manifest.append(dict(source_file=rel(path), report_type="performance_review",
                                 report_period=month_from_name(path.name), status="failed",
                                 notes=f"exception: {e!r}"))
            continue
        all_perf += perf
        all_detail += detail
        manifest.append(man)
        print(f"{man['source_file']}: perf={man['rows_perf']} detail={man['rows_perf_detail']} {man['status']}")
    for m in perf_sum_checks(all_perf):
        print("SUM CHECK:", m)
    write_part(all_perf, FAMILY, "perf", PERF_COLS)
    write_part(all_detail, FAMILY, "perf_detail", PERF_DETAIL_COLS)
    write_part(manifest, FAMILY, "manifest", MANIFEST_COLS)
    print(f"files={len(files)} perf={len(all_perf)} perf_detail={len(all_detail)} failed={failed}")


def selfcheck():
    assert month_from_name("CompleteReviewReportFev2018.pdf") == "2018-02"
    assert month_from_name("CompleteReviewReportDec2017.pdf") == "2017-12"
    assert month_from_name("CompleteReviewReportSeptember2015.pdf") == "2015-09"
    assert period_of("April,2017- January 2018 Target", "2018-01") == ("2017-04", "2018-01")
    assert period_of("Annual Target 2017-2018", "2018-01") == ("2017-04", "2018-03")
    assert period_of("April 2014 Actual", "2015-04") == ("2014-04", "2014-04")
    assert col_period("% Variation Over Actual April- Oct. 2014", ("2015-04", "2015-10"), "2015-10") \
        == ("2015-04", "2015-10")
    assert col_role("% Variation Over Target December 2017") == "var_target"
    assert col_role("December 2017 Achievement (Provisional)") == "actual"
    assert unit_of("Cargo handled at major ports (MT") == "MT"
    assert unit_of("Net Addition in Switching Capacity (Fixed+WLL+GSM) ('000 Lines)") == "'000 Lines"
    assert strip_marks("Revenue earning goods Traffic (MT) **") == "Revenue earning goods Traffic (MT)"
    assert is_colnum_row(["1", "3", "4", "5", "6", "6"]) and not is_colnum_row(["1", "2.5", "3"])
    # a % value too wide for its cell wraps: '155.6' then '0' on the next line
    recs = [dict(label="Strengthening of existing weak", cells={5: "155.6"}, y=513.0),
            dict(label="pavement (Kms.)", cells={2: "42.00", 3: "107.35", 5: "0", 6: "75.95"}, y=521.0),
            dict(label="Total of (b)", cells={2: "92.25", 5: "62.47"}, y=530.0)]
    out = merge_wrapped_numbers(recs)
    assert len(out) == 2 and out[0]["cells"][5] == "155.60", out
    assert out[0]["label"] == "Strengthening of existing weak pavement (Kms.)"
    assert merge_wrapped_numbers(recs[1:]) == recs[1:]          # normal rows untouched
    # a negative too wide for its cell: '-' alone on the line above, right-aligned with the digits
    wd = lambda t, x0, x1: dict(t=t, x0=x0, x1=x1, cy=0)
    ls = fix_wrapped_signs([dict(cy=100, w=[wd("-", 296, 300)]),
                            dict(cy=108, w=[wd("Switching", 10, 50), wd("1032.143", 120, 150), wd("193.93", 280, 300)])])
    assert len(ls) == 1 and ls[0]["text"] == "Switching 1032.143 -193.93", ls
    m = STALE_RE.search("** M/o Road Transport and Highways have not provided the updated data for the month of "
                        "April 2016. Therefore, the data for the month of March 2016 has been used.")
    assert sector_of(m[1]) == "Roads" and ym_in_text(m[2]) == ["2016-03"], m
    print("selfcheck ok")


if __name__ == "__main__":
    selfcheck()
    if "--selfcheck" not in sys.argv:
        main()
