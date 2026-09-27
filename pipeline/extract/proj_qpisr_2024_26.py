"""
Extractor for the QPISR quarterly reports FY 2024-25 Q1 .. FY 2025-26 Q1
(MoSPI IPMD "Quarterly Project Implementation Status Report", central sector
projects costing Rs 150 crore and above).

Run from repo root:  python pipeline/extract/proj_qpisr_2024_26.py

Every table in these PDFs is drawn with thin filled rectangles as cell
borders, so parsing is geometry-first:
  * vertical rules  -> column boundaries (semantics from the header words)
  * horizontal rules -> row boundaries. A rule's left end tells its level:
    it starts at the State column (state group change), the Sector column
    (sector group change) or the Sl No column (plain row boundary).
  * State / Sector are printed once per group cell (top-aligned in some
    tables, vertically centred in others), so a row takes the label of the
    group cell that contains it; an unlabeled first cell on a page continues
    the previous page's group. Same idea as pipeline/extract_pdf_context.py
    (read words by column position, forward-fill), but anchored on the
    drawn cell borders instead of label/row top alignment, which breaks for
    the centred labels of Tables 3/4.
  * The project cell stacks NAME / (AGENCY) / (CODE) / (STATE); the order of
    the bracketed lines differs between tables and reports, so agency vs
    state is decided by the report's own state list (Table 2).
  * Tri-value cells "Original (Revised) {Anticipated}" are split by bracket
    type, not by line position.

Tables per report: 1 sector-wise and 2 state-wise overview (-> summary),
3 completed, 4 added, 5 frozen/deleted, 6 North-East ongoing (subset of 7,
same fields -> used only as a cross-check), 7 all ongoing (master list).
"""
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import fitz  # PyMuPDF

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (DATASET, MANIFEST_COLS, PROJECT_COLS, SUMMARY_COLS,  # noqa: E402
                    fiscal_year, rel, to_num, to_ym, write_part)

FAMILY = "proj_qpisr_2024_26"
QDIR = DATASET / "Project Monitoring" / "Quaterly Reports"
REPORT_TYPE = "quarterly_qpisr"

# (path, quarter, quarter-end period, part kind)
FILES = [
    (QDIR / "2024-25" / "QPISR_1st_QTR_2024-25 PART1.pdf", "Q1", "2024-06", "synopsis"),
    (QDIR / "2024-25" / "QPISR_1st_QTR_2024-25 PART2.pdf", "Q1", "2024-06", "tables"),
    (QDIR / "2024-25" / "QPISR_2nd_QTR_2024-25 PART1.pdf", "Q2", "2024-09", "synopsis"),
    (QDIR / "2024-25" / "QPISR_2nd_QTR_2024-25 PART2.pdf", "Q2", "2024-09", "tables"),
    (QDIR / "2024-25" / "QPISR_3rd_QTR_2024-25.pdf", "Q3", "2024-12", "tables"),
    (QDIR / "2024-25" / "QPISR_4th_QTR_2024-25.pdf", "Q4", "2025-03", "tables"),
    (QDIR / "2025-26" / "QPISR_QR_1st_2025-26.pdf", "Q1", "2025-06", "tables"),
]
DUPLICATES = [  # byte-identical copies of the 2025-26 Q1 report
    (DATASET / "Project Monitoring" / "Quaterly Reports" / "2024-25" / "QPISR_QR_1st_2025-26.pdf",
     QDIR / "2025-26" / "QPISR_QR_1st_2025-26.pdf"),
    (DATASET / "Project Monitoring" / "Flash Reports monthly" / "2025-26" / "QPISR_QR_1st_2025-26.pdf",
     QDIR / "2025-26" / "QPISR_QR_1st_2025-26.pdf"),
]

LIST_TYPES = {3: "completed", 4: "newly_added", 5: "dropped", 6: "ne_region", 7: "ongoing"}
TABLE_TITLES = {1: "Overview of Ongoing Projects: Sector-wise Distribution",
                2: "Overview of Ongoing Projects: State-wise Distribution",
                3: "Project List: Completed during quarter",
                4: "Project List: Added during quarter",
                5: "Project List: Frozen/Deleted during quarter",
                6: "Project List: Ongoing Projects of North-East Region",
                7: "Project List: Ongoing Projects during quarter"}
MONTH_NAMES = ["january", "february", "march", "april", "may", "june", "july",
               "august", "september", "october", "november", "december"]

STATIC_STATES = {
    "ANDAMAN AND NICOBAR ISLANDS", "ANDHRA PRADESH", "ARUNACHAL PRADESH", "ASSAM", "BIHAR",
    "CHANDIGARH", "CHHATTISGARH", "DADRA AND NAGAR HAVELI AND DAMAN AND DIU", "DELHI", "GOA",
    "GUJARAT", "HARYANA", "HIMACHAL PRADESH", "JAMMU AND KASHMIR", "JHARKHAND", "KARNATAKA",
    "KERALA", "LADAKH", "LAKSHADWEEP", "MADHYA PRADESH", "MAHARASHTRA", "MANIPUR", "MEGHALAYA",
    "MIZORAM", "MULTI STATE", "NAGALAND", "ODISHA", "PUDUCHERRY", "PUNJAB", "RAJASTHAN",
    "SIKKIM", "TAMIL NADU", "TELANGANA", "TRIPURA", "UTTAR PRADESH", "UTTARAKHAND",
    "WEST BENGAL"}

CODE_RE = re.compile(r"^\(?(N\d{8}|\d{9})\)?$")
TOKEN_RE = re.compile(r"\{[^{}]*\}?|\([^()]*\)?|[^\s(){}]+")


def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


def unbracket(s):
    """'(MoRTH )' -> 'MoRTH' (outer brackets only, case kept as printed)."""
    s = clean(s)
    s = s[1:] if s.startswith("(") else s
    s = s[:-1] if s.endswith(")") else s
    return clean(s) or None


def norm_label(s):
    """'(TAMIL NADU )' -> 'TAMIL NADU' for vocabulary matching."""
    return clean(re.sub(r"[()]", " ", s)).upper()


# ---------------------------------------------------------------- geometry
def rules(page):
    """Thin filled rects / lines -> horizontal [(y, x0, x1)], vertical [(x, y0, y1)]."""
    hs, vs = [], []
    for g in page.get_drawings():
        for it in g["items"]:
            if it[0] == "re":
                r = it[1]
                if r.height < 2.5 and r.width > 5:
                    hs.append(((r.y0 + r.y1) / 2, r.x0, r.x1))
                elif r.width < 2.5 and r.height > 5:
                    vs.append(((r.x0 + r.x1) / 2, r.y0, r.y1))
            elif it[0] == "l":
                a, b = it[1], it[2]
                if abs(a.y - b.y) < 1 and abs(a.x - b.x) > 5:
                    hs.append((a.y, min(a.x, b.x), max(a.x, b.x)))
                elif abs(a.x - b.x) < 1 and abs(a.y - b.y) > 5:
                    vs.append((a.x, min(a.y, b.y), max(a.y, b.y)))
    return hs, vs


def dedupe(vals, tol=2.0):
    out = []
    for v in sorted(vals):
        if not out or v - out[-1] > tol:
            out.append(v)
    return out


def page_table_no(words):
    for w in words:
        if w[1] < 110:
            m = re.match(r"^Table:-(\d+)\.?$", w[4])
            if m:
                return int(m[1])
    return None


def classify_header(text):
    t = text.lower()
    if re.search(r"\bprojects\b", t) and "name" not in t:
        return "n"
    if "project" in t:
        return "project"
    if t.startswith("sl"):
        return "sl"
    if t.startswith("state"):
        return "state"
    if t.startswith("sector"):
        return "sector"
    if "approval" in t:
        return "doa"
    if "commission" in t:
        return "doc"
    if "cumulative" in t or "expenditure" in t:
        return "exp"
    if "cost" in t:
        return "cost"
    if "physical" in t or "progress" in t:
        return "progress"
    return None


def layout(page, words):
    """Columns {name: (x0, x1)}, body y-range and horizontal rules of a table page."""
    hs, vs = rules(page)
    sl = [w for w in words if re.match(r"^Sl\.?$", w[4]) and w[1] < 200]
    if not sl or not vs:
        return None
    sl_y = min(w[1] for w in sl)
    xs = dedupe([v[0] for v in vs if v[2] - v[1] > 40])
    if len(xs) < 3:
        return None
    left, right = xs[0], xs[-1]
    full = [h for h in hs if h[1] <= left + 3 and h[2] >= right - 3]
    tops = [h[0] for h in full if h[0] > sl_y + 5]
    if not tops:
        return None
    body_top = min(tops)
    bottom = max(v[2] for v in vs if v[2] - v[1] > 40)
    cols = {}
    for x0, x1 in zip(xs, xs[1:]):
        hw = sorted((w for w in words if sl_y - 4 <= w[1] < body_top and x0 <= (w[0] + w[2]) / 2 < x1),
                    key=lambda w: (round(w[1]), w[0]))
        name = classify_header(" ".join(w[4] for w in hw))
        if name and name not in cols:
            cols[name] = (x0, x1)
    body_rules = [h for h in hs if h[2] >= right - 3 and body_top - 1 <= h[0] <= bottom + 1]
    return {"cols": cols, "top": body_top, "bottom": bottom, "hrules": body_rules,
            "left": left, "right": right}


def cells(lay, col):
    """Vertical intervals of the cells of column `col` (boundaries = rules reaching it)."""
    x0 = lay["cols"][col][0]
    ys = [lay["top"], lay["bottom"]] + [h[0] for h in lay["hrules"] if h[1] <= x0 + 3]
    ys = dedupe(ys, 3)
    return [(a, b) for a, b in zip(ys, ys[1:]) if b - a > 4]


def in_box(w, x0, x1, y0, y1):
    cx, cy = (w[0] + w[2]) / 2, (w[1] + w[3]) / 2
    return x0 <= cx < x1 and y0 <= cy < y1


def lines_of(ws, tol=3.0):
    """Group words into text lines (top-to-bottom), each a string."""
    out = []
    for w in sorted(ws, key=lambda w: (w[1], w[0])):
        if out and abs(w[1] - out[-1][0]) <= tol:
            out[-1][1].append(w)
        else:
            out.append([w[1], [w]])
    return [" ".join(x[4] for x in sorted(ln, key=lambda x: x[0])) for _, ln in out]


def tokens(ws):
    """Words of a value cell -> tokens; brackets kept, words inside a bracket joined."""
    return TOKEN_RE.findall(" ".join(lines_of(ws)))


def split_tri(toks):
    """['417.23', '(707.73)', '{707.73}'] -> (orig, revised, anticipated) raw strings.
    Returns also a list of problems (e.g. two plain values)."""
    o = r = a = None
    probs = []
    for t in toks:
        if t.startswith("{"):
            v = t.strip("{} ")
            if a is not None:
                probs.append(f"dup anticipated {t}")
            a = v
        elif t.startswith("("):
            v = t.strip("() ")
            if r is not None:
                probs.append(f"dup revised {t}")
            r = v
        else:
            if o is not None:
                probs.append(f"dup original {t}")
            o = t
    return o, r, a, probs


# ------------------------------------------------------------ raw page scan
def scan(path):
    """Yield per table page: (page_no, table_no, layout, words)."""
    doc = fitz.open(path)
    for i, page in enumerate(doc):
        words = page.get_text("words")
        if not words:
            continue
        text = " ".join(w[4] for w in words[:60])
        if "CONTENTS" in text or "LIST OF TABLES" in text:
            continue
        tno = page_table_no(words)
        if tno is None:
            continue
        # Q1 2024-25 prints the page footer "27of 323" inside the table frame
        # (only that word and the page count right of it: a project code can share the line)
        foot = [w for w in words if re.match(r"^\d+of$", w[4])]
        words = [w for w in words if not any(
            w is f or (abs(w[1] - f[1]) < 3 and w[4].isdigit() and 0 <= w[0] - f[2] < 10) for f in foot)]
        lay = layout(page, words)
        yield i + 1, tno, lay, words
    doc.close()


def join_label(lines, vocab):
    """Narrow State/Sector cells break words mid-word ('ARUNACHA' / 'L PRADESH').
    Try every space/no-space join of the lines and keep one found in the
    report's own vocabulary (Table 1/2 labels); else plain space join."""
    default = clean(" ".join(lines))
    if len(lines) < 2 or len(lines) > 7 or default.upper() in vocab:
        return default
    for mask in range(2 ** (len(lines) - 1)):
        s = lines[0]
        for i, ln in enumerate(lines[1:]):
            s += ("" if mask >> i & 1 else " ") + ln
        if clean(s).upper() in vocab:
            return clean(s)
    return default


def group_labels(lay, words, col, vocab):
    """[(y0, y1, label or '')] for the State/Sector column of one page, plus
    whether a new group starts at the top of the body. The header's bottom
    border is one rule; a group cell opening right under it draws a second
    rule reaching this column at the same y (a continued group does not)."""
    x0, x1 = lay["cols"][col]
    out = []
    for a, b in cells(lay, col):
        ws = [w for w in words if in_box(w, x0, x1, a, b)]
        out.append((a, b, join_label(lines_of(ws), vocab)))
    new_top = sum(1 for h in lay["hrules"] if abs(h[0] - lay["top"]) < 2 and h[1] <= x0 + 3) >= 2
    return out, new_top


def resolve_groups(page_cells, vocab):
    """page_cells: [(pno, [(y0, y1, label)], new_top)] of one table/column in page order.
    An unlabeled cell that opens a page continues the previous page's group
    (unless the rules say a new group starts there); an unlabeled cell whose
    group runs on past the page end had its (vertically centred) label printed
    in a later fragment; a label cut by the page break ('ROAD TRANSPORT AND' |
    'HIGHWAYS') is re-joined. Returns {pno: cells}."""
    new_top = [nt for _, _, nt in page_cells]
    page_cells = [(p, [list(c) for c in cl]) for p, cl, _ in page_cells]
    for (_, prev), (_, cur) in zip(page_cells, page_cells[1:]):
        if prev and cur and prev[-1][2] and cur[0][2] and prev[-1][2].upper() not in vocab:
            joined = join_label([prev[-1][2], cur[0][2]], vocab)
            if joined.upper() in vocab:
                prev[-1][2] = cur[0][2] = joined
    out, carry = {}, None
    for i, (pno, cl) in enumerate(page_cells):
        res = []
        for k, (a, b, lab) in enumerate(cl):
            if not lab and k == 0 and carry and not new_top[i]:
                lab = carry
            elif not lab and k == len(cl) - 1:
                # follow the split cell forward: full-page unlabeled fragments, then
                # the first cell of the page where the group ends
                for j in range(i + 1, len(page_cells)):
                    nxt = page_cells[j][1]
                    if not nxt or new_top[j]:
                        break
                    if nxt[0][2]:
                        lab = nxt[0][2]
                        break
                    if len(nxt) > 1:
                        break
            res.append((a, b, lab or None))
        if res:
            carry = res[-1][2]
        out[pno] = res
    return out


def raw_rows(lay, words):
    """Row cells of a list/summary table page -> list of dicts of words per column."""
    anchor = "sl" if "sl" in lay["cols"] else "project"
    rows = []
    for a, b in cells(lay, anchor):
        r = {"y0": a, "y1": b}
        for c, (x0, x1) in lay["cols"].items():
            r[c] = [w for w in words if in_box(w, x0, x1, a, b)]
        if any(r[c] for c in lay["cols"] if c not in ("state", "sector")):
            rows.append(r)
    return rows


# --------------------------------------------------------- project-cell parse
def parse_project_cell(lines, states):
    """NAME lines / (AGENCY) / (CODE) / (STATE) in any bracket order.
    Returns dict(name, agency, state, code, problems)."""
    res = {"name": None, "agency": None, "state": None, "code": None, "problems": []}
    ci = None
    for i, ln in enumerate(lines):
        m = CODE_RE.match(ln.replace(" ", ""))
        if m:
            ci = i
            res["code"] = m[1]
    if ci is None:
        res["name"] = clean(" ".join(lines))
        res["problems"].append("no project code")
        return res
    # bracketed meta line(s) just before the code; may wrap onto 2 lines
    mb = ci - 1
    if mb >= 0 and not lines[mb].lstrip().startswith("(") and mb - 1 >= 0 \
            and lines[mb - 1].lstrip().startswith("(") and ")" not in lines[mb - 1]:
        mb -= 1
    before = clean(" ".join(lines[mb:ci])) if mb >= 0 and lines[mb].lstrip().startswith("(") else None
    name_lines = lines[:mb] if before is not None else lines[:ci]
    after = clean(" ".join(lines[ci + 1:])) or None
    metas = [m for m in (before, after) if m]
    st = [m for m in metas if norm_label(m) in states]
    if len(metas) == 2:
        if len(st) == 1:
            res["state"] = norm_label(st[0])
            res["agency"] = unbracket([m for m in metas if m is not st[0]][0])
        else:
            res["problems"].append(f"cannot tell agency/state: {metas}")
            # leave both blank rather than guess
    elif len(metas) == 1:
        if st and after:            # only a state after the code, no agency
            res["state"] = norm_label(st[0])
        else:
            res["agency"] = unbracket(metas[0])
    res["name"] = clean(" ".join(name_lines)) or None
    if not res["name"]:
        res["problems"].append("empty name")
    return res


def report_meta(path):
    """Period text from the running header, e.g. 'MOSPI_ (April-June 2024) 1st_QPSR_'."""
    doc = fitz.open(path)
    txt = ""
    for p in range(min(12, doc.page_count)):
        txt += " " + doc[p].get_text()
    doc.close()
    txt = clean(txt.replace("\xa0", " ").replace("‐", "-"))
    m = re.search(r"\((January|April|July|October)\s*-\s*(March|June|September|December)[_,\s]*(\d{4})", txt)
    if m:
        return f"{int(m[3]):04d}-{MONTH_NAMES.index(m[2].lower()) + 1:02d}", m[0]
    m = re.search(r"(\d)(?:st|nd|rd|th)\s*Quarter[^()]*\((April|July|October|January)-(June|September|December|March)[_\s]*(\d{4})-(\d{2})\)", txt)
    if m:
        start = int(m[4])
        mon = MONTH_NAMES.index(m[3].lower()) + 1
        y = start + 1 if mon <= 3 else start
        return f"{y:04d}-{mon:02d}", m[0]
    # PART1 synopsis files: the text layer is fragmented ("Implementation_1 / st ... ne_ 2024-25)")
    compact = re.sub(r"\s+", "", txt)
    q = re.search(r"mentation_(\d)(?:st|nd|rd|th)", compact)
    fy = re.search(r"(\d{4})-(\d{2})\)", compact)
    if q and fy:
        qn, start = int(q[1]), int(fy[1])
        return f"{start + 1 if qn == 4 else start:04d}-{[6, 9, 12, 3][qn - 1]:02d}", f"Q{qn} {fy[0][:-1]}"
    return None, None


# ------------------------------------------------------------- per report
def extract_report(path, quarter, period):
    src = rel(path)
    base = {"report_period": period, "report_type": REPORT_TYPE,
            "fiscal_year": fiscal_year(period), "quarter": quarter, "source_file": src}
    pages = list(scan(path))
    notes, problems = [], []

    # vocabularies: Table 1 sector labels, Table 2 state labels (+ static list)
    vocab = {"sector": set(), "state": set(STATIC_STATES)}
    for pno, tno, lay, words in pages:
        if lay and tno in (1, 2):
            dim = "sector" if tno == 1 else "state"
            for r in raw_rows(lay, words):
                lab = norm_label(" ".join(lines_of(r.get(dim, []))))
                if lab and lab != "TOTAL":
                    vocab[dim].add(lab)
    states = vocab["state"]

    summary, raw = [], defaultdict(list)
    table_pages = defaultdict(list)
    gcells = defaultdict(list)                  # (table, col) -> [(pno, cells)]
    for pno, tno, lay, words in pages:
        table_pages[tno].append(pno)
        if lay is None:
            problems.append(f"p{pno}: table {tno} layout not found")
            continue
        if tno in LIST_TYPES:
            for gcol in ("state", "sector"):
                if gcol in lay["cols"]:
                    gcells[(tno, gcol)].append((pno, *group_labels(lay, words, gcol, vocab[gcol])))
    glab = {k: resolve_groups(v, vocab[k[1]]) for k, v in gcells.items()}
    unknown = Counter()
    for (tno, gcol), per_page in glab.items():
        for cl in per_page.values():
            for a, b, lab in cl:
                if lab and lab.upper() not in vocab[gcol] and "total" not in lab.lower():
                    unknown[f"{gcol}:{lab}"] += 1
    if unknown:
        notes.append("group labels not in Table 1/2 vocab (kept as printed): " + ", ".join(sorted(unknown)))

    for pno, tno, lay, words in pages:
        if lay is None:
            continue
        cols = lay["cols"]
        if tno in (1, 2):
            dim = "sector" if tno == 1 else "state"
            for r in raw_rows(lay, words):
                label = clean(" ".join(lines_of(r.get(dim, []))))
                sl = clean(" ".join(lines_of(r.get("sl", []))))
                if not label:
                    continue
                if label.lower() == "total":
                    label = "Total"
                elif not sl.isdigit():
                    problems.append(f"p{pno}: T{tno} row without Sl: {label}")
                o, rv, a, pr = split_tri(tokens(r.get("cost", [])))
                if pr:
                    problems.append(f"p{pno}: T{tno} {label}: {pr}")
                vals = {"n_projects": " ".join(w[4] for w in r.get("n", [])),
                        "cost_original_cr": o, "cost_latest_cr": rv, "cost_anticipated_cr": a,
                        "expenditure_cr": " ".join(w[4] for w in r.get("exp", []))}
                for metric, v in vals.items():
                    num = to_num(v)
                    if num is None:
                        continue
                    summary.append({**base, "page": pno, "table_title": TABLE_TITLES[tno],
                                    "dimension": "overall" if label == "Total" else dim,
                                    "dimension_value": label, "sub_dimension_value": None,
                                    "metric": metric, "value": num,
                                    "unit": "count" if metric == "n_projects" else "Rs crore"})
            continue
        if tno not in LIST_TYPES:
            continue
        for r in raw_rows(lay, words):
            ymid = r["y0"] + 2
            rec = {"page": pno, "y0": r["y0"],
                   "sl": clean(" ".join(w[4] for w in r.get("sl", []))),
                   "lines": lines_of(r.get("project", [])),
                   "vals": {c: tokens(r[c]) for c in ("doa", "doc", "cost", "exp", "progress") if c in r}}
            for gcol in ("state", "sector"):
                if (tno, gcol) in glab:
                    cl = glab[(tno, gcol)].get(pno, [])
                    rec[gcol] = next((lab for a, b, lab in cl if a - 1 <= ymid < b), None)
            raw[tno].append(rec)

    # merge rows split across a page break (fragment without code joins its neighbour)
    rows_out, ne_rows = [], []
    counts = Counter()
    for tno, recs in raw.items():
        merged = []
        for rec in recs:
            has_code = any(CODE_RE.match(ln.replace(" ", "")) for ln in rec["lines"])
            is_total = (rec["lines"][0].lower().startswith("total") if rec["lines"]
                        else "total" in (rec.get("sector") or "").lower())
            if merged and not is_total and rec["page"] != merged[-1]["page"] and (
                    not has_code or not merged[-1]["_code"]) and rec["y0"] < 200:
                prev = merged[-1]
                prev["lines"] += rec["lines"]
                prev["sl"] = prev["sl"] or rec["sl"]
                for c, v in rec["vals"].items():
                    prev["vals"][c] = prev["vals"].get(c, []) + v
                prev["_code"] = prev["_code"] or has_code
                notes.append(f"T{tno}: row split p{prev['page']}->p{rec['page']} merged")
                continue
            rec["_code"] = has_code
            rec["_total"] = is_total
            merged.append(rec)
        sls = []
        for rec in merged:
            if rec["_total"]:
                o, rv, a, _ = split_tri(rec["vals"].get("cost", []))
                # the (Revised) total equals the sum of revised-else-original = latest cost
                for metric, v in (("cost_original_cr", o), ("cost_latest_cr", rv),
                                  ("cost_anticipated_cr", a),
                                  ("expenditure_cr", " ".join(rec["vals"].get("exp", [])))):
                    if to_num(v) is not None:
                        summary.append({**base, "page": rec["page"], "table_title": TABLE_TITLES[tno] + " (Total row)",
                                        "dimension": "overall", "dimension_value": "Total",
                                        "sub_dimension_value": None, "metric": metric,
                                        "value": to_num(v), "unit": "Rs crore"})
                continue
            if not rec["lines"]:
                continue
            pc = parse_project_cell(rec["lines"], states)
            for p in pc["problems"]:
                problems.append(f"p{rec['page']}: T{tno} sl {rec['sl']}: {p}")
            if not pc["code"]:
                continue
            if rec["sl"].isdigit():
                sls.append(int(rec["sl"]))
            else:
                problems.append(f"p{rec['page']}: T{tno} {pc['code']}: Sl '{rec['sl']}'")
            v = rec["vals"]
            co, cr, ca, p1 = split_tri(v.get("cost", []))
            do, dr, da, p2 = split_tri(v.get("doc", []))
            doa, _, _, p3 = split_tri(v.get("doa", []))
            for p in p1 + p2 + p3:
                problems.append(f"p{rec['page']}: T{tno} {pc['code']}: {p}")
            row = {**base, "page": rec["page"], "list_type": LIST_TYPES[tno],
                   "project_code": pc["code"], "project_name": pc["name"],
                   "sector_raw": rec.get("sector"), "agency": pc["agency"],
                   "state": rec.get("state") or pc["state"],
                   "doa_original": to_ym(doa),
                   "cost_original_cr": to_num(co), "cost_revised_cr": to_num(cr),
                   "cost_anticipated_cr": to_num(ca),
                   "expenditure_cum_cr": to_num(" ".join(v.get("exp", []))) if len(v.get("exp", [])) == 1 else None,
                   "doc_original": to_ym(do), "doc_revised": to_ym(dr), "doc_anticipated": to_ym(da),
                   "physical_progress_pct": to_num(v["progress"][0]) if len(v.get("progress", [])) == 1 else None}
            if len(v.get("exp", [])) > 1 or len(v.get("progress", [])) > 1:
                problems.append(f"p{rec['page']}: T{tno} {pc['code']}: multi exp/progress {v.get('exp')} {v.get('progress')}")
            if not row["sector_raw"] or not row["state"]:
                problems.append(f"p{rec['page']}: T{tno} {pc['code']}: missing sector/state "
                                f"{row['sector_raw']!r}/{row['state']!r}")
            # unparsed-but-printed values are a parsing problem, not a blank
            for fld, raw_v in (("doa_original", doa), ("doc_original", do), ("doc_revised", dr),
                               ("doc_anticipated", da)):
                if raw_v and row[fld] is None and to_num(raw_v) is None and raw_v.upper() not in ("N.A.", "NA", ""):
                    problems.append(f"p{rec['page']}: T{tno} {pc['code']}: unparsed {fld} '{raw_v}'")
            if tno == 6:
                ne_rows.append(row)
            else:
                rows_out.append(row)
                counts[LIST_TYPES[tno]] += 1
        if sls and sorted(sls) != list(range(1, len(sls) + 1)):
            miss = sorted(set(range(1, max(sls) + 1)) - set(sls))
            dup = [k for k, c in Counter(sls).items() if c > 1]
            problems.append(f"T{tno}: Sl sequence gaps {miss[:10]} dups {dup[:10]} (n={len(sls)}, max={max(sls)})")
    return rows_out, ne_rows, summary, counts, table_pages, notes, problems, states


def main():
    all_rows, all_summary, manifest = [], [], []
    for path, quarter, period, kind in FILES:
        src = rel(path)
        doc = fitz.open(path)
        npages = doc.page_count
        doc.close()
        found_period, found_txt = report_meta(path)
        mnote = [f"period confirmed by PDF text '{found_txt}'" if found_period == period else
                 f"period in PDF text {found_period!r} ({found_txt}) != filename {period}"]
        if kind == "synopsis":
            manifest.append({"source_file": src, "report_type": REPORT_TYPE, "report_period": period,
                             "pages": npages, "parser_variant": "synopsis_image",
                             "rows_ongoing": 0, "rows_completed": 0, "rows_other": 0, "rows_summary": 0,
                             "status": "ok",
                             "notes": "; ".join(mnote + ["PART1 = image-only synopsis/infographic pages (no text-layer "
                                                         "tables, no OCR); all tables are in the PART2 file"])})
            print(f"{src}: synopsis only")
            continue
        rows, ne_rows, summary, counts, tpages, notes, problems, states = extract_report(path, quarter, period)
        stated = next((s["value"] for s in summary if s["dimension"] == "overall"
                       and s["metric"] == "n_projects" and s["table_title"] == TABLE_TITLES[1]), None)
        # cross-check: NE table (T6) against master list (T7)
        ongoing = {r["project_code"]: r for r in rows if r["list_type"] == "ongoing"}
        ne_missing = [r["project_code"] for r in ne_rows if r["project_code"] not in ongoing]
        ne_diff = [r["project_code"] for r in ne_rows if r["project_code"] in ongoing and any(
            r[k] != ongoing[r["project_code"]][k] for k in ("state", "sector_raw", "cost_original_cr",
                                                             "expenditure_cum_cr", "physical_progress_pct"))]
        n_on = counts["ongoing"]
        gap = None if not stated else (n_on - stated) / stated * 100
        status = "ok" if not problems and (gap is None or abs(gap) <= 2) else "partial"
        mnote += [f"tables pages: " + ", ".join(f"T{k}:{v[0]}-{v[-1]}" for k, v in sorted(tpages.items())),
                  f"Table 6 (North-East ongoing, {len(ne_rows)} rows) not written: subset of Table 7 with the same "
                  f"fields; cross-check vs T7: {len(ne_missing)} missing, {len(ne_diff)} field mismatches",
                  "ministry/location/capacity/delay not printed in these reports; sector_raw = 'Sector' group column",
                  "Table 1 '(Revised)*' = revised or original cost -> cost_latest_cr"]
        if gap is not None:
            mnote.append(f"ongoing rows {n_on} vs Table 1 Total projects {stated:.0f} ({gap:+.2f}%)")
        mnote += notes[:5]
        if problems:
            mnote.append(f"{len(problems)} parse problems: " + " | ".join(problems[:8]))
        manifest.append({"source_file": src, "report_type": REPORT_TYPE, "report_period": period,
                         "pages": npages, "parser_variant": "qpisr_ruled_tables_v1",
                         "stated_total_projects": stated, "rows_ongoing": n_on,
                         "rows_completed": counts["completed"],
                         "rows_other": counts["newly_added"] + counts["dropped"],
                         "rows_summary": len(summary), "status": status, "notes": "; ".join(mnote)})
        all_rows += rows
        all_summary += summary
        print(f"{src}: {dict(counts)} NE={len(ne_rows)} summary={len(summary)} stated={stated} "
              f"problems={len(problems)} ne_missing={len(ne_missing)} ne_diff={len(ne_diff)}")
        for p in problems[:40]:
            print("   ", p)
    for dup, orig in DUPLICATES:
        manifest.append({"source_file": rel(dup), "report_type": REPORT_TYPE, "report_period": "2025-06",
                         "status": "skipped_duplicate",
                         "notes": f"byte-identical copy of {rel(orig)} (processed there)"})
    for name, rows_, cols in (("projects", all_rows, PROJECT_COLS), ("summary", all_summary, SUMMARY_COLS),
                              ("manifest", manifest, MANIFEST_COLS)):
        print("wrote", write_part(rows_, FAMILY, name, cols), len(rows_))
    return all_rows, all_summary, manifest


def self_check():
    st = {"TAMIL NADU", "MAHARASHTRA", "KERALA"}
    # name / (agency) / (code) / (state)  -- Q1 2024-25 Table 3 order
    r = parse_project_cell(["C/O OF 152 NOS TYPE-II", "CHENNAI", "(CPWD FOR FINANC )",
                            "(N28000089 )", "(TAMIL NADU )"], st)
    assert (r["code"], r["agency"], r["state"], r["name"]) == \
        ("N28000089", "CPWD FOR FINANC", "TAMIL NADU", "C/O OF 152 NOS TYPE-II CHENNAI"), r
    # name / (state) / (code) / (agency)  -- Q1 2025-26 Table 3 order
    r = parse_project_cell(["PANDHARPUR TO SANGOLA", "(MAHARASHTRA)", "(N24001102 )", "(MoRTH )"], st)
    assert (r["agency"], r["state"]) == ("MoRTH", "MAHARASHTRA"), r
    # Table 7: name / (agency) / (code); a name may itself contain brackets
    r = parse_project_cell(["SUBANSIRI LOWER H.E.P (8X250 MW)", "(NHPC)", "(NHPC )", "( 180100221 )"], st)
    assert (r["code"], r["agency"], r["state"], r["name"]) == \
        ("180100221", "NHPC", None, "SUBANSIRI LOWER H.E.P (8X250 MW) (NHPC)"), r
    assert split_tri(tokens([(0, 0, 0, 0, "9/2018"), (0, 10, 0, 0, "(May-23)"), (0, 20, 0, 0, "{6/2023}")]))[:3] \
        == ("9/2018", "May-23", "6/2023")
    assert split_tri(TOKEN_RE.findall("417.23 (N.A.) {707.73}"))[:3] == ("417.23", "N.A.", "707.73")
    # group labels across pages (Q2 2024-25 Table 4, p16-19): RAILWAYS ends on p16, a new
    # group opens at the top of p17 (double rule) whose centred label sits on p18
    pages = [(16, [(159, 600, "POWER"), (600, 673, "RAILWAYS")], True),
             (17, [(159, 686, "")], True),
             (18, [(159, 735, "ROAD TRANSPORT AND HIGHWAYS")], False),
             (19, [(159, 453, ""), (453, 600, "URBAN DEVELOPMENT")], False)]
    g = resolve_groups(pages, {"RAILWAYS", "ROAD TRANSPORT AND HIGHWAYS"})
    assert [c[2] for c in g[17] + g[19]] == ["ROAD TRANSPORT AND HIGHWAYS"] * 2 + ["URBAN DEVELOPMENT"], g
    # label cut by the page break, word broken inside a narrow cell
    g = resolve_groups([(13, [(700, 732, "COAL"), (732, 747, "ROAD TRANSPORT AND")], False),
                        (14, [(130, 767, "HIGHWAYS")], False)], {"COAL", "ROAD TRANSPORT AND HIGHWAYS"})
    assert g[13][1][2] == g[14][0][2] == "ROAD TRANSPORT AND HIGHWAYS", g
    assert join_label(["ARUNACHA", "L PRADESH"], {"ARUNACHAL PRADESH"}) == "ARUNACHAL PRADESH"
    assert to_ym("May-23") == "2023-05" and to_ym("01-12-2021") == "2021-12" and to_ym("2-2024") == "2024-02"
    print("self-check ok")


if __name__ == "__main__":
    self_check()
    main()
