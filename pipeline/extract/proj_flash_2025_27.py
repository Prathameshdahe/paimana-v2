"""
Extractor for the monthly flash reports Apr 2025 - Jul 2026 in
"Project Monitoring/Flash Reports monthly/2025-26/" (family proj_flash_2025_27).

Two layouts:
  * ocms   (FRApril2025, FR_May2025, FR_JUNE_2025; portrait Word export):
           Table 1 sector-wise, Table 2 state-wise, Table 3 completed,
           Table 4 added, Table 5 frozen/deleted (May/Jun), Table 6 NE,
           Table 7 all ongoing (state > sector > project).
  * paimana (FlashReport_*; landscape web export from ipm.mospi.gov.in):
           KPI tiles (overview, NE, HML categories, major ministries),
           HML "Sector - Overview" tables, Table 1 ministry-wise,
           Table 2 state-wise (state x ministry x sector), Completed,
           Newly Added, NE, All Ongoing (ministry > sector > project).

Every table is drawn with cell borders, so a table page is parsed as a grid:
column edges from the header band, row edges per column from horizontal
rules / cell rectangles, words assigned to cells by their centre. Spanning
(merged) cells therefore carry their label to every leaf row they cover.

NE-region project lists repeat the master list with no extra fields: they are
parsed only to check that (manifest note) and not written; their totals are
still in the KPI tiles. "Major On-going Projects" top-5 lists on dashboard
pages are skipped for the same reason.

Printed ids other than project_code go to project_code_alt ('OCMS:<legacy
code>;PMG:<PMGID>'), the actual completion date to date_completed_actual, and
the PAIMANA start date to remarks as 'start: YYYY-MM'. dq_note flags used:
label_restored (ocms group label wrapped / split / printed on the next page),
doc_before_doa, progress_out_of_range:<printed>; in summary
pan_india_row_in_state_group, includes_pan_india_rows, state_not_printed,
duplicate_key_in_source, rounded_6_sig_figs (Table 1/2 latest cost, %g print).

Run from repo root:  python pipeline/extract/proj_flash_2025_27.py
"""
import hashlib
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (DATASET, MANIFEST_COLS, PROJECT_COLS, SUMMARY_COLS,  # noqa: E402
                    fiscal_year, rel, to_num, to_ym, write_part)

FAMILY = "proj_flash_2025_27"
SRC_DIR = DATASET / "Project Monitoring" / "Flash Reports monthly" / "2025-26"
DUP_DIR = DATASET / "Performance Monitoring" / "2026-27"
SKIP = {"QPISR_QR_1st_2025-26.pdf"}  # quarterly report, handled by another family
REPORT_TYPE = "paimana_flash"

MONTHS = ["january", "february", "march", "april", "may", "june", "july",
          "august", "september", "october", "november", "december"]
DARK_BLUE = (0.071, 0.145, 0.529)      # paimana header cells
LIGHT_BLUE = (0.813, 0.871, 0.91)      # ocms header band
MINISTRY_PINK = (0.996, 0.839, 0.855)  # paimana ministry group row
SECTOR_PINK = (0.984, 0.898, 0.906)    # paimana sector group row


# ----------------------------------------------------------------- geometry
def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


def segments(page):
    """Horizontal rules (x0, x1, y), vertical rules (y0, y1, x) and filled
    rectangles (Rect, fill). Thin filled rects (0.7-2.5pt) are rules; thinner
    ones are text underlines and ignored. Cell rects contribute their edges."""
    H, V, R = [], [], []
    for d in page.get_drawings():
        for it in d["items"]:
            if it[0] == "re":
                r = it[1]
                if 0.7 <= r.height <= 2.5 and r.width > 2.5:
                    H.append((r.x0, r.x1, (r.y0 + r.y1) / 2))
                elif 0.7 <= r.width <= 2.5 and r.height > 2.5:
                    V.append((r.y0, r.y1, (r.x0 + r.x1) / 2))
                elif r.width > 2.5 and r.height > 2.5:
                    H += [(r.x0, r.x1, r.y0), (r.x0, r.x1, r.y1)]
                    V += [(r.y0, r.y1, r.x0), (r.y0, r.y1, r.x1)]
                    if d.get("fill"):
                        R.append((r, tuple(round(v, 3) for v in d["fill"])))
            elif it[0] == "l":
                a, b = it[1], it[2]
                if abs(a.y - b.y) < 0.6:
                    H.append((min(a.x, b.x), max(a.x, b.x), a.y))
                elif abs(a.x - b.x) < 0.6:
                    V.append((min(a.y, b.y), max(a.y, b.y), a.x))
    return H, V, R


def dedupe(vals, tol=1.5):
    out = []
    for v in sorted(vals):
        if not out or v - out[-1] > tol:
            out.append(v)
    return out


def lines_of(words):
    """Group words (x0,y0,x1,y1,text,...) into text lines, top to bottom."""
    lines = []
    for w in sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0])):
        yc = (w[1] + w[3]) / 2
        if lines and abs(lines[-1][0] - yc) < 3.0:
            lines[-1][1].append(w)
        else:
            lines.append([yc, [w]])
    return [" ".join(x[4] for x in sorted(ws, key=lambda w: w[0])) for _, ws in lines]


class Grid:
    """One table on one page. cols: [(x0, x1, header_text)]; rows: leaf rows
    [(y0, y1, {col: [lines]}, fill)] where a merged cell repeats its lines in
    every leaf row it spans."""

    def __init__(self, page, H, R, words, col_edges, head_band, bottom, heads=None):
        top, body_top = head_band
        self.cols = []
        for k, (x0, x1) in enumerate(zip(col_edges, col_edges[1:])):
            hw = [w for w in words if x0 <= (w[0] + w[2]) / 2 < x1
                  and top <= (w[1] + w[3]) / 2 <= body_top]
            self.cols.append((x0, x1, heads[k] if heads else clean(" ".join(lines_of(hw)))))
        cells, allb = [], []
        for x0, x1, _ in self.cols:
            ys = [y for a, b, y in H if body_top - 2 <= y <= bottom + 2
                  and min(b, x1) - max(a, x0) >= 0.6 * (x1 - x0)]
            ys = dedupe(ys + [body_top, bottom])
            allb += ys
            cw = [w for w in words if x0 <= (w[0] + w[2]) / 2 < x1
                  and body_top < (w[1] + w[3]) / 2 < bottom]
            col = []
            for a, b in zip(ys, ys[1:]):
                if b - a >= 2:
                    col.append((a, b, lines_of([w for w in cw if a <= (w[1] + w[3]) / 2 < b])))
            cells.append(col)
        width = col_edges[-1] - col_edges[0]
        self.rows = []
        edges = dedupe(allb)
        for a, b in zip(edges, edges[1:]):
            if b - a < 2:
                continue
            yc = (a + b) / 2
            row = {}
            for ci, col in enumerate(cells):
                for c in col:
                    if c[0] <= yc < c[1]:
                        row[ci] = c[2]
                        break
            fill = next((f for r, f in R if r.width >= 0.6 * width
                         and r.y0 <= a + 1 and r.y1 >= b - 1), None)
            self.rows.append((a, b, row, fill))


def page_tables(page, prev=None):
    """All grids on a page: [(title_above, Grid)]. `prev` = a Grid of the
    previous page, reused for ocms continuation pages printed without a
    header row (same vertical rules)."""
    H, V, R = segments(page)
    words = page.get_text("words")
    bands = []
    if page.rect.width > 700:  # paimana: dark-blue header cells below the banner
        hr = [r for r, f in R if f == DARK_BLUE and r.y0 > 190]
        for y0 in dedupe([r.y0 for r in hr], 3):
            cells = [r for r in hr if abs(r.y0 - y0) <= 3]
            y1 = max(r.y1 for r in cells)
            xs = dedupe([r.x0 for r in cells] + [r.x1 for r in cells], 2)
            bands.append((y0, y1, xs))
    else:  # ocms: light-blue header band, columns from vertical rules
        for r, f in R:
            if f == LIGHT_BLUE and r.width > 400:
                xs = dedupe([x for a, b, x in V if a <= r.y0 + 3 and b >= r.y1 - 3], 2)
                if len(xs) >= 3:
                    bands.append((r.y0, r.y1, xs))
    bands.sort()
    out = []
    if not bands and prev is not None and page.rect.width <= 700:
        xs = [c[0] for c in prev.cols] + [prev.cols[-1][1]]
        vx = dedupe([x for a, b, x in V if b - a > 100], 2)
        if len(vx) == len(xs) and all(abs(a - b) < 2 for a, b in zip(vx, xs)):
            hs = [y for a, b, y in H if b >= xs[-1] - 3 and b - a > 0.4 * (xs[-1] - xs[0])]
            if hs:
                return [("", Grid(page, H, R, words, xs, (min(hs), min(hs)), max(hs),
                                  heads=[c[2] for c in prev.cols]))]
    limit_page = page.rect.height - (70 if page.rect.width > 700 else 0)
    for i, (y0, y1, xs) in enumerate(bands):
        limit = bands[i + 1][0] - 5 if i + 1 < len(bands) else limit_page
        # table bottom = lowest rule reaching the right edge (ocms row rules
        # start right of the merged group columns)
        hs = [y for a, b, y in H if y1 < y < limit and b >= xs[-1] - 3 and b - a > 0.4 * (xs[-1] - xs[0])]
        bottom = max(hs) if hs else limit
        above = clean(" ".join(lines_of([w for w in words if y0 - 60 < w[3] <= y0 + 1])))
        out.append((above, Grid(page, H, R, words, xs, (y0, y1), bottom)))
    return out


# ------------------------------------------------------------ text helpers
def unwrap(s):
    """'(265.91)' -> '265.91', '{6/2023}' -> '6/2023'."""
    s = clean(s)
    if len(s) >= 2 and s[0] + s[-1] in ("()", "{}"):
        s = s[1:-1].strip()
    return s


def slots(lines, styles="p({"):
    """Cell lines -> one value per slot. `styles` gives the bracket each slot
    is printed with ('p' plain, '(' or '{'). A line goes to the first free
    slot of its own style, else to the first free slot. Handles
    'orig / (rev) / {ant}', 'orig / rev' (Jul 2025 prints some revised DoCs
    unbracketed), '(start)' printed without an approval date,
    'actual / (orig) / (rev)' and '(orig) / (rev)' (Jun 2026 completed)."""
    out = [None] * len(styles)
    for ln in lines:
        s = clean(ln)
        if not s:
            continue
        st = s[0] if s[0] in "({" else "p"
        free = [i for i in range(len(styles)) if out[i] is None]
        pick = [i for i in free if styles[i] == st] or free
        if pick:
            out[pick[0]] = unwrap(s)
    return out


def num(s):
    """to_num on an unwrapped value ('(265.91)', '1.06074e+006', None ok)."""
    return to_num(unwrap(s))


def ym(s):
    return to_ym(unwrap(s))


def pop_paren(lines):
    """Take the trailing balanced '( ... )' group (may span lines) off `lines`.
    Returns (inner_text, remaining_lines) or (None, lines)."""
    for k in range(len(lines) - 1, -1, -1):
        chunk = clean(" ".join(lines[k:]))
        if chunk.startswith("(") and chunk.endswith(")") and chunk.count("(") == chunk.count(")"):
            # outer group must close at the very end
            depth = 0
            for i, ch in enumerate(chunk):
                depth += ch == "("
                depth -= ch == ")"
                if depth == 0 and i < len(chunk) - 1:
                    break
            else:
                return clean(chunk[1:-1]), lines[:k]
        if len(lines) - k >= 4:
            break
    return None, lines


CODE_RE = re.compile(r"^\(?\s*(N?\d{3,}|-|NA)\s*\)?$")
ID_RE = re.compile(r"\(?\s*(N?\d{3,}|-|NA)\s*\)?")
IDS_LINE_RE = re.compile(r"(?:\(?\s*(?:N?\d{3,}|-|NA)\s*\)?\s*)+")


def parse_name_cell(lines, header="(project code)"):
    """Project cell -> dict(project_name, agency, project_code, legacy_code,
    pmgid, state). The header says which trailing ids are printed, e.g.
    'Project Name (Agency) (Project Code) (Legacy OCMS Code) (PMGID)' or
    'Project Name (Agency Name) (Project Code) (State Name)' (ocms lists).
    Ids are one per line, with or without brackets; '-' means not printed."""
    lines = [clean(x) for x in lines if clean(x)]
    header = header.lower()
    out = {}
    if "(state name)" in header:
        st, rest = pop_paren(lines)
        if st is not None and not CODE_RE.match(f"({st})"):
            out["state"] = st
            lines = rest
    keys = ["project_code"] + ["legacy_code"] * ("legacy" in header) + ["pmgid"] * ("pmgid" in header)
    ids = []
    while lines and len(ids) < len(keys) and IDS_LINE_RE.fullmatch(lines[-1]):
        ids = [m.group(1) for m in ID_RE.finditer(lines[-1])] + ids
        lines = lines[:-1]
    for k, v in zip(keys, ids):  # ids come in header order
        if v not in ("-", "NA"):
            out[k] = v
    ag, rest = pop_paren(lines)
    if ag is not None and rest:
        out["agency"] = ag
        lines = rest
    out["project_name"] = clean(" ".join(lines))
    return out


# ------------------------------------------------------------ report meta
def period_from_name(fn):
    s = fn.lower()
    for i, m in enumerate(MONTHS):
        if m in s:
            y = re.search(r"(20\d\d)", s)
            return f"{y.group(1)}-{i + 1:02d}"
    return None


def period_in_text(doc, layout):
    txt = " ".join(doc[i].get_text() for i in range(min(6, doc.page_count)))
    if layout == "paimana":
        m = re.search(r"as of ([A-Za-z]+) (20\d\d)", txt) or re.search(
            r"\b(" + "|".join(MONTHS) + r")\s+(20\d\d)\b", txt, re.I)
    else:
        m = re.search(r"MOSPI_\s*\(?\s*([A-Za-z]+)\s+(20\d\d)", txt)
    return to_ym(f"{m.group(1)} {m.group(2)}") if m else None


def base(fn, period, page):
    return {"report_period": period, "report_type": REPORT_TYPE,
            "fiscal_year": fiscal_year(period), "quarter": None,
            "source_file": fn, "page": page}


# ------------------------------------------------------------ column roles
def role(h):
    h = h.lower()
    if re.fullmatch(r"s\.?\s*l?\.?\s*no\.?|sl\.?\s*no\.?|s\.no\.", h):
        return "sl"
    if h.startswith("project name"):
        return "name"
    if h.startswith("state"):
        return "state"
    if h.startswith("allocated to"):
        return "ministry"
    if h.startswith("sector"):
        return "sector"
    if h.startswith("project count") or h == "projects":
        return "count"
    if h.startswith("date of approval"):
        return "doa"
    if h.startswith("actual date of completion"):
        return "doc_completed"
    if "doc" in h or h.startswith("date of commissioning"):
        return "doc"
    if "cost" in h:
        return "cost"
    if h.startswith("cumulative expenditure"):
        return "exp"
    if "progress" in h:
        return "progress"
    return None


def join_wrapped(lines):
    """The web export prints some totals with float noise ('799040.390000001')
    and wraps the last digit onto its own line ('799040.39000000' | '1').
    Re-join such a pair and round to paise."""
    out = []
    for ln in lines:
        if out and re.fullmatch(r"\d+", clean(ln)) and re.fullmatch(r"-?[\d,]*\.\d{6,}", clean(out[-1])):
            out[-1] = f"{float(clean(out[-1]).replace(',', '') + clean(ln)):.2f}"
        else:
            out.append(ln)
    return out


def cellmap(grid, row):
    """leaf row -> {role: lines}"""
    out = {}
    for ci, (_, _, h) in enumerate(grid.cols):
        r = role(h)
        if r and r not in out:
            out[r] = join_wrapped(row.get(ci, []))
    return out


def add_dq(d, flag):
    """Append a ';'-joined data-quality flag to a row dict (no duplicates)."""
    cur = [x for x in (d.get("dq_note") or "").split(";") if x]
    if flag not in cur:
        d["dq_note"] = ";".join(cur + [flag])


# ------------------------------------------------------------ project lists
class ListState:
    """Group labels, parsed rows and printed Total rows of one list, carried across pages."""

    def __init__(self, list_type, title):
        self.list_type, self.title = list_type, title
        self.ministry = self.sector = self.state = None
        self.rows, self.totals = [], []
        # ocms: rows of a merged State/Sector cell whose label is printed on a later page
        self.pending = {"state": None, "sector": None}


def project_record(cm, st, has_start, header):
    """Build a PROJECT_COLS dict (minus base fields) from role->lines."""
    doc_head = next((h for h in header.split(" | ") if role(h) == "doc"), "")
    name = parse_name_cell(cm.get("name", []), header)
    rec = {"list_type": st.list_type,
           "project_code": name.get("project_code"),
           "project_name": name.get("project_name") or None,
           "agency": name.get("agency"),
           "sector_raw": st.sector, "ministry": st.ministry}
    state = clean(" ".join(cm.get("state", []))) or name.get("state") or st.state
    rec["state"] = state or None
    # other printed ids: legacy OCMS code (Feb-May 2026) and PMGID (Apr-Jul 2026)
    alt = ([f"OCMS:{name['legacy_code']}"] if name.get("legacy_code") else []) + (
        [f"PMG:{name['pmgid']}"] if name.get("pmgid") else [])
    rec["project_code_alt"] = ";".join(alt) or None
    notes = []
    doa = slots(cm.get("doa", []), "p(")  # approval, (start date)
    rec["doa_original"] = ym(doa[0])
    if has_start and ym(doa[1]):  # no start-date column in PROJECT_COLS
        notes.append(f"start: {ym(doa[1])}")
    if "doc_completed" in cm:  # paimana completed list: actual, (original), (revised)
        dc = slots(cm["doc_completed"], "p((")
        rec["date_completed_actual"] = ym(dc[0])
        rec["doc_original"], rec["doc_revised"] = ym(dc[1]), ym(dc[2])
    else:  # original, (revised), {anticipated}; Jun 2026 completed: (original), (revised)
        dc = slots(cm.get("doc", []), "((" if doc_head.startswith("(") else "p({")
        rec["doc_original"], rec["doc_revised"] = ym(dc[0]), ym(dc[1])
        rec["doc_anticipated"] = ym(dc[2]) if len(dc) > 2 else None
    co = slots(cm.get("cost", []))
    rec["cost_original_cr"], rec["cost_revised_cr"], rec["cost_anticipated_cr"] = map(num, co)
    rec["expenditure_cum_cr"] = num(clean(" ".join(cm.get("exp", []))) or None)
    pp = clean(" ".join(cm.get("progress", [])))
    prog = num(pp) if pp else None
    if prog is not None and not 0 <= prog <= 100:  # impossible value: keep text only
        add_dq(rec, f"progress_out_of_range:{pp}")
        prog = None
    rec["physical_progress_pct"] = prog
    if rec["doa_original"] and rec["doc_original"] and rec["doc_original"] < rec["doa_original"]:
        add_dq(rec, "doc_before_doa")  # kept as printed
    rec["remarks"] = "; ".join(notes) or None
    return rec


def parse_project_grid(grid, st, fn, period, page, ocms):
    """One page of a project list. Group labels come from full-width pink rows
    (paimana) or merged State/Sector columns (ocms); printed Total rows are
    kept for the summary. No list row in this family breaks across a page
    (checked on all files), so any row that is neither a project, a group,
    nor a total is recorded as unparsed instead of being guessed at."""
    header = " | ".join(c[2].lower() for c in grid.cols)
    has_start = "(start date)" in header
    roles = [role(c[2]) for c in grid.cols]
    group_ci = {k: roles.index(k) for k in ("state", "sector") if ocms and k in roles}
    prev = {}
    for k, (a, b, row, fill) in enumerate(grid.rows):
        cm = cellmap(grid, row)
        # cells starting in this leaf row (a merged cell is the same list object)
        fresh = [" ".join(v) for ci, v in row.items() if prev.get(ci) is not v
                 and not (ocms and roles[ci] in ("state", "sector"))]
        new_cell = {key: row.get(ci) is not prev.get(ci) for key, ci in group_ci.items()}
        prev = row
        sl = clean(" ".join(cm.get("sl", [])))
        nm = clean(" ".join(cm.get("name", [])))
        if sl.lower().startswith("note") or nm.lower().startswith("note"):
            break
        if fill == MINISTRY_PINK:
            st.ministry, st.sector = nm, None
            continue
        if fill == SECTOR_PINK:
            st.sector = nm
            continue
        tot_txt = next((clean(" ".join(v)) for v in row.values()
                        if re.match(r"(grand )?total\b", clean(" ".join(v)).lower())), "")
        if ocms and not tot_txt:
            # Merged State/Sector cells print their label vertically centred, so a
            # group that starts near the foot of a page can have its label on the
            # next page. An empty cell is a continuation only when it is the first
            # row of the page and a label is already known; otherwise the label is
            # still to come and the rows wait for it.
            for key, ci in group_ci.items():
                txt = clean(" ".join(row.get(ci, [])))
                if txt:
                    for r in st.pending[key] or []:
                        r["sector_raw" if key == "sector" else "state"] = txt
                        add_dq(r, "label_restored")
                    st.pending[key] = None
                    setattr(st, key, txt)
                elif new_cell[key] and (k > 0 or getattr(st, key) is None) and st.pending[key] is None:
                    setattr(st, key, None)
                    st.pending[key] = []
        if re.fullmatch(r"\d+", sl):
            rec = project_record(cm, st, has_start, header)
            rec.update(base(fn, period, page))
            rec["_sl"] = int(sl)
            for key in group_ci:
                if st.pending[key] is not None:
                    st.pending[key].append(rec)
            st.rows.append(rec)
        elif tot_txt:
            st.totals.append((base(fn, period, page), st.ministry, None if ocms else st.sector, tot_txt, cm))
        elif any(re.sub(r"\s|\*|N\.?A\.?", "", x) for x in fresh):  # ignore '****', stray 'N.A.'
            st.rows.append({"_unparsed": True, "_text": f"p{page}: {sl} | {nm[:80]}"})


# ------------------------------------------------------------ summaries
def srow(b, title, dim, val, sub, metric, value, unit="Rs crore"):
    if value is None:
        return None
    d = dict(b)
    d.update(table_title=title, dimension=dim, dimension_value=val,
             sub_dimension_value=sub, metric=metric, value=value, unit=unit)
    return d


def cost_metrics(lines):
    v = slots(lines)
    return [("cost_original_cr", num(v[0])), ("cost_latest_cr", num(v[1])),
            ("cost_anticipated_cr", num(v[2]))]


def parse_ocms_overview(grid, b, title, dim):
    """ocms Table 1 (sector) / Table 2 (state): one row per label, Total row."""
    out = []
    for a, bb, row, fill in grid.rows:
        cm = cellmap(grid, row)
        label = clean(" ".join(cm.get(dim, [])))  # the Total row prints 'Total' here too
        if not label:
            continue
        d = "overall" if label.lower() == "total" else dim
        mets = [("n_projects", num(clean(" ".join(cm.get("count", [])))))] + cost_metrics(
            cm.get("cost", [])) + [("expenditure_cr", num(clean(" ".join(cm.get("exp", [])))))]
        for mname, v in mets:
            out.append(srow(b, title, d, label, None, mname, v, "count" if mname == "n_projects" else "Rs crore"))
    return [r for r in out if r]


NON_STATES = {"PAN India", "Offshore", "(blank)"}


def sig6(lines):
    """True if a Table 1/2 latest cost is printed with 6 significant digits
    (the web export uses %g, so it may be rounded, e.g. 1.06074e+006)."""
    v = slots(lines)[1] or ""
    return "e+" in v or len(re.sub(r"\D", "", v).lstrip("0")) >= 6


def parse_group_table(rows_iter, b_of, title, kind):
    """paimana Table 1 (ministry x sector) / Table 2 (state x ministry x sector).
    rows_iter yields (page, cm) in document order. Leaf rows are buffered per
    Sl.No group and written at the group's Total row, where the group's state
    is known."""
    rows_iter = list(rows_iter)
    # From Jun 2026 every state group also lists the PAN India projects that
    # cover that state. The first group (Offshore / PAN India / blank) is the
    # table's own non-state bucket and is kept as printed.
    pan_groups = {clean(" ".join(cm.get("sl", []))) for _, cm in rows_iter
                  if clean(" ".join(cm.get("state", []))) == "PAN India"}
    pan_in_states = kind == "state" and len(pan_groups) > 1
    out, leaves, labels = [], [], []
    n_group, cur = 0, None

    def emit(b, dim, val, sub, mets, dq=(), sig=False):
        for mname, v in mets:
            r = srow(b, title, dim, val, sub, mname, v, "count" if mname == "n_projects" else "Rs crore")
            if r:
                for f in list(dq) + (["rounded_6_sig_figs"] if sig and mname == "cost_latest_cr" else []):
                    add_dq(r, f)
                out.append(r)

    for page, cm in rows_iter:
        b = b_of(page)
        sl = clean(" ".join(cm.get("sl", [])))
        sector = clean(" ".join(cm.get("sector", [])))
        ministry = clean(" ".join(cm.get("ministry", [])))
        state = clean(" ".join(cm.get("state", [])))
        count = num(clean(" ".join(cm.get("count", []))))
        exp = num(clean(" ".join(cm.get("exp", []))))
        costs = cost_metrics(cm.get("cost", []))
        tot_mets = [("n_projects", count), ("cost_original_cr", costs[0][1]), ("expenditure_cr", exp)]
        if sl and cur != sl:
            for lv in leaves:  # previous group had no printed Total (Jul/Aug 2025 Table 1)
                emit(**lv)
            cur, labels, leaves = sl, [], []
            n_group += 1
        if not sector and "total" in (ministry.lower(), state.lower()):  # grand total
            emit(b, "overall", "Total", None, tot_mets)
            continue
        if sector.lower() == "total":
            labs = list(dict.fromkeys(x or "(blank)" for x in labels))
            dq = []
            if kind == "ministry":
                dim, val = "ministry", " / ".join(labs) or None
            else:
                dim = "state"
                real = [x for x in labs if x not in NON_STATES]
                only_pan = pan_in_states and n_group > 1 and labs == ["PAN India"]
                if real or only_pan:  # a state group: move its non-state rows under the state
                    val = " / ".join(real) or None
                    dq = ["state_not_printed"] * only_pan + ["includes_pan_india_rows"] * ("PAN India" in labs)
                    for lv in leaves:
                        if not lv["val"] or lv["val"] in NON_STATES:
                            lv["dq"] = ["state_not_printed"] * only_pan + [
                                "pan_india_row_in_state_group" if lv["val"] == "PAN India"
                                else "non_state_row_in_state_group"]
                            lv["sub"] = f"{lv['val'] or '(blank)'} | {lv['sub']}"
                            lv["val"] = val
                else:  # the non-state bucket
                    val = " / ".join(labs) or None
            for lv in leaves:
                emit(**lv)
            leaves = []
            emit(b, dim, val, None, tot_mets, dq)
            continue
        if not sector:
            continue
        labels.append(ministry if kind == "ministry" else state)
        lv = dict(b=b, dim="ministry_sector" if kind == "ministry" else "state_ministry_sector",
                  val=(ministry if kind == "ministry" else state) or None,
                  sub=sector if kind == "ministry" else f"{ministry} | {sector}",
                  mets=[("n_projects", count)] + costs[:2] + [("expenditure_cr", exp)],
                  dq=[], sig=sig6(cm.get("cost", [])))
        leaves.append(lv)
    for lv in leaves:  # last group without a printed Total
        emit(**lv)
    # the state table sometimes prints two rows with the same state/ministry/sector
    key = lambda r: (r["dimension"], r["dimension_value"], r["sub_dimension_value"], r["metric"])  # noqa: E731
    seen = Counter(key(r) for r in out)
    for r in out:
        if seen[key(r)] > 1:
            add_dq(r, "duplicate_key_in_source")
    return out


TILE_PATTERNS = [
    (r"([\d,]+)\s*\|\s*(\d+)\s*\n\s*Ongoing Projects\s*\|", ("n_projects", "n_ministries")),
    (r"(?:^|\n)\s*([\d,]+)\s*\n\s*Ongoing Projects\s*\n", ("n_projects",)),
    (r"([\d,]+)\s*\n\s*Commissioned during month", ("n_completed",)),
    (r"([\d,]+)\s*\n\s*Newly Added during month", ("n_new",)),
    (r"₹?\s*([\d,]+)\s*\n\s*Original Cost\s*\n", ("cost_original_cr",)),
    (r"₹?\s*([\d,]+)\s*\n\s*Revised Cost\s*\n", ("cost_latest_cr",)),
    (r"₹?\s*([\d,]+)\s*\n\s*\(\s*([\d.]+)% of Revised Cost\)\s*\n\s*(?:Cumulative )?Expenditure",
     ("expenditure_cr", "expenditure_pct")),
]


def parse_tiles(page, b, title):
    """KPI tiles of paimana dashboard pages -> summary rows."""
    txt = page.get_text()
    if title.startswith("Flash Report"):
        dim, val = "overall", "All ongoing projects"
    elif title.startswith("Special Focus"):
        dim, val = "other", "North Eastern Region"
    elif title.startswith("HML Category") or title.startswith("Other Sectors"):
        dim, val = "other", title
    elif title.startswith(("Ministry", "Department")):
        dim, val = "ministry", title
    else:
        return [], None
    out, found = [], {}
    for pat, names in TILE_PATTERNS:
        m = re.search(pat, txt)
        if not m or names[0] in found:
            continue
        for i, n in enumerate(names):
            v = to_num(m.group(i + 1))
            found[n] = v
            unit = "pct" if n.endswith("pct") else "count" if n.startswith("n_") else "Rs crore"
            out.append(srow(b, f"{title} (KPI tiles)", dim, val, None, n, v, unit))
    for m in re.finditer(r"([\d,]+)\s*\|\s*₹\s*([\d,]+)\s*\n\s*(Major|Mega) Projects", txt):
        sub = f"{m.group(3)} Projects"
        out.append(srow(b, f"{title} (KPI tiles)", dim, val, sub, "n_projects", to_num(m.group(1)), "count"))
        out.append(srow(b, f"{title} (KPI tiles)", dim, val, sub, "cost_original_cr", to_num(m.group(2))))
    return [r for r in out if r], found


def parse_hml_sector(grid, b, title):
    out = []
    names = {"project count": "n_projects", "original cost": "cost_original_cr",
             "revised cost": "cost_latest_cr", "expenditure": "expenditure_cr"}
    for a, bb, row, fill in grid.rows:
        vals = {c[2].lower(): clean(" ".join(row.get(i, []))) for i, c in enumerate(grid.cols)}
        sector = next((v for k, v in vals.items() if k.startswith("sector name")), "")
        if not sector:
            continue
        for k, v in vals.items():
            for key, metric in names.items():
                if k.startswith(key):
                    out.append(srow(b, f"{title} - Sector Overview", "sector", sector, None, metric,
                                    num(v), "count" if metric == "n_projects" else "Rs crore"))
    return [r for r in out if r]


def list_totals(st, title):
    """Printed 'Total (n)' rows of project lists -> summary (per ministry x sector
    for paimana, per table for ocms)."""
    out = []
    for b, ministry, sector, txt, cm in st.totals:
        m = re.search(r"\((\d+)\)", txt)
        cost = slots(cm.get("cost", []))
        if ministry or sector:
            dim, val, sub = "ministry_sector", ministry, sector
        else:
            dim, val, sub = "overall", "Total", None
        out.append(srow(b, title, dim, val, sub, "n_projects", float(m.group(1)) if m else None, "count"))
        # the '(revised)' slot of a list Total is the sum of the revised costs printed
        # in the list (N.A. rows add nothing), not the latest cost of Tables 1/2
        for mname, v in zip(("cost_original_cr", "cost_revised_cr", "cost_anticipated_cr"), cost):
            out.append(srow(b, title, dim, val, sub, mname, num(v)))
        out.append(srow(b, title, dim, val, sub, "expenditure_cr", num(clean(" ".join(cm.get("exp", []))) or None)))
    return [r for r in out if r]


def repair_labels(rows, key, vocab):
    """ocms merged-cell labels get mangled two ways: Word breaks long words
    inside narrow cells ('MAHARASHTR A') and a label can flow across a page
    break ('ROAD TRANSPORT AND' | 'HIGHWAYS'). Rows are in document order;
    each run of equal labels not in `vocab` (the Table 1/2 labels) is mapped
    to the vocab entry equal to it, or to it joined with the neighbouring
    run, ignoring whitespace. Returns labels left unresolved."""
    def ns(s):
        return re.sub(r"\s+", "", s or "").upper()
    V = {ns(v): v for v in vocab if v}
    runs = []
    for r in rows:
        if runs and runs[-1][0] == r.get(key):
            runs[-1][1].append(r)
        else:
            runs.append([r.get(key), [r]])
    left = set()
    for i, (lab, rs) in enumerate(runs):
        if not lab or lab in vocab or not V:
            continue
        cand = V.get(ns(lab))
        if not cand and i > 0 and runs[i - 1][0] not in vocab:
            cand = V.get(ns(runs[i - 1][0]) + ns(lab))
        if not cand and i + 1 < len(runs) and runs[i + 1][0] not in vocab:
            cand = V.get(ns(lab) + ns(runs[i + 1][0]))
        if cand:
            for r in rs:
                r[key] = cand
                add_dq(r, "label_restored")
        else:
            left.add(lab)
    return sorted(left)


# ------------------------------------------------------------ per file
# "ne" (North-East Region ongoing list) is parsed only to check that it is a
# subset of the master ongoing list with the same fields; it is not written.
PAIMANA_LISTS = {"All Ongoing Projects": "ongoing", "Completed Projects During Month": "completed",
                 "Newly Added Projects": "newly_added", "Ongoing Projects of North-East Region": "ne"}
OCMS_LISTS = [("Completed during", "completed"), ("Added during", "newly_added"),
              ("Frozen", "dropped"), ("Ongoing Projects as of", "ongoing"),
              ("Ongoing Projects of North-East", "ne")]
NE_FIELDS = ["project_name", "agency", "state", "doa_original", "doc_original", "doc_revised",
             "doc_anticipated", "cost_original_cr", "cost_revised_cr", "cost_anticipated_cr",
             "expenditure_cum_cr", "physical_progress_pct", "remarks"]


def check_ne(ne_rows, ongoing):
    """NE list vs master list -> note string."""
    by = {r.get("project_code"): r for r in ongoing}
    miss = [r.get("project_code") for r in ne_rows if r.get("project_code") not in by]
    diff = Counter(f for r in ne_rows if r.get("project_code") in by
                   for f in NE_FIELDS if r.get(f) != by[r["project_code"]].get(f))
    return (f"NE-region list not written: {len(ne_rows)} rows, same columns as the master ongoing list; "
            f"{len(ne_rows) - len(miss)} found there" + (f", {len(miss)} not found e.g. {miss[:3]}" if miss else "")
            + (f", field differences {dict(diff)} (as printed: name wrap spacing, Multi-States order or "
               f"NE part only, 6-digit revised cost, progress 0 vs N.A.; master list kept)" if diff
               else ", all fields identical"))


def process_file(path):
    fn = rel(path)
    doc = fitz.open(path)
    layout = "paimana" if doc[0].rect.width > 700 or doc[min(2, doc.page_count - 1)].rect.width > 700 else "ocms"
    period = period_from_name(path.name)
    in_text = period_in_text(doc, layout)
    notes = []
    if in_text != period:
        notes.append(f"period in text {in_text} != filename {period}")
    b_of = lambda pg: base(fn, period, pg)  # noqa: E731
    projects, summary = [], []
    lists = {}
    group_rows = defaultdict(list)
    stated, tiles_overall = None, {}
    skipped_titles = Counter()
    prev_title = prev_grid = None
    for i, page in enumerate(doc):
        pg = i + 1
        if layout == "paimana":
            title = clean(" ".join(lines_of([w for w in page.get_text("words") if w[3] < 190])))
            title = clean(re.sub(r"\b(" + "|".join(MONTHS) + r")\s+20\d\d\b", " ", title, flags=re.I))
            if not title:
                continue
            if title.startswith(("Flash Report", "Special Focus", "HML Category", "Other Sectors",
                                 "Ministry", "Department")) and "Ongoing" not in title:
                rows, found = parse_tiles(page, b_of(pg), title)
                summary += rows
                if title.startswith("Flash Report"):
                    tiles_overall = found
                for above, g in page_tables(page):
                    if any(role(c[2]) == "sector" for c in g.cols) and "SECTOR NAME" in " ".join(c[2] for c in g.cols):
                        summary += parse_hml_sector(g, b_of(pg), title)
                continue
            lt = PAIMANA_LISTS.get(title)
            tables = page_tables(page)
            if lt:
                st = lists.setdefault(lt, ListState(lt, title))
                for _, g in tables:
                    parse_project_grid(g, st, fn, period, pg, False)
            elif title in ("Ministry-wise Ongoing Projects", "Ongoing Projects State-Wise"):
                for _, g in tables:
                    for a, bb, row, fill in g.rows:
                        group_rows[title].append((pg, cellmap(g, row)))
            elif not title.startswith(("*", "Note")):
                skipped_titles[title[:60]] += 1
        else:
            t = page.get_text()
            m = re.search(r"Table:-\s*\d+\.\s*([^\n]*)", t)
            if not m or "Abbreviations" in t[:200]:
                continue
            title = clean(m.group(1))
            tables = page_tables(page, prev_grid if prev_title == title else None)
            prev_title, prev_grid = title, (tables[-1][1] if tables else None)
            if "Sector-wise Distribution" in title:
                for _, g in tables:
                    summary += parse_ocms_overview(g, b_of(pg), title, "sector")
            elif "State-wise Distribution" in title:
                for _, g in tables:
                    summary += parse_ocms_overview(g, b_of(pg), title, "state")
            else:
                lt = next((v for k, v in OCMS_LISTS if k in title), None)
                if lt is None:
                    skipped_titles[title] += 1
                    continue
                st = lists.setdefault(lt, ListState(lt, title))
                for _, g in tables:
                    parse_project_grid(g, st, fn, period, pg, True)
    for title, rows in group_rows.items():
        kind = "ministry" if title.startswith("Ministry") else "state"
        summary += parse_group_table(rows, b_of, title, kind)
    unparsed, ne_rows = [], []
    for lt, st in lists.items():
        for r in st.rows:
            if r.get("_unparsed"):
                unparsed.append(r["_text"])
            else:
                (ne_rows if lt == "ne" else projects).append(r)
        for key, rs in st.pending.items():
            if rs:
                notes.append(f"{lt}: {len(rs)} rows whose {key} label is never printed (left blank)")
        if lt != "ne":
            summary += list_totals(st, st.title)
    if unparsed:
        notes.append(f"{len(unparsed)} unparsed list rows e.g. {unparsed[:3]}")
    if skipped_titles:
        notes.append("skipped sections: " + ", ".join(f"{k} ({v}p)" for k, v in skipped_titles.items()))
    # stated totals
    if layout == "paimana":
        stated = tiles_overall.get("n_projects")
    else:
        stated = next((r["value"] for r in summary if r["dimension"] == "overall" and r["metric"] == "n_projects"
                       and "Sector-wise" in r["table_title"]), None)
    if layout == "ocms":
        vocab = {k: {r["dimension_value"] for r in summary if r["dimension"] == d} for k, d in
                 (("sector_raw", "sector"), ("state", "state"))}
        for key, voc in vocab.items():
            for lt in lists:
                left = repair_labels([r for r in projects + ne_rows if r["list_type"] == lt], key, voc)
                if left:
                    notes.append(f"{lt}: {key} labels not in Table 1/2 vocabulary: {left}")
    if ne_rows:
        notes.append(check_ne(ne_rows, [r for r in projects if r["list_type"] == "ongoing"]))
    tail = " ".join(doc[k].get_text() for k in range(max(0, doc.page_count - 3), doc.page_count))
    m = re.search(r"projects with ids ([\d,\sand]+?) (?:are not|have not been) published", tail, re.I)
    if m:
        notes.append(f"report note: projects with ids {clean(m.group(1))} not published (expenditure inconsistency)")
    m = re.search(r"\(excluding ([^)]*?)\)", clean(doc[min(1, doc.page_count - 1)].get_text()))
    if m:
        notes.append(f"report scope note: excluding {clean(m.group(1))}")
    doc.close()
    return {"fn": fn, "layout": layout, "period": period, "pages": i + 1, "projects": projects,
            "summary": summary, "stated": stated, "notes": notes, "lists": lists}


# ------------------------------------------------------------ validation
def validate(res):
    """Per-file checks -> list of note strings; also drops exact duplicate rows."""
    notes = []
    projs = res["projects"]
    by_list = defaultdict(list)
    for r in projs:
        by_list[r["list_type"]].append(r)
    # serial numbers contiguous
    for lt, rows in by_list.items():
        sls = [r["_sl"] for r in rows]
        if sls != list(range(1, len(sls) + 1)):
            missing = sorted(set(range(1, max(sls) + 1)) - set(sls))
            dup = [k for k, v in Counter(sls).items() if v > 1]
            notes.append(f"{lt}: serial gaps {missing[:10]} dups {dup[:10]}")
    # list totals vs parsed counts
    for lt, st in res["lists"].items():
        if lt == "ne":
            continue
        grp = Counter((r.get("ministry"), r.get("sector_raw")) for r in by_list[lt])
        for b, ministry, sector, txt, cm in st.totals:
            m = re.search(r"\((\d+)\)", txt)
            if m and (ministry or sector) and grp.get((ministry, sector)) != int(m.group(1)):
                notes.append(f"{lt}: group {ministry}/{sector} printed {m.group(1)} parsed {grp.get((ministry, sector))}")
    # aggregate tables: leaf rows must add up to their printed totals
    sm = [r for r in res["summary"] if r["metric"] == "n_projects"]
    for title, leaf_dim, tot_dim in (("Ministry-wise Ongoing Projects", "ministry_sector", "ministry"),
                                     ("Ongoing Projects State-Wise", "state_ministry_sector", "state")):
        leaf = sum(r["value"] for r in sm if r["table_title"] == title and r["dimension"] == leaf_dim)
        tots = sum(r["value"] for r in sm if r["table_title"] == title and r["dimension"] == tot_dim)
        overall = [r["value"] for r in sm if r["table_title"] == title and r["dimension"] == "overall"]
        if leaf and ((tots and leaf != tots) or (overall and title.startswith("Ministry") and leaf != overall[0])):
            notes.append(f"{title}: leaf rows sum {leaf} vs group totals {tots} / overall {overall}")
    if res["layout"] == "ocms":
        # ongoing list per sector / state vs Table 1 / Table 2 counts
        for key, dim in (("sector_raw", "sector"), ("state", "state")):
            printed = {r["dimension_value"]: r["value"] for r in sm if r["dimension"] == dim}
            got = Counter(r.get(key) for r in by_list.get("ongoing", []))
            bad = {k: (v, got.get(k, 0)) for k, v in printed.items() if got.get(k, 0) != v}
            bad.update({k: (None, v) for k, v in got.items() if k not in printed})
            if bad:
                notes.append(f"ongoing per-{dim} counts vs Table 1/2 (printed, parsed): {bad}")
        # other lists: every (agency, sector) pair should also occur in the ongoing list
        pairs = {(r.get("agency"), r.get("sector_raw")) for r in by_list.get("ongoing", [])}
        agencies = {a for a, _ in pairs}
        odd = [(r["list_type"], r.get("project_code"), r.get("agency"), r.get("sector_raw"))
               for lt in ("completed", "newly_added", "dropped") for r in by_list.get(lt, [])
               if r.get("agency") in agencies and (r.get("agency"), r.get("sector_raw")) not in pairs]
        if odd:
            notes.append(f"(agency, sector) pairs not seen in the ongoing list: {odd[:5]}")
    stated = res["stated"]
    n = len(by_list.get("ongoing", []))
    if stated:
        gap = (n - stated) / stated * 100
        if abs(gap) > 0:
            notes.append(f"ongoing rows {n} vs stated {int(stated)} ({gap:+.1f}%)")
    # value sanity
    bad = Counter()
    for r in projs:
        p = r.get("physical_progress_pct")
        if p is not None and not (0 <= p <= 100):
            bad["progress_out_of_range"] += 1
        for k in ("cost_original_cr", "cost_revised_cr", "cost_anticipated_cr"):
            if r.get(k) is not None and r[k] <= 0:
                bad[f"{k}<=0"] += 1
        if r.get("doa_original") and r.get("doc_original") and r["doc_original"] < r["doa_original"]:
            bad["doc_before_doa"] += 1
        if not r.get("project_code"):
            bad["no_code"] += 1
        if not r.get("agency"):
            bad["no_agency"] += 1
    if bad:
        notes.append("sanity: " + ", ".join(f"{k}={v}" for k, v in bad.items()))
    keys = Counter((r["list_type"], r.get("project_code") or r.get("project_name")) for r in projs)
    dups = [k for k, v in keys.items() if v > 1]
    if dups:
        notes.append(f"{len(dups)} duplicate (list_type, code) keys e.g. {dups[:3]}")
    return notes


def content_hash(path):
    """Hash of the text of every page (to compare byte-different copies)."""
    h = hashlib.sha1()
    with fitz.open(path) as d:
        for p in d:
            h.update(p.get_text().encode("utf-8"))
    return h.hexdigest()


def main():
    files = sorted(p for p in SRC_DIR.glob("*.pdf") if p.name not in SKIP)
    all_proj, all_sum, manifest = [], [], []
    for path in files:
        print("processing", path.name, flush=True)
        try:
            res = process_file(path)
        except Exception as e:  # keep going; record failure
            manifest.append({"source_file": rel(path), "report_type": REPORT_TYPE, "status": "failed",
                             "notes": f"{type(e).__name__}: {e}"})
            print("  FAILED", e)
            continue
        vnotes = validate(res)
        projs = res["projects"]
        cnt = Counter(r["list_type"] for r in projs)
        status = "ok"
        stated = res["stated"]
        if stated and abs(cnt.get("ongoing", 0) - stated) / stated > 0.02:
            status = "partial"
        variant = "ocms_word_2025" if res["layout"] == "ocms" else "paimana_web"
        manifest.append({
            "source_file": res["fn"], "report_type": REPORT_TYPE, "report_period": res["period"],
            "pages": res["pages"], "parser_variant": variant, "stated_total_projects": stated,
            "rows_ongoing": cnt.get("ongoing", 0), "rows_completed": cnt.get("completed", 0),
            "rows_other": sum(v for k, v in cnt.items() if k not in ("ongoing", "completed")),
            "rows_summary": len(res["summary"]), "rows_perf": None, "rows_perf_detail": None,
            "status": status, "notes": "; ".join(res["notes"] + vnotes) or None})
        print(f"  {res['layout']} {res['period']} {dict(cnt)} summary={len(res['summary'])} stated={stated}")
        for n in res["notes"] + vnotes:
            print("   -", n[:300])
        for r in projs:
            r.pop("_sl", None)
        all_proj += projs
        all_sum += res["summary"]
    # Performance Monitoring/2026-27 copies of the Apr-Jul 2026 reports
    for dup in sorted(DUP_DIR.glob("FlashReport_*.pdf")):
        twin = SRC_DIR / dup.name
        same_bytes = twin.exists() and twin.read_bytes() == dup.read_bytes()
        same_text = twin.exists() and (same_bytes or content_hash(twin) == content_hash(dup))
        with fitz.open(dup) as d:
            pages = d.page_count
        manifest.append({
            "source_file": rel(dup), "report_type": REPORT_TYPE, "report_period": period_from_name(dup.name),
            "pages": pages, "parser_variant": "paimana_web",
            "status": "skipped_duplicate" if same_text else "failed",
            "notes": (f"duplicate of {rel(twin)} ("
                      + ("byte-identical" if same_bytes else "bytes differ, text of every page identical")
                      + ")") if same_text else "copy differs in content from Project Monitoring file - NOT processed"})
    write_part(all_proj, FAMILY, "projects", PROJECT_COLS)
    write_part(all_sum, FAMILY, "summary", SUMMARY_COLS)
    write_part(manifest, FAMILY, "manifest", MANIFEST_COLS)
    print(f"projects={len(all_proj)} summary={len(all_sum)} manifest={len(manifest)}")


def selfcheck():
    r = parse_name_cell(["Construction of New Domestic Terminal Building Building and miscellaneous works",
                         "including maintenance, operations and AICMC at Kadapa Airport",
                         "(Airport Authority of India [AAI])", "(612786)", "(N04000106)"],
                        "project name (agency) (project code) (legacy ocms code)")
    assert r["project_code"] == "612786" and r["legacy_code"] == "N04000106"
    assert r["agency"] == "Airport Authority of India [AAI]"
    assert r["project_name"].endswith("at Kadapa Airport")
    r = parse_name_cell(["Development of Keshod Airport.", "(Airport Authority of India [AAI])", "(619054)", "(-)"],
                        "project name (agency) (project code) (legacy ocms code)")
    assert r["project_code"] == "619054" and "legacy_code" not in r
    hdr = "Project Name (Agency) (Project Code) (Legacy OCMS Code) (PMGID)"
    r = parse_name_cell(["Vijayawada Airport.", "(Airport Authority of India [AAI])", "(701107)",
                         "(N04000091) (4353)"], hdr)  # legacy + PMGID share a line
    assert (r["project_code"], r["legacy_code"], r["pmgid"]) == ("701107", "N04000091", "4353")
    r = parse_name_cell(["Kadapa Airport", "(AAI)", "(612786)", "(N04000106) (-)"], hdr)
    assert r["project_code"] == "612786" and r["legacy_code"] == "N04000106" and "pmgid" not in r
    r = parse_name_cell(["354 Uncovered Villages Scheme", "(Department of Telecommunications [DoT])", "701600"])
    assert r["project_code"] == "701600" and r["agency"] == "Department of Telecommunications [DoT]"
    r = parse_name_cell(["REHABILITATION AND UP", "KM 206.00 TO KM 242.00", "(NIMBUTALA TO AUSTIN CREEK)", "O",
                         "(NHIDCL )", "(N24000749 )"])
    assert r["project_code"] == "N24000749" and r["agency"] == "NHIDCL"
    assert r["project_name"] == "REHABILITATION AND UP KM 206.00 TO KM 242.00 (NIMBUTALA TO AUSTIN CREEK) O"
    r = parse_name_cell(["UPGRADATION OF PASSENGER TERMINAL", "(AAI)", "(N04000075 )", "(TAMIL NADU )"],
                        "Project Name (Agency Name) (Project Code) (State Name)")
    assert r == {"state": "TAMIL NADU", "project_code": "N04000075", "agency": "AAI",
                 "project_name": "UPGRADATION OF PASSENGER TERMINAL"}
    r = parse_name_cell(["X PROJECT", "(Haldia Dock Complex, Syama Prasad", "Mookerjee Port Authority)", "701576"])
    assert r["agency"] == "Haldia Dock Complex, Syama Prasad Mookerjee Port Authority"
    assert slots(["417.23", "(N.A.)", "{707.73}"]) == ["417.23", "N.A.", "707.73"]
    assert slots(["01/2026", "03/2026"]) == ["01/2026", "03/2026", None]  # Jul 2025 unbracketed revised
    assert slots(["(12/2018)"], "p(") == [None, "12/2018"]  # start date only
    assert slots(["NA", "(10/2021)", "(08/2025)"], "p((") == ["NA", "10/2021", "08/2025"]  # completed list
    assert slots(["(12/2021)", "(04/2026)"], "((") == ["12/2021", "04/2026"]  # Jun 2026 completed
    assert num("1.06074e+006") == 1060740.0 and ym("(6/2023)") == "2023-06" and ym("10-2013") == "2013-10"
    assert period_from_name("FR_JUNE_2025.pdf") == "2025-06" and period_from_name("FRApril2025.pdf") == "2025-04"
    rows = [{"s": x} for x in ("ROAD TRANSPORT AND", "HIGHWAYS", "HIGHWAYS", "MAHARASHTR A", "POWER", "XYZ")]
    assert repair_labels(rows, "s", {"ROAD TRANSPORT AND HIGHWAYS", "MAHARASHTRA", "POWER"}) == ["XYZ"]
    assert [r["s"] for r in rows] == ["ROAD TRANSPORT AND HIGHWAYS"] * 3 + ["MAHARASHTRA", "POWER", "XYZ"]
    assert join_wrapped(["799040.39000000", "1"]) == ["799040.39"]
    assert join_wrapped(["417.23", "(N.A.)"]) == ["417.23", "(N.A.)"]

    # ocms: a Sector cell that starts empty at the foot of page 1 takes the
    # label printed on page 2 (FR_May2025 p16-17, N24002237/N24002238)
    class G:
        def __init__(self, cells):
            self.cols = [(0, 1, "Sector"), (1, 2, "Sl. No."),
                         (2, 3, "Project Name (Agency Name) (Project Code) (State Name)")]
            self.rows = [(0, 1, {0: c, 1: [str(sl)], 2: ["X", "(MoRTH)", f"(N{sl:08d})", "(ASSAM)"]}, None)
                         for sl, c in cells]
    power, empty, road = ["POWER"], [], ["ROAD TRANSPORT AND HIGHWAYS"]
    st = ListState("newly_added", "t")
    parse_project_grid(G([(7, power), (8, empty), (9, empty)]), st, "f", "2025-05", 16, True)
    parse_project_grid(G([(10, road), (11, road)]), st, "f", "2025-05", 17, True)
    assert [r["sector_raw"] for r in st.rows] == ["POWER"] + ["ROAD TRANSPORT AND HIGHWAYS"] * 4
    assert [r.get("dq_note") for r in st.rows] == [None, "label_restored", "label_restored", None, None]
    # ...while an empty cell in the first row of a page continues the previous label
    st = ListState("ongoing", "t")
    parse_project_grid(G([(1, power)]), st, "f", "2025-05", 1, True)
    parse_project_grid(G([(2, empty), (3, road)]), st, "f", "2025-05", 2, True)
    assert [r["sector_raw"] for r in st.rows] == ["POWER", "POWER", "ROAD TRANSPORT AND HIGHWAYS"]

    # paimana Table 2: PAN India rows inside a state group stay under that state
    def cm(sl, state, sector, n):
        return (1, {"sl": [sl], "state": [state], "ministry": ["DoT"], "sector": [sector],
                    "count": [str(n)], "cost": ["10", "20"], "exp": ["5"]})
    rows = [cm("1", "Offshore", "Oil", 1), cm("1", "PAN India", "Tel", 3), cm("1", "", "Total", 4),
            cm("2", "Bihar", "Tel", 1), cm("2", "PAN India", "Tel", 2), cm("2", "", "Total", 3),
            cm("3", "PAN India", "Tel", 2), cm("3", "", "Total", 2)]
    out = [r for r in parse_group_table(rows, lambda pg: {}, "T", "state") if r["metric"] == "n_projects"]
    got = [(r["dimension"], r["dimension_value"], r["sub_dimension_value"], r.get("dq_note")) for r in out]
    assert got == [("state_ministry_sector", "Offshore", "DoT | Oil", None),
                   ("state_ministry_sector", "PAN India", "DoT | Tel", None),
                   ("state", "Offshore / PAN India", None, None),
                   ("state_ministry_sector", "Bihar", "DoT | Tel", None),
                   ("state_ministry_sector", "Bihar", "PAN India | DoT | Tel", "pan_india_row_in_state_group"),
                   ("state", "Bihar", None, "includes_pan_india_rows"),
                   ("state_ministry_sector", None, "PAN India | DoT | Tel",
                    "state_not_printed;pan_india_row_in_state_group"),
                   ("state", None, None, "state_not_printed;includes_pan_india_rows")], got
    print("selfcheck ok")


if __name__ == "__main__":
    selfcheck()
    if "--check" not in sys.argv:
        main()
