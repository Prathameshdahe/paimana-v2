"""
Extractor for MoSPI IPMD monthly Flash Reports, FY 2013-14 .. 2015-16
("Project Monitoring/monthly/2013-14|2014-15|2015-16/FR_<mon>_<year>.pdf").

Run from repo root:  python pipeline/extract/proj_monthly_2013_16.py [--selftest]

Outputs (dataset/clean/_parts/proj_monthly_2013_16/):
  projects.csv  ongoing       master list "Sector Wise Details" (always complete)
                completed     month-wise list of completed projects; each project
                              is emitted once, from the first report of the FY that
                              lists it (the lists are FY-to-date and repeat).
                              Printed codes are checked against the master lists
                              (the deleted lists of Nov 2014 - Oct 2015 print other
                              projects' codes). DOA, now-anticipated cost/DOC and
                              final expenditure come from the "List of projects
                              completed/dropped/Frozen during current month".
                              Completions a later report of the FY no longer lists
                              are withdrawn and not emitted (manifest notes).
                dropped       month-wise list of deleted projects, same rules
                other:dropped_or_frozen  entries of the current-month list found in
                              neither month-wise list (the source does not say
                              whether dropped or frozen)
                newly_added   "List of projects added"
                other:additionally_delayed  "List of projects reporting additional
                              delays" (carries last-month/this-month DOC and the
                              additional delay, which the master list lacks)
                other:delayed_wrt_original  Annexure "Details of Delayed Projects
                              w.r.t. Original (and Revised) Schedule" (May 2014,
                              Jun 2014, Oct 2014 onwards): remarks = reasons for
                              delay as reported, delay_months = time overrun,
                              cost_overrun_pct as printed
                Other derived annexure lists (ahead of schedule, cost overrun,
                without DOC, ...) repeat master-list fields only and are skipped.
  summary.csv   long form: sector totals of the master list, executive-summary
                sector table, sector-wise analysis, "Extent of cost / time /
                time & cost overrun" tables (sector and state), state annexure,
                current-status counts (overall and per sector), milestones.
  manifest.csv  one row per PDF.

Parsing is by word coordinates (PyMuPDF). The document is cut into segments at
section titles (a table may start half-way down another table's page); every
table derives its column anchors from its own header on each page. Hindi pages
are skipped.
"""
import bisect
import difflib
import re
import sys
from collections import Counter
from pathlib import Path

import fitz  # PyMuPDF

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (DATASET, MANIFEST_COLS, MONTHS, PROJECT_COLS,  # noqa: E402
                    SUMMARY_COLS, fiscal_year, rel, to_num, to_ym, write_part)

FAMILY = "proj_monthly_2013_16"
SRC_DIRS = [DATASET / "Project Monitoring" / "monthly" / fy for fy in ("2013-14", "2014-15", "2015-16")]
REPORT_TYPE = "monthly_flash"

DATE_RE = re.compile(r"^\d{1,2}/\d{4}$")
NUM_RE = re.compile(r"^-?[\d,]*\.?\d+$")
DELAY_RE = re.compile(r"^(-?\d+)\((O|R)\)$")
MILE_RE = re.compile(r"^\d+/\d+$")
RANGE_RE = re.compile(r"^(\d+)-(\d+)$")
FOOTER_RE = re.compile(r"Hkkjr|vkbZ|MoSPI|OCMS|ljdkj")


# ----------------------------------------------------------------------------
# generic helpers
# ----------------------------------------------------------------------------
def clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def page_lines(page, tol=2.5):
    """Words grouped into visual lines (top->bottom, left->right), running
    headers/footers (legacy-font Hindi banner, 'MoSPI OCMS', page no.) removed.
    Rotated (landscape) pages are read in their displayed orientation."""
    ws = page.get_text("words")
    if page.rotation:
        M = page.rotation_matrix
        ws = [tuple(fitz.Rect(w[:4]) * M) + tuple(w[4:]) for w in ws]
    ws = sorted(ws, key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    lines = []
    for w in ws:
        yc = (w[1] + w[3]) / 2
        if lines and abs(lines[-1]["y"] - yc) < tol:
            lines[-1]["w"].append(w)
        else:
            lines.append({"y": yc, "w": [w]})
    H = page.rect.height
    out = []
    for ln in lines:
        ln["w"].sort(key=lambda w: w[0])
        ln["t"] = " ".join(w[4] for w in ln["w"])
        if FOOTER_RE.search(ln["t"]):
            continue
        if ln["y"] > 0.88 * H and len(ln["w"]) == 1 and ln["w"][0][4].isdigit():
            continue
        out.append(ln)
    return out


def mark_bold(page, lines):
    """ln['bold'] = every word of the line is set in a bold font. Sector headings of
    the short lists are bold; wrapped name lines are not."""
    M = page.rotation_matrix if page.rotation else fitz.Identity
    bold = [fitz.Rect(s["bbox"]) * M for b in page.get_text("dict")["blocks"] for ln in b.get("lines", [])
            for s in ln["spans"] if s["text"].strip() and (s["flags"] & 16 or "bold" in s["font"].lower())]
    for ln in lines:
        ln["bold"] = all(any(r.x0 - .5 <= (w[0] + w[2]) / 2 <= r.x1 + .5 and r.y0 - .5 <= (w[1] + w[3]) / 2 <= r.y1 + .5
                             for r in bold) for w in ln["w"])


def add_dq(r, flag):
    """Append a data-quality flag to r['dq_note'] (';'-joined, no repeats)."""
    old = [x for x in (r.get("dq_note") or "").split(";") if x]
    if flag not in old:
        r["dq_note"] = ";".join(old + [flag])


def is_hindi(text):
    return len(re.findall(r"[\u0900-\u097F]", text)) > 30  # Devanagari


def norm_key(s):
    s = str(s or "").upper().replace("&", " AND ")
    return re.sub(r"[^A-Z0-9]", "", s)


def strip_marks(s):
    """Footnote markers printed after sector names ('RAILWAYS *', 'HIGHWAYS**')."""
    return clean(re.sub(r"[\s*$^#]+$", "", clean(s))) or None


def period_from_name(path):
    m = re.match(r"FR_([A-Za-z]+)_(\d{4})", Path(path).stem)
    mon = m[1].lower()
    mo = MONTHS.get(mon, MONTHS.get(mon[:3]))
    return f"{int(m[2]):04d}-{mo:02d}"


def base_row(ctx, page, list_type):
    return {
        "report_period": ctx["period"], "report_type": REPORT_TYPE,
        "fiscal_year": fiscal_year(ctx["period"]), "quarter": None,
        "source_file": ctx["src"], "page": page, "list_type": list_type,
    }


def summ(ctx, page, title, dim, dval, metric, value, sub=None, unit=None, dq=None):
    v = value if isinstance(value, (int, float)) else to_num(value)
    if v is None:
        return None
    return {
        "report_period": ctx["period"], "report_type": REPORT_TYPE,
        "fiscal_year": fiscal_year(ctx["period"]), "quarter": None,
        "source_file": ctx["src"], "page": page, "table_title": title,
        "dimension": dim, "dimension_value": clean(dval),
        "sub_dimension_value": sub, "metric": metric, "value": v, "unit": unit, "dq_note": dq,
    }


# ----------------------------------------------------------------------------
# sectioning: cut every page at section titles
# ----------------------------------------------------------------------------
_PFX = r"^(?:[IVX]+\.\s*)?"
TITLES = [
    ("ongoing", _PFX + r"Sector\s*Wise\s*Details"),
    ("sect_analysis", _PFX + r"Sector\s*wise\s*analysis\s*of\s*projects"),
    ("sector_status", _PFX + r"Sector\s*wise\s*current\s*status"),
    ("summary_page", _PFX + r"Summary\s*of\s*projects\s*in\s*the\s*Flash"),
    ("cmpl_mw", _PFX + r"Month\s*wise\s*List\s*of\s*Completed"),
    ("del_mw", _PFX + r"Month\s*wise\s*List\s*of\s*Deleted"),
    ("cur_cmpl", _PFX + r"List\s*of\s*projects\s*completed"),
    ("added", _PFX + r"List\s*of\s*projects\s*added"),
    ("addl", _PFX + r"List\s*of\s*projects\s*reporting\s*additional"),
    ("milestones", _PFX + r"Milestones\s*\((?:Cumulative|Total)"),
    ("co_orig_sector", _PFX + r"Extent of cost overruns? in projects with respect to original schedule\s*\(\s*Sector"),
    ("co_orig_state", _PFX + r"Extent of cost overruns? in projects with respect to original schedule\s*\(\s*State"),
    ("to_orig_state", _PFX + r"Extent of (?:the )?time overruns? in projects with respect to original schedule\s*\(\s*State"),
    ("to_orig_sector", _PFX + r"Extent of (?:the )?time overruns? in projects with respect to original schedule"),
    ("to_latest", _PFX + r"Extent of (?:the )?time overruns? in projects with respect to latest"),
    ("co_latest", _PFX + r"Extent of cost overruns? in projects with respect to latest"),
    ("tco_latest", _PFX + r"Extent of time\s*&\s*cost overruns? in projects with respect to latest"),
    ("tco_orig", _PFX + r"Extent of time\s*&\s*cost overruns? in projects with respect to original"),
    ("exec", _PFX + r"EXECUTIVE\s*SUMMARY"),
    ("status", _PFX + r"Projects?\s*Added\s*/\s*Completed"),
    ("annex_state", r"^(?:LIST OF CENTRAL SECTOR PROJECTS(?:\s*$|\s+All\s+Cost)|STATUS OF CENTRAL SECTOR PROJECTS COST"
                    r"|SN\s+STATE\s+(?:NO\s+OF|PROJECTS))"),
    ("graph", r"^Graphical"),
    ("other", r"^(?:ANNEXURES?\b|Annexure|Contents|Abbreviations|(?:List|LIST|Details|DETAILS)\s+(?:of|OF)\b)"),
]
# + GRID_TABLES keys (below). 'status': its last table can run onto the next page (Jan 2016 p55)
MULTI_PAGE = {"ongoing", "cmpl_mw", "del_mw", "added", "addl", "cur_cmpl", "status"}


def title_of(text):
    for k, p in TITLES:
        if re.search(p, text, re.I if k != "exec" else 0):
            return k
    return None


def sections(doc):
    """{key: [(page_no, lines), ...]} in document order. Content above the
    first title of a page continues the previous page's list (multi-page
    lists only); everything else belongs to the title above it."""
    out, cur_key, hindi = {}, None, 0
    for i, page in enumerate(doc):
        pno = i + 1
        if is_hindi(page.get_text()):
            hindi += 1
            cur_key = None
            continue
        lines = page_lines(page)
        if any(re.match(r"^Contents", ln["t"]) for ln in lines[:3]):
            cur_key = None  # table of contents: titles without tables
            continue
        dly = delayed_anchor(lines)
        if dly:  # every page of the delayed-with-reasons annexure repeats its header
            j, variant, pts = dly
            out.setdefault("delayed_rsn", []).append((pno, (variant, pts, lines[j:])))
        marks = [(j, k) for j, ln in enumerate(lines) for k in [title_of(ln["t"])] if k]
        first = marks[0][0] if marks else len(lines)
        if first > 0 and cur_key in MULTI_PAGE:
            out.setdefault(cur_key, []).append((pno, lines[:first]))
        for n, (j, k) in enumerate(marks):
            end = marks[n + 1][0] if n + 1 < len(marks) else len(lines)
            out.setdefault(k, []).append((pno, lines[j:end]))
            cur_key = k
    return out, hindi


# ----------------------------------------------------------------------------
# master list ("Sector Wise Details") -> list_type=ongoing
# ----------------------------------------------------------------------------
NAME_RE = re.compile(r"^(?P<name>.*?)\s*-?\s*\[(?P<code>[A-Za-z0-9]+)\]\s*(?P<rest>.*)$")


def split_name(text):
    """'KAKRAPAR ... - [N02000010]NPCIL,Gujarat , PPP (BOT)' ->
    (name, code, agency, state, mode). Mode is the implementation mode that
    2015-16 reports print after the state ('.' = not given)."""
    text = clean(text)
    m = NAME_RE.match(text)
    if not m:
        return text.rstrip(" -"), None, None, None, None
    name, code, rest = m["name"].rstrip(" -"), m["code"], clean(m["rest"])
    rest = re.sub(r"(\s*-)+$", "", rest).strip()
    agency = state = mode = None
    if "," in rest:
        agency, tail = rest.split(",", 1)
        parts = [clean(p) for p in re.split(r"\s,", tail)]
        state = parts[0].rstrip(" ,.") or None
        if len(parts) > 1:
            mode = clean(" ".join(parts[1:])).strip(" ,.") or None
    else:
        agency = rest or None
    return clean(name), code, clean(agency) or None, state, mode


def ongoing_anchors(lines):
    for i, ln in enumerate(lines):
        if [w[4] for w in ln["w"]] == [str(k) for k in range(1, 11)]:
            return i, [(w[0] + w[2]) / 2 for w in ln["w"]]
    return None, None


def ongoing_col(w, C):
    """Column (1..10) of a word, from the printed column-number row. Numbers
    are right-aligned in some files and centred in others, so the right edge
    x1 is used: a word belongs to the right-most column whose centre-5 it passes."""
    x0, x1 = w[0], w[2]
    if x0 < C[0] + 6 and w[4].isdigit():
        return 1
    if x1 <= C[2] - 5:
        return 2
    col = 3
    for c in range(3, 11):
        if x1 > C[c - 1] - 5:
            col = c
    return col


def merge_wrapped(tokens):
    """'1,058,599.4' followed by '5' on the next line -> '1,058,599.45'."""
    out = []
    for t in tokens:
        if out and re.fullmatch(r"\d", t) and re.search(r"\d\.\d$", out[-1]):
            out[-1] += t
        else:
            out.append(t)
    return out


def finish_ongoing(ctx, r, out, issues):
    name, code, agency, state, mode = split_name(" ".join(r["name"]))
    first, later = r["first"], r["later"]
    row = base_row(ctx, r["page"], "ongoing")

    def toks(c, which):
        return [t for t in merge_wrapped(which.get(c, [])) if t != "-"]

    def single(c):
        t = toks(c, first) + toks(c, later)
        if len(t) > 1:
            issues.append(f"p{r['page']} sno {r['sno']}: col{c} multiple {t}")
        return t[0] if t else None

    doa = single(3)
    co, cr = toks(4, first), toks(4, later)
    doc_o, doc_r = toks(7, first), toks(7, later)
    dl = toks(9, first) + toks(9, later)
    ant, exp_, doc_a, mil = single(5), single(6), single(8), single(10)
    checks = [(3, doa, DATE_RE), (5, ant, NUM_RE), (6, exp_, NUM_RE), (8, doc_a, DATE_RE), (10, mil, MILE_RE)]
    checks += [(4, t, NUM_RE) for t in co + cr] + [(7, t, DATE_RE) for t in doc_o + doc_r] + [(9, t, DELAY_RE) for t in dl]
    for c, t, pat in checks:
        if t is not None and not pat.match(t):
            issues.append(f"p{r['page']} sno {r['sno']}: col{c} bad token {t!r}")
    if len(co) > 1 or len(cr) > 1 or len(doc_o) > 1 or len(doc_r) > 1:
        issues.append(f"p{r['page']} sno {r['sno']}: extra original/revised values {co} {cr} {doc_o} {doc_r}")

    def ok(t, pat):
        return t if t is not None and pat.match(t) else None

    def delay(kind):
        for t in dl:
            m = DELAY_RE.match(t)
            if m and m[2] == kind:
                return float(m[1])
        return None

    remarks = []
    dr = delay("R")
    if dr is not None:
        remarks.append(f"delay w.r.t. revised schedule: {int(dr)} months")
    if ok(mil, MILE_RE):
        remarks.append(f"milestones achieved/total: {mil}")
    if mode:
        remarks.append(f"implementation mode: {mode}")
    row.update({
        "project_code": code, "project_name": name, "sector_raw": r["sector"],
        "agency": agency, "state": state,
        "doa_original": to_ym(ok(doa, DATE_RE)),
        "cost_original_cr": to_num(ok(co[0] if co else None, NUM_RE)),
        "cost_revised_cr": to_num(ok(cr[0] if cr else None, NUM_RE)),
        "cost_anticipated_cr": to_num(ok(ant, NUM_RE)),
        "expenditure_cum_cr": to_num(ok(exp_, NUM_RE)),
        "doc_original": to_ym(ok(doc_o[0] if doc_o else None, DATE_RE)),
        "doc_revised": to_ym(ok(doc_r[0] if doc_r else None, DATE_RE)),
        "doc_anticipated": to_ym(ok(doc_a, DATE_RE)),
        "delay_months": delay("O"),
        "remarks": "; ".join(remarks) or None,
        "_sno": r["sno"],
    })
    out.append(row)


def parse_ongoing(ctx, segs):
    rows, summary, issues = [], [], []
    sector, cur, heading_open = None, None, False
    title = "Sector Wise Details (list of all ongoing projects)"
    for pno, lines in segs:
        hi, C = ongoing_anchors(lines)
        if C is None:
            issues.append(f"p{pno}: no column-number row")
            continue
        for ln in lines[hi + 1:]:
            cells = {}
            for w in ln["w"]:
                cells.setdefault(ongoing_col(w, C), []).append(w[4])
            c2 = " ".join(cells.get(2, []))
            others = {c: v for c, v in cells.items() if c not in (1, 2)}
            if 1 in cells:
                if cur:
                    finish_ongoing(ctx, cur, rows, issues)
                cur = {"sno": int(cells[1][0]), "page": pno, "sector": strip_marks(sector),
                       "name": [c2] if c2 else [], "first": others, "later": {}}
                heading_open = False
                continue
            if re.match(r"^(Grand\s+)?Total\b", c2, re.I):
                if cur:
                    finish_ongoing(ctx, cur, rows, issues)
                    cur = None
                grand = c2.lower().startswith("grand")
                dim, dval = ("overall", "Total") if grand else ("sector", strip_marks(sector))
                vals = {c: merge_wrapped(v) for c, v in others.items()}
                for c, metric in ((4, "cost_original_cr"), (5, "cost_anticipated_cr"), (6, "expenditure_cr")):
                    t = [x for x in vals.get(c, []) if x != "-"]
                    if t:
                        summary.append(summ(ctx, pno, title, dim, dval, metric, t[0], unit="Rs crore"))
                m = [x for x in vals.get(10, []) if MILE_RE.match(x)]
                if m:
                    a, b = m[0].split("/")
                    summary.append(summ(ctx, pno, title, dim, dval, "n_milestones_achieved", a))
                    summary.append(summ(ctx, pno, title, dim, dval, "n_milestones_total", b))
                heading_open = False
                continue
            if not others and c2:
                if cur is None:
                    # sector heading (possibly wrapped over two lines)
                    sector = f"{sector} {c2}" if heading_open else c2
                    heading_open = True
                    continue
                cur["name"].append(c2)
                continue
            heading_open = False
            if cur is None:
                continue  # dashes under a Total row, footnotes after the Grand Total
            if c2:
                cur["name"].append(c2)
            for c, v in others.items():
                cur["later"].setdefault(c, []).extend(v)
        heading_open = False
    if cur:
        finish_ongoing(ctx, cur, rows, issues)
    return rows, [s for s in summary if s], issues


# ----------------------------------------------------------------------------
# month-wise completed / deleted lists -> list_type completed / dropped
# ----------------------------------------------------------------------------
CODE_TAIL_RE = re.compile(r"\s*-?\s*\[(?P<code>[A-Za-z0-9]+)\]\s*$")
MONTH_HEAD_RE = re.compile(r"^([A-Za-z]+),(\d{4})$")


def split_paren_agency(text):
    """'KOLDAM HEP (NTPC)(NATIONAL THERMAL POWER CORPORATION) - [180100211]'
    -> ('KOLDAM HEP (NTPC)', 'NATIONAL THERMAL POWER CORPORATION', '180100211').
    The agency is the last balanced (...) group before ' - [code]'."""
    text = clean(text)
    m = CODE_TAIL_RE.search(text)
    code = m["code"] if m else None
    body = text[: m.start()].rstrip(" -") if m else text
    if body.endswith(")"):
        depth = 0
        for i in range(len(body) - 1, -1, -1):
            if body[i] == ")":
                depth += 1
            elif body[i] == "(":
                depth -= 1
                if depth == 0:
                    return clean(body[:i]).rstrip(" -") or None, clean(body[i + 1:-1]) or None, code
    return body or None, None, code


def parse_monthwise(ctx, segs, list_type):
    """All rows of a month-wise completed/deleted list, with the printed month."""
    out, issues = [], []
    month = sector = cur = None
    anchors = None

    def finish():
        if not cur:
            return
        name, agency, code = split_paren_agency(" ".join(cur["name"]))
        if not code:
            issues.append(f"p{cur['page']} sno {cur['sno']}: no project code in {' '.join(cur['name'])!r}")
        cost = [t for t in cur["cost"] if NUM_RE.match(t)]
        exp_ = [t for t in cur["exp"] if NUM_RE.match(t)]
        doc_o = [t for t in cur["doc"] if DATE_RE.match(t)]
        bad = [t for t in cur["cost"] + cur["exp"] + cur["doc"] if not (is_blank(t) or NUM_RE.match(t) or DATE_RE.match(t))]
        if bad or len(cost) > 1 or len(exp_) > 1 or len(doc_o) > 1:
            issues.append(f"p{cur['page']} sno {cur['sno']}: odd values {cur['cost']} {cur['doc']} {cur['exp']}")
        row = base_row(ctx, cur["page"], list_type)
        row.update({
            "project_code": code, "project_name": name, "agency": agency, "sector_raw": strip_marks(cur["sector"]),
            "cost_original_cr": to_num(cost[0]) if len(cost) == 1 else None,
            "doc_original": to_ym(doc_o[0]) if len(doc_o) == 1 else None,
            "expenditure_cum_cr": to_num(exp_[0]) if len(exp_) == 1 else None,
            "_month": cur["month"], "_sno": cur["sno"],
        })
        out.append(placeholder_zeros(row))

    for pno, lines in segs:
        hi = next((i for i, ln in enumerate(lines) if re.search(r"Project\s+Name", ln["t"])), None)
        if hi is not None:
            hdr = [w for ln in lines[max(0, hi - 4):hi + 1] for w in ln["w"]]
            d1 = min((w[0] for w in hdr if w[4].lower().startswith("commissi") or w[4] == "Date"), default=None)
            d2 = min((w[0] for w in hdr if w[4].startswith("Cumulative")), default=None)
            name_x = min((w[0] for w in hdr if w[4] == "Project"), default=None)
            cost_x = min((w[0] for w in hdr if w[4] == "Original"), default=None)
            if None in (d1, d2, name_x, cost_x):
                issues.append(f"p{pno}: header anchors missing")
                continue
            anchors = (d1 - 8, d2 - 4, name_x, cost_x)
        else:
            nxt = str(cur["sno"] + 1) if cur else "1"  # untitled page: must continue the numbering
            if anchors is None or not any(ln["w"][0][4] == nxt for ln in lines[:5]):
                continue
        d1, d2, name_x, cost_x = anchors
        for ln in lines[(hi + 1) if hi is not None else 0:]:
            ws, t = ln["w"], ln["t"]
            if re.match(r"^Month\s*wise", t) or re.match(r"^\(?Rs\.?\s*crore", t):
                continue
            m = MONTH_HEAD_RE.match(t.replace(" ", ""))
            if m and m[1][:3].lower() in MONTHS:
                month = t.replace(" ", "")
                continue
            if ws[0][4].isdigit() and ws[0][2] < name_x - 2:
                finish()
                cur = {"sno": int(ws[0][4]), "page": pno, "sector": sector, "month": month,
                       "name": [], "cost": [], "doc": [], "exp": []}
                ws = ws[1:]
            elif cur is None or CODE_TAIL_RE.search(" ".join(cur["name"])):
                if all(w[2] < cost_x for w in ws) and not any(re.search(r"\d", w[4]) for w in ws):
                    finish()
                    cur = None
                    sector = clean(t)
                    continue
                if cur is None:
                    issues.append(f"p{pno}: orphan line {t!r}")
                    continue
            for w in ws:
                xc = (w[0] + w[2]) / 2
                is_val = (NUM_RE.match(w[4]) or DATE_RE.match(w[4]) or is_blank(w[4])) and xc > cost_x - 15
                if not is_val:
                    cur["name"].append(w[4])
                elif xc < d1:
                    cur["cost"].append(w[4])
                elif xc < d2:
                    cur["doc"].append(w[4])
                else:
                    cur["exp"].append(w[4])
    finish()
    return out, issues


# ----------------------------------------------------------------------------
# short lists with sector headings: projects added / additional delays
# ----------------------------------------------------------------------------
BLANKS = ("-", "/", "N.A.", "N.A", "NA", "N.R.", "N.R")  # printed 'not available' markers


def is_blank(t):
    """Printed 'no value' markers, including the '0/0' date placeholder (Jul 2013)."""
    return t in BLANKS or bool(re.fullmatch(r"0+/0+", t))


ZERO_COLS = ("cost_original_cr", "cost_revised_cr", "cost_anticipated_cr", "expenditure_cum_cr")


def placeholder_zeros(r):
    """A cost or expenditure printed as 0 / .00 in the derived lists stands for 'not
    reported': the master list prints '-' there and never 0 ('.00' final expenditure
    of completed projects costing Rs 1,000 crore, Jan 2014 p38; 'Pen-Roha doubling'
    98.74 / 0.00, Jul 2013). Blanked, flagged placeholder_zero:<column>."""
    for c in ZERO_COLS:
        if r.get(c) == 0:
            r[c] = None
            add_dq(r, f"placeholder_zero:{c}")
    return r


def _cx(w):
    return (w[0] + w[2]) / 2


def added_anchors(lines):
    """Header 'Project ... DOA Cost DOC Cost DOC' (spread over up to 4 lines)."""
    for i in range(len(lines)):
        if not any(w[4] in ("DOA", "DOC") for w in lines[i]["w"]):
            continue
        band = [w for ln in lines[max(0, i - 3):i + 1] if not re.search(r"\(All|sums of money", ln["t"])
                for w in ln["w"]]
        cs = sorted([w for w in band if w[4] == "Cost"], key=lambda w: w[0])
        ds = sorted([w for w in band if w[4] == "DOC"], key=lambda w: w[0])
        doa = [w for w in band if w[4] == "DOA"]
        proj = [w for w in band if w[4] == "Project"]
        if len(cs) == 2 and len(ds) == 2 and doa and proj:
            return i, {"doa": _cx(doa[0]), "cost_o": _cx(cs[0]), "doc_o": _cx(ds[0]),
                       "cost_a": _cx(cs[1]), "doc_a": _cx(ds[1]), "_name": proj[0][0]}
    return None, None


def addl_anchors(lines):
    for i, ln in enumerate(lines):
        toks = [w[4] for w in ln["w"]]
        if "Original" in toks and toks.count("month") >= 2 and ("name" in toks or "Project" in toks):
            ws = ln["w"]
            prev = [w for l2 in lines[max(0, i - 3):i] for w in l2["w"]]
            origs = [w for w in ws if w[4] == "Original"]
            ant = [w for w in ws + prev if w[4] in ("Anticipated", "Antici", "pated")]
            last = [w for w in ws + prev if w[4] == "Last"]
            this = [w for w in ws + prev if w[4] == "This"]
            dl = [w for w in ws + prev if w[4] in ("Delay", "months)")]
            proj = next((w for w in ws if w[4] == "Project"), None)
            if len(origs) < 2 or not (ant and last and this and dl and proj):
                continue
            mon = [w for w in ws if w[4] == "month"]
            lx = (last[0][0] + mon[0][2]) / 2 if mon and mon[0][0] > last[0][0] else _cx(last[0])
            tx = (this[0][0] + mon[-1][2]) / 2 if mon and mon[-1][0] > this[0][0] else _cx(this[0])
            return i, {"cost_o": _cx(origs[0]), "cost_a": _cx(ant[0]), "doc_o": _cx(origs[1]),
                       "doc_last": lx, "doc_this": tx, "delay": _cx(dl[0]), "_name": proj[0]}
    return None, None


def parse_anchored_list(segs, find_anchors, sector_keys):
    """A line whose first word is an integer left of the name column starts a
    row; value words go to the nearest header anchor; the rest is name text.
    A number-free line naming a known sector (or clearly separated and in
    capitals) is a sector heading. Anchors carry over to an untitled page only
    if the next serial number starts a row near its top."""
    raw, issues = [], []
    sector = cur = A = None
    for pno, lines in segs:
        hi, A2 = find_anchors(lines)
        if A2 is not None:
            A = A2
        else:
            nxt = str(raw[-1]["sno"] + 1) if raw else "1"
            if A is None or not any(ln["w"][0][4] == nxt for ln in lines[:4]):
                if len(lines) > 3 and any(title_of(ln["t"]) for ln in lines[:2]):
                    issues.append(f"p{pno}: no header")
                cur = None
                continue
        anchors = {k: v for k, v in A.items() if k != "_name"}
        name_x, first_x = A["_name"], min(anchors.values())
        body = lines[(hi + 1) if hi is not None else 0:]
        page_bold = any(ln.get("bold") for ln in body)  # this page sets its sector headings in bold
        prev_y, skip = None, 0
        for li, ln in enumerate(body):
            if skip:
                skip -= 1
                continue
            t, ws = ln["t"], ln["w"]
            if title_of(t) or not re.search(r"[A-Za-z0-9]", t):
                continue
            wrap_gap = prev_y is not None and ln["y"] - prev_y < 16  # wrapped name lines sit ~10 pt below
            gap = ln["y"] - prev_y if prev_y is not None else 0
            prev_y = ln["y"]
            nxt = (raw[-1]["sno"] + 1) if raw else 1
            if len(ws) == 1 and raw and ws[0][4] == str(raw[-1]["sno"]):
                raw.append({"sno": raw[-1]["sno"], "page": pno, "sector": sector, "name": [], "v": {}, "count": True})
                cur = None  # printed count below the list
                continue
            if (ws[0][4].isdigit() and int(ws[0][4]) == nxt and ws[0][2] < first_x - 40
                    and (len(ws) == 1 or _cx(ws[1]) < first_x - 25)):
                cur = {"sno": int(ws[0][4]), "page": pno, "sector": sector, "name": [], "v": {}}
                raw.append(cur)
                ws = ws[1:]
            elif not re.search(r"\d", t):
                # sector heading, possibly over two lines ('Road Transport &' / 'Highways'). Headings
                # are bold: while a row is open, a regular-weight line is its wrapped name even when
                # it reads like a sector ('MINE' under 'MUNGOLI ... (DEEP) OC', Dec 2015 p65). Pages
                # without bold headings fall back to the line gap.
                head = None
                if cur is not None and not ln.get("bold", True) and (page_bold or wrap_gap):
                    pass
                elif norm_key(t).rstrip("S") in sector_keys:
                    head = clean(t)
                elif (li + 1 < len(body) and not re.search(r"\d", body[li + 1]["t"])
                      and norm_key(t + " " + body[li + 1]["t"]).rstrip("S") in sector_keys):
                    head, skip = clean(t + " " + body[li + 1]["t"]), 1
                elif gap > 22 and t.strip() == t.strip().upper() and len(t) > 3:
                    head = clean(t)
                elif not raw and len(ws) <= 4:  # before the first row ('Fertilisers', May 2013)
                    head = clean(t)
                if head:
                    if head != sector:  # the heading is repeated at the top of a new page
                        sector, cur = head, None
                    continue
                if cur is None:
                    issues.append(f"p{pno}: orphan line {t!r}")
                    continue
            elif cur is None:
                issues.append(f"p{pno}: orphan line {t!r}")
                continue
            for w in ws:
                xc = _cx(w)
                is_val = (NUM_RE.match(w[4]) or DATE_RE.match(w[4]) or is_blank(w[4])) and xc > first_x - 25
                if not is_val:
                    cur["name"].append(w[4])
                else:
                    k = min(anchors, key=lambda k: abs(anchors[k] - xc))
                    cur["v"].setdefault(k, []).append(w[4])
    return raw, issues


def one_val(v, k, pat):
    toks = [t for t in v.get(k, []) if not is_blank(t)]
    return toks[0] if len(toks) == 1 and pat.match(toks[0]) else None


def check_vals(r, spec, issues):
    for k, pat in spec:
        toks = [t for t in r["v"].get(k, []) if not is_blank(t)]
        if len(toks) > 1 or (toks and not pat.match(toks[0])):
            issues.append(f"p{r['page']} sno {r['sno']}: {k} odd {toks}")


def parse_added(ctx, segs, sector_keys):
    raw, issues = parse_anchored_list(segs, added_anchors, sector_keys)
    rows = []
    for r in raw:
        if r.get("count") or not r["name"]:
            continue
        v = r["v"]
        check_vals(r, (("doa", DATE_RE), ("doc_o", DATE_RE), ("doc_a", DATE_RE), ("cost_o", NUM_RE),
                       ("cost_a", NUM_RE)), issues)
        row = base_row(ctx, r["page"], "newly_added")
        row.update({
            "project_name": clean(" ".join(r["name"])), "sector_raw": strip_marks(r["sector"]),
            "doa_original": to_ym(one_val(v, "doa", DATE_RE)),
            "cost_original_cr": to_num(one_val(v, "cost_o", NUM_RE)),
            "doc_original": to_ym(one_val(v, "doc_o", DATE_RE)),
            "cost_anticipated_cr": to_num(one_val(v, "cost_a", NUM_RE)),
            "doc_anticipated": to_ym(one_val(v, "doc_a", DATE_RE)),
            "_sno": r["sno"],
        })
        rows.append(placeholder_zeros(row))
    return rows, issues


def parse_addl(ctx, segs, sector_keys, agencies):
    raw, issues = parse_anchored_list(segs, addl_anchors, sector_keys)
    rows, total = [], None
    for r in raw:
        v = r["v"]
        if r.get("count"):
            total = r["sno"]  # printed count under the list
            continue
        if not r["name"]:
            if v:
                issues.append(f"p{r['page']} sno {r['sno']}: row without name")
            continue
        check_vals(r, (("doc_o", DATE_RE), ("doc_last", DATE_RE), ("doc_this", DATE_RE), ("cost_o", NUM_RE),
                       ("cost_a", NUM_RE), ("delay", NUM_RE)), issues)
        name = clean(" ".join(r["name"]))
        agency = None
        words = name.split(" ")
        for k in (3, 2, 1):  # agency abbreviation printed after the name ('... Mangalore Refin')
            if len(words) > k and " ".join(words[-k:]).upper() in agencies:
                name, agency = " ".join(words[:-k]), " ".join(words[-k:])
                break
        last, this = to_ym(one_val(v, "doc_last", DATE_RE)), to_ym(one_val(v, "doc_this", DATE_RE))
        row = base_row(ctx, r["page"], "other:additionally_delayed")
        row.update({
            "project_name": name, "agency": agency, "sector_raw": strip_marks(r["sector"]),
            "cost_original_cr": to_num(one_val(v, "cost_o", NUM_RE)),
            "cost_anticipated_cr": to_num(one_val(v, "cost_a", NUM_RE)),
            "doc_original": to_ym(one_val(v, "doc_o", DATE_RE)),
            "doc_anticipated": this,
            "additional_delay_months": to_num(one_val(v, "delay", NUM_RE)),
            "remarks": f"DOC reported last month: {last}; DOC reported this month: {this}" if last else None,
            "_sno": r["sno"],
        })
        rows.append(placeholder_zeros(row))
    return rows, total, issues


def cur_cmpl_anchors(lines):
    """'List of projects completed/dropped/Frozen during current month': the
    'added' header (DOA, Original Cost/DOC, Now anticipated Cost/DOC) plus
    'Final Expenditure'."""
    i, A = added_anchors(lines)
    if A is None:
        return None, None
    ex = [w for ln in lines[max(0, i - 3):i + 1] for w in ln["w"] if w[4].startswith("Expenditure")]
    if not ex:
        return None, None
    A["exp"] = _cx(ex[0])
    return i, A


def parse_cur_cmpl(ctx, segs, sector_keys):
    raw, issues = parse_anchored_list(segs, cur_cmpl_anchors, sector_keys)
    rows = []
    for r in raw:
        if r.get("count") or not r["name"]:
            continue
        v = r["v"]
        check_vals(r, (("doa", DATE_RE), ("doc_o", DATE_RE), ("doc_a", DATE_RE), ("cost_o", NUM_RE),
                       ("cost_a", NUM_RE), ("exp", NUM_RE)), issues)
        row = base_row(ctx, r["page"], "other:dropped_or_frozen")
        row.update({
            "project_name": clean(" ".join(r["name"])), "sector_raw": strip_marks(r["sector"]),
            "doa_original": to_ym(one_val(v, "doa", DATE_RE)),
            "cost_original_cr": to_num(one_val(v, "cost_o", NUM_RE)),
            "doc_original": to_ym(one_val(v, "doc_o", DATE_RE)),
            "cost_anticipated_cr": to_num(one_val(v, "cost_a", NUM_RE)),
            "doc_anticipated": to_ym(one_val(v, "doc_a", DATE_RE)),
            "expenditure_cum_cr": to_num(one_val(v, "exp", NUM_RE)),
            "_sno": r["sno"],
        })
        rows.append(placeholder_zeros(row))
    return rows, issues


# ----------------------------------------------------------------------------
# 'Details of Delayed Projects w.r.t. Original (and Revised) Schedule' with the
# reasons for delay (Annexure VI; May 2014 and Jun 2014 onwards)
# -> list_type other:delayed_wrt_original
# ----------------------------------------------------------------------------
DLY_A = [str(k) for k in range(1, 12)]
DLY_B = ["SN", "PROJ", "IMPL", "DATE", "ORIG", "ANTI", "COST", "COST", "REPO", "COST", "TIME", "REAS"]
DLY_FIELDS = {  # field per column. A: numbered 11-column table; B: May 2014 (landscape, no codes)
    "A": ["sno", "name", "doa", "cost", "cost_a", "exp", "doc", "doc_a", "tor", "cop", "reason"],
    "B": ["sno", "name", "agency", "doa", "doc", "doc_a", "cost", "cost_a", "exp", "cop", "tor", "reason"],
}
NO_REASON = {"NR", "N.R.", "N.R", "NA", "N.A.", "-", "--"}


def delayed_anchor(lines):
    """(line index, variant, x of a point inside each column) of the table header."""
    for j, ln in enumerate(lines):
        toks = [w[4] for w in ln["w"]]
        if toks == DLY_A and any("Reasons" in x["t"] for x in lines[max(0, j - 10):j]):
            return j, "A", [_cx(w) for w in ln["w"]]
        if toks[:2] == ["SN", "PROJECT"] and "REASONS" in toks:
            pts = []
            for w in ln["w"]:
                if len(pts) < len(DLY_B) and w[4][:4] == DLY_B[len(pts)]:
                    pts.append(w[0] + 2)  # headers are left-aligned in their cells
            if len(pts) == len(DLY_B):
                return j, "B", pts
    return None


def rule_xs(page, y0):
    """x of the vertical table rules that reach below y0 (display coordinates)."""
    M = page.rotation_matrix if page.rotation else fitz.Identity
    xs = []
    for d in page.get_drawings():
        for it in d["items"]:
            if it[0] == "l":
                a, b = it[1] * M, it[2] * M
                if abs(a.x - b.x) < 1 and abs(a.y - b.y) > 4 and max(a.y, b.y) > y0:
                    xs.append(a.x)
            elif it[0] == "re":
                r = it[1] * M
                if r.width < 2 and r.height > 4 and r.y1 > y0:
                    xs.append((r.x0 + r.x1) / 2)
    return xs


def col_bounds(pts, xs):
    """Boundary between neighbouring columns: the table rule between their points
    (the one nearest the midpoint), else the midpoint. The reasons text is centred
    and starts right at the rule, so midpoints of column centres are not enough."""
    out, n_mid = [], 0
    for a, b in zip(pts, pts[1:]):
        mid = (a + b) / 2
        between = [x for x in xs if a + 1 < x < b - 1]
        out.append(min(between, key=lambda x: abs(x - mid)) if between else mid)
        n_mid += not between
    return out, n_mid


def parse_delayed(ctx, segs, doc, sector_keys, by_name):
    """Rows start at a serial number; name, value and reason cells wrap over the
    following lines. Reason text can run past the row's last name line and past
    the sector Total line, so reason-only lines go to the last row started."""
    raw, issues, notes = [], [], []
    sector = cur = last = None
    heading_open = done = False
    n_mid = 0
    for pno, (variant, pts, lines) in segs:
        if done:
            break
        F = DLY_FIELDS[variant]
        bounds, nm = col_bounds(pts, rule_xs(doc[pno - 1], lines[0]["y"]))
        n_mid += nm
        body = lines[1:]
        if variant == "B":  # header continues below the anchor line, down to 'AGENCIES )'
            k = next((i for i, ln in enumerate(body[:6]) if "AGENCIES" in ln["t"]), None)
            body = body[k + 1:] if k is not None else body
        skip = 0
        for li, ln in enumerate(body):
            if skip or re.fullmatch(r"Page\s+\d+", ln["t"]):
                skip = 0
                continue
            cells = {}
            for w in ln["w"]:
                cells.setdefault(F[bisect.bisect(bounds, _cx(w))], []).append(w[4])
            name = " ".join(cells.get("name", []))
            vals = {f: v for f, v in cells.items() if f not in ("sno", "name", "reason", "agency")}
            sno = cells.get("sno", [])
            if sno and re.fullmatch(r"\d+", sno[0]):
                cur = {"sno": int(sno[0]), "page": pno, "sector": sector, "variant": variant,
                       "name": [name] if name else [], "agency": cells.get("agency", []),
                       "first": vals, "later": {}, "reason": cells.get("reason", [])}
                raw.append(cur)
                last, heading_open = cur, False
                continue
            if cells.get("reason") and last:
                last["reason"] += cells["reason"]
            if re.match(r"^(Grand\s+)?Total\b", name, re.I):
                cur, heading_open = None, False
                if name.lower().startswith("grand"):
                    done = True
                    break
                continue
            if name and not vals and variant == "A" and not cells.get("agency") and cur is None:
                sector = f"{sector} {name}" if heading_open else name  # A: headings follow the sector Total
                heading_open = True
                continue
            if name and not vals and variant == "B":
                # B: no Total rows. The heading can spill into the agency column
                # ('ROAD TRANSPORT AND HIGHWAYS', May 2014 p184) or wrap onto the next line.
                head = clean(" ".join([name] + cells.get("agency", [])))
                two = clean(head + " " + body[li + 1]["t"]) if li + 1 < len(body) else ""
                if norm_key(head).rstrip("S") in sector_keys:
                    sector, cur = head, None
                    continue
                if two and norm_key(two).rstrip("S") in sector_keys:
                    sector, cur, skip = two, None, 1
                    continue
            heading_open = False
            if cur is None:
                continue
            if name:
                cur["name"].append(name)
            cur["agency"] += cells.get("agency", [])
            for f, v in vals.items():
                cur["later"].setdefault(f, []).extend(v)
    if n_mid:
        notes.append(f"delayed-with-reasons annexure: {n_mid} column boundaries taken from header midpoints (no table rule)")

    rows = []
    for r in raw:
        F_, L_ = r["first"], r["later"]

        def toks(f, which):
            return [t for t in merge_wrapped(which.get(f, [])) if not is_blank(t)]

        def one(f, pat):
            t = toks(f, F_) + toks(f, L_)
            if len(t) == 1 and pat.match(t[0]):
                return t[0]
            if t:
                notes.append(f"delayed-with-reasons annexure p{r['page']} sno {r['sno']}: {f} printed as {t} (left blank)")
            return None

        if r["variant"] == "A":
            name, code, agency, state, _ = split_name(" ".join(r["name"]))
            co, cr, do, dr = toks("cost", F_), toks("cost", L_), toks("doc", F_), toks("doc", L_)
        else:
            name, code, agency, state = clean(" ".join(r["name"])), None, clean(" ".join(r["agency"])) or None, None
            co, cr, do, dr = toks("cost", F_) + toks("cost", L_), [], toks("doc", F_) + toks("doc", L_), []
        for f, t, pat in (("cost", co, NUM_RE), ("cost", cr, NUM_RE), ("doc", do, DATE_RE), ("doc", dr, DATE_RE)):
            if len(t) > 1 or (t and not pat.match(t[0])):
                notes.append(f"delayed-with-reasons annexure p{r['page']} sno {r['sno']}: {f} printed as {t} (left blank)")
        reason = clean(" ".join(r["reason"]))
        remarks = [reason] if reason and reason.upper() not in NO_REASON else []
        by_nm = False
        if not code:
            codes = by_name.get(norm_key(name))
            if codes and len(codes) == 1:
                code, by_nm = next(iter(codes)), True
        row = base_row(ctx, r["page"], "other:delayed_wrt_original")
        if by_nm:
            add_dq(row, "code_from_master_by_name")
        row.update({
            "project_code": code, "project_name": name, "sector_raw": strip_marks(r["sector"]),
            "agency": agency, "state": state,
            "doa_original": to_ym(one("doa", DATE_RE)),
            "cost_original_cr": to_num(co[0]) if len(co) == 1 and NUM_RE.match(co[0]) else None,
            "cost_revised_cr": to_num(cr[0]) if len(cr) == 1 and NUM_RE.match(cr[0]) else None,
            "cost_anticipated_cr": to_num(one("cost_a", NUM_RE)),
            "expenditure_cum_cr": to_num(one("exp", NUM_RE)),
            "doc_original": to_ym(do[0]) if len(do) == 1 and DATE_RE.match(do[0]) else None,
            "doc_revised": to_ym(dr[0]) if len(dr) == 1 and DATE_RE.match(dr[0]) else None,
            "doc_anticipated": to_ym(one("doc_a", DATE_RE)),
            "delay_months": to_num(one("tor", NUM_RE)),
            "cost_overrun_pct": to_num(one("cop", NUM_RE)),
            "remarks": "; ".join(remarks) or None,
            "_sno": r["sno"],
        })
        rows.append(placeholder_zeros(row))
    odd = [f"p{r['page']} #{i + 1} printed {r['sno']}" for i, r in enumerate(raw) if r["sno"] != i + 1]
    if odd:  # e.g. Jan 2016 p191 prints '5' for row 95
        notes.append("delayed-with-reasons annexure: serial number misprinted: " + ", ".join(odd[:5]))
    return rows, issues, notes


# ----------------------------------------------------------------------------
# aggregate tables -> summary
# ----------------------------------------------------------------------------
def merge_ranges(ws):
    """'3' '-' '11' -> '3-11'; '0-' '0' -> '0-0' (delay range columns)."""
    out = []
    i = 0
    while i < len(ws):
        w = ws[i]
        t = w[4]
        if (i + 2 < len(ws) and re.fullmatch(r"\d+", t) and ws[i + 1][4] == "-" and re.fullmatch(r"\d+", ws[i + 2][4])
                and ws[i + 2][0] - w[2] < 14):
            out.append((w[0], w[1], ws[i + 2][2], w[3], f"{t}-{ws[i + 2][4]}"))
            i += 3
            continue
        if i + 1 < len(ws) and re.fullmatch(r"\d+-", t) and re.fullmatch(r"\d+", ws[i + 1][4]) and ws[i + 1][0] - w[2] < 10:
            out.append((w[0], w[1], ws[i + 1][2], w[3], t + ws[i + 1][4]))
            i += 2
            continue
        if i + 1 < len(ws) and re.fullmatch(r"\d+", t) and re.fullmatch(r"-\d+", ws[i + 1][4]) and ws[i + 1][0] - w[2] < 10:
            out.append((w[0], w[1], ws[i + 1][2], w[3], t + ws[i + 1][4]))
            i += 2
            continue
        out.append(w)
        i += 1
    return out


VAL_RE = re.compile(r"^-?(?:[\d,]*\.\d+|[\d,]*\d\.?)$")  # also '1087065.' (decimals wrapped)


def is_value(t):
    return bool(VAL_RE.match(t) or RANGE_RE.match(t) or t == "-")


def _wrap_target(row, w):
    """Index of the value in `row` that fragment `w` completes, else None
    ('197,793.0' + '4', '1087065.' + '02'; aligned left or right)."""
    if not re.fullmatch(r"\d{1,2}", w[4]):
        return None
    for i, p in enumerate(row["vals"]):
        if ((abs(p[0] - w[0]) < 4 or abs(p[2] - w[2]) < 4) and re.search(r"\d\.\d?$", p[4])
                and len(p[4].split(".")[1]) + len(w[4]) == 2):
            return i
    return None


def grid_rows(lines, n=None, stop_at_total=True):
    """Rows of an aggregate table: [label words][value words]. Label-only lines
    extend the previous label, value-only lines are wrapped cells of the
    previous row, lone serial numbers are ignored."""
    rows, done, pre = [], False, None
    for ln in lines:
        ws = [tuple(w[:5]) for w in merge_ranges(ln["w"])]
        if not ws:
            continue
        if done:  # after the Total row only its wrapped digits are read
            if rows and ln["y"] - rows[-1]["y"] < 16 and all(_wrap_target(rows[-1], w) is not None for w in ws):
                for w in ws:
                    i = _wrap_target(rows[-1], w)
                    p = rows[-1]["vals"][i]
                    rows[-1]["vals"][i] = (p[0], p[1], max(p[2], w[2]), p[3], p[4] + w[4])
            break
        had_sno = False
        if re.fullmatch(r"\d+\.?", ws[0][4]) and len(ws) > 1 and not is_value(ws[1][4]):
            ws, had_sno = ws[1:], True  # serial number
        elif len(ws) == 1 and re.fullmatch(r"\d+\.", ws[0][4]):
            continue
        # 'ANDAMAN & NICOBAR' / '1  <values>' / 'ISLANDS': the serial number sits on the value
        # line and the label starts on the line above
        pre_row = bool(pre and not had_sno and re.fullmatch(r"\d+\.?", ws[0][4]) and len(ws) > 1
                       and is_value(ws[1][4]) and ln["y"] - pre["y"] < 16 and ws[0][2] < pre["x"])
        if pre_row:
            ws, had_sno = ws[1:], True
        label, vals = [], []
        for w in ws:
            if is_value(w[4]) and (label or rows or pre_row):
                vals.append(w)
            elif vals:
                label = None  # words after numbers: running text, not a table row
                break
            else:
                label.append(w)
        if label is None:
            continue
        if pre_row and vals and all(is_value(w[4]) for w in vals):
            rows.append({"label": pre["t"], "vals": vals, "y": ln["y"]})
            pre = None
            continue
        lab = clean(" ".join(w[4] for w in label))
        if (label and not vals and rows and re.search(r"(?:\bAND|&)$", rows[-1]["label"], re.I)
                and 0 < ln["y"] - rows[-1]["y"] < 30):
            rows[-1]["label"] += " " + lab  # 'ROAD TRANSPORT AND' ... 'HIGHWAYS' printed 19 pt lower
            continue
        near = rows and ln["y"] - rows[-1]["y"] < 16
        wrapped = near and vals and (all(_wrap_target(rows[-1], w) is not None for w in vals) or (
            n and not had_sno and len(vals) <= 2 and len(rows[-1]["vals"]) + len(vals) <= n))
        if label and vals and not wrapped:
            if pre and ln["y"] - pre["y"] < 16 and abs(pre["x"] - label[0][0]) < 4:
                lab = f"{pre['t']} {lab}"  # first label wrapped above its row ('ANDAMAN & NICOBAR' / 'ISLANDS')
            pre = None
            rows.append({"label": lab, "vals": vals, "y": ln["y"]})
            done = stop_at_total and bool(re.match(r"^(Grand\s+)?Total\b", lab, re.I))
            continue
        if label and not vals and not rows:
            pre = {"t": lab, "y": ln["y"], "x": label[0][0]}
            continue
        if label and near and len(label) <= 3:
            prev = rows[-1]["label"]
            last = prev.split(" ")[-1]
            joiner = "" if len(last) >= 14 and last.isupper() and lab.isupper() and len(lab) <= 4 else " "
            rows[-1]["label"] = prev + joiner + lab
        if vals and near:
            for w in vals:
                i = _wrap_target(rows[-1], w)
                if i is not None:
                    p = rows[-1]["vals"][i]
                    rows[-1]["vals"][i] = (p[0], p[1], max(p[2], w[2]), p[3], p[4] + w[4])
                else:
                    rows[-1]["vals"].append(w)
    for r in rows:
        # values from continuation lines go back into column order
        r["vals"] = sorted(((a, b, c, d, t.rstrip(".")) if re.fullmatch(r"[\d,]+\.", t) else (a, b, c, d, t)
                            for a, b, c, d, t in r["vals"]), key=lambda w: w[0] + w[2])
    return rows


def grid_assign(rows, n, issues, where):
    """Assign value words to n columns. Rows with exactly n values define the
    column right edges; other rows are assigned to the nearest edge."""
    full = [r for r in rows if len(r["vals"]) == n]
    if not full:
        issues.append(f"{where}: no row with {n} values (counts {[len(r['vals']) for r in rows]})")
        return []
    edges = []
    for j in range(n):
        xs = sorted(r["vals"][j][2] for r in full)
        edges.append(xs[len(xs) // 2])
    out = []
    for r in rows:
        cols = [None] * n
        if len(r["vals"]) == n:
            cols = [w[4] for w in r["vals"]]
        else:
            for w in r["vals"]:
                j = min(range(n), key=lambda k: abs(edges[k] - w[2]))
                if cols[j] is not None:
                    issues.append(f"{where}: row {r['label']!r} two values for column {j}")
                    cols = None
                    break
                cols[j] = w[4]
            if cols is None:
                continue
        out.append((r["label"], cols))
    return out


def _is_total(label):
    return bool(re.match(r"^(Grand\s+)?Total\b", label, re.I))


GRID_TABLES = {
    # key: (title, dimension, [metric per column]); metrics prefixed 'sub:' belong to the
    # "projects with ..." sub-table and are written under table_title + ' - projects with ...'
    "co_orig_sector": ("Extent of cost overrun w.r.t. original schedule (sector-wise)", "sector",
                       ["n_projects", "cost_original_cr", "cost_anticipated_cr", "cost_overrun_pct",
                        "sub:n_cost_overrun", "sub:cost_original_cr", "sub:cost_anticipated_cr", "sub:cost_overrun_pct"],
                       "projects with cost overrun"),
    "co_orig_state": ("Extent of cost overrun w.r.t. original schedule (state-wise)", "state",
                      ["n_projects", "cost_original_cr", "cost_anticipated_cr", "cost_overrun_pct",
                       "sub:n_cost_overrun", "sub:cost_original_cr", "sub:cost_anticipated_cr", "sub:cost_overrun_pct"],
                      "projects with cost overrun"),
    "to_orig_sector": ("Extent of time overrun w.r.t. original schedule (sector-wise)", "sector",
                       ["n_projects", "cost_original_cr", "cost_anticipated_cr", "cost_overrun_pct",
                        "sub:n_delayed", "sub:cost_original_cr", "sub:cost_anticipated_cr", "sub:range"],
                       "projects with time overrun"),
    "to_orig_state": ("Extent of time overrun w.r.t. original schedule (state-wise)", "state",
                      ["n_projects", "cost_original_cr", "cost_anticipated_cr", "cost_overrun_pct",
                       "sub:n_delayed", "sub:cost_original_cr", "sub:cost_anticipated_cr", "sub:range"],
                      "projects with time overrun"),
    "to_latest": ("Extent of time overrun w.r.t. latest schedule (sector-wise)", "sector",
                  ["n_projects", "cost_original_cr", "cost_anticipated_cr", "cost_overrun_pct",
                   "sub:n_delayed_wrt_latest", "sub:cost_original_cr", "sub:cost_anticipated_cr", "sub:range"],
                  "projects with time overrun"),
    "co_latest": ("Extent of cost overrun w.r.t. latest schedule (sector-wise)", "sector",
                  ["n_projects", "cost_latest_cr", "cost_anticipated_cr", "cost_overrun_pct",
                   "sub:n_cost_overrun", "sub:cost_latest_cr", "sub:cost_anticipated_cr", "sub:cost_overrun_pct"],
                  "projects with cost overrun"),
    "tco_latest": ("Extent of time & cost overrun w.r.t. latest schedule (sector-wise)", "sector",
                   ["n_projects", "cost_original_cr", "cost_anticipated_cr", "cost_overrun_pct",
                    "sub:n_time_and_cost_overrun", "sub:cost_original_cr", "sub:cost_anticipated_cr", "sub:range"],
                   "projects with time & cost overrun"),
    "tco_orig": ("Extent of time & cost overrun w.r.t. original schedule (sector-wise)", "sector",
                 ["n_projects", "cost_original_cr", "cost_anticipated_cr", "cost_overrun_pct",
                  "sub:n_time_and_cost_overrun", "sub:cost_original_cr", "sub:cost_anticipated_cr", "sub:range"],
                 "projects with time & cost overrun"),
    "sect_analysis": ("Sector-wise analysis of projects", "sector",
                      ["n_projects", "cost_original_cr", "cost_latest_cr", "cost_anticipated_cr", "expenditure_cr"],
                      None),
    "annex_state": ("State-wise status of central sector projects (annexure)", "state",
                    ["n_projects", "cost_original_cr", "cost_anticipated_cr", "expenditure_cr"], None),
}


MULTI_PAGE |= set(GRID_TABLES)


def unit_of(metric):
    return "Rs crore" if metric.endswith("_cr") else ("percent" if metric.endswith("_pct") else
                                                       ("months" if "months" in metric else None))


def emit_grid(ctx, pno, key, table, issues, out):
    title, d, metrics, subname = GRID_TABLES[key]
    for label, cols in table:
        dval = "Total" if _is_total(label) else strip_marks(label)
        for metric, v in zip(metrics, cols):
            if v is None or v == "-":
                continue
            t = title
            if metric.startswith("sub:"):
                metric = metric[4:]
                t = f"{title} - {subname}"
            if metric == "range":
                m = RANGE_RE.match(v)
                if not m:
                    issues.append(f"p{pno} {key}: bad range {v!r} for {label!r}")
                    continue
                out.append(summ(ctx, pno, t, d, dval, "min_delay_months", float(m[1]), unit="months"))
                out.append(summ(ctx, pno, t, d, dval, "max_delay_months", float(m[2]), unit="months"))
                continue
            if not NUM_RE.match(v):
                issues.append(f"p{pno} {key}: bad value {v!r} for {label!r}")
                continue
            out.append(summ(ctx, pno, t, d, dval, metric, v, unit=unit_of(metric)))


def parse_grid_section(ctx, key, segs, issues, out):
    """An aggregate table starts at its title and may run onto the next page(s)
    (untitled, or with the title repeated); reading stops at the Total row."""
    if not segs:
        return 0
    pno, rows, last = segs[0][0], [], None
    for p, lines in segs:
        if last is not None and p not in (last, last + 1):
            break
        rows += grid_rows(lines[1:] if title_of(lines[0]["t"]) else lines, len(GRID_TABLES[key][2]))
        last = p
        if rows and _is_total(rows[-1]["label"]):
            break
    n = len(GRID_TABLES[key][2])
    table = grid_assign(rows, n, issues, f"p{pno} {key}")
    if table and not any(_is_total(lb) for lb, _ in table):
        issues.append(f"p{pno} {key}: no Total row")
    before = len(out)
    emit_grid(ctx, pno, key, table, issues, out)
    return len(out) - before


def parse_exec_table(ctx, segs, issues, out):
    """Executive-summary sector table: projects on monitor, delayed (w.r.t.
    latest schedule in 2013-14/2014-15 reports, w.r.t. original later),
    additionally delayed, additionally delayed mega projects."""
    for pno, lines in segs:
        hi = next((i for i, ln in enumerate(lines) if re.search(r"\bSector\b", ln["t"])
                   and re.search(r"monitor", " ".join(x["t"] for x in lines[i:i + 4]), re.I)), None)
        if hi is None:
            continue
        hdr = " ".join(ln["t"] for ln in lines[hi:hi + 5])
        n = 4 if re.search(r"Mega", hdr) else 2
        rows = grid_rows(lines[hi + 1:], n)
        # header words interleave across lines ('Projects w.r.t' / 'latest' / 'schedule')
        basis = "n_delayed_wrt_latest" if re.search(r"latest", hdr, re.I) else "n_delayed"
        metrics = (["n_projects", basis, "n_additional_delay", "n_additional_delay_mega"] if n == 4
                   else ["n_projects", "n_additional_delay"])
        table = grid_assign(rows, n, issues, f"p{pno} exec")
        title = "Executive summary: sector-wise delayed / additionally delayed projects"
        for label, cols in table:
            dval = "Total" if _is_total(label) else strip_marks(label)
            for metric, v in zip(metrics, cols):
                if v not in (None, "-") and NUM_RE.match(v):
                    out.append(summ(ctx, pno, title, "sector", dval, metric, v))
        return len(table)
    issues.append("exec: sector table not found")
    return 0


def parse_status(ctx, segs_status, segs_summary, out):
    """Overall current-status counts ('Number of Projects in Previous Month ...')
    and the brief analysis sentence (status w.r.t. original schedule)."""
    title = "Summary of projects: current status"
    pats = [
        (r"in\s+Previous\s+Month\s+(\d+)$", "n_projects_prev_month"),
        (r"Completed\s*/\s*Dropped\s*/\s*Frozen\s+in\s+Current\s+Month\s+(\d+)$", "n_completed_dropped_frozen"),
        (r"Anti(?:cipated|\.)\s*Cost\s+(?:below|less\s+th[ae]n)\s+Rs\.?\s*150\s*crore.*?\s(\d+)$", "n_below_threshold"),
        (r"added\s+in\s+Current\s+Month\s+(\d+)$", "n_new"),
        (r"^(?:No\.?|Number)\s+of\s+Projects\s+in\s+Current\s+Month\s+(\d+)$", "n_projects"),
    ]
    got = {}
    for segs in (segs_summary[:1], segs_status[:1]):
        for pno, lines in segs:
            for ln in lines:
                t = re.sub(r"^(?:I\.\s*)?", "", ln["t"])
                for p, metric in pats:
                    m = re.search(p, t, re.I)
                    if m and metric not in got:
                        got[metric] = (pno, m[1])
                        break
    for metric, (pno, v) in got.items():
        out.append(summ(ctx, pno, title, "overall", "Total", metric, v))
    if segs_summary:
        pno, lines = segs_summary[0]
        text = " ".join(ln["t"] for ln in lines)
        m = re.search(r"Status with respect to Original\s*Schedule\s*:\s*Out of\s*(\d+)\s*projects,(.*?)(?:Investment|$)",
                      text, re.I)
        if m:
            body = m[2]
            t2 = "Brief analysis: status w.r.t. original schedule"
            for p, metric in ((r"(\d+)\s*projects?\s*(?:is|are)\s*ahead", "n_ahead"),
                              (r"(\d+)\s*projects?\s*(?:is|are)\s*on\s*schedule", "n_on_schedule"),
                              (r"(\d+)\s*projects?\s*(?:is|are)\s*delayed", "n_delayed"),
                              (r"(\d+)\s*projects?\s*do(?:es)?\s*not\s*have\s*fixed", "n_without_doc"),
                              (r"(\d+)\s*projects?\s*(?:were|was)\s*sanctioned\s*without", "n_without_odc_but_doc")):
                mm = re.search(p, body.replace(",", ", "), re.I)
                if mm:
                    out.append(summ(ctx, pno, t2, "overall", "Total", metric, mm[1]))
            out.append(summ(ctx, pno, t2, "overall", "Total", "n_projects", m[1]))
    return got


SECTOR_STATUS = [
    (r"^$", "n_projects"), (r"^On\s*Schedule$", "n_on_schedule"), (r"^Delayed$", "n_delayed"),
    (r"^Ahead(?:\s*of\s*Schedule)?$", "n_ahead"), (r"^Without\s*Date\s*Of\s*Commissioning$", "n_without_doc"),
    (r"^Without\s*Original\s*Date\s*Of\s*Commissioning.*$", "n_without_odc_but_doc"),
]


def parse_sector_status(ctx, segs, sector_names, out, issues):
    """Per-sector 'Current Status' pages. The printed sector name is sometimes
    cut ('ROAD TRANSPORT AND HIGHW'); it is mapped to the master-list sector
    name it is a prefix of."""
    title = "Sector-wise current status of projects"
    n = 0
    for pno, lines in segs:
        sector = None
        for ln in lines[1:4]:
            k = norm_key(ln["t"])
            hits = [nm for nm in sector_names if len(k) >= 4 and norm_key(nm).startswith(k)]
            if len(hits) == 1:
                sector = hits[0]
                break
        if not sector:
            issues.append(f"p{pno} sector_status: sector name not found")
            continue
        for ln in lines:
            m = re.match(r"^Number\s+of\s+Projects\s*(.*?)\s+(-?\d+)$", ln["t"])
            if not m:
                continue
            metric = next((mt for p, mt in SECTOR_STATUS if re.match(p, m[1], re.I)), None)
            if metric is None:
                issues.append(f"p{pno} sector_status: unknown label {m[1]!r}")
                continue
            out.append(summ(ctx, pno, title, "sector", strip_marks(sector), metric, m[2]))
            n += 1
    return n


def parse_milestones(ctx, segs, out):
    for pno, lines in segs[:1]:
        t = "Milestones (cumulative due & achieved)"
        for ln in lines:
            m = re.match(r"^Total\s+(\d+)$", ln["t"])
            if m:
                out.append(summ(ctx, pno, t, "overall", "Total", "n_milestones_due", m[1]))
            m = re.match(r"^Achieved\s+up\s+to\s+month\s+(\d+)$", ln["t"])
            if m:
                out.append(summ(ctx, pno, t, "overall", "Total", "n_milestones_achieved", m[1]))


# ----------------------------------------------------------------------------
# per report
# ----------------------------------------------------------------------------
def stated_total(doc):
    for i in range(min(60, doc.page_count)):
        t = " ".join(doc[i].get_text().split())
        m = re.search(r"Flash Report for\s*([A-Za-z]+)\s*,?\s*(\d{4})\s*contains information on the status of the\s*(\d+)", t)
        if m:
            return to_ym(f"{m[1]} {m[2]}"), int(m[3])
    return None, None


def process(path):
    doc = fitz.open(path)
    ctx = {"period": period_from_name(path), "src": rel(path)}
    notes, issues = [], []
    sec, n_hindi = sections(doc)
    for k in ("added", "addl", "cur_cmpl"):  # sector headings of these lists are told apart by weight
        for pno, lines in sec.get(k, []):
            mark_bold(doc[pno - 1], lines)
    title_ym, stated = stated_total(doc)
    if title_ym != ctx["period"]:
        notes.append(f"title month {title_ym} differs from file name {ctx['period']}")

    projects, summary = [], []
    ong, ong_sum, iss = parse_ongoing(ctx, sec.get("ongoing", []))
    projects += ong
    summary += ong_sum
    issues += [f"ongoing {x}" for x in iss]
    # data-currency footnotes (stale Railways / NHAI data) anywhere in the report
    text = " ".join(" ".join(p.get_text().split()) for p in doc)
    for pat in (r"Information in respect of Ministry of Railways is as on [\d.]+",
                r"information\s*/\s*data \(as on \w+ \d{4}\) has been used in respect of all projects of Railways",
                r"Out of \d+ projects, the data\s*/\s*information of only \d+ projects were submitted online by the NHAI"
                r" for the month of \w+ \d{4}",
                r"The information\s*/\s*data of\s*(?:\d+\s*)?Road Sector Projects have not been updated online by the NHAI"):
        m = re.search(pat, text, re.I)
        if m:
            notes.append(f"footnote: {m[0]}")
    sector_keys = {norm_key(r["sector_raw"]).rstrip("S") for r in ong}
    agencies = {r["agency"].upper() for r in ong if r["agency"]}
    by_name = {}
    for r in ong:
        by_name.setdefault(norm_key(r["project_name"]), set()).add(r["project_code"])

    mw = {}
    for key, lt in (("cmpl_mw", "completed"), ("del_mw", "dropped")):
        rows, iss = parse_monthwise(ctx, sec.get(key, []), lt)
        mw[lt] = rows
        issues += [f"{key} {x}" for x in iss]

    cc, iss = parse_cur_cmpl(ctx, sec.get("cur_cmpl", []), sector_keys)
    issues += [f"cur_cmpl {x}" for x in iss]
    mw["cur_cmpl"] = cc
    dly, iss, dnotes = parse_delayed(ctx, sec.get("delayed_rsn", []), doc, sector_keys, by_name)
    issues += iss
    notes += dnotes[:8] + ([f"... {len(dnotes) - 8} more"] if len(dnotes) > 8 else [])
    ong_by_code = {r["project_code"]: r for r in ong if r["project_code"]}
    for r in dly:
        o = ong_by_code.get(r["project_code"])
        for f in ("project_name", "agency", "state"):
            if o and r[f] and o[f] and r[f] != o[f] and norm_key(r[f]) == norm_key(o[f]):
                r[f] = o[f]  # the narrow annexure column breaks words ('GUJAR' / 'AT'); same text in the master list
    projects += dly

    added, iss = parse_added(ctx, sec.get("added", []), sector_keys)
    issues += [f"added {x}" for x in iss]
    addl, addl_total, iss = parse_addl(ctx, sec.get("addl", []), sector_keys, agencies)
    issues += [f"addl {x}" for x in iss]
    for lst in (added, addl):
        seen = Counter(norm_key(r["project_name"]) for r in lst)
        dup = {k for k, c in seen.items() if c > 1}
        for r in lst:
            codes = by_name.get(norm_key(r["project_name"]))
            if not codes or len(codes) != 1 or norm_key(r["project_name"]) in dup:
                continue  # only an unambiguous exact-name match is used
            r["project_code"] = next(iter(codes))
            add_dq(r, "code_from_master_by_name")
    projects += added + addl
    projects = [fix_placeholder_dates(r) for r in projects]
    n_dup = flag_exact_duplicates(projects)
    if n_dup:
        notes.append(f"{n_dup} project row(s) printed twice with identical values in the same list; "
                     "all kept as printed (dq_note duplicate_in_source)")
    if addl_total is not None:
        summary.append(summ(ctx, sec["addl"][-1][0], "List of projects reporting additional delays", "overall",
                            "Total", "n_additional_delay", addl_total))
        if addl_total != len(addl):
            issues.append(f"addl: printed count {addl_total} != rows {len(addl)}")

    for key in GRID_TABLES:
        parse_grid_section(ctx, key, sec.get(key, []), issues, summary)
    parse_exec_table(ctx, sec.get("exec", []), issues, summary)
    status = parse_status(ctx, sec.get("status", []), sec.get("summary_page", []), summary)
    parse_sector_status(ctx, sec.get("sector_status", []), {r["sector_raw"] for r in ong}, summary, issues)
    parse_milestones(ctx, sec.get("milestones", []), summary)

    # consistency with the report's own totals
    n_ong = len(ong)
    snos = [r["_sno"] for r in ong]
    if snos != list(range(1, n_ong + 1)):
        issues.append("ongoing serial numbers not contiguous")
    grand = [s for s in ong_sum if s["dimension"] == "overall" and s["metric"] == "cost_original_cr"]
    if grand:
        tot = sum(r["cost_original_cr"] or 0 for r in ong)
        if abs(tot - grand[0]["value"]) > max(1.0, 0.0005 * grand[0]["value"]):
            issues.append(f"ongoing: sum original cost {tot:.2f} != grand total {grand[0]['value']}")
    for s in ong_sum:
        if s["dimension"] == "sector" and s["metric"] == "cost_anticipated_cr":
            tot = sum(r["cost_anticipated_cr"] or 0 for r in ong if r["sector_raw"] == s["dimension_value"])
            if abs(tot - s["value"]) > max(1.0, 0.0005 * s["value"]):
                issues.append(f"ongoing: sector {s['dimension_value']} anticipated sum {tot:.2f} != total {s['value']}")
    nd = next((s["value"] for s in summary if s and s["table_title"].startswith("Brief analysis")
               and s["metric"] == "n_delayed"), None)
    if dly and nd is not None and nd != len(dly):
        issues.append(f"delayed-with-reasons annexure has {len(dly)} rows; summary page says {nd:.0f} delayed")
    ncdf = status.get("n_completed_dropped_frozen")
    if ncdf and int(ncdf[1]) != len(cc):  # May 2014 prints 2 of 5, Nov 2014 15 of 16 (checked on the page)
        notes.append(f"current-month completed/dropped/frozen list prints {len(cc)} rows; status page says {ncdf[1]}")
    summary, n_sd = dedupe_summary(summary)
    if n_sd:
        notes.append(f"{n_sd} summary row(s) repeated with identical key and value (page printed twice); kept the first")
    cur_n = status.get("n_projects")
    if cur_n and int(cur_n[1]) != n_ong:
        notes.append(f"summary page says {cur_n[1]} projects in current month; master list has {n_ong}")
    if stated and stated != n_ong:
        notes.append(f"executive summary states {stated} projects; master list has {n_ong} rows")
    info = {"pages": doc.page_count, "stated": stated, "n_hindi": n_hindi,
            "sections": {k: [p for p, _ in v] for k, v in sec.items()}}
    return ctx, projects, mw, summary, issues, notes, info


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------
def name_sim(a, b):
    a, b = norm_key(a), norm_key(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if min(len(a), len(b)) >= 15 and (a.startswith(b) or b.startswith(a)):
        return 0.95  # truncated name
    return difflib.SequenceMatcher(None, a, b).ratio()


def master_index(rows):
    """code -> names / original costs, and normalised name -> codes, over the
    master lists of all reports (a project code never changes meaning)."""
    names, costs, by_key = {}, {}, {}
    for r in rows:
        c = r["project_code"]
        if c:
            names.setdefault(c, set()).add(r["project_name"])
            costs.setdefault(c, set()).add(r["cost_original_cr"])
            by_key.setdefault(norm_key(r["project_name"]), set()).add(c)
    return names, costs, by_key


def code_by_name(name, idx):
    """Unique master-list code for a name (exact normalised match, else a
    unique prefix match for truncated names), else None."""
    by_key, k = idx[2], norm_key(name)
    codes = by_key.get(k)
    if not codes and len(k) >= 20:
        codes = {c for kk, cs in by_key.items() if len(kk) >= 20 and (kk.startswith(k) or k.startswith(kk)) for c in cs}
    return next(iter(codes)) if codes and len(codes) == 1 else None


def verify_code(r, idx):
    """The month-wise deleted lists of Nov 2014 - Oct 2015 print other projects'
    codes. A printed code is kept when its master-list name matches (or the
    original cost matches and the name is close); otherwise it is replaced by
    the unique master-list code of the name, or blanked. A code that is in no
    master list cannot be checked and is kept. Returns a dq_note flag or None:
    code_misprint:<printed code> (it belongs to another master-list project;
    replaced by the name match, or blanked) or code_from_master_by_name."""
    names, costs = idx[0], idx[1]
    code, nm = r["project_code"], r["project_name"]
    if code and code in names:
        sim = max(name_sim(nm, x) for x in names[code])
        if sim >= 0.8 or (sim >= 0.4 and r["cost_original_cr"] in costs[code]):
            return None
        r["project_code"] = code_by_name(nm, idx)
        return f"code_misprint:{code}"
    if not code:
        fix = code_by_name(nm, idx)
        if fix:
            r["project_code"] = fix
            return "code_from_master_by_name"
    return None


def same_event(a, b):
    if a["project_code"] and a["project_code"] == b["project_code"]:
        return True
    return (norm_key(a["project_name"]) == norm_key(b["project_name"])
            and a["cost_original_cr"] == b["cost_original_cr"] and a["doc_original"] == b["doc_original"])


def dedupe_events(mw_by_report, list_type, idx):
    """completed/dropped: the month-wise lists are FY-to-date and repeat every
    month, sometimes under a different (wrong) code, so each project is kept
    once, from the earliest report of the FY that lists it. Two listings are
    the same project when their verified codes agree or when name, original
    cost and original DOC agree (from a different report or month heading;
    Dec 2015 lists three NH-67 entries with distinct codes under one month)."""
    seen_code, seen_name, out = set(), {}, []
    word = "completed" if list_type == "completed" else "deleted"
    for period, rows in sorted(mw_by_report, key=lambda x: x[0]):
        for r in rows:
            r["_code_note"] = verify_code(r, idx)
            fy = r["fiscal_year"]
            kc = (fy, r["project_code"]) if r["project_code"] else None
            kn = (fy, norm_key(r["project_name"]), r["cost_original_cr"], r["doc_original"])
            where = (period, r["_month"])
            if (kc and kc in seen_code) or (kn in seen_name and seen_name[kn] != where):
                continue
            if kc:
                seen_code.add(kc)
            seen_name.setdefault(kn, where)
            m = r["_month"]
            ym = to_ym(m.replace(",", " ")) if m else None
            misyear = bool(ym and ym[5:] == period[5:] and ym != period)
            if misyear:  # heading year misprinted: no completion date taken from it
                add_dq(r, f"month_heading_year_differs_from_report:{m.replace(',', ' ')}")
            if list_type == "completed":
                r["date_completed_actual"] = None if misyear else ym  # the month heading it is listed under
            elif m:
                r["remarks"] = f"listed under '{m}' in the month-wise {word} list"
            if r["_code_note"]:
                add_dq(r, r["_code_note"])
            out.append(r)
    return out


def withdrawn_completions(kept, mw_by_report):
    """Completed rows missing from the FY-to-date list of the FY's last report
    that prints the list: the source withdrew the completion."""
    last = {}
    for period, rows in mw_by_report:
        fy = fiscal_year(period)
        if rows and (fy not in last or period > last[fy][0]):
            last[fy] = (period, rows)
    out = []
    for r in kept:
        lp = last.get(r["fiscal_year"])
        if lp and lp[0] > r["report_period"] and not any(same_event(r, x) for x in lp[1]):
            out.append((r, lp[0]))
    return out


def attach_cur_cmpl(cc_by_report, kept, idx, ong_periods):
    """'List of projects completed/dropped/Frozen during current month' (no codes)
    adds DOA, now-anticipated cost and DOC (the completion month for completed
    projects) and final expenditure to the matching completed/deleted row of the
    FY (same name, or close name with the same original cost). `kept` also holds
    withdrawn completions, which absorb their entries without being emitted.
    Unmatched entries were dropped or frozen; the list does not say which.
    Returns the rows for list_type other:dropped_or_frozen."""
    extra, seen = [], set()
    for period, rows in sorted(cc_by_report, key=lambda x: x[0]):
        cands = [r for r in kept if r["fiscal_year"] == fiscal_year(period)]
        for c in rows:
            best = []
            for r in cands:
                s = round(name_sim(c["project_name"], r["project_name"]), 3)
                if s >= 0.9 or (s >= 0.6 and r["cost_original_cr"] == c["cost_original_cr"]):
                    raw = difflib.SequenceMatcher(None, c["project_name"].upper(), r["project_name"].upper()).ratio()
                    best.append((s, raw, r))
            if best:
                top = max(x[0] for x in best)
                best = [x for x in best if x[0] == top]
                same_cost = [x for x in best if x[2]["cost_original_cr"] == c["cost_original_cr"]]
                best = same_cost or best
                # duplicate entries of one project tie (Dec 2015: three NH-67 rows); take one not
                # matched yet, first listed in this report, with the closest literal name
                best.sort(key=lambda x: (bool(x[2].get("_cc")), x[2]["report_period"] != period, -x[1]))
                r = best[0][2]
                if r.get("_cc"):
                    continue  # listed again in a later month's list
                r["_cc"] = True
                got = []
                for f in ("doa_original", "cost_anticipated_cr", "doc_anticipated", "expenditure_cum_cr"):
                    if r.get(f) is None and c[f] is not None:
                        r[f] = c[f]
                        got.append(f)
                if got:
                    add_dq(r, f"from_current_month_list:{period}:p{c['page']}:{','.join(got)}")
                if "placeholder_zero:expenditure_cum_cr" in (c.get("dq_note") or "") and r["expenditure_cum_cr"] is None:
                    add_dq(r, "placeholder_zero:expenditure_cum_cr")  # '.00' there, N.A. in the month-wise list
                if c["expenditure_cum_cr"] is not None and r["expenditure_cum_cr"] not in (None, c["expenditure_cum_cr"]):
                    add_dq(r, f"current_month_list_expenditure:{c['expenditure_cum_cr']}")
                continue
            kn = (c["fiscal_year"], norm_key(c["project_name"]), c["cost_original_cr"], c["doc_original"])
            if kn in seen:
                continue
            seen.add(kn)
            code = code_by_name(c["project_name"], idx)
            c["project_code"] = code
            back = sorted(p for p in ong_periods.get(code, ()) if p > period)
            # in the current-month list but in neither month-wise list: the source does not say dropped or frozen
            add_dq(c, "not_in_monthwise_lists")
            if code:
                add_dq(c, "code_from_master_by_name")
            if back:
                c["remarks"] = f"the project is in the master list again from {back[0]}"
            extra.append(c)
    return extra


def dedupe_summary(rows):
    """A page printed twice (Jul 2015 pp118-119, TELECOMMUNICATIONS status)
    yields identical summary rows; keep the first page's."""
    seen, out = set(), []
    for s in rows:
        if not s:
            continue
        k = tuple(s[c] for c in ("table_title", "dimension", "dimension_value", "sub_dimension_value", "metric", "value"))
        if k not in seen:
            seen.add(k)
            out.append(s)
    return out, sum(1 for s in rows if s) - len(out)


def fix_placeholder_dates(r, doa=None):
    """Railway entries carry '01/1999' as a dummy commissioning date (earlier
    than their approval, `doa` when the row prints none); such dates are left
    blank, with every delay computed from them. dq_note placeholder_doc_1999."""
    hit = [c for c in ("doc_original", "doc_revised", "doc_anticipated") if r.get(c) == "1999-01"]
    doa = r.get("doa_original") or doa
    if hit and doa and doa > "1999-01":
        for c in hit:
            r[c] = None
        if {"doc_original", "doc_anticipated"} & set(hit):
            r["delay_months"] = None
        if r.get("remarks") and {"doc_revised", "doc_anticipated"} & set(hit):
            r["remarks"] = "; ".join(x for x in r["remarks"].split("; ")
                                     if not x.startswith("delay w.r.t. revised schedule")) or None
        add_dq(r, "placeholder_doc_1999")
    return r


def flag_exact_duplicates(rows):
    """Rows printed twice in the same list with identical values (Jul 2014
    N18000169, sno 221/222) are all kept, as printed (the report's own totals
    count both), and flagged duplicate_in_source. Rows without a code are not
    flagged: distinct projects can share a (truncated) name and identical figures
    (Dec 2015 newly added: NH-67 entries). Returns the number of extra copies."""
    groups = {}
    for r in rows:
        if not r.get("project_code"):
            continue
        key = tuple((k, v) for k, v in sorted(r.items()) if k not in ("page", "_sno", "dq_note"))
        groups.setdefault(key, []).append(r)
    n = 0
    for g in groups.values():
        if len(g) > 1:
            n += len(g) - 1
            for r in g:
                add_dq(r, "duplicate_in_source")
    return n


def main(cache=None):
    """cache: optional {file name: process() result} (used while developing)."""
    files = sorted((p for d in SRC_DIRS for p in d.glob("*.pdf")), key=period_from_name)
    results, failed = [], []
    for path in files:
        try:
            res = cache[path.name] if cache and path.name in cache else process(path)
        except Exception as e:  # keep going; record the failure
            failed.append((rel(path), repr(e)))
            results.append((path, None, repr(e)))
            print(f"FAILED {path.name}: {e!r}")
            continue
        results.append((path, res, None))
    assemble(results)
    return failed


def assemble(results):
    all_proj, all_summ, manifest = [], [], []
    mw_rows = {"completed": [], "dropped": [], "cur_cmpl": []}
    for path, res, err in results:
        if res is None:
            manifest.append({"source_file": rel(path), "report_type": REPORT_TYPE,
                             "report_period": period_from_name(path), "status": "failed", "notes": err})
            continue
        ctx, projects, mw, summary, issues, notes, info = res
        for lt in mw:
            mw_rows[lt].append((ctx["period"], mw[lt]))
        all_proj += projects
        all_summ += [s for s in summary if s]
        n_ong = sum(r["list_type"] == "ongoing" for r in projects)
        status = "ok" if n_ong and not issues else ("partial" if n_ong else "failed")
        notes = notes + [f"{len(issues)} parser warnings: " + " | ".join(issues[:6])] if issues else notes
        manifest.append({
            "source_file": ctx["src"], "report_type": REPORT_TYPE, "report_period": ctx["period"],
            "pages": info["pages"], "parser_variant": "fitz-words: sections by title; master list anchored on column-number row",
            "stated_total_projects": info["stated"], "rows_ongoing": n_ong,
            "rows_other": sum(r["list_type"] not in ("ongoing",) for r in projects),
            "rows_summary": sum(1 for s in summary if s), "status": status,
            "notes": notes,
            "_mw": {lt: len(v) for lt, v in mw.items()},
        })
        print(f"{path.name:22s} {ctx['period']} ongoing={n_ong:5d} stated={info['stated']} other={manifest[-1]['rows_other']:4d}"
              f" summary={manifest[-1]['rows_summary']:4d} warnings={len(issues)}")

    idx = master_index([r for r in all_proj if r["list_type"] == "ongoing"])
    kept = {lt: dedupe_events(mw_rows[lt], lt, idx) for lt in ("completed", "dropped")}
    wd = withdrawn_completions(kept["completed"], mw_rows["completed"])
    wd_ids = {id(r) for r, _ in wd}
    kept["completed"] = [r for r in kept["completed"] if id(r) not in wd_ids]
    ong_periods = {}
    for r in all_proj:
        if r["list_type"] == "ongoing" and r["project_code"]:
            ong_periods.setdefault(r["project_code"], set()).add(r["report_period"])
    extra = attach_cur_cmpl(mw_rows["cur_cmpl"], kept["completed"] + kept["dropped"] + [r for r, _ in wd], idx,
                            ong_periods)
    by_src = {m["source_file"]: m for m in manifest}
    for r, later in wd:
        m = by_src[r["source_file"]]
        m["notes"].append(f"completed project '{r['project_name']}' ({r['project_code']}) is not in the FY-to-date completed "
                          f"list of the {later} report (completion withdrawn by the source); not emitted")
    events = kept["completed"] + kept["dropped"] + extra
    doa_by_code = {r["project_code"]: r["doa_original"] for r in all_proj
                   if r["list_type"] == "ongoing" and r["project_code"] and r["doa_original"]}
    for r in events:  # the month-wise lists print no DOA; the master list's is used for the 01/1999 check
        fix_placeholder_dates(r, doa_by_code.get(r["project_code"]))
    all_proj += events
    for m in manifest:
        mwc = m.pop("_mw", {})
        if m.get("status") == "failed":
            continue
        mine = [r for r in events if r["source_file"] == m["source_file"]]
        n_c = sum(r["list_type"] == "completed" for r in mine)
        n_d = sum(r["list_type"] == "dropped" for r in mine)
        n_f = sum(r["list_type"] == "other:dropped_or_frozen" for r in mine)
        m["rows_completed"] = n_c
        m["rows_other"] += n_d + n_f
        fixed = sum(1 for r in mine if "code_misprint:" in (r.get("dq_note") or ""))
        m["notes"].append(
            f"month-wise lists printed {mwc.get('completed', 0)} completed / {mwc.get('dropped', 0)} deleted rows (FY to date); "
            f"kept {n_c} / {n_d} first appearances" + (f" ({fixed} with a misprinted code)" if fixed else "")
            + f"; current-month completed/dropped/frozen list: {mwc.get('cur_cmpl', 0)} rows, {n_f} in neither month-wise list")
        m["notes"] = "; ".join(m["notes"]) or None
    for r in all_proj:
        for k in [k for k in r if k.startswith("_")]:
            del r[k]
    write_part(all_proj, FAMILY, "projects", PROJECT_COLS)
    write_part(all_summ, FAMILY, "summary", SUMMARY_COLS)
    write_part(manifest, FAMILY, "manifest", MANIFEST_COLS)
    print(f"projects={len(all_proj)} summary={len(all_summ)} files={len(manifest)} withdrawn={len(wd)}")


# ----------------------------------------------------------------------------
# self-check of the trickiest parsing helpers
# ----------------------------------------------------------------------------
def selftest():
    # master-list name cell
    assert split_name("KAKRAPAR ATOMIC POWER PROJECT - 3 and 4 - [N02000010]NPCIL,Gujarat") == \
        ("KAKRAPAR ATOMIC POWER PROJECT - 3 and 4", "N02000010", "NPCIL", "Gujarat", None)
    assert split_name("NH-X - [N24000166]NHAI,BIHAR , PPP (ANNUITY) - - -") == \
        ("NH-X", "N24000166", "NHAI", "BIHAR", "PPP (ANNUITY)")
    assert split_name("KULDA OCP - [060100092]MCL,ODISHA , .")[2:4] == ("MCL", "ODISHA")
    assert split_name("GONDA LOOP - [N22000345],UTTAR PRADESH , .")[1:4] == ("N22000345", None, "UTTAR PRADESH")
    # month-wise list name cell with nested brackets
    assert split_paren_agency("EXPANSION OF DURGAPUR STEEL PLANT (STEEL AUTHORITY OF INDIA LIMITED (SAIL)) - [N12000074]") == \
        ("EXPANSION OF DURGAPUR STEEL PLANT", "STEEL AUTHORITY OF INDIA LIMITED (SAIL)", "N12000074")
    assert split_paren_agency("KOLDAM HEP (NTPC) (NATIONAL THERMAL POWER CORPORATION) - [180100211]") == \
        ("KOLDAM HEP (NTPC)", "NATIONAL THERMAL POWER CORPORATION", "180100211")
    # column assignment by right edge (Apr-2013 anchors): cost '-', DOC, delay, milestones
    C = [100, 173, 256.5, 301.5, 346.5, 391.5, 436.5, 477, 513, 549]
    assert ongoing_col((98.3, 0, 101.9, 0, "1"), C) == 1
    assert ongoing_col((113.1, 0, 148.8, 0, "KAKRAPAR"), C) == 2
    assert ongoing_col((244.6, 0, 268.4, 0, "10/2009"), C) == 3
    assert ongoing_col((320.4, 0, 322.6, 0, "-"), C) == 4
    assert ongoing_col((338.3, 0, 367.5, 0, "11,459.00"), C) == 5
    assert ongoing_col((387.0, 0, 412.5, 0, "2,771.00"), C) == 6
    assert ongoing_col((435.4, 0, 437.6, 0, "-"), C) == 7
    assert ongoing_col((465.1, 0, 488.8, 0, "11/2016"), C) == 8
    assert ongoing_col((511.9, 0, 514.1, 0, "-"), C) == 9
    assert ongoing_col((538.9, 0, 559.0, 0, "39/106"), C) == 10
    assert merge_wrapped(["1,058,599.4", "5"]) == ["1,058,599.45"]
    assert [w[4] for w in merge_ranges([(500, 0, 505, 0, "3"), (508, 0, 511, 0, "-"), (514, 0, 520, 0, "11")])] == ["3-11"]
    assert strip_marks("RAILWAYS *") == "RAILWAYS" and strip_marks("ROAD TRANSPORT AND HIGHWAYS **") == "ROAD TRANSPORT AND HIGHWAYS"
    # a table row with a value wrapped onto the next line
    L = [{"y": 10, "w": [(50, 0, 55, 0, "10"), (77, 0, 100, 0, "HEAVY"), (182, 0, 186, 0, "1"),
                         (230, 0, 259, 0, "1,718.00"), (371, 0, 375, 0, "1")]},
         {"y": 20, "w": [(77, 0, 110, 0, "INDUSTRY"), (330, 0, 353, 0, "122.78")]},
         {"y": 30, "w": [(90, 0, 107, 0, "Total"), (230, 0, 259, 0, "107,142.1"), (303, 0, 336, 0, "1087065.")]},
         {"y": 40, "w": [(255, 0, 259, 0, "6"), (303, 0, 310, 0, "02")]}]
    g = grid_rows(L, 4)
    assert g[0]["label"] == "HEAVY INDUSTRY" and [w[4] for w in g[0]["vals"]] == ["1", "1,718.00", "122.78", "1"]
    assert [w[4] for w in g[1]["vals"]] == ["107,142.16", "1087065.02"]
    # label wrapped 19 pt below its row ('ROAD TRANSPORT AND' .. 'HIGHWAYS'), with a lone serial in between
    L = [{"y": 340, "w": [(86, 0, 130, 0, "ROAD"), (137, 0, 215, 0, "TRANSPORT"), (222, 0, 240, 0, "AND"),
                          (274, 0, 290, 0, "138"), (353, 0, 363, 0, "89")]},
         {"y": 350, "w": [(55, 0, 62, 0, "2.")]},
         {"y": 359, "w": [(104, 0, 150, 0, "HIGHWAYS")]},
         {"y": 380, "w": [(86, 0, 120, 0, "POWER"), (274, 0, 290, 0, "102"), (353, 0, 363, 0, "52")]}]
    assert [r["label"] for r in grid_rows(L, 2)] == ["ROAD TRANSPORT AND HIGHWAYS", "POWER"]
    # serial number on the value line, label above and below it (Apr 2015 state annexure)
    L = [{"y": 173.6, "w": [(129, 0, 170, 0, "ANDAMAN"), (181, 0, 187, 0, "&"), (191, 0, 230, 0, "NICOBAR")]},
         {"y": 180.8, "w": [(85, 0, 90, 0, "1"), (272, 0, 277, 0, "1"), (320, 0, 350, 0, "314.61"),
                            (392, 0, 420, 0, "314.61"), (472, 0, 495, 0, "17.82")]},
         {"y": 188.1, "w": [(162, 0, 200, 0, "ISLANDS")]},
         {"y": 202.6, "w": [(85, 0, 90, 0, "2"), (139, 0, 175, 0, "ANDHRA"), (181, 0, 220, 0, "PRADESH"),
                            (269, 0, 277, 0, "27"), (313, 0, 350, 0, "24,854.07"), (385, 0, 420, 0, "31,076.50"),
                            (462, 0, 495, 0, "19,298.43")]}]
    g = grid_rows(L, 4)
    assert [r["label"] for r in g] == ["ANDAMAN & NICOBAR ISLANDS", "ANDHRA PRADESH"] and len(g[0]["vals"]) == 4
    assert is_blank("0/0") and is_blank("N.A.") and not is_blank("03/2015")
    # wrapped name line 'MINE' (regular weight) under an open row is not the sector MINES (Dec 2015 p65)
    L = [{"y": 240, "w": [(103, 0, 300, 0, "hdr")]},
         {"y": 250, "w": [(103, 0, 130, 0, "COAL")], "bold": True},
         {"y": 311, "w": [(85, 0, 90, 0, "1"), (103, 0, 200, 0, "MUNGOLI"), (289, 0, 320, 0, "11/2015")], "bold": False},
         {"y": 321, "w": [(103, 0, 125, 0, "MINE")], "bold": False},
         {"y": 334, "w": [(85, 0, 90, 0, "2"), (103, 0, 130, 0, "HURA"), (289, 0, 320, 0, "10/2015")], "bold": False}]
    for ln in L:
        ln["t"] = " ".join(w[4] for w in ln["w"])
    raw, _ = parse_anchored_list([(65, L)], lambda ls: (0, {"doa": 305, "_name": 103}), {"COAL", "MINE"})
    assert raw[0]["name"] == ["MUNGOLI", "MINE"] and raw[1]["sector"] == "COAL"
    # 01/1999 placeholder DOC: blanked with the delay computed from it
    r = fix_placeholder_dates({"doa_original": "1999-04", "doc_original": "1999-01", "doc_anticipated": "2016-03",
                               "delay_months": 206.0})
    assert r["doc_original"] is None and r["delay_months"] is None and r["dq_note"] == "placeholder_doc_1999"
    assert fix_placeholder_dates({"doc_original": "1999-01"}, "2000-02")["doc_original"] is None
    rows = [{"project_code": "N18000169", "cost_original_cr": 288.49, "_sno": s} for s in (221, 222)]
    assert flag_exact_duplicates(rows) == 1 and len(rows) == 2 and rows[1]["dq_note"] == "duplicate_in_source"
    # delayed-with-reasons annexure: the reasons column starts right at its rule (466), left of the midpoint 477
    pts = [66, 122, 186, 226, 266, 307, 349, 385, 419, 451, 502]
    b, n_mid = col_bounds(pts, [54, 77, 167, 205, 247, 285, 330, 368, 402, 436, 466, 538])
    assert n_mid == 0 and b[-1] == 466 and DLY_FIELDS["A"][bisect.bisect(b, 473)] == "reason"
    assert DLY_FIELDS["A"][bisect.bisect(b, 451)] == "cop"
    # a deleted-list row printed with another project's code
    idx = master_index([{"project_code": "N06000019", "project_name": "BINA EXTN. PROJ(6.0 MTPA)", "cost_original_cr": 1.0},
                        {"project_code": "300100001", "project_name": "PAGLADIYA DAM PROJECT", "cost_original_cr": 542.9}])
    r = {"project_code": "N06000019", "project_name": "PAGLADIYA DAM PROJECT", "cost_original_cr": 542.9}
    assert verify_code(r, idx) == "code_misprint:N06000019" and r["project_code"] == "300100001"
    r = {"project_code": "300100001", "project_name": "Pagladiya Dam Project", "cost_original_cr": 542.9}
    assert verify_code(r, idx) is None and r["project_code"] == "300100001"
    # re-listed in a later report under another wrong code -> kept once, from the first report
    ev = lambda per, code, mon: {"fiscal_year": "2014-15", "project_code": code, "project_name": "PAGLADIYA DAM PROJECT",
                                 "cost_original_cr": 542.9, "doc_original": "2007-12", "_month": mon, "report_period": per}
    kept = dedupe_events([("2014-11", [ev("2014-11", "N06000019", "October,2014")]),
                          ("2014-12", [ev("2014-12", "180100250", "October,2014")])], "dropped", idx)
    assert len(kept) == 1 and kept[0]["report_period"] == "2014-11" and kept[0]["project_code"] == "300100001"
    print("selftest ok")


if __name__ == "__main__":
    selftest()
    if "--selftest" not in sys.argv:
        main()
