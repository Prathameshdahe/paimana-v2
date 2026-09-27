"""
Extractor for the MoSPI IPMD monthly Flash Reports, May 2005 .. March 2010
("Project Monitoring/monthly/2005-06" .. "2009-10", 58 PDFs).

Run from repo root:  python pipeline/extract/proj_monthly_2005_10.py

The text layer is clean but pdftotext -layout scrambles the stacked cells,
so everything is parsed from PyMuPDF word boxes (x/y), grouped into lines.

Two layouts of the master ("sector-wise analysis") list:
  A  May 2005 .. Feb 2009 and Apr .. Aug 2009. Every cell stacks
     Original / (Revised) / [Anticipated] on three lines; the value kind is
     told by the bracket type, not by line position. Delay cell stacks
     delay w.r.t. original / (w.r.t. revised) / [additional delay in month].
     Columns come from the last header line ("No. Name of the Project
     (Revised) [Anticipated] (Revised) Expenditure [Anticipated] Month] Total").
  B  Mar 2009 and Sep 2009 .. Mar 2010. Numbered columns 1..10 (the number
     line gives the column centres). Cost and DOC cells stack Original over
     Revised by line order ("-" = no revision). Project code "[N06000044]"
     follows the name. Column 9 is "Addl. Delay During Month" (B1, Mar 2009)
     or "Delay w.r.t Original" printed as "28(R1)" / "0(O)" (B2): the suffix
     names the schedule the delay is measured against, so only "(O)" values
     go to delay_months; "(Rn)" values go to remarks.
     Oct 2009 prints col 9 without suffix; those values are the month's
     additional delays (checked against the report's own count) and are
     loaded as additional_delay_months.
Group headings (sector) are bold lines (or, in the non-bold Mar 2009 file,
plain text lines after a Total row) and are forward-filled; they are printed
only when the sector changes (also across pages). Sector "Total" rows go to
the summary part, never to projects.

Other tables: completed/dropped during the month, projects added, (layout B2
only) projects reporting additional delays -> projects part; sector-wise
counts, the summary sections I-IV, the sector abstract, sector totals of the
master list and (B) the per-sector status pages -> summary part. In the
un-numbered B lists the value line can sit vertically centred between name
lines, so name lines are attached to value lines by splitting at the largest
vertical gap (ListParser.group_items).
Master lists that belong to another month are detected by row overlap
(drop_stale_masters): Apr 2006 and Jul 2008 reprint the previous month's list
unchanged -> loaded with dq_note stale_repeat_of:<period>; the truncated
Sep 2007 file carries Oct 2007 rows -> not loaded, and its other rows carry
dq_note report_truncated.
'(x)' / '(Rn)' delays w.r.t. the revised schedule and (layout A) '(x)' cost
overrun w.r.t. revised cost have no schema column and go to remarks as
'delay_wrt_revised_months: N' / 'cost_overrun_wrt_revised_cr: X'.
Repeated list headers on continuation pages are skipped (is_list_header) and
a list whose title is reprinted per page is parsed as one list, so the sector
carries across pages.
Skipped on purpose: the FY-to-date "Month wise list of completed / deleted
projects" annexures (repeat the monthly completed lists), the executive
summary narrative and charts, and in layout A/B1 the "additional delays"
list (its delay figure is already in the master list).
"""
import re
import sys
from collections import Counter
from pathlib import Path

import fitz  # PyMuPDF

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (DATASET, MANIFEST_COLS, PROJECT_COLS, SUMMARY_COLS,  # noqa: E402
                    fiscal_year, rel, to_num, to_ym, write_part)

FAMILY = "proj_monthly_2005_10"
REPORT_TYPE = "monthly_flash"
SRC = DATASET / "Project Monitoring" / "monthly"
FYS = ["2005-06", "2006-07", "2007-08", "2008-09", "2009-10"]

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


# --------------------------------------------------------------------------
# words / lines
# --------------------------------------------------------------------------
class W:
    __slots__ = ("x0", "y0", "x1", "y1", "t", "b")

    def __init__(self, x0, y0, x1, y1, t, b=False):
        self.x0, self.y0, self.x1, self.y1, self.t, self.b = x0, y0, x1, y1, t, b

    @property
    def xc(self):
        return (self.x0 + self.x1) / 2

    @property
    def yc(self):
        return (self.y0 + self.y1) / 2

    def __repr__(self):
        return f"{self.t}@{self.x0:.0f}"


class Line:
    def __init__(self, page, words):
        self.p = page
        self.w = sorted(words, key=lambda w: w.x0)
        self.y = sum(w.yc for w in words) / len(words)
        self.text = " ".join(w.t for w in self.w)
        self.low = self.text.lower()

    def __repr__(self):
        return f"p{self.p + 1} y{self.y:.0f}: {self.w}"


def page_lines(page, pno, tol=4.0):
    bold = []
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            for s in ln["spans"]:
                if s["text"].strip() and ((s["flags"] & 16) or "bold" in s["font"].lower()):
                    bold.append(s["bbox"])
    words = []
    for x0, y0, x1, y1, t, *_ in page.get_text("words"):
        t = t.strip()
        if not t:
            continue
        xc, yc = (x0 + x1) / 2, (y0 + y1) / 2
        isb = any(b[0] - 1 <= xc <= b[2] + 1 and b[1] - 1 <= yc <= b[3] + 1 for b in bold)
        pieces = split_glued_values(t)
        if pieces:          # '12/2003286.6312/2006' printed without spaces
            pos = 0
            for piece in pieces:
                a = x0 + (x1 - x0) * pos / len(t)
                pos += len(piece)
                words.append(W(a, y0, x0 + (x1 - x0) * pos / len(t), y1, piece, isb))
        else:
            words.append(W(x0, y0, x1, y1, t, isb))
    words.sort(key=lambda w: (w.yc, w.x0))
    lines, cur = [], []
    for w in words:
        if cur and w.yc - cur[0].yc > tol:
            lines.append(Line(pno, cur))
            cur = []
        cur.append(w)
    if cur:
        lines.append(Line(pno, cur))
    return lines


GLUE_RE = re.compile(r"\d{1,2}/\d{4}|-?\d[\d,]*\.\d{2}")


def split_glued_values(t):
    """'12/2003286.6312/2006355.2104/2009' -> ['12/2003', '286.63', '12/2006', '355.21',
    '04/2009']; None when t is not a run of >= 2 dates/2-decimal numbers."""
    if re.fullmatch(r"[\d/.,-]+", t) is None:
        return None
    parts = GLUE_RE.findall(t)
    if len(parts) >= 2 and "".join(parts) == t:
        return parts
    return None


def is_footer(line):
    """Page numbers ('- 13 -', '17') and the NIC footer."""
    if "nic-mos" in line.low:
        return True
    return bool(re.fullmatch(r"[-\s]*\d{1,3}[-\s]*", line.text)) and line.y > 700


# --------------------------------------------------------------------------
# value tokens
# --------------------------------------------------------------------------
NUM_RE = re.compile(r"-?\d[\d,]*(\.\d+)?|-?\.\d+")
DATE_RE = re.compile(r"\d{1,2}/\d{2,4}")
BLANK_TOK = {"-", "--", "-na-", "na", "n.a.", "n.a", "nr", "n.r.", "-nr-", "nil", "*", "/"}


def unwrap(t):
    """'(12.5)' -> ('(', '12.5'), '[3/2006]' -> ('[', '3/2006'), '5' -> ('', '5')."""
    t = t.strip()
    if len(t) >= 2 and t[0] == "(" and t[-1] == ")":
        return "(", t[1:-1].strip()
    if len(t) >= 2 and t[0] == "[" and t[-1] == "]":
        return "[", t[1:-1].strip()
    return "", t


def is_value_tok(t):
    k, v = unwrap(t)
    v = v.lower()
    if v in BLANK_TOK or v == "":
        return True
    if NUM_RE.fullmatch(v) or DATE_RE.fullmatch(v):
        return True
    if re.fullmatch(r"-?\d+\((o|r\d*)\)", v):          # 28(R1), 0(O)
        return True
    if re.fullmatch(r"\d*/\d*|/", v):                  # milestones 10/20, '/'
        return True
    return False


def num(t):
    """Number from a (possibly bracketed) token; never reads '(x)' as negative."""
    return to_num(unwrap(t)[1])


def ym(t):
    v = unwrap(t)[1]
    if v.lower() in BLANK_TOK:
        return None
    return to_ym(v)


def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


# --------------------------------------------------------------------------
# project name helpers
# --------------------------------------------------------------------------
CODE_RE = re.compile(r"\[\s*([A-Z]?\d{6,12})\s*\]")
# trailing "(AGENCY)" groups that are unambiguously an implementing agency
AGENCIES = {
    "NPCIL", "BHAVINI", "NTPC", "NHPC", "NHPCL", "PGCIL", "P.GRID", "P.GR.", "PGCL", "POWERGRID",
    "THDC", "THDCL", "NEEPCO", "SJVNL", "DVC", "NLC", "SAIL", "RINL", "NMDC", "NALCO",
    "ONGC", "ONGCL", "IOC", "IOCL", "HPCL", "BPCL", "GAIL", "OIL", "CPCL", "MRPL", "NRL", "BRPL",
    "EIL", "CIL", "SECL", "MCL", "NCL", "CCL", "BCCL", "WCL", "ECL", "SCCL", "NEC",
    "BSNL", "MTNL", "RVNL", "IRCON", "KRCL", "DMRC", "NHAI", "AAI", "BVFC", "FACT", "NFL",
    "RCF", "HFCL", "BCPL", "ONGC VIDESH", "NTPC-SAIL", "NSPCL", "IOCL/GAIL",
}


def split_name(raw):
    """'KAIGA 3 and 4 UNITS (NPCIL) - [020100041]' -> (name, agency, code)."""
    s = clean(raw)
    code = None
    m = CODE_RE.search(s)
    if m:
        code = m.group(1)
        s = clean(s[:m.start()] + " " + s[m.end():])
    s = re.sub(r"\s*-\s*$", "", s).strip()
    agency = None
    m = re.search(r"\(\s*([A-Za-z.\- /]+?)\s*\)\s*$", s)
    if m and m.group(1).upper() in AGENCIES:
        agency = m.group(1)
        s = s[:m.start()].strip()
        s = re.sub(r"\s*-\s*$", "", s).strip()
    return s, agency, code


# --------------------------------------------------------------------------
# master list, layouts A and B
# --------------------------------------------------------------------------
def header_cols_a(line):
    """Column centres from the last A header line."""
    toks = line.w
    rev = [w for w in toks if w.t.startswith("(Revised")]
    ant = [w for w in toks if w.t.startswith("[Anticipated")]
    exp = [w for w in toks if w.t.startswith("Expenditure")]
    mon = [w for w in toks if w.t.startswith("Month")]
    tot = [w for w in toks if w.t == "Total"]
    name = [w for w in toks if w.t in ("Name", "No.")]
    if len(rev) < 2 or len(ant) < 2 or not exp or not mon or not tot:
        return None
    cols = {"doa": rev[0].xc, "cost": ant[0].xc, "overrun": rev[1].xc, "exp": exp[0].xc,
            "doc": ant[1].xc, "delay": mon[0].xc, "ms": tot[0].xc}
    name_x = [w for w in toks if w.t == "Name"]
    return {"cols": cols, "vbound": rev[0].x0 - 4,
            "name_x0": name_x[0].x0 if name_x else name[0].x1 + 2}


def header_cols_b(line, hdr_text):
    toks = [w for w in line.w if w.t.isdigit()]
    if [w.t for w in toks] != [str(i) for i in range(1, 11)]:
        return None
    c = {w.t: w.xc for w in toks}
    cols = {"doa": c["3"], "cost": c["4"], "antc": c["5"], "exp": c["6"], "doc": c["7"],
            "doca": c["8"], "delay": c["9"], "ms": c["10"]}
    sub = "B1" if ("addl" in hdr_text or "during" in hdr_text) else "B2"
    # serials sit at x~99-110 and names start at x~113 (= column '2' centre - 58)
    return {"cols": cols, "vbound": toks[2].x0 - 12, "name_x0": toks[1].x0 - 58, "sub": sub}


def nearest(cols, x):
    return min(cols, key=lambda k: abs(cols[k] - x))


def is_serial(w, name_x0):
    return bool(re.fullmatch(r"\d{1,4}\.?", w.t)) and w.x0 < name_x0 - 4


def split_glued_serial(ln, name_x0):
    """'100.LUBE' printed as one word at the serial position -> '100.' + 'LUBE'."""
    w = ln.w[0]
    m = re.fullmatch(r"(\d{1,4}\.)(\S+)", w.t)
    if m and w.x0 < name_x0 and (not re.fullmatch(r"[\d.,/]+", m.group(2)) or w.x1 > name_x0 + 3):
        cut = w.x0 + (w.x1 - w.x0) * len(m.group(1)) / len(w.t)
        ln.w[0:1] = [W(w.x0, w.y0, cut, w.y1, m.group(1), w.b),
                     W(cut + 1, w.y0, w.x1, w.y1, m.group(2), w.b)]


def parse_master(lines):
    """Walk all lines of a document; return (projects, totals, variant).
    projects: dicts with page, sector, serial, name tokens, cells.
    totals: sector Total rows (cells) for the summary part."""
    projects, totals = [], []
    hdr = None          # current column spec
    variant = None
    in_hdr = False
    hdr_text = ""
    sector = None
    cur = None          # current block (project or total)
    for ln in lines:
        low = ln.low
        # --- header detection ---------------------------------------------------
        if re.fullmatch(r"sector-wise analysis of projects", low):
            continue                      # page title above the A header
        if ("(units:" in low and "cost/expenditure" in low) or re.search(r"^\((jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*,\s*\d{4}\)$", low):
            in_hdr, hdr_text = True, low
            continue
        if in_hdr:
            hdr_text += " " + low
            a = header_cols_a(ln) if "name of the project" in low else None
            b = header_cols_b(ln, hdr_text) if a is None else None
            if a:
                hdr, variant, in_hdr = a, "A", False
            elif b:
                hdr, variant, in_hdr = b, b["sub"], False
            elif len(hdr_text) > 800:     # not a master-list page after all
                in_hdr = False
            continue
        if hdr is None:
            continue
        # a new, different section ends the master list
        if re.search(r"sector-?\s?wise (number|analysis of projects \(abstract)|summary of projects on", low):
            hdr = None
            cur = None
            continue
        if is_footer(ln):
            continue
        name_x0 = hdr["name_x0"]
        vb = hdr["vbound"]
        split_glued_serial(ln, name_x0)
        first = ln.w[0]
        # --- sector heading ----------------------------------------------------
        # bold, no values; or (layouts without bold, e.g. Mar 2009) a plain
        # text line right after a Total row / at the start of the list
        texty = [w for w in ln.w if w.t not in ("", "-")]
        plain = texty and not any(is_value_tok(w.t) for w in texty) \
            and not is_serial(first, name_x0) and first.t not in ("Total", "Grand") \
            and re.search(r"[A-Za-z]{3}", ln.text) and not CODE_RE.search(ln.text)
        if plain and (all(w.b for w in texty) or cur is None or cur["kind"] == "total"):
            sector = clean(" ".join(w.t for w in texty))
            cur = None
            continue
        # --- total row ------------------------------------------------------------
        name_toks = [w for w in ln.w if w.x0 < vb or not is_value_tok(w.t)]
        if name_toks and name_toks[0].t in ("Total", "Grand"):
            cur = {"kind": "total", "page": ln.p, "sector": sector, "hdr": hdr, "variant": variant,
                   "label": clean(" ".join(w.t for w in name_toks)).rstrip(" :"), "lines": [ln]}
            totals.append(cur)
            continue
        # --- project start ---------------------------------------------------------
        if is_serial(first, name_x0):
            cur = {"kind": "project", "page": ln.p, "sector": sector,
                   "serial": first.t.rstrip("."), "lines": [ln], "variant": variant,
                   "hdr": hdr}
            projects.append(cur)
            continue
        if cur is not None:
            cur["lines"].append(ln)
    return projects, totals, variant


def block_cells(block, hdr):
    """Split a block into name tokens and per-column value tokens (y-ordered)."""
    cols, vb = hdr["cols"], hdr["vbound"]
    name, cells = [], {k: [] for k in cols}
    for ln in block["lines"]:
        for w in ln.w:
            if block["kind"] == "project" and w is block["lines"][0].w[0]:
                continue                                    # serial number
            if w.x0 >= vb and is_value_tok(w.t):
                cells[nearest(cols, w.xc)].append(w)
            else:
                name.append(w)
    return name, cells


def ms_text(ws):
    s = "".join(w.t for w in ws)
    return s if re.fullmatch(r"\d+/\d+", s) else None


def build_project_a(block):
    hdr = block["hdr"]
    name, cells = block_cells(block, hdr)
    rec, probs = {}, []

    def by_kind(col):
        out = {"": [], "(": [], "[": []}
        for w in cells[col]:
            k, v = unwrap(w.t)
            out[k].append(w.t)
        return out

    def one(lst, col, kind):
        if len(lst) > 1:
            probs.append(f"{col}{kind}x{len(lst)}")
        return lst[0] if lst else None

    d = by_kind("doa")
    rec["doa_original"] = ym(one(d[""], "doa", "")) if d[""] else None
    rec["doa_revised"] = ym(one(d["("], "doa", "(")) if d["("] else None
    c = by_kind("cost")
    rec["cost_original_cr"] = num(one(c[""], "cost", "")) if c[""] else None
    rec["cost_revised_cr"] = num(one(c["("], "cost", "(")) if c["("] else None
    rec["cost_anticipated_cr"] = num(one(c["["], "cost", "[")) if c["["] else None
    o = by_kind("overrun")
    rec["cost_overrun_cr"] = num(one(o[""], "overrun", "")) if o[""] else None
    e = by_kind("exp")
    rec["expenditure_cum_cr"] = num(one(e[""], "exp", "")) if e[""] else None
    dc = by_kind("doc")
    rec["doc_original"] = ym(one(dc[""], "doc", "")) if dc[""] else None
    rec["doc_revised"] = ym(one(dc["("], "doc", "(")) if dc["("] else None
    rec["doc_anticipated"] = ym(one(dc["["], "doc", "[")) if dc["["] else None
    dl = by_kind("delay")
    rec["delay_months"] = num(one(dl[""], "delay", "")) if dl[""] else None
    rec["additional_delay_months"] = num(one(dl["["], "delay", "[")) if dl["["] else None
    # '(x)' in the delay / overrun cells is measured against the revised
    # schedule / revised cost; no schema column, so it goes to remarks
    dr = num(one(dl["("], "delay", "(")) if dl["("] else None
    orv = num(one(o["("], "overrun", "(")) if o["("] else None
    extra = join_remarks(f"delay_wrt_revised_months: {dr:g}" if dr is not None else None,
                         f"cost_overrun_wrt_revised_cr: {orv:.2f}" if orv is not None else None)
    ms = ms_text(cells["ms"])
    raw = clean(" ".join(w.t for w in name))
    return rec, raw, ms, extra, probs


def build_project_b(block, col9=None):
    """col9: 'addl' (additional delay in month) or 'wrt' (delay w.r.t. a schedule,
    printed with an (O)/(Rn) suffix). Default from the header wording."""
    hdr = block["hdr"]
    name, cells = block_cells(block, hdr)
    rec, probs, extra = {}, [], None

    def seq(col, n):
        ws = sorted(cells[col], key=lambda w: (w.yc, w.x0))
        if len(ws) > n:
            probs.append(f"{col}x{len(ws)}")
        return [w.t for w in ws] + [None] * n

    d = seq("doa", 2)
    rec["doa_original"], rec["doa_revised"] = ym(d[0]) if d[0] else None, ym(d[1]) if d[1] else None
    c = seq("cost", 2)
    rec["cost_original_cr"], rec["cost_revised_cr"] = (num(c[0]) if c[0] else None,
                                                       num(c[1]) if c[1] else None)
    a = seq("antc", 1)
    rec["cost_anticipated_cr"] = num(a[0]) if a[0] else None
    e = seq("exp", 1)
    rec["expenditure_cum_cr"] = num(e[0]) if e[0] else None
    dc = seq("doc", 2)
    rec["doc_original"], rec["doc_revised"] = ym(dc[0]) if dc[0] else None, ym(dc[1]) if dc[1] else None
    da = seq("doca", 1)
    rec["doc_anticipated"] = ym(da[0]) if da[0] else None
    dl = seq("delay", 1)[0]
    block["col9"] = dl
    col9 = col9 or ("addl" if hdr["sub"] == "B1" else "wrt")
    if dl:
        m = re.fullmatch(r"(-?\d+)\((O|R\d*)\)", dl.strip(), re.I)
        if col9 == "addl":
            rec["additional_delay_months"] = num(dl)
            if m:
                probs.append(f"delay_suffix_in_addl_mode:{dl}")
        elif m and m.group(2).upper() == "O":
            rec["delay_months"] = float(m.group(1))
        elif m:
            extra = f"delay_wrt_revised_months: {int(m.group(1))} (schedule {m.group(2).upper()})"
        elif dl.strip() not in ("-",):
            probs.append(f"delay_nosuffix:{dl}")      # ambiguous -> left blank
    ms = ms_text(cells["ms"])
    raw = clean(" ".join(w.t for w in name))
    return rec, raw, ms, extra, probs


# --------------------------------------------------------------------------
# report period
# --------------------------------------------------------------------------
MONTH_WORD = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"


def period_from_name(name):
    """'MonthlyFR_may_2005.pdf' / 'FLR_FEB_2009.pdf' / 'FR_MARCH_2010.pdf' -> 'YYYY-MM'."""
    m = re.match(r"(?:MonthlyFR|FLR|FR)_([A-Za-z]+)_(\d{4})", name, re.I)
    return f"{int(m.group(2)):04d}-{MONTHS[m.group(1)[:3].lower()]:02d}"


def period_in_pdf(lines):
    pats = [rf"flash report for (?:the month of )?{MONTH_WORD}[\s,'’.]*(\d{{4}})",
            rf"on\s?-?going projects in {MONTH_WORD}[\s,'’.]*(\d{{4}})",
            rf"^\({MONTH_WORD},\s*(\d{{4}})\)$"]
    for pat in pats:
        for ln in lines:
            m = re.search(pat, ln.low)
            if m:
                return f"{int(m.group(2)):04d}-{MONTHS[m.group(1)]:02d}", ln.text
    return None, None


# --------------------------------------------------------------------------
# section walker for everything except the master list
# --------------------------------------------------------------------------
SECTIONS = [
    ("master", rf"^sector-wise analysis of projects$|^\(units:|^\({MONTH_WORD},\s*\d{{4}}\)$"),
    ("count", r"sector-?\s?wise number of on\s?-?going projects"),
    ("count", r"projects on monitor"),
    ("fy_list", r"month\s?wise list of (completed|deleted)"),
    ("sum_I", r"^i\.\s*projects? (added|implementation)"),
    ("sum_II", r"^ii\.\s*project status"),
    ("narr", r"brief analysis|investment scenario|^executive summary"),
    ("cost:Project cost", r"^iii\.\s*(\(a\)\s*)?project cost"),
    ("cost:Delayed project cost", r"^iii\.\s*\(b\)\s*delayed project cost"),
    ("cost:Additional delayed project cost", r"^iv\.\s*additional delayed project cost"),
    ("ms", r"milestones\s*\(cumulative"),
    ("completed", r"list of projects completed"),
    ("added", r"list of projects added"),
    ("addl", r"list of projects reporting additional delay"),
    ("abstract", r"^sector\s?wise analysis of projects(\s*\(abstract\))?$"),
    ("status", r"sector\s?wise current status of projects"),
    ("status", r"^\d+\.\s*sector\s*:"),
]

GLOBAL_METRICS = [   # (regex on line text, metric) -> overall summary rows
    (r"projects (?:in )?previous month\s*:?\s*(\d+)$", "n_projects_prev_month"),
    (r"completed/dropped/frozen in previous month\s*:?\s*(\d+)$", "n_completed_dropped_frozen_prev_month"),
    (r"completed/dropped/frozen in current month\s*:?\s*(\d+)$", "n_completed_dropped_frozen"),
    (r"added in current month\s*:?\s*(\d+)$", "n_new"),
    (r"projects in current month\s*:?\s*(\d+)$", "n_projects"),
    (r"number of projects reporting additional delay\s*=\s*(\d+)$", "n_additional_delay"),
]


def numeric_tail(toks):
    """Split tokens into (label tokens, trailing numeric tokens)."""
    i = len(toks)
    while i > 0 and NUM_RE.fullmatch(toks[i - 1].t.replace("%", "")):
        i -= 1
    return toks[:i], toks[i:]


def norm_sector(s):
    return re.sub(r"[^A-Z]", "", (s or "").upper().replace("&", "AND"))


# column-header vocabulary of the small lists; a line made only of these words
# (with at least one strong one) is a (reprinted) header, never a sector/name
HDR_WORDS = {"sl", "no", "noproject", "project", "name", "doa", "doc", "cost", "original",
             "anticipated", "anticipatedoriginal", "final", "expenditure", "last", "this",
             "month", "months", "in", "delay", "date", "of", "commissioning", "rs", "crore",
             "rscrore", "crores", "rscrores", "reported", "now"}
HDR_STRONG = {"sl", "noproject", "doa", "doc", "cost", "original", "anticipated", "crores",
              "anticipatedoriginal", "expenditure", "delay", "commissioning", "crore", "rscrore",
              "last", "this"}


def is_list_header(ln):
    """'No.Project DOA Cost DOC Cost DOC', 'Sl. Original Anticipated',
    'Cost ( Rs. Crore) DOC reported', 'Delay' -> True."""
    toks = [t for t in (re.sub(r"[^a-z]", "", w.t.lower()) for w in ln.w) if t]
    return bool(toks) and all(t in HDR_WORDS for t in toks) and any(t in HDR_STRONG for t in toks)


class ListParser:
    """Completed / added / additional-delay lists (one row per project)."""
    FIELDS = {
        "completed": ["doa_original", "cost_original_cr", "doc_original",
                      "cost_anticipated_cr", "doc_anticipated", "expenditure_cum_cr"],
        "added": ["doa_original", "cost_original_cr", "doc_original",
                  "cost_anticipated_cr", "doc_anticipated"],
    }

    def __init__(self, kind, known_sectors):
        self.kind, self.known = kind, known_sectors
        self.cols = None
        self.rows = []
        self.cur = None
        self.sector = None
        self.serial_mode, self.name_x0, self.vbound = False, 0, 0
        self.ended = False
        self.rehdr = False      # title reprinted: skip the reprinted header block
        self.items = []

    def header(self, ln):
        toks = ln.w
        if self.kind in ("completed", "added"):
            i = next((k for k, w in enumerate(toks) if w.t == "DOA"), None)
            if i is None:
                return False
            vals = toks[i:]
            names = self.FIELDS[self.kind]
            if len(vals) < len(names):
                return False
            self.cols = {f: w.xc for f, w in zip(names, vals)}
            self.vbound = toks[i].x0 - 20      # DOA values start left of the centred header
        else:
            if not ("project" in ln.low and "last" in ln.low and "this" in ln.low):
                return False
            orig = [w for w in toks if w.t == "Original"]
            ant = [w for w in toks if w.t.startswith("Anticipated")]
            last = [w for w in toks if w.t == "Last"]
            this = [w for w in toks if w.t == "This"]
            inm = [w for w in toks if w.t.startswith("(in") or w.t.startswith("months")]
            if len(orig) < 2 or not ant or not last or not this or not inm:
                return False
            self.cols = {"cost_original_cr": orig[0].xc, "cost_anticipated_cr": ant[0].xc,
                         "doc_original": orig[1].xc, "doc_last_month": last[0].x1 + 5,
                         "doc_anticipated": this[0].x1 + 5,
                         "additional_delay_months": sum(w.xc for w in inm) / len(inm)}
            self.vbound = orig[0].x0 - 12
        nx = [w for w in toks if w.t == "Project"]
        glued = [w for w in toks if re.fullmatch(r"No\.?Project", w.t)]
        self.serial_mode = any(w.t in ("No.", "No") for w in toks) or bool(glued)
        self.name_x0 = nx[0].x0 if nx else 0
        if glued:
            self.name_x0 = glued[0].x0 + (glued[0].x1 - glued[0].x0) * 0.3
        return True

    def feed(self, ln):
        if self.ended:
            return
        if self.cols is None:
            self.header(ln)
            return
        if self.rehdr:
            if self.header(ln):
                self.rehdr = False
                return
            if sum(is_value_tok(w.t) for w in ln.w) < 2:
                return
            self.rehdr = False           # no header found: data resumes
        if re.search(r"number of projects reporting", ln.low):
            self.ended, self.cur = True, None
            return
        if is_list_header(ln):          # header reprinted on a continuation page
            return
        if self.serial_mode:
            split_glued_serial(ln, self.name_x0)
        vals = [w for w in ln.w if w.x0 >= self.vbound and is_value_tok(w.t)]
        first = ln.w[0]
        texty = [w for w in ln.w if w not in vals]
        if not vals and texty and not (self.serial_mode and is_serial(first, self.name_x0)):
            txt = clean(" ".join(w.t for w in texty))
            if not STATUS_RE.search(txt) and (all(w.b for w in texty) or norm_sector(txt) in self.known):
                self.sector, self.cur = txt, None
                self.items.append(("sector", None, ln.p, txt, []))
                return
            if self.serial_mode and self.cur is not None:
                self.cur["name"] += texty
            if not self.serial_mode:
                self.items.append(("txt", ln.p * 2000 + ln.y, ln.p, texty, []))
            return
        if not self.serial_mode:
            if len(vals) >= 2:
                self.items.append(("val", ln.p * 2000 + ln.y, ln.p, texty, vals))
            return
        if self.serial_mode:
            start = is_serial(first, self.name_x0)
        else:
            start = len(vals) >= 2
        if start:
            self.cur = {"page": ln.p, "sector": self.sector, "name": [], "vals": []}
            self.rows.append(self.cur)
            texty = [w for w in texty if not (self.serial_mode and w is first)]
        if self.cur is None:
            return
        self.cur["name"] += texty
        self.cur["vals"] += vals

    def group_items(self):
        """Rows of a list without serial numbers. The value line may sit on
        the first name line or be vertically centred between name lines, so
        the text lines between two value lines are split at the largest
        vertical gap; a sector heading is a hard boundary."""
        rows, seg = [], []
        for it in self.items + [("sector", None, None, None, [])]:
            if it[0] != "sector":
                seg.append(it)
                continue
            vi = [k for k, x in enumerate(seg) if x[0] == "val"]
            if vi:
                owner = {}
                for k in range(0, vi[0]):
                    owner[k] = vi[0]
                for k in range(vi[-1] + 1, len(seg)):
                    owner[k] = vi[-1]
                for a, b in zip(vi, vi[1:]):
                    ys = [seg[k][1] for k in range(a, b + 1)]
                    gaps = [ys[k + 1] - ys[k] for k in range(len(ys) - 1)]
                    cut = a + gaps.index(max(gaps))      # last line owned by a
                    for k in range(a + 1, b):
                        owner[k] = a if k <= cut else b
                for v in vi:
                    ks = sorted([v] + [k for k, o in owner.items() if o == v])
                    rows.append({"page": seg[v][2], "sector": self.sector_at.get(id(seg[v])),
                                 "name": [w for k in ks for w in seg[k][3]], "vals": seg[v][4]})
            seg = []
        return rows

    def records(self):
        out = []
        if not self.serial_mode:
            sector = None
            self.sector_at = {}
            for it in self.items:
                if it[0] == "sector":
                    sector = it[3]
                else:
                    self.sector_at[id(it)] = sector
            self.rows = self.group_items()
        for r in self.rows:
            rec, probs = {}, []
            for w in r["vals"]:
                f = nearest(self.cols, w.xc)
                if f in rec:
                    probs.append(f"dup:{f}:{w.t}")
                    continue
                if f.startswith("doa") or f.startswith("doc"):
                    rec[f] = ym(w.t)
                    if rec[f] is None and unwrap(w.t)[1].lower() not in BLANK_TOK:
                        probs.append(f"baddate:{w.t}")
                else:
                    rec[f] = num(w.t)
            raw = clean(" ".join(w.t for w in r["name"]))
            out.append((r, rec, raw, probs))
        return out


def parse_other(lines, known_sectors):
    """Walk the non-master sections; return (list parsers, summary tuples, facts)."""
    summ = []           # (page, table_title, dimension, value, sub, metric, value, unit)
    lists = {"completed": [], "added": [], "addl": []}
    facts = {}
    sec = None
    lp = None
    count_hdr = ""
    abstract_rows = []
    status_sector = None
    status_pending = None      # status label wrapped onto the next line
    count_rows, count_buf = [], []
    prev_low = ""
    for ln in lines:
        low = ln.low
        if is_footer(ln):
            continue
        hit = next((name for name, pat in SECTIONS if re.search(pat, low)), None)
        if hit:
            if hit in ("completed", "added", "addl"):
                # the list title is reprinted on every continuation page (B2
                # additional-delay list): keep the same parser so the sector
                # carries over the page break
                if sec == hit and lp is not None and lp.cols is not None and not lp.ended:
                    lp.rehdr = True
                else:
                    lp = ListParser(hit, known_sectors)
                    lists[hit].append(lp)
            elif hit == "count":
                count_hdr = (prev_low + " " + low) if "projects on monitor" in low else low
                count_rows, count_buf = [], []
            elif hit == "status":
                m = re.match(r"^\d+\.\s*sector\s*:\s*-?\s*(.+)$", ln.text, re.I)
                if m:
                    status_sector = clean(m.group(1))
            sec = hit
            prev_low = low
            continue
        prev_low = low
        if sec != "master":
            for pat, metric in GLOBAL_METRICS:
                m = re.search(pat, low)
                if m:
                    title = ("List of projects reporting additional delays"
                             if metric == "n_additional_delay" else
                             "Summary of projects: projects added/completed/dropped/frozen")
                    summ.append((ln.p, title, "overall", "Total", None, metric,
                                 float(m.group(1)), "count"))
        if sec in (None, "master", "fy_list", "narr"):
            continue
        if sec in ("completed", "added", "addl"):
            lp.feed(ln)
            continue
        lab, nums = numeric_tail(ln.w)
        label = clean(" ".join(w.t for w in lab))
        vals = [to_num(w.t) for w in nums]
        if label == "Approved":            # 'Latest' printed on the line above
            label = "Latest Approved"
        if sec == "count":
            m = re.match(r"^(\d{1,2})\.?\s*(.*)$", label)
            if not nums:
                # sector name printed around a vertically centred row
                if count_rows and count_rows[-1].get("tail"):
                    count_rows[-1]["name"] += " " + label
                    count_rows[-1]["tail"] = False
                elif label and not re.search(r"(?i)projects|sector", label):
                    count_buf.append(label)
                continue
            if len(vals) <= 2 and (m or label.lower() == "total"):
                name = (m.group(2) if m else "Total").strip()
                row = {"p": ln.p, "name": name, "vals": vals}
                if m and not re.search(r"[A-Za-z]", name):
                    row["name"], row["tail"] = " ".join(count_buf), True
                count_buf = []
                count_rows.append(row)
                if name == "Total":
                    if "monitor" not in count_hdr:
                        title = "Sector-wise number of ongoing projects"
                    else:
                        title = "Executive summary: projects on monitor"
                        if len(vals) > 1:
                            title += " and projects reporting additional delay"
                            if "additional" not in count_hdr:
                                title += " (column printed as 'Projects Delayed')"
                    for r in count_rows:
                        nm = clean(r["name"])
                        nm = re.sub(r"(\w)- (\w)", r"\1\2", nm)      # 'HIGH- WAYS'
                        dim = "overall" if nm == "Total" else "sector"
                        summ.append((r["p"], title, dim, nm, None, "n_projects", r["vals"][0], "count"))
                        if len(r["vals"]) > 1:
                            summ.append((r["p"], title, dim, nm, None, "n_additional_delay",
                                         r["vals"][1], "count"))
                    facts.setdefault("count_total", vals[0])
                    count_rows = []
                    sec = None
            continue
        if sec == "sum_II":
            if len(vals) == 7 and label in ("Original", "Latest Approved"):
                for met, v, u in zip(["n_delayed", "n_ahead", "n_on_schedule",
                                      "n_without_odc_doc_available", "n_without_doc",
                                      "n_projects", "pct_delayed"], vals,
                                     ["count"] * 6 + ["percent"]):
                    summ.append((ln.p, "Project status with respect to original / latest approved schedule",
                                 "overall", label, None, met, v, u))
            continue
        if sec.startswith("cost:"):
            if len(vals) == 7 and label in ("Original", "Revised", "Latest Approved", "Total"):
                for met, v, u in zip(["n_projects", "cost_latest_cr", "cost_anticipated_cr",
                                      "expenditure_cr", "expenditure_pct", "cost_overrun_cr",
                                      "cost_overrun_pct"], vals,
                                     ["count", "Rs crore", "Rs crore", "Rs crore", "percent",
                                      "Rs crore", "percent"]):
                    summ.append((ln.p, sec[5:] + " (projects with original / revised cost)",
                                 "other", label, None, met, v, u))
            continue
        if sec == "ms":
            if len(vals) == 1 and label == "Total":
                summ.append((ln.p, "Milestones (cumulative due and achieved)", "overall", "Total",
                             None, "n_milestones_total", vals[0], "count"))
            elif len(vals) == 1 and re.fullmatch(r"achieved up\s?to month", label.lower()):
                summ.append((ln.p, "Milestones (cumulative due and achieved)", "overall", "Total",
                             None, "n_milestones_achieved", vals[0], "count"))
            continue
        if sec == "abstract":
            m = re.match(r"^(\d{1,2})\s+(.*)$", label)
            if len(vals) == 4 and re.search(r"[A-Za-z]", label):
                name = m.group(2) if m else label
                if re.match(r"grand total", name.lower()):
                    abstract_rows.append([ln.p, "Total", vals])
                    sec = None
                else:
                    abstract_rows.append([ln.p, name, vals])
            elif not nums and abstract_rows and label and abstract_rows[-1][1] != "Total" \
                    and not re.search(r"(?i)projects|cost|sector|approved", label):
                abstract_rows[-1][1] += " " + label           # wrapped sector name
            continue
        if sec == "status":
            m = re.match(r"^\d+\.\s*sector\s*:\s*-?\s*(.+)$", label, re.I)
            if m and not nums:
                status_sector = clean(m.group(1))
                continue
            lab = label.lower()
            if status_pending and len(vals) == 1 and "projects" not in lab:
                lab = status_pending + " " + lab    # 'Number of Projects Without original date' / 'of commissioning 1'
            status_pending = None
            # the label can be clipped in the text layer: 'f Projects on schedule 15'
            m = re.fullmatch(r"([a-z ]*?)\s*projects(?: (.+))?", lab)
            if m and "number of".endswith(m.group(1)) and not nums:
                status_pending = lab
            elif m and "number of".endswith(m.group(1)) and len(vals) == 1 and status_sector:
                q = (m.group(2) or "").replace(" ", "_")
                met = {"": "n_projects", "on_schedule": "n_on_schedule", "delayed": "n_delayed",
                       "ahead": "n_ahead", "wo_doc_original": "n_without_doc",
                       "wo_odc_original": "n_without_odc_doc_available",
                       "without_original_date_of_commissioning": "n_without_odc_doc_available",
                       }.get(q, "n_" + q)
                summ.append((ln.p, "Sector wise current status of projects (w.r.t. original schedule)",
                             "sector", status_sector, None, met, vals[0], "count",
                             None if m.group(1) == "number of" else "label_restored"))
            continue
    for p, name, vals in abstract_rows:
        dim = "overall" if name == "Total" else "sector"
        for met, v, u in zip(["n_projects", "cost_original_cr", "cost_latest_cr",
                              "cost_anticipated_cr"], vals, ["count"] + ["Rs crore"] * 3):
            summ.append((p, "Sectorwise analysis of projects (abstract)", dim, clean(name),
                         None, met, v, u))
    return lists, summ, facts


# --------------------------------------------------------------------------
# per-report processing
# --------------------------------------------------------------------------
STATUS_RE = re.compile(r"\{\s*(Completed|Dropped|Frozen|Deleted)\s*\}", re.I)
LIST_TYPE = {"completed": "completed", "dropped": "dropped", "frozen": "other:frozen",
             "deleted": "dropped"}


def load_lines(path):
    doc = fitz.open(path)
    lines = []
    for p in range(doc.page_count):
        lines += page_lines(doc[p], p)
    return doc.page_count, lines


def join_remarks(*parts):
    parts = [p for p in parts if p]
    return "; ".join(parts) if parts else None


def add_dq(cur, flag):
    """Append a data-quality flag to a ';'-joined dq_note."""
    flags = [f for f in (cur or "").split(";") if f]
    return ";".join(flags + [flag] if flag not in flags else flags)


def process(path):
    name = path.name
    period = period_from_name(name)
    npages, lines = load_lines(path)
    base = {"report_period": period, "report_type": REPORT_TYPE,
            "fiscal_year": fiscal_year(period), "quarter": None, "source_file": rel(path)}
    notes, problems = [], Counter()
    pdf_period, pdf_txt = period_in_pdf(lines)
    if pdf_period is None:
        notes.append("report month not found in PDF text")
    elif pdf_period != period:
        notes.append(f"PDF text says {pdf_period} ('{pdf_txt}') but filename says {period}")

    projs, totals, variant = parse_master(lines)
    known = {norm_sector(b["sector"]) for b in projs if b["sector"]}
    lists, summ, facts = parse_other(lines, known)
    stated = {}
    for t in summ:
        if t[2] == "overall" and t[1].startswith("Summary of projects") or t[5] == "n_additional_delay" \
                and t[1].startswith("List of"):
            stated.setdefault(t[5], t[6])

    # ---- master list -----------------------------------------------------------
    col9_mode = None
    if variant == "B2":
        for b in projs:
            build_project_b(b)
        toks = [b.get("col9") for b in projs if b.get("col9") and b.get("col9") != "-"]
        if toks and not any(re.search(r"\((O|R\d*)\)", t, re.I) for t in toks):
            # Oct 2009: header says 'Delay w.r.t Original' but the unsuffixed
            # values are the month's additional delays (Kaiga 2 vs 28-30 months
            # w.r.t. schedule in Sep/Nov). Accept that reading only when the
            # count of positive values matches the report's own count.
            npos = sum(1 for t in toks if (to_num(t) or 0) > 0)
            st_ad = stated.get("n_additional_delay")
            if st_ad is not None and abs(npos - st_ad) <= max(1, 0.05 * st_ad):
                col9_mode = "addl"
                notes.append("column 9 is headed 'Delay w.r.t Original' but printed without "
                             f"(O)/(Rn) suffix; its {npos} positive values match the report's "
                             f"{int(st_ad)} projects reporting additional delay -> loaded as "
                             "additional_delay_months (delay_months left blank)")
            else:
                notes.append("column 9 printed without (O)/(Rn) suffix and does not match the "
                             "additional-delay count -> delay left blank")
    rows = []
    for b in projs:
        if b["variant"] == "A":
            rec, raw, ms, extra, probs = build_project_a(b)
        else:
            rec, raw, ms, extra, probs = build_project_b(b, col9_mode)
        for p in probs:
            problems[p.split(":")[0]] += 1
        pname, agency, code = split_name(raw)
        if not pname:
            problems["empty_name"] += 1
        rows.append({**base, "page": b["page"] + 1, "list_type": "ongoing",
                     "project_code": code, "project_name": pname, "sector_raw": b["sector"],
                     "agency": agency, **rec,
                     "remarks": join_remarks(f"Milestones achieved/total: {ms}" if ms else None, extra)})
    n_ongoing = len(rows)

    # ---- small lists -----------------------------------------------------------------
    n_completed = n_other = 0
    list_counts = Counter()
    for kind, parsers in lists.items():
        if kind == "addl" and not (variant == "B2" and col9_mode is None):
            continue          # additional delay already in the master list
        for lp in parsers:
            for r, rec, raw, probs in lp.records():
                for p in probs:
                    problems[f"{kind}_{p.split(':')[0]}"] += 1
                remark = None
                if kind == "completed":
                    m = STATUS_RE.search(raw)
                    if m:
                        lt = LIST_TYPE[m.group(1).lower()]
                        raw = clean(STATUS_RE.sub(" ", raw))
                        remark = f"Status: {m.group(1).capitalize()}"
                    else:
                        lt = "completed"
                        remark = ("Listed under 'projects completed/dropped during the month'; "
                                  "status not printed per project")
                elif kind == "added":
                    lt = "newly_added"
                else:
                    lt = "other:additional_delay"
                    last = rec.pop("doc_last_month", None)
                    remark = f"DOC reported last month: {last}" if last else None
                pname, agency, code = split_name(raw)
                rows.append({**base, "page": r["page"] + 1, "list_type": lt, "project_code": code,
                             "project_name": pname, "sector_raw": r["sector"], "agency": agency,
                             **rec, "remarks": remark})
                list_counts[kind] += 1
                if kind == "completed":
                    n_completed += 1
                else:
                    n_other += 1

    # a printed cost of 0.00 is a placeholder, not a cost
    for r in rows:
        for k in ("cost_original_cr", "cost_revised_cr", "cost_anticipated_cr"):
            if r.get(k) is not None and r[k] <= 0:
                r["remarks"] = join_remarks(r.get("remarks"), f"{k} printed as {r[k]:.2f} (blanked)")
                r["dq_note"] = add_dq(r.get("dq_note"), "placeholder_zero")
                r[k] = None
                problems["zero_cost_blanked"] += 1

    # ---- summary ------------------------------------------------------------------------
    srows = []
    for p, title, dim, val, sub, met, v, unit, *dq in summ:
        srows.append({**base, "page": p + 1, "table_title": title, "dimension": dim,
                      "dimension_value": val, "sub_dimension_value": sub, "metric": met,
                      "value": v, "unit": unit, "dq_note": dq[0] if dq else None})
    for t in totals:
        name_w, cells = block_cells(t, t["hdr"])
        label = t["label"]
        grand = label.lower().startswith("grand")
        dim, dval = ("overall", "Total") if grand else ("sector", t["sector"])
        mets = []
        if t["variant"] == "A":
            for col, kind, met in [("cost", "", "cost_original_cr"), ("cost", "[", "cost_anticipated_cr"),
                                   ("overrun", "", "cost_overrun_cr"), ("exp", "", "expenditure_cr")]:
                ws = [w for w in cells[col] if unwrap(w.t)[0] == kind]
                if ws and num(ws[0].t) is not None:
                    mets.append((met, num(ws[0].t), "Rs crore"))
        else:
            for col, met in [("cost", "cost_original_cr"), ("antc", "cost_anticipated_cr"),
                             ("exp", "expenditure_cr")]:
                ws = sorted(cells[col], key=lambda w: w.yc)
                if ws and num(ws[0].t) is not None:
                    mets.append((met, num(ws[0].t), "Rs crore"))
        ms = ms_text(cells["ms"])
        if ms:
            a, b = ms.split("/")
            mets += [("n_milestones_achieved", float(a), "count"), ("n_milestones_total", float(b), "count")]
        for met, v, unit in mets:
            srows.append({**base, "page": t["page"] + 1,
                          "table_title": MASTER_TOTALS,
                          "dimension": dim, "dimension_value": dval, "sub_dimension_value": None,
                          "metric": met, "value": v, "unit": unit})
    # de-duplicate identical facts printed twice (e.g. summary I on two pages)
    seen, uniq = set(), []
    for r in srows:
        k = (r["table_title"], r["dimension"], r["dimension_value"], r["metric"], r["value"])
        if k not in seen:
            seen.add(k)
            uniq.append(r)
    srows = uniq

    # ---- checks against the report's own totals -----------------------------------------------
    st = stated.get("n_projects") or facts.get("count_total")
    status = "ok"
    if n_ongoing == 0:
        status = "failed"
        notes.append("master list not found")
    elif st:
        gap = n_ongoing - st
        if gap:
            notes.append(f"ongoing rows {n_ongoing} vs stated {int(st)} ({int(gap):+d})")
        if abs(gap) > 0.02 * st:
            status = "partial"
    if stated.get("n_new") is not None and list_counts["added"] != stated["n_new"]:
        notes.append(f"added-list rows {list_counts['added']} vs stated {int(stated['n_new'])}")
    if stated.get("n_completed_dropped_frozen") is not None and \
            list_counts["completed"] != stated["n_completed_dropped_frozen"]:
        notes.append(f"completed/dropped-list rows {list_counts['completed']} vs stated "
                     f"{int(stated['n_completed_dropped_frozen'])}")
    if "n_additional_delay" in stated:
        if list_counts["addl"]:
            got = list_counts["addl"]
        else:
            got = sum(1 for r in rows if r["list_type"] == "ongoing"
                      and (r.get("additional_delay_months") or 0) > 0)
        if got != stated["n_additional_delay"]:
            notes.append(f"projects with additional delay {got} vs stated "
                         f"{int(stated['n_additional_delay'])}")
    # sector Total rows vs sum of the sector's projects (original cost)
    bad = []
    for t in totals:
        if t["label"].lower().startswith("grand"):
            continue
        tv = [r["value"] for r in srows if r["table_title"].startswith("Sector-wise analysis")
              and r["dimension_value"] == t["sector"] and r["metric"] == "cost_original_cr"]
        sv = sum(r.get("cost_original_cr") or 0 for r in rows
                 if r["list_type"] == "ongoing" and r["sector_raw"] == t["sector"])
        if tv and abs(tv[0] - sv) > max(1.0, 0.001 * tv[0]):
            bad.append(f"{t['sector']}: total {tv[0]:.2f} vs sum {sv:.2f}")
    if bad:
        notes.append("sector original-cost totals differ from project sums: " + "; ".join(bad[:4])
                     + (f" (+{len(bad) - 4} more)" if len(bad) > 4 else ""))
    if problems:
        notes.append("parse flags: " + ", ".join(f"{k}={v}" for k, v in sorted(problems.items())))
    if name == "MonthlyFR_sep_2007.pdf":
        status = "partial"
        notes.append("PDF is truncated after page 17: master list stops at project 147 "
                     "(HEALTH & FW) of 503; later sectors absent from the source file; "
                     "all rows of this report carry dq_note report_truncated")
        for r in rows + srows:
            r["dq_note"] = add_dq(r.get("dq_note"), "report_truncated")
    variant_note = {"A": "A: stacked Original/(Revised)/[Anticipated] cells",
                    "B1": "B1: numbered columns, col 9 = additional delay in month",
                    "B2": "B2: numbered columns with project codes, col 9 = delay with (O)/(Rn) suffix"}
    man = {"source_file": rel(path), "report_type": REPORT_TYPE, "report_period": period,
           "pages": npages,
           "parser_variant": (variant or "") + ("/col9=addl" if col9_mode else ""),
           "stated_total_projects": st, "rows_ongoing": n_ongoing, "rows_completed": n_completed,
           "rows_other": n_other, "rows_summary": len(srows), "rows_perf": None,
           "rows_perf_detail": None, "status": status,
           "notes": " | ".join([variant_note.get(variant, "")] + notes)}
    return rows, srows, man


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def files():
    out = []
    for fy in FYS:
        out += sorted((SRC / fy).glob("*.pdf"))
    return out


def sanity(rows):
    """Row-level checks; returns a list of short messages."""
    msgs = []
    for r in rows:
        tag = f"{r['source_file']} p{r['page']} {r['project_name'][:40] if r['project_name'] else ''}"
        for k in ("cost_original_cr", "cost_revised_cr", "cost_anticipated_cr"):
            if r.get(k) is not None and r[k] <= 0:
                msgs.append(f"non-positive {k}={r[k]}: {tag}")
        if r.get("doa_original") and r.get("doc_original") and r["doc_original"] < r["doa_original"]:
            msgs.append(f"doc_original {r['doc_original']} < doa {r['doa_original']}: {tag}")
    return msgs


MASTER_KEY = ("project_name", "sector_raw", "cost_original_cr", "cost_anticipated_cr",
              "expenditure_cum_cr", "doc_anticipated", "delay_months", "additional_delay_months",
              "remarks")
MASTER_TOTALS = "Sector-wise analysis of projects (printed Total rows)"


def drop_stale_masters(all_rows, all_summ, mans):
    """Some reports print a master list that belongs to another month.
    Apr 2006 and Jul 2008 reprint the previous month's list unchanged (every
    row identical, while their own summary tables are updated): those master
    rows and sector Total rows are kept but flagged dq_note
    stale_repeat_of:<previous period>. The truncated Sep 2007 file carries
    rows mostly identical to the next (Oct 2007) report and contradicting its
    own additional-delay list; those are neither this month's figures nor an
    exact repeat, so they are dropped. Normal consecutive reports share < 55%
    of rows. The manifest says which case applied."""
    by_file = {}
    for r in all_rows:
        if r["list_type"] == "ongoing":
            by_file.setdefault(r["source_file"], set()).add(tuple(str(r.get(k)) for k in MASTER_KEY))
    order = sorted((m for m in mans if m.get("rows_ongoing")), key=lambda m: m["report_period"])
    def share(x, y):
        a, b = by_file.get(x["source_file"], set()), by_file.get(y["source_file"], set())
        return len(a & b) / len(b) if b else 0.0

    stale = {}
    for prev, cur in zip(order, order[1:]):          # pass 1: reprint of previous month
        if share(prev, cur) >= 0.99:
            stale[cur["source_file"]] = (prev, share(prev, cur), True)
    for cur, nxt in zip(order, order[1:]):           # pass 2: carries next month's rows
        if cur["source_file"] not in stale and nxt["source_file"] not in stale                 and share(nxt, cur) >= 0.85:
            stale[cur["source_file"]] = (nxt, share(nxt, cur), False)
    drop = set()
    for m in mans:
        hit = stale.get(m["source_file"])
        if not hit:
            continue
        other, share, is_prev = hit
        oname = other["source_file"].split("/")[-1]
        m["status"] = "partial"
        if is_prev:
            flag = f"stale_repeat_of:{other['report_period']}"
            for r in all_rows:
                if r["list_type"] == "ongoing" and r["source_file"] == m["source_file"]:
                    r["dq_note"] = add_dq(r.get("dq_note"), flag)
            for r in all_summ:
                if r["table_title"] == MASTER_TOTALS and r["source_file"] == m["source_file"]:
                    r["dq_note"] = add_dq(r.get("dq_note"), flag)
            m["notes"] += (f" | master list rows are {share:.0%} identical to the previous report "
                           f"{oname} (normal month-to-month overlap < 55%), i.e. "
                           f"{other['report_period']} figures reprinted -> master rows and its "
                           f"sector Total rows loaded with dq_note {flag}; other tables are this "
                           "month's own")
        else:
            drop.add(m["source_file"])
            m["notes"] += (f" | master list rows are {share:.0%} identical to the next report "
                           f"{oname} (normal month-to-month overlap < 55%), i.e. another month's "
                           "figures -> master rows and its sector Total rows NOT loaded; other "
                           "tables kept")
            m["rows_ongoing"] = 0
    all_rows[:] = [r for r in all_rows if not (r["list_type"] == "ongoing" and r["source_file"] in drop)]
    all_summ[:] = [r for r in all_summ if not (r["table_title"] == MASTER_TOTALS and r["source_file"] in drop)]
    for m in mans:
        if m["source_file"] in drop:
            m["rows_summary"] = sum(1 for r in all_summ if r["source_file"] == m["source_file"])


def main():
    all_rows, all_summ, mans, failed = [], [], [], []
    for path in files():
        try:
            rows, srows, man = process(path)
        except Exception as e:  # keep going; the manifest records the failure
            failed.append((rel(path), repr(e)))
            mans.append({"source_file": rel(path), "report_type": REPORT_TYPE,
                         "report_period": period_from_name(path.name), "status": "failed",
                         "notes": f"exception: {e!r}"})
            continue
        all_rows += rows
        all_summ += srows
        mans.append(man)
        print(f"{path.name:28s} {man['parser_variant']:10s} ongoing={man['rows_ongoing']:4d} "
              f"stated={man['stated_total_projects']} compl={man['rows_completed']} "
              f"other={man['rows_other']} summ={man['rows_summary']} {man['status']}")
    drop_stale_masters(all_rows, all_summ, mans)
    for k in ("cost_original_cr", "cost_revised_cr", "cost_anticipated_cr", "cost_overrun_cr",
              "expenditure_cum_cr", "delay_months", "additional_delay_months"):
        for r in all_rows:
            r.setdefault(k, None)
    write_part(all_rows, FAMILY, "projects", PROJECT_COLS)
    write_part(all_summ, FAMILY, "summary", SUMMARY_COLS)
    write_part(mans, FAMILY, "manifest", MANIFEST_COLS)
    msgs = sanity(all_rows)
    print(f"projects={len(all_rows)} summary={len(all_summ)} manifest={len(mans)} "
          f"failed={len(failed)} sanity_flags={len(msgs)}")
    for m in msgs[:30]:
        print("  SANITY", m)
    return failed


def self_check():
    """Asserts on the trickiest parsing helpers."""
    assert unwrap("(12/1997)") == ("(", "12/1997") and unwrap("[3282.00]") == ("[", "3282.00")
    assert num("(6421.00)") == 6421.0 and num("-931.00") == -931.0 and num("[-]") is None
    assert ym("[3/2006]") == "2006-03" and ym("(-)") is None and ym("-NA-") is None
    assert is_value_tok("28(R1)") and is_value_tok("0/0") and not is_value_tok("KM.53-")
    assert split_name("KAIGA 3 and 4 UNITS (NPCIL) - [020100041]") == \
        ("KAIGA 3 and 4 UNITS", "NPCIL", "020100041")
    assert split_name("BASUNDHRA(WEST)O.C.P (MCL) (2.40 MTY)") == \
        ("BASUNDHRA(WEST)O.C.P (MCL) (2.40 MTY)", None, None)
    assert split_name("GSM PROJECT MOTOROLA (MTNL) (DELHI)")[1] is None
    assert period_from_name("FLR_FEB_2009.pdf") == "2009-02"
    assert period_from_name("MonthlyFR_july_2005.pdf") == "2005-07"
    assert period_from_name("FR_MARCH_2010.pdf") == "2010-03"
    # a layout-A block: stacked cells split by bracket type, glued serial
    hdr = header_cols_a(Line(0, [W(68, 0, 80, 9, "No."), W(85, 0, 105, 9, "Name"),
                                 W(206, 0, 240, 9, "(Revised)"), W(246, 0, 295, 9, "[Anticipated]"),
                                 W(300, 0, 334, 9, "(Revised)"), W(339, 0, 385, 9, "Expenditure"),
                                 W(395, 0, 444, 9, "[Anticipated]"), W(463, 0, 487, 9, "Month]"),
                                 W(513, 0, 533, 9, "Total")]))
    l1 = Line(0, [W(64, 20, 100, 29, "100.POOTKI"), W(122, 20, 160, 29, "BALIHARI"),
                  W(210, 20, 240, 29, "12/1983"), W(259, 20, 285, 29, "199.87"),
                  W(307, 20, 330, 29, "-17.27"), W(352, 20, 380, 29, "173.03"),
                  W(409, 20, 430, 29, "3/1994"), W(471, 20, 480, 29, "156"),
                  W(515, 20, 519, 29, "3"), W(522, 20, 525, 29, "/"), W(527, 20, 531, 29, "5")])
    l2 = Line(0, [W(209, 31, 245, 40, "(4/1997)"), W(256, 31, 290, 40, "(199.87)"),
                  W(304, 31, 334, 40, "(-17.27)"), W(406, 31, 440, 40, "(3/2000)"),
                  W(470, 31, 485, 40, "(84)")])
    l3 = Line(0, [W(85, 42, 110, 51, "UG"), W(256, 42, 290, 51, "[182.60]"),
                  W(406, 42, 440, 51, "[3/2007]"), W(473, 42, 485, 51, "[-]")])
    split_glued_serial(l1, hdr["name_x0"])
    assert l1.w[0].t == "100." and is_serial(l1.w[0], hdr["name_x0"])
    rec, raw, ms, extra, probs = build_project_a({"kind": "project", "lines": [l1, l2, l3], "hdr": hdr})
    assert raw == "POOTKI BALIHARI UG" and ms == "3/5" and not probs, (raw, ms, probs)
    assert rec["doa_original"] == "1983-12" and rec["doa_revised"] == "1997-04"
    assert (rec["cost_original_cr"], rec["cost_revised_cr"], rec["cost_anticipated_cr"]) == \
        (199.87, 199.87, 182.60)
    assert rec["cost_overrun_cr"] == -17.27 and rec["expenditure_cum_cr"] == 173.03
    assert (rec["doc_original"], rec["doc_revised"], rec["doc_anticipated"]) == \
        ("1994-03", "2000-03", "2007-03")
    assert rec["delay_months"] == 156 and rec["additional_delay_months"] is None
    assert extra == "delay_wrt_revised_months: 84; cost_overrun_wrt_revised_cr: -17.27", extra

    def mk(*ts):
        return Line(0, [W(10 * i, 0, 10 * i + 8, 9, t, True) for i, t in enumerate(ts)])
    assert is_list_header(mk("No.Project", "DOA", "Cost", "DOC", "Cost", "DOC"))
    assert is_list_header(mk("Sl.", "Original", "Anticipated"))
    assert is_list_header(mk("Cost", "(", "Rs.", "Crore)", "DOC", "reported"))
    assert is_list_header(mk("Delay"))
    assert not is_list_header(mk("Road", "Transport", "&", "Highways"))
    assert not is_list_header(mk("PROJECT")) and not is_list_header(mk("POWER"))
    assert add_dq(add_dq(None, "a"), "b") == "a;b" and add_dq("a;b", "a") == "a;b"
    print("self-check ok")


if __name__ == "__main__":
    self_check()
    failed = main()
    sys.exit(1 if failed else 0)
