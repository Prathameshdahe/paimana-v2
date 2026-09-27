"""
Extractor for the MoSPI IPMD quarterly "Project Implementation Status Report"
(QPSIR / QPSR) FY 2021-22 Q1 .. FY 2023-24 Q4, central sector projects
costing Rs 150 crore and above.

Run from repo root:  python pipeline/extract/proj_qpsir_2021_24.py

Two report layouts:
  * "detail" (2021-22 Q1..Q4, 2022-23 Q1..Q4, 2023-24 Q1): Part-II prints one
    Courier-font card per ongoing project (serial + name, code / Location /
    Capacity line, a 7-column x 3-row value grid, then a free-text Background).
    Those cards are the master ongoing list. Sector = the "Sector: X / Status of
    projects as on" page that opens each section, agency = the bold 12pt
    heading printed when the agency changes.
  * "lists" (2023-24 Q2, Q3 and the Q4 Part_II file): no cards; the ongoing
    projects are spread over the schedule-status annexure lists (ahead /
    on schedule / delayed / without DOC / without original DOC), which
    partition the monitored set. Those lists are parsed by word position
    (column x-ranges from the header words, row 1 = the S.No line, row 2 =
    the next line) and together form the ongoing list.
Every table is parsed from PyMuPDF span coordinates (pdftotext -layout
misaligns these files). Overview tables (Highlights, Table 1-4, sector-wise
implementation status, per-sector status pages) go to the summary part.
"""
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import fitz  # PyMuPDF

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (DATASET, MANIFEST_COLS, PROJECT_COLS, SUMMARY_COLS,  # noqa: E402
                    fiscal_year, rel, to_num, to_ym, write_part)

FAMILY = "proj_qpsir_2021_24"
REPORT_TYPE = "quarterly_qpisr"
QDIR = DATASET / "Project Monitoring" / "Quaterly Reports"

# (path, quarter, quarter-end period, layout)
FILES = [
    (QDIR / "2021-22" / "QPSIR1stqtr2021-22.pdf", "Q1", "2021-06", "detail"),
    (QDIR / "2021-22" / "QPSIR_2nd_qtr_2021-22.pdf", "Q2", "2021-09", "detail"),
    (QDIR / "2021-22" / "QPSIR_3qtr_21-22.pdf", "Q3", "2021-12", "detail"),
    (QDIR / "2021-22" / "QPSIR_4th_QTR_2021-22.pdf", "Q4", "2022-03", "detail"),
    (QDIR / "2022-23" / "QPSIR_1st_QTR_2022-23.pdf", "Q1", "2022-06", "detail"),
    (QDIR / "2022-23" / "QPSIR_2nd_QTR_2022-23.pdf", "Q2", "2022-09", "detail"),
    (QDIR / "2022-23" / "QPSIR_3rd_QTR_2022-23.pdf", "Q3", "2022-12", "detail"),
    (QDIR / "2022-23" / "QPSIR_4th_QTR_2022-23.pdf", "Q4", "2023-03", "detail"),
    (QDIR / "2023-24" / "QPSR_1st_QTR_2023-24.pdf", "Q1", "2023-06", "detail"),
    (QDIR / "2023-24" / "QPSR_2nd_QTR_2023-24.pdf", "Q2", "2023-09", "lists"),
    (QDIR / "2023-24" / "QPSR_3rd_QTR_2023-24.pdf", "Q3", "2023-12", "lists"),
    (QDIR / "2023-24" / "QPSR-4th_QTR_2023-2024 Part_I.pdf", "Q4", "2024-03", "overview"),
    (QDIR / "2023-24" / "QPSR-4th_QTR_2023-2024 Part_II.pdf", "Q4", "2024-03", "lists"),
]

CODE_RE = re.compile(r"^(N\d{8}|\d{9})$")


def clean(s):
    # U+FFFD = an unmapped line-end glyph in the card text layer (pdftotext drops it)
    return re.sub(r"\s+", " ", (s or "").replace("�", " ")).strip()


# --------------------------------------------------------------------------- spans
def is_page_number(s, page):
    """Printed page number: a small digits-only span, horizontally centred in the bottom
    margin. It can share a text line with a heading printed just above the margin
    (completed list, QPSIR_2nd_qtr_2021-22 p852/p856: 'NTPC' + '848')."""
    r = page.rect
    return (re.fullmatch(r"\d{1,4}", s["t"]) is not None and s["size"] <= 8.5
            and s["y0"] > r.height - 80 and abs(s["xc"] - r.width / 2) < 20)


def page_spans(page, _dropped=None):
    """Non-empty text spans with geometry and font flags (printed page numbers removed)."""
    out = []
    for b in page.get_text("dict", flags=0)["blocks"]:
        for ln in b.get("lines", []):
            for s in ln["spans"]:
                t = s["text"].strip()
                if not t:
                    continue
                x0, y0, x1, y1 = s["bbox"]
                sp = {"x0": x0, "y0": y0, "x1": x1, "y1": y1, "xc": (x0 + x1) / 2, "t": t,
                      "size": round(s["size"], 1), "font": s["font"],
                      "bold": "Bold" in s["font"] or "bold" in s["font"].lower()}
                if is_page_number(sp, page):
                    if _dropped is not None:
                        _dropped.append(sp)
                    continue
                out.append(sp)
    out.sort(key=lambda s: (round(s["y0"]), s["x0"]))
    return out


def page_words(page):
    """Words (x0, y0, x1, y1, text) plus bold flag from the owning span."""
    ws = []
    pgnum = []
    spans = page_spans(page, pgnum)
    for w in page.get_text("words"):
        x0, y0, x1, y1, t = w[:5]
        xc, yc = (x0 + x1) / 2, (y0 + y1) / 2
        if any(s["x0"] - 1 <= xc <= s["x1"] + 1 and s["y0"] - 1 <= yc <= s["y1"] + 1 for s in pgnum):
            continue
        bold = any(s["x0"] - 1 <= xc <= s["x1"] + 1 and s["y0"] - 1 <= yc <= s["y1"] + 1 and s["bold"]
                   for s in spans)
        ws.append({"x0": x0, "y0": y0, "x1": x1, "y1": y1, "xc": xc, "yc": yc, "t": t, "bold": bold})
    return ws


def lines_of(items, tol=2.5, key="y0"):
    """Group items into lines by y (items sorted by y then x)."""
    lines = []
    for it in sorted(items, key=lambda s: (s[key], s["x0"])):
        if lines and abs(it[key] - lines[-1][0][key]) <= tol:
            lines[-1].append(it)
        else:
            lines.append([it])
    return [sorted(ln, key=lambda s: s["x0"]) for ln in lines]


def ym(s):
    s = clean(s)
    return to_ym(s) if s else None


# --------------------------------------------------------------------------- detail cards
# grid columns: (1) date of approval, (2) cost original/revised/anticipated, (3) cost overrun %
# w.r.t. original/revised, (4) DOC original/revised/anticipated, (5) outlay / expenditure up to
# previous FY / cumulative expenditure, (6) time overrun months w.r.t. original/revised,
# (7) physical progress %.
def detail_cards(doc):
    """Walk the Part-II card pages as one stream of text lines (page, y order)."""
    cards = []
    sector, agency, card, state = None, None, None, None
    started = False
    for pno in range(doc.page_count):
        sp = page_spans(doc[pno])
        if not sp:
            continue
        text = " ".join(s["t"] for s in sp)
        # 'Sector: X' is the first span (after a stray page number in Q1 2022-23)
        m = next((mm for mm in (re.match(r"^Sector\s*:\s*(.+)$", x["t"]) for x in sp[:2]) if mm), None)
        if m and ("Status of projects" in text or len(sp) <= 3):
            sector = clean(m.group(1))
            agency, card, state = None, None, None
            continue
        cour = [s for s in sp if "Courier" in s["font"]]
        if not cour:
            card, state = None, None        # overview / narrative page ends a background
            if started and re.search(r"DETAILS OF CENTRAL SECTOR|List of [Pp]rojects|STATUS OF CENTRAL SECTOR"
                                     r"|List of Delayed|List of on", text):
                break
            continue
        for ln in lines_of(cour, tol=3.0):
            first = ln[0]
            if first["bold"] and first["size"] >= 11.5:                      # agency heading
                agency, card, state = clean(" ".join(s["t"] for s in ln)), None, None
                continue
            if (first["bold"] and first["size"] == 10.0 and first["x0"] < 50
                    and re.fullmatch(r"\d{1,4}|\*+", first["t"]) and len(ln) > 1 and ln[1]["bold"]):
                started = True
                card = {"page": pno + 1, "serial": first["t"], "sector": sector, "agency": agency,
                        "name": [s["t"] for s in ln[1:]], "bg": [], "anchors": {}, "vals": [],
                        "problems": [], "warnings": [], "code": None}
                cards.append(card)
                state = "name"
                continue
            if card is None:
                continue
            locs = [s for s in ln if s["bold"] and s["t"].startswith("Location")]
            if locs and state == "name":
                lo = locs[0]
                capl = [s for s in ln if s["t"].startswith("Capa")]
                capx0 = capl[0]["x0"] if capl else 396
                card["code"] = clean(" ".join(s["t"] for s in ln if s["x1"] <= lo["x0"] + 1))
                card["location"] = clean(" ".join(s["t"] for s in ln if lo["x1"] - 1 <= s["x0"] < capx0 - 1))
                card["capacity"] = clean(" ".join(s["t"] for s in ln if capl and s["x0"] >= capl[0]["x1"] - 1))
                card["code_page"] = pno + 1
                state = "grid"
                continue
            if state == "name":
                card["name"] += [s["t"] for s in ln if s["bold"]]
                continue
            if state == "grid":
                if not card["code"]:
                    # code line split by a page break: labels on one page, code/state on the next
                    cd = [s for s in ln if s["bold"] and CODE_RE.match(s["t"]) and s["x0"] < 140]
                    if cd:
                        card["code"] = cd[0]["t"]
                        card["location"] = clean(" ".join(s["t"] for s in ln if s["bold"] and 190 < s["x0"] < 390))
                        card["code_page"] = pno + 1
                        card["warnings"].append("code line split across pages")
                if first["bold"] and first["t"] == "Background":
                    state = "bg"
                    continue
                for s in ln:
                    if s["bold"]:
                        continue
                    mm = re.fullmatch(r"\((\d)\)", s["t"])
                    if mm:
                        card["anchors"].setdefault(int(mm.group(1)), (s["xc"], s["y0"], pno))
                    elif s["size"] >= 9.5:
                        card["vals"].append({**s, "pno": pno})
                continue
            if state == "bg":
                card["bg"] += [s["t"] for s in ln if not (s["bold"] and s["t"] == "Background")]
    for c in cards:
        c["name"] = clean(" ".join(c["name"]))
        if not c["code"]:
            c["code"] = None
            c["problems"].append("no code line")
        c["cells"] = grid_cells(c)
    return cards


def grid_cells(card, pitch=13.45):
    """Assign value spans to (column, row). Columns: nearest '(n)' marker by x.
    Rows: offset from the '(1)' marker (+13.3pt per row) when on the same page,
    else offset from the first value line of the page (grid split by a page break)."""
    anchors, cells = card["anchors"], {}
    if len(anchors) < 7:
        if card["vals"]:
            card["problems"].append(f"column markers {sorted(anchors)}")
        if not anchors:
            return cells
    ref = anchors.get(1) or min(anchors.values(), key=lambda a: a[1])
    for s in card["vals"]:
        col = min(anchors, key=lambda n: abs(anchors[n][0] - s["xc"]))
        if abs(anchors[col][0] - s["xc"]) > 45:
            card["problems"].append(f"value {s['t']!r} off-column")
            continue
        if s["pno"] == ref[2]:
            row = round((s["y0"] - ref[1] - 13.3) / pitch) + 1
        else:
            # continuation page: rows restart at the top margin (~70.6pt), after
            # whatever rows were already printed under the markers
            done = [round((v["y0"] - ref[1] - 13.3) / pitch) + 1 for v in card["vals"] if v["pno"] == ref[2]]
            top = min(v["y0"] for v in card["vals"] if v["pno"] == s["pno"])
            top = top if top < 80 else 70.6
            row = (max(done) if done else 0) + round((s["y0"] - top) / pitch) + 1
            if "grid split across pages" not in card["warnings"]:
                card["warnings"].append("grid split across pages")
        if not 1 <= row <= 3:
            card["problems"].append(f"value {s['t']!r} row {row}")
            continue
        key = (col, row)
        if key in cells:
            card["problems"].append(f"two values in cell {key}: {cells[key]!r} {s['t']!r}")
            cells[key] = clean(cells[key] + " " + s["t"])
        else:
            cells[key] = s["t"]
    return cells


def card_row(card, meta):
    c = card.get("cells", {})
    g = lambda col, row: c.get((col, row))  # noqa: E731
    return {
        **meta, "page": card.get("code_page", card["page"]), "list_type": "ongoing",
        "project_code": card.get("code"), "project_name": card.get("name"),
        "sector_raw": card.get("sector"), "agency": card.get("agency"),
        "state": card.get("location") or None, "capacity": card.get("capacity") or None,
        "doa_original": ym(g(1, 1)), "doa_revised": ym(g(1, 2)),
        "cost_original_cr": to_num(g(2, 1)), "cost_revised_cr": to_num(g(2, 2)),
        "cost_anticipated_cr": to_num(g(2, 3)),
        "cost_overrun_pct": to_num(g(3, 1)),
        "outlay_current_fy_cr": to_num(g(5, 1)), "expenditure_cum_cr": to_num(g(5, 3)),
        "expenditure_upto": meta["report_period"] if to_num(g(5, 3)) is not None else None,
        "doc_original": ym(g(4, 1)), "doc_revised": ym(g(4, 2)), "doc_anticipated": ym(g(4, 3)),
        "delay_months": to_num(g(6, 1)), "physical_progress_pct": to_num(g(7, 1)),
        "remarks": clean(" ".join(card["bg"])) or None,
    }


# --------------------------------------------------------------------------- annexure lists
# list kind -> (title regex, list_type, {column number: field}); row 1 / row 2 of an
# "Original/Revised" column are the original and the revised value.
LIST_KINDS = {
    "ahead": (r"List of Projects Ahead of Schedule", "ongoing",
              {3: "doa", 4: "cost", 5: "cost_ant", 6: "exp", 7: "doc", 8: "doc_ant"}),
    "on_schedule": (r"List of on schedule Projects", "ongoing",
                    {3: "doa", 4: "cost", 5: "cost_ant", 6: "exp", 7: "doc", 8: "doc_ant"}),
    "delayed": (r"List of Delayed Projects", "ongoing",
                {3: "doa", 4: "cost", 5: "cost_ant", 6: "exp", 7: "doc", 8: "doc_ant", 9: "delay",
                 10: "delay_rev"}),
    "without_odc": (r"List of projects without Original Date of Commissioning", "ongoing",
                    {3: "doa", 4: "cost", 5: "cost_ant", 6: "exp", 7: "doc", 8: "doc_ant", 9: "delay",
                     10: "milestones"}),
    "without_doc": (r"List of projects without Date of Commissioning", "ongoing",
                    {3: "doa", 4: "cost", 5: "doc", 6: "doc_ant"}),
    "added": (r"List of Added Projects", "newly_added", {}),
    "completed": (r"List of Completed Projects", "completed", {}),
    # derived lists: not part of the ongoing union; used to fill fields / missing projects
    "time_cost": (r"Details of Ongoing Projects having Both", None,
                  {3: "doa", 4: "cost", 5: "cost_ant", 6: "doc", 7: "doc_ant", 8: "cor_pct", 9: "tor"}),
    "exp_over_cost": (r"List of Projects in which Expenditure", None,
                      {3: "doa", 4: "cost", 5: "cost_ant", 6: "exp", 7: "doc", 8: "doc_ant"}),
}
# header keyword expected over each semantic column (sanity check of the column map)
FIELD_KEYWORDS = {"doa": "Approval", "cost": "Original", "cost_ant": "Antic", "exp": "Cumulative",
                  "doc": "Original", "doc_ant": "Antici", "delay": "Delay", "delay_rev": "Delay",
                  "milestones": "Milestones", "cor_pct": "Overrun", "tor": "T.O.R"}
PROJ_CELL_RE = re.compile(r"^(?P<name>.*?)\s*-?\s*\[\s*(?P<code>N\d{8}|\d{9})\s*\]?\s*(?P<rest>.*)$")


def list_kind_of_page(text):
    for kind, (pat, _, _) in LIST_KINDS.items():
        if re.search(pat, text):
            return kind
    return None


def split_project_cell(cell):
    """'NAME - [N02000027]NPCIL,RAJASTHAN' -> (name, code, agency, state).
    Q3 2023-24 truncates the cell to 'NAME - [N22000273' (no agency/state)."""
    cell = clean(cell)
    m = PROJ_CELL_RE.match(cell)
    if not m:
        return cell.rstrip(" -"), None, None, None
    name, code, rest = clean(m["name"]).rstrip(" -"), m["code"], clean(m["rest"])
    agency = state = None
    if rest:
        if "," in rest:
            agency, state = (clean(x) for x in rest.rsplit(",", 1))
        else:
            agency = rest
    return name, code, agency or None, state or None


def column_header(ws):
    """Bold '1 2 3 ... N' column-number line -> {n: word}."""
    for ln in lines_of([w for w in ws if w["bold"] and re.fullmatch(r"\d{1,2}", w["t"])], tol=2.0):
        nums = [int(w["t"]) for w in ln]
        if len(ln) >= 4 and nums == list(range(1, len(ln) + 1)):
            return {int(w["t"]): w for w in ln}
    return {}


def column_extents(cols, hdr):
    """x-extent of every numbered column from its header words (words spanning two
    column centres, e.g. 'Commissioning' over cols 7-8, are ignored)."""
    ext = {n: [w["x0"], w["x1"]] for n, w in cols.items()}
    centres = sorted((w["xc"], n) for n, w in cols.items())
    for w in hdr:
        if sum(1 for c, _ in centres if w["x0"] <= c <= w["x1"]) > 1:
            continue
        n = min(cols, key=lambda k: abs(cols[k]["xc"] - w["xc"]))
        ext[n][0], ext[n][1] = min(ext[n][0], w["x0"]), max(ext[n][1], w["x1"])
    return ext


def pick_column(w, ext, cols):
    """Column with the largest horizontal overlap with word w; nearest centre if none."""
    best, best_ov = None, 0.0
    for n, (a, b) in ext.items():
        ov = min(w["x1"], b + 2) - max(w["x0"], a - 2)
        if ov > best_ov:
            best, best_ov = n, ov
    return best if best is not None else min(cols, key=lambda k: abs(cols[k]["xc"] - w["xc"]))


def list_page_records(page, kind, prev_sector):
    """Parse one annexure-list page with numbered columns.
    Returns (records, sector at page end, problems, text continuing the previous record)."""
    fields = LIST_KINDS[kind][2]
    ws = page_words(page)
    problems = []
    cols = column_header(ws)
    if not cols:
        return [], prev_sector, ["no column-number header"], ""
    y_hdr = cols[1]["y0"]
    need = max(fields)
    if len(cols) != need:
        problems.append(f"{len(cols)} columns, expected {need}")
    hdr = [w for w in ws if w["bold"] and w["y1"] <= y_hdr + 1 and w["y0"] > y_hdr - 95]
    ext = column_extents(cols, hdr)
    for n, f in fields.items():
        if n not in cols:
            continue
        words = " ".join(w["t"] for w in hdr if ext[n][0] <= w["xc"] <= ext[n][1])
        if FIELD_KEYWORDS[f].lower() not in words.lower():
            problems.append(f"col {n} ({f}) header {words[:40]!r}")
    # the project column ends where the column-3 (Date of Approval) header words start
    x_split = ext[3][0] - 1 if 3 in ext else 1e9
    proj = [w for w in hdr if w["t"] == "Project"]
    x_sno = proj[0]["x0"] - 1 if proj else cols[1]["x1"] + 8
    page_bottom = page.rect.height - 60
    body = [w for w in ws if w["y0"] > y_hdr + 5]
    recs, sector, cont = [], prev_sector, []
    cur = None
    for ln in lines_of(body, tol=2.5):
        first = ln[0]
        txt = " ".join(w["t"] for w in ln)
        if ln[0]["y0"] > page_bottom and re.fullmatch(r"[\d\s]+", txt):
            continue                                   # page number
        if all(w["bold"] for w in ln):
            if re.match(r"^(Grand )?Total\b", txt):
                cur = None
            elif all(w["x1"] <= x_split + 3 for w in ln) and not re.fullmatch(r"[\d\s]+", txt):
                sector, cur = clean(txt), None
            elif not re.fullmatch(r"[\d\s.,/-]+", txt):     # Total row 2
                problems.append(f"bold line ignored: {txt[:50]!r}")
            continue
        # serial = digits centred under the column-1 number; a wrapped name that starts with
        # digits at a page top ('500 MWE) - [020100044', x +21pt) is not a serial
        if (not first["bold"] and re.fullmatch(r"\d{1,4}", first["t"]) and first["x1"] <= x_sno
                and abs(first["xc"] - cols[1]["xc"]) < 12 and len(ln) > 1):
            cur = {"sno": int(first["t"]), "y": first["y0"], "sector": sector, "name": [],
                   "vals": defaultdict(dict), "page": page.number + 1}
            recs.append(cur)
            ln = ln[1:]
        if cur is None:
            name_w = [w["t"] for w in ln if w["x1"] <= x_split + 3]
            if not recs and name_w and all(w["t"] == "-" for w in ln if w["x1"] > x_split + 3):
                cont.append(" ".join(name_w))      # name (+ blank row-2 '-') of the previous page's record
            else:
                problems.append(f"orphan line: {txt[:50]!r}")
            continue
        dy = ln[0]["y0"] - cur["y"]
        for w in ln:
            if w["x1"] <= x_split + 3:
                cur["name"].append(w["t"])
                continue
            n = pick_column(w, {k: v for k, v in ext.items() if k >= 3}, cols)
            f = fields.get(n)
            if f is None:
                problems.append(f"value {w['t']!r} in unmapped column {n}")
                continue
            row = 1 if dy < 4 else 2 if dy < 14 else None
            if row is None:
                problems.append(f"sno {cur['sno']}: value {w['t']!r} {dy:.0f}pt below row 1")
                continue
            if row in cur["vals"][f]:
                problems.append(f"sno {cur['sno']}: two values for {f} row {row}")
                cur["vals"][f][row] += " " + w["t"]
            else:
                cur["vals"][f][row] = w["t"]
    return recs, sector, problems, clean(" ".join(cont))


def name_list_page_records(page, prev_sector, geom):
    """'List of Added / Completed Projects' (Q4 2023-24 Part II): Sr. No. | Project | Agency.
    The column header is printed on the first page only; geom carries it over."""
    ws = page_words(page)
    hdr = [w for w in ws if w["bold"] and w["t"] == "Agency"]
    proj = [w for w in ws if w["bold"] and w["t"] == "Project"]
    if hdr and proj:
        geom.update(x_ag=hdr[0]["x0"] - 5, x_proj=proj[0]["x0"] - 1)
        y_top = hdr[0]["y1"]
    else:
        title = [w for w in ws if w["bold"] and w["t"] == "Projects"]
        y_top = title[0]["y1"] if title else 0
    if "x_ag" not in geom:
        return [], prev_sector, ["no Agency header"], ""
    recs, sector, problems, cur, cont = [], prev_sector, [], None, []
    for ln in lines_of([w for w in ws if w["y0"] > y_top + 2], tol=2.5):
        txt = " ".join(w["t"] for w in ln)
        first = ln[0]
        if ln[0]["y0"] > page.rect.height - 60 and re.fullmatch(r"[\d\s]+", txt):
            continue
        is_start = re.fullmatch(r"\d{1,4}", first["t"]) and first["x1"] < geom["x_proj"] and len(ln) > 1
        if all(w["bold"] for w in ln) and not is_start:
            if not re.fullmatch(r"[\d\s]+", txt):
                sector, cur = clean(txt), None
            continue
        if is_start:
            cur = {"sno": int(first["t"]), "sector": sector, "name": [], "agency": [], "page": page.number + 1}
            recs.append(cur)
            ln = ln[1:]
        if cur is None:
            if not recs:
                cont.append(txt)          # name wrapped over the page break
            else:
                problems.append(f"orphan line: {txt[:50]!r}")
            continue
        for w in ln:
            (cur["agency"] if w["x0"] >= geom["x_ag"] else cur["name"]).append(w["t"])
    return recs, sector, problems, clean(" ".join(cont))


def list_record_row(rec, meta, list_type):
    name, code, agency, state = split_project_cell(" ".join(rec["name"]))
    v = rec["vals"]
    g = lambda f, r=1: (v.get(f) or {}).get(r)  # noqa: E731
    exp = to_num(g("exp"))
    return {
        **meta, "page": rec["page"], "list_type": list_type,
        "project_code": code, "project_name": name, "sector_raw": rec["sector"], "agency": agency,
        "state": state,
        "doa_original": ym(g("doa")), "doa_revised": ym(g("doa", 2)),
        "cost_original_cr": to_num(g("cost")), "cost_revised_cr": to_num(g("cost", 2)),
        "cost_anticipated_cr": to_num(g("cost_ant")),
        "expenditure_cum_cr": exp, "expenditure_upto": meta["report_period"] if exp is not None else None,
        "doc_original": ym(g("doc")), "doc_revised": ym(g("doc", 2)), "doc_anticipated": ym(g("doc_ant")),
        "delay_months": to_num(g("delay")),
    }


def parse_lists(doc):
    """All numbered-column annexure lists + the added/completed name lists of a report.
    Returns {kind: [records]}, {kind: [pages]}, problems."""
    out, pages, problems = defaultdict(list), defaultdict(list), []
    kind, sector, geom = None, None, {}
    for pno in range(doc.page_count):
        page = doc[pno]
        head = " ".join(s["t"] for s in page_spans(page)[:6])
        k = list_kind_of_page(head)
        if k and k != kind:
            kind, sector, geom = k, None, {}
        elif not k and kind and not column_header(page_words(page)) and kind not in ("added", "completed"):
            kind = None
        if kind in (None, "skip"):
            continue
        pages[kind].append(pno + 1)
        if kind in ("added", "completed"):
            if re.search(r"Contents", head):
                continue
            recs, sector, pr, cont = name_list_page_records(page, sector, geom)
        else:
            recs, sector, pr, cont = list_page_records(page, kind, sector)
        if cont and out[kind]:
            out[kind][-1]["name"].append(cont)
        out[kind] += recs
        problems += [f"p{pno + 1} {kind}: {p}" for p in pr]
    return out, pages, problems


# --------------------------------------------------------------------------- overview tables -> summary
_ALL = None
_OVR = "projects with cost overrun"
_DEL = "delayed projects"
_OVRL = "projects with cost overrun w.r.t. latest cost"
_DELL = "projects delayed w.r.t. latest schedule"
_TC = "projects with time & cost overrun"
RANGE = "delay_range"            # 'a - b' months -> delay_range_min/max_months

# (key, title regex, dimension, [(metric, sub_dimension_value)])  -- column order left to right
TABLE_SPECS = [
    ("impl_status", r"Sector wise Implementation Status|Annex 5: Sector.wise distribution . Ahead", "sector",
     [("n_ahead", _ALL), ("n_ahead_wrt_latest", _ALL), ("n_on_schedule", _ALL), ("n_on_schedule_wrt_latest", _ALL),
      ("n_delayed", _ALL), ("n_delayed_wrt_latest", _ALL), ("n_without_doc", _ALL),
      ("n_without_doc_wrt_latest", _ALL), ("n_without_odc_doc_available", _ALL),
      ("n_without_odc_doc_available_wrt_latest", _ALL)]),
    ("mega_major", r"Classification of projects in Mega and Major", "project_size",
     [("n_projects", _ALL), ("cost_anticipated_cr", _ALL), ("anticipated_cost_share_pct", _ALL),
      ("expenditure_cr", _ALL), ("cost_original_cr", _ALL)]),
    ("sector_mega_major", r"Sector-wise distribution of projects at the end", "sector",
     [("n_projects", "Mega"), ("cost_anticipated_cr", "Mega"), ("cost_original_cr", "Mega"),
      ("n_projects", "Major"), ("cost_anticipated_cr", "Major"), ("cost_original_cr", "Major")]),
    ("added_dropped", r"Summary of projects added/dropped|Annex 1: Sector.wise distribution: Project summary", "sector",
     [("n_projects_prev_quarter", _ALL), ("n_new", _ALL), ("n_dropped", _ALL), ("n_projects", _ALL)]),
    ("expenditure", r"Analysis of planned and balance expenditure", "sector",
     [("n_projects", _ALL), ("cost_original_cr", _ALL), ("cost_anticipated_cr", _ALL), ("expenditure_cr", _ALL),
      ("balance_expenditure_cr", _ALL), ("outlay_cr", _ALL), ("expenditure_pct", _ALL)],
     [("n_projects", _ALL), ("cost_original_cr", _ALL), ("cost_anticipated_cr", _ALL), ("expenditure_cr", _ALL),
      ("balance_expenditure_cr", _ALL), ("expenditure_qtr_cr", _ALL), ("outlay_cr", _ALL),
      ("expenditure_pct", _ALL)]),
    ("expenditure_p1", r"Annex 2: Sector-wise distribution: Original Cost", "sector",
     [("n_projects", _ALL), ("project_share_pct", _ALL), ("cost_original_cr", _ALL), ("cost_anticipated_cr", _ALL),
      ("cost_overrun_cr", _ALL), ("expenditure_cr", _ALL), ("balance_expenditure_cr", _ALL)]),
    ("mega_major_p1", r"Annex 3: Project Type", "sector",
     [("n_projects", "Mega"), ("cost_anticipated_cr", "Mega"), ("cost_original_cr", "Mega"),
      ("n_projects", "Major"), ("cost_anticipated_cr", "Major"), ("cost_original_cr", "Major")]),
    ("ongoing_p1", r"Annex 4: Sector.wise distribution . Ongoing Projects", "sector",
     [("n_projects", _ALL), ("cost_original_cr", _ALL), ("cost_anticipated_cr", _ALL), ("expenditure_cr", _ALL),
      ("cost_overrun_cr", _ALL), ("n_delayed", _ALL), ("n_cost_overrun", _ALL)]),
    ("cost_overrun_orig", r"Extent of cost overruns in projects with respect to original"
                          r"|Extent of cost overruns with respect to Original Sanctioned", "sector",
     [("n_projects", _ALL), ("cost_original_cr", _ALL), ("cost_anticipated_cr", _ALL), ("cost_overrun_pct", _ALL),
      ("n_cost_overrun", _OVR), ("cost_original_cr", _OVR), ("cost_anticipated_cr", _OVR),
      ("cost_overrun_pct", _OVR)]),
    ("time_overrun_orig", r"Extent of the time overruns in projects with respect to original"
                          r"|Extent of the time overruns with respect to Original", "sector",
     [("n_projects", _ALL), ("cost_original_cr", _ALL), ("cost_anticipated_cr", _ALL), ("cost_overrun_pct", _ALL),
      ("n_delayed", _DEL), ("cost_original_cr", _DEL), ("cost_anticipated_cr", _DEL), ("cost_overrun_pct", _DEL),
      (RANGE, _DEL)]),
    ("cost_overrun_latest", r"Extent of cost overruns in projects with respect to latest"
                            r"|Extent of cost overruns with respect to Latest", "sector",
     [("n_projects", _ALL), ("cost_latest_cr", _ALL), ("cost_anticipated_cr", _ALL),
      ("cost_overrun_pct_wrt_latest", _ALL), ("n_cost_overrun_wrt_latest", _OVRL), ("cost_latest_cr", _OVRL),
      ("cost_anticipated_cr", _OVRL), ("cost_overrun_pct_wrt_latest", _OVRL)]),
    ("time_overrun_latest", r"Extent of time overruns in projects with respect to latest"
                            r"|Extent of time overruns with respect to Latest", "sector",
     [("n_projects", _ALL), ("cost_latest_cr", _ALL), ("cost_anticipated_cr", _ALL),
      ("cost_overrun_pct_wrt_latest", _ALL), ("n_delayed_wrt_latest", _DELL), ("cost_latest_cr", _DELL),
      ("cost_anticipated_cr", _DELL), ("cost_overrun_pct_wrt_latest", _DELL), (RANGE, _DELL)]),
    ("time_cost_overrun", r"Extent of time & cost overruns in projects with respect to original", "sector",
     [("n_projects", _ALL), ("cost_original_cr", _ALL), ("cost_anticipated_cr", _ALL), ("cost_overrun_pct", _ALL),
      ("n_time_and_cost_overrun", _TC), ("cost_original_cr", _TC), ("cost_anticipated_cr", _TC),
      ("cost_overrun_pct", _TC), (RANGE, _TC)]),
    ("rce", r"Sector-wise distribution of projects requiring review|Sector.wise distribution: requiring review",
     "sector",
     [("n_projects", _ALL), ("n_approved_cost_below_anticipated", "Mega"),
      ("n_approved_cost_below_expenditure", "Mega"), ("n_approved_cost_below_anticipated", "Major"),
      ("n_approved_cost_below_expenditure", "Major"), ("n_approved_cost_below_anticipated", "Total"),
      ("n_approved_cost_below_expenditure", "Total")]),
    ("state", r"STATUS OF CENTRAL SECTOR PROJECTS COSTING", "state",
     [("n_projects", _ALL), ("cost_original_cr", _ALL), ("cost_anticipated_cr", _ALL), ("expenditure_cr", _ALL)]),
]
COUNT_METRICS_PREFIX = "n_"
VALUE_TOKEN = re.compile(r"^[‐\-−]?[\d,]*\.?\d+%?$|^[‐\-−]$|^N\.?A\.?$|^\.00$"
                         r"|^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[‐\-]\d{1,3}$")  # Excel 'Oct-51' = '10-51'



def is_value(t):
    return bool(VALUE_TOKEN.match(t))


def table_title_line(lines, pattern):
    for i, ln in enumerate(lines):
        txt = " ".join(w["t"] for w in ln).replace("‐", "-")
        if re.search(pattern, txt, re.I):
            return i, clean(txt)
    return None, None


def label_rows(lines):
    """Split lines into (label, [value words], y, has_serial); merge wrapped labels and
    label rows whose values are printed on two text lines (vertically centred cells)."""
    rows = []
    for ln in lines:
        ws = [dict(w, t=w["t"].replace("‐", "-").replace("−", "-")) for w in ln]
        # range 'a - b' -> one token
        merged, i = [], 0
        while i < len(ws):
            for n in (3, 2):        # '36 - 145', '74- 145', '74 -145' -> one range token
                grp = ws[i:i + n]
                if (len(grp) == n and re.fullmatch(r"\d+\s*-\s*\d+", " ".join(w["t"] for w in grp))
                        and all(b["x0"] - a["x1"] < 12 for a, b in zip(grp, grp[1:]))):
                    a, b = re.findall(r"\d+", " ".join(w["t"] for w in grp))
                    merged.append(dict(grp[0], t=f"{a} - {b}", x1=grp[-1]["x1"], xc=(grp[0]["x0"] + grp[-1]["x1"]) / 2))
                    i += n
                    break
            else:
                merged.append(ws[i])
                i += 1
        ws = merged
        last_alpha = max((k for k, w in enumerate(ws) if re.search(r"[A-Za-z]", w["t"]) and not is_value(w["t"])),
                         default=-1)
        lab, vals = ws[:last_alpha + 1], ws[last_alpha + 1:]
        serial = bool(lab) and re.fullmatch(r"\d{1,2}\.?", lab[0]["t"]) is not None
        if serial:
            lab = lab[1:]
        elif not lab and vals and re.fullmatch(r"\d{1,2}\.", vals[0]["t"]) and vals[0]["x0"] < 110:
            serial, vals = True, vals[1:]           # '1.' printed on a line of its own values
        rows.append({"label": clean(" ".join(w["t"] for w in lab)), "vals": vals, "y": ln[0]["y0"],
                     "serial": serial})
    return rows


_SHORT_WORDS = {"AND", "OF", "THE", "FOR", "TO", "IN", "ON", "&", "A", "OR"}


def join_label(a, b):
    """Join a label with its continuation line -> (label, True if a split word was re-joined).
    A long word broken by a narrow cell ('TELECOMMUNICATIO' / 'NS') is joined without space."""
    ta, tb = (a.split() or [""])[-1], (b.split() or [""])[0]
    if (len(ta) >= 10 and ta.isalpha() and ta.isupper() and 1 <= len(tb) <= 3 and tb.isalpha()
            and tb.isupper() and tb not in _SHORT_WORDS):
        return clean(a + b), True
    return clean(a + " " + b), False


def cluster_columns(rows, pad=1.0):
    """Columns = connected components of overlapping value x-intervals (works for
    left-, right- and centre-aligned columns). Returns [(x0, x1)] left to right."""
    iv = sorted((v["x0"], v["x1"]) for r in rows for v in r["vals"])
    cols = []
    for a, b in iv:
        if cols and a <= cols[-1][1] + pad:
            cols[-1][1] = max(cols[-1][1], b)
        else:
            cols.append([a, b])
    return [tuple(c) for c in cols]


TOTAL_RE = re.compile(r"^(Grand\s+)?Total\b", re.I)


def parse_label_table(pages_words, pattern, variants, max_rows=120):
    """Generic sector/state table: title line, then rows of label + numbers until the
    Total row, continuing on the next page when the Total is not reached.
    Columns = connected x-intervals of the values, mapped left-to-right to the metric
    variant with the same number of columns. Returns (title, metrics, rows, problems, restored)
    with rows = [(label, {column index: text})] and restored = labels re-joined from a word
    split over two lines."""
    lines = lines_of(pages_words[0], tol=3.0)
    i0, title = table_title_line(lines, pattern)
    if i0 is None:
        return None, None, [], [], set()
    need = min(len(v) for v in variants) if variants else 2
    body, done = [], False
    for pi, words in enumerate(pages_words):
        page_lines = lines[i0 + 1:] if pi == 0 else lines_of(words, tol=3.0)
        started, part, pending, total_wait = False, [], None, None
        for ln in page_lines:
            if len(ln) == 1 and re.fullmatch(r"\d{1,4}", ln[0]["t"]) and ln[0]["y0"] > 720:
                continue                                        # page number
            rs = label_rows([ln])[0]
            rs["y"] += 1000 * pi
            if total_wait is not None:
                tv = total_wait["vals"]
                if not tv:
                    # 'Total' label printed a few points above its values
                    if not rs["label"] and rs["vals"] and rs["y"] - total_wait["y"] < 10:
                        total_wait["vals"] = rs["vals"]
                elif (not rs["label"] and rs["vals"] and rs["y"] - total_wait["y"] < 14
                      and all(re.fullmatch(r"\d{1,2}", v["t"]) and any(
                          re.search(r"\.\d$", t["t"]) and abs(t["x1"] - v["x1"]) < 3 for t in tv)
                              for v in rs["vals"])):
                    # last decimal digit of a Total value wrapped onto the next line
                    # ('10,07,250.1' + '8' right-aligned under it)
                    total_wait["vals"] = tv + rs["vals"]
                break
            n_alpha = len(re.findall(r"[A-Za-z]{3,}", rs["label"]))
            if not started:
                # continuation page: the Total row may come first (its label sits below its values)
                if n_alpha <= 6 and ((len(rs["vals"]) >= max(2, (need + 1) // 2) and (rs["label"] or pi > 0))
                                     or (rs["serial"] and len(rs["vals"]) >= 1)):
                    started = True
                    # 'Mega' / 'Projects': first half of a two-line label printed above the values
                    if pending and rs["label"].lower().startswith("project") and rs["y"] - pending["y"] < 14:
                        rs["label"] = clean(pending["label"] + " " + rs["label"])
                else:
                    pending = rs if rs["label"] and not rs["vals"] and n_alpha <= 3 else None
                    continue
            if n_alpha > 8 or re.match(r"^(\^|\$|\*|Note|Page\b)", rs["label"]):
                break
            part.append(rs)
            if TOTAL_RE.match(rs["label"]) or len(body) + len(part) > max_rows:
                done = True
                if TOTAL_RE.match(rs["label"]):
                    total_wait = rs          # look at one more line: values below / wrapped digit
                    continue
                break
        # rows on the following page are only taken when that page closes the table
        if pi == 0 or done:
            body += part
        if done or pi > 0:
            break
    # merge continuation lines (wrapped labels, values of one row printed on two lines)
    rows = []
    for r in body:
        # second line of a wrapped label: within 12.5pt, or 15pt for a label-only line under a
        # numbered row (Part I annexes: 'Road Transport and' / 'Highways' 13.8pt apart)
        gap = 16 if not r["label"] else 15 if (not r["vals"] and rows and rows[-1]["serial"]) else 12.5
        if rows and not r["serial"] and r["y"] - rows[-1]["y_last"] < gap \
                and not TOTAL_RE.match(r["label"]):
            prev = rows[-1]
            if not r["vals"] or not any(abs(v["xc"] - pv["xc"]) < 10 for v in r["vals"] for pv in prev["vals"]) \
                    or (not r["label"] and all(re.fullmatch(r"\d{1,2}", v["t"]) for v in r["vals"])):
                prev["label"], split = join_label(prev["label"], r["label"])
                prev["restored"] = prev.get("restored") or split
                prev["vals"] += r["vals"]
                prev["y_last"] = r["y"]
                continue
        rows.append(dict(r, y_last=r["y"]))
    rows = [r for r in rows if r["label"] or r["vals"]]
    # first half of a two-line label on its own line above the values ('Major' / 'Projects ...')
    for k in range(len(rows) - 1):
        a, b = rows[k], rows[k + 1]
        if a["label"] and not a["vals"] and b["vals"] and b["label"].lower().startswith("project") \
                and b["y"] - a["y_last"] < 14:
            b["label"], a["label"] = clean(a["label"] + " " + b["label"]), ""
    # value line printed just above its label (e.g. Total row of Table 8)
    for k in range(len(rows) - 1):
        a, b = rows[k], rows[k + 1]
        if not a["label"] and a["vals"] and b["label"] and not b["vals"] and b["y"] - a["y_last"] < 14:
            b["vals"], a["vals"] = a["vals"], []
    rows = [r for r in rows if r["label"] or r["vals"]]
    # Q4 2022-23 Table 4 prints its bold Total values without the word 'Total'
    if rows and not rows[-1]["label"] and rows[-1]["vals"] and all(v.get("bold") for v in rows[-1]["vals"]):
        rows[-1]["label"] = "Total"
    # wrapped last digit of a number ('1,16,741.0' + '0' on the next line) is not a column
    core = [dict(r, vals=[v for v in r["vals"] if not re.fullmatch(r"\d{1,2}", v["t"])
                          or v["y0"] + 1000 * (r["y"] >= 1000) - r["y"] < 5])
            for r in rows if not TOTAL_RE.match(r["label"])]
    cols = cluster_columns(core or rows)
    problems = []
    metrics = next((v for v in variants if len(v) == len(cols)), None) if variants else None
    if variants and metrics is None:
        return title, None, [], [f"{len(cols)} value columns found, expected {sorted({len(v) for v in variants})}"], set()
    out, seen = [], set()
    for r in rows:
        cells = {}
        for v in sorted(r["vals"], key=lambda v: (v["y0"], v["x0"])):
            k = max(range(len(cols)), key=lambda i: (min(v["x1"], cols[i][1]) - max(v["x0"], cols[i][0]),
                                                     -abs((cols[i][0] + cols[i][1]) / 2 - v["xc"])))
            if k in cells:
                if re.search(r"\.\d?$", cells[k]) and re.fullmatch(r"\d{1,2}", v["t"]):
                    cells[k] += v["t"]            # wrapped last decimal digit
                    continue
                problems.append(f"{r['label']!r}: two values in column {k}")
            cells[k] = v["t"]
        if not r["label"]:
            problems.append(f"row without label at y={r['y']:.0f}")
            continue
        key = (r["label"], tuple(sorted(cells.items())))
        if key in seen:
            problems.append(f"row {r['label']!r} printed twice (dropped repeat)")
            continue
        seen.add(key)
        out.append((r["label"], cells))
    return title, metrics, out, problems, {r["label"] for r in rows if r.get("restored")}


def summary_rows_from_table(meta, page_no, key, title, dimension, metrics, rows, restored=()):
    out = []
    for label, cells in rows:
        is_total = re.match(r"^(Grand\s+)?Total\b", label, re.I) is not None
        dval = "Total" if is_total else label.rstrip(":")
        for k, txt in cells.items():
            metric, sub = metrics[k]
            base = {**meta, "page": page_no, "table_title": title, "dimension": dimension,
                    "dimension_value": dval, "sub_dimension_value": sub,
                    "dq_note": "label_restored" if label in restored else None}
            if metric == RANGE:
                m = re.fullmatch(r"(\d+)\s*-\s*(\d+)", txt)
                if m:
                    out.append({**base, "metric": "delay_range_min_months", "value": float(m[1]), "unit": "months"})
                    out.append({**base, "metric": "delay_range_max_months", "value": float(m[2]), "unit": "months"})
                continue
            val = to_num(txt.replace("‐", "-"))
            if val is None:
                continue
            unit = ("count" if metric.startswith("n_") else "Rs crore" if metric.endswith("_cr")
                    else "percent" if "pct" in metric else "")
            out.append({**base, "metric": metric, "value": val, "unit": unit})
    return out


def check_totals(rows, metrics):
    """Sum of component rows vs printed Total row for count metrics -> list of problems."""
    probs = []
    tot = [c for lab, c in rows if re.match(r"^(Grand\s+)?Total\b", lab, re.I)]
    if not tot:
        return ["no Total row"]
    for k, (metric, sub) in enumerate(metrics):
        if not metric.startswith("n_") or k not in tot[0]:
            continue
        s = sum(to_num(c.get(k)) or 0 for lab, c in rows if not re.match(r"^(Grand\s+)?Total\b", lab, re.I))
        t = to_num(tot[0][k])
        if t is not None and abs(s - t) > 0.5:
            probs.append(f"{metric}/{sub}: rows sum {s:g} != Total {t:g}")
    return probs


HL_PATS = [(r"Total number of projects on the monitor", "n_projects"),
           (r"Total Original estimated cost", "cost_original_cr"),
           (r"Total latest approved cost", "cost_latest_cr"),
           (r"Total anticipated cost", "cost_anticipated_cr"),
           (r"^(Total|Cumulative) Expenditure", "expenditure_cr"),
           (r"cost overrun with respect to original", "cost_overrun_pct"),
           (r"cost overrun with respect to latest", "cost_overrun_pct_wrt_latest"),
           (r"showing cost overrun w\.?r\.?t\.? original", "n_cost_overrun"),
           (r"showing time overrun w\.?r\.?t\.? original", "n_delayed"),
           (r"Percentage cost overrun in (\d+ )?delayed", "cost_overrun_pct_delayed_projects"),
           (r"due for commis+ioning during (the year|FY)", "n_due_for_commissioning_fy"),
           (r"due for commis+ioning during the quarter", "n_due_for_commissioning_qtr"),
           (r"projects completed during (the year|FY)", "n_completed_fy_to_date"),
           (r"projects completed during the quarter", "n_completed_qtr"),
           (r"Total sanctioned cost\*? of completed", "cost_sanctioned_completed_fy_to_date_cr"),
           (r"Total final cost of the completed", "cost_final_completed_fy_to_date_cr"),
           (r"Total Cost of the completed projects", "cost_completed_fy_to_date_cr")]


def hl_num(t):
    return to_num(t.replace("%", "").replace("crore", ""))


def highlights(words, meta, page_no):
    """'Highlights' box. An item = a line with its value right of x=290 plus the label-only
    lines below it (wrapped label, '(ranging from a to b' line). The Q4 2023-24 Part I box
    prints two year columns (2023-24 first): values right of the gap between the two year
    headers belong to the previous year and are ignored."""
    lines = lines_of(words, tol=3.0)
    top = next((ln[0]["y0"] for ln in lines if any(w["t"].lower() == "highlights" for w in ln)), 0)
    lines = [ln for ln in lines if ln[0]["y0"] > top]
    x_cut = 1e9
    for ln in lines:
        yrs = [w for w in ln if w["x0"] >= 290 and re.fullmatch(r"\d{4}[-‐]\d{2}", w["t"])]
        if len(yrs) >= 2:
            x_cut = (yrs[0]["x1"] + yrs[1]["x0"]) / 2
            break
    items = []
    for ln in lines:
        lab = " ".join(w["t"] for w in ln if w["x1"] < 300)
        region = [w["t"] for w in ln if 290 <= w["x0"] < x_cut]
        i = next((k for k, t in enumerate(region) if hl_num(t) is not None), None)
        if i is not None and not any("(" in t or "rang" in t.lower() for t in region[:i]):
            items.append({"lab": lab, "labs": [lab], "val": hl_num(region[i]), "text": " ".join(region)})
        elif items:
            items[-1]["labs"].append(lab)
            items[-1]["text"] += " " + " ".join(region)
    out, completed_qtr = [], False
    for it in items:
        metric = next((m for pat, m in HL_PATS if re.search(pat, it["lab"], re.I)), None)             or next((m for pat, m in HL_PATS if re.search(pat, clean(" ".join(it["labs"])), re.I)), None)
        if metric is None:
            continue
        if metric.startswith("n_completed"):
            completed_qtr = metric.endswith("_qtr")
        if metric == "cost_completed_fy_to_date_cr" and completed_qtr:
            metric = "cost_completed_qtr_cr"   # Q4 2021-22: 'completed during the quarter' box
        base = {**meta, "page": page_no, "table_title": "Highlights", "dimension": "overall",
                "dimension_value": "All projects", "sub_dimension_value": None}
        unit = "count" if metric.startswith("n_") else "Rs crore" if metric.endswith("_cr") else "percent"
        out.append({**base, "metric": metric, "value": it["val"], "unit": unit})
        m = re.search(r"rang\w*\s+from\s+(\d+)\s+to\s+(\d+)", it["text"], re.I)
        if metric == "n_delayed" and m:
            out.append({**base, "metric": "delay_range_min_months", "value": float(m[1]), "unit": "months"})
            out.append({**base, "metric": "delay_range_max_months", "value": float(m[2]), "unit": "months"})
    return out


STATUS_COLS = {2: "n_projects", 3: "n_within_time_and_cost", 4: "n_cost_overrun_within_time",
               5: "n_time_overrun_within_cost", 6: "n_time_and_cost_overrun", 7: "n_without_doc_within_cost",
               8: "n_without_doc_with_cost_overrun"}


def sector_status_page(page, sector, meta):
    """'Sector: X / Status of projects as on dd-mm-yy' box: rows Major / Mega / Total.
    Row labels and value lines are not vertically aligned (Total label sits a line
    lower), so value lines are matched to labels in top-to-bottom order."""
    ws = page_words(page)
    cols = column_header(ws)
    stext = " ".join(w["t"] for w in ws)
    m = re.search(r"Status of projects as on ([\d\-/.]+)", stext)
    title = f"Sector status of projects as on {m[1]}" if m else "Sector status of projects"
    if len(cols) != 8:
        return [], [f"status page {sector}: {len(cols)} columns"]
    y_hdr = cols[1]["y1"]
    labels = [ln[0] for ln in lines_of([w for w in ws if w["y0"] > y_hdr], tol=2.5)
              if ln[0]["t"] in ("Major", "Mega", "Total", "Total:") and abs(ln[0]["x0"] - cols[1]["x0"]) < 20
              and all(re.fullmatch(r"\d+", w["t"]) for w in ln[1:])]
    vlines = [ln for ln in lines_of([w for w in ws if w["y0"] > y_hdr and re.fullmatch(r"\d+", w["t"])
                                     and w["x0"] > cols[1]["x1"] + 5], tol=2.5) if len(ln) >= 5]
    labels.sort(key=lambda w: w["y0"])
    if len(labels) != len(vlines) or not labels:
        return [], [f"status page {sector}: {len(labels)} labels vs {len(vlines)} value lines"]
    out, table = [], []
    for lab, ln in zip(labels, vlines):
        cells = {}
        for w in ln:
            n = min(cols, key=lambda k: abs(cols[k]["x0"] - w["x0"]))
            cells[n] = w["t"]
        table.append((lab["t"].rstrip(":"), cells))
    probs = []
    tot = [c for l, c in table if l == "Total"]
    parts = [c for l, c in table if l != "Total"]
    if tot:
        for n in STATUS_COLS:
            s = sum(to_num(c.get(n)) or 0 for c in parts)
            if to_num(tot[0].get(n)) is not None and abs(s - to_num(tot[0][n])) > 0.5:
                probs.append(f"status page {sector}: col {n} parts {s:g} != Total {tot[0][n]}")
    for lab, cells in table:
        for n, metric in STATUS_COLS.items():
            v = to_num(cells.get(n))
            if v is None:
                continue
            out.append({**meta, "page": page.number + 1, "table_title": title, "dimension": "sector",
                        "dimension_value": sector, "sub_dimension_value": lab, "metric": metric, "value": v,
                        "unit": "count"})
    return out, probs


# --------------------------------------------------------------------------- completed list (card-layout reports)
def completed_list_old(doc, pages):
    """'List of projects completed in YYYY-YYYY as on dd-mm-yyyy' (Arial Narrow).
    Per project: serial + name lines, one location line (may be blank), '(STATE)';
    DOC original / '(revised)', approved cost original / '(revised)', cumulative
    expenditure, 'Qtr. n of YYYY-YYYY'. Sector = italic 'Sector X', agency = bold 11pt."""
    recs, problems = [], []
    sector = agency = cur = None
    for pno in pages:
        page = doc[pno - 1]
        sp = page_spans(page)
        hdr = {k: next((s for s in sp if s["bold"] and s["t"].startswith(k)), None)
               for k in ("commissioning", "Approved", "expenditure", "During", "Project")}
        if any(v is None for v in hdr.values()):
            problems.append(f"p{pno}: completed-list header not found")
            continue
        centres = {"doc": hdr["commissioning"]["xc"], "cost": hdr["Approved"]["xc"],
                   "exp": hdr["expenditure"]["xc"], "qtr": hdr["During"]["xc"]}
        # name spans start at the Project column; value spans start right of the DOC header
        x_split = min(s["x0"] for s in sp if s["bold"] and s["y0"] < hdr["Approved"]["y1"] + 25
                      and abs(s["xc"] - hdr["commissioning"]["xc"]) < 30) - 4
        x_name_end = x_split
        y_top = max(v["y1"] for v in hdr.values())
        italic = []
        for ln in lines_of([s for s in sp if s["y0"] > y_top], tol=2.5):
            first = ln[0]
            txt = " ".join(s["t"] for s in ln)
            if first["y0"] > page.rect.height - 60 and re.fullmatch(r"[\d\s]+", txt):
                continue                                           # page number
            if "Italic" in first["font"]:
                if first["t"] == "Sector":
                    italic = [" ".join(s["t"] for s in ln[1:])]
                else:
                    italic.append(txt)
                new_sector = clean(" ".join(italic))
                if new_sector != sector and not (sector or "").startswith(new_sector):
                    agency, cur = None, None     # a heading repeated at a page top keeps the open record
                sector = new_sector if not (sector or "").startswith(new_sector) else sector
                continue
            if first["bold"] and first["size"] >= 10.5 and first["x0"] < x_name_end:
                if clean(txt) != agency:
                    agency, cur = clean(txt), None
                continue
            if re.fullmatch(r"\d{1,4}", first["t"]) and first["x1"] < hdr["Project"]["x0"] + 8 and len(ln) > 1:
                cur = {"sno": int(first["t"]), "y": first["y0"], "page": pno, "sector": sector, "agency": agency,
                       "lines": [], "vals": defaultdict(dict)}
                recs.append(cur)
                ln = ln[1:]
            if cur is None:
                if not re.fullmatch(r"[\d\s]+", txt):
                    problems.append(f"p{pno}: orphan line {txt[:40]!r}")
                continue
            names = [s for s in ln if s["x0"] < x_name_end]
            if names:
                y = ln[0]["y0"] if cur["page"] == pno else (cur["lines"][-1][0] + 10 if cur["lines"] else 0)
                cur["lines"].append((y, " ".join(s["t"] for s in names)))
            vals = [s for s in ln if s["x0"] >= x_name_end]
            if not vals:
                continue
            if cur["page"] != pno:
                problems.append(f"p{pno} sno {cur['sno']}: values continue on next page")
                continue
            dy = vals[0]["y0"] - cur["y"]
            row = 1 if dy < 5 else 2 if dy < 18 else None
            if row is None:
                if not (len(vals) == 1 and re.fullmatch(r"\d{1,4}", vals[0]["t"])):   # page number
                    problems.append(f"p{pno} sno {cur['sno']}: value {vals[0]['t']!r} {dy:.0f}pt below")
                continue
            for s in vals:
                if s["x0"] >= centres["qtr"] - 45:
                    f = "qtr"
                else:
                    f = min(("doc", "cost", "exp"), key=lambda k: abs(centres[k] - s["xc"]))
                    if abs(centres[f] - s["xc"]) > 25:
                        continue                       # page number printed between columns
                cur["vals"][f][row] = clean((cur["vals"][f].get(row, "") + " " + s["t"]))
    return recs, problems


def completed_old_row(rec, meta):
    lines = rec["lines"]
    state = location = None
    m = re.fullmatch(r"(.*?)\s*\(([^()]*)\)", lines[-1][1].strip()) if lines else None
    if m:
        state = clean(m[2])
        body = lines[:-1]
        if m[1]:
            location = clean(m[1])                  # 'JODHPUR (RAJASTHAN)' on one line
        elif len(body) >= 2 and lines[-1][0] - body[-1][0] < 14:
            # location = the single line just above '(STATE)' unless that slot is blank
            location = body[-1][1]
            body = body[:-1]
    else:
        body = lines
    v = rec["vals"]
    par = lambda t: re.sub(r"^\((.*)\)$", r"\1", clean(t or ""))  # noqa: E731
    exp = to_num(v["exp"].get(1))
    qtr = clean(v["qtr"].get(1))
    return {
        **meta, "page": rec["page"], "list_type": "completed",
        "project_name": clean(" ".join(t for _, t in body)), "sector_raw": rec["sector"], "agency": rec["agency"],
        "state": state, "location": location,
        "cost_original_cr": to_num(v["cost"].get(1)), "cost_revised_cr": to_num(par(v["cost"].get(2))),
        "expenditure_cum_cr": exp, "expenditure_upto": meta["report_period"] if exp is not None else None,
        "doc_original": ym(v["doc"].get(1)), "doc_revised": ym(par(v["doc"].get(2))),
        "remarks": f"Completed during {qtr}" if qtr else None,
    }


# --------------------------------------------------------------------------- additionally delayed list
def additionally_delayed(doc, pages):
    """'List Of Additionally Delayed Projects' (Courier): per agency block a header,
    then SN | Project Name | DOA | Cost original / anticipated | DOC original /
    anticipated during last qtr / anticipated latest | Additional delay (months)."""
    recs, problems = [], []
    sector = agency = None
    cols = None
    cur = None
    for pno in pages:
        sp = page_spans(doc[pno - 1])
        for ln in lines_of(sp, tol=2.5):
            first = ln[0]
            txt = clean(" ".join(s["t"] for s in ln))
            if first["bold"]:
                if first["size"] >= 13.5 and first["x0"] < 60:
                    sector, agency, cur = txt, None, None
                elif first["size"] >= 10.5 and first["x0"] < 60:
                    agency, cur = txt, None
                elif any(s["t"] == "DOA" for s in ln):
                    doa = next(s for s in ln if s["t"] == "DOA")
                    cols = {"doa": doa["x0"]}
                continue
            if "Courier" not in first["font"]:
                continue
            if first["size"] >= 9.5 and re.fullmatch(r"\d{1,4}", first["t"]) and first["x0"] < 60:
                cur = {"sno": int(first["t"]), "y": first["y0"], "page": pno, "sector": sector, "agency": agency,
                       "name": [], "vals": defaultdict(dict)}
                recs.append(cur)
                ln = ln[1:]
            if cur is None:
                problems.append(f"p{pno}: orphan line {txt[:40]!r}")
                continue
            for s in ln:
                if s["size"] < 9.5 and s["x1"] < 272:
                    cur["name"].append(s["t"])
                    continue
                if cur["page"] != pno:
                    problems.append(f"p{pno} sno {cur['sno']}: values continue on next page")
                    continue
                f = ("doa" if s["xc"] < 322 else "cost" if s["xc"] < 425 else "doc" if s["xc"] < 505 else "addl")
                row = round((s["y0"] - cur["y"]) / 13.5) + 1
                if not 1 <= row <= 3:
                    problems.append(f"p{pno} sno {cur['sno']}: value {s['t']!r} row {row}")
                    continue
                cur["vals"][f][row] = s["t"]
    return recs, problems


def addl_row(rec, meta):
    v = rec["vals"]
    prev = ym(v["doc"].get(2))
    return {
        **meta, "page": rec["page"], "list_type": "other:additionally_delayed",
        "project_name": clean(" ".join(rec["name"])), "sector_raw": rec["sector"], "agency": rec["agency"],
        "doa_original": ym(v["doa"].get(1)),
        "cost_original_cr": to_num(v["cost"].get(1)), "cost_anticipated_cr": to_num(v["cost"].get(2)),
        "doc_original": ym(v["doc"].get(1)), "doc_anticipated": ym(v["doc"].get(3)),
        "additional_delay_months": to_num(v["addl"].get(1)),
        "remarks": f"Anticipated DOC reported in the previous quarter: {prev}" if prev else None,
    }


# --------------------------------------------------------------------------- report driver
QWORD = {"1st": "Q1", "first": "Q1", "2nd": "Q2", "second": "Q2", "3rd": "Q3", "third": "Q3",
         "4th": "Q4", "fourth": "Q4"}
MONTH_Q = {"apr": "Q1", "jul": "Q2", "oct": "Q3", "jan": "Q4"}


def period_in_pdf(texts, quarter, period):
    """Compare the quarter / FY printed in the report (foreword sentence, cover line,
    Part I/II running head) with the one derived from the file name. Returns a note or None."""
    head = clean(" ".join(texts[:8]).replace("‐", "-").replace("–", "-"))
    expect = f"{quarter} FY {fiscal_year(period)}"
    found = []
    m = re.search(r"for the (1st|2nd|3rd|4th|first|second|third|fourth) quarter of (\d{4})-(\d{2})\s*\((\w{3})",
                  head, re.I)
    if m:
        found.append(("foreword", f"{QWORD[m[1].lower()]} FY {m[2]}-{m[3]}"))
        mq = MONTH_Q.get(m[4][:3].lower())
        if mq and mq != QWORD[m[1].lower()]:
            found.append(("foreword months", f"{mq} FY {m[2]}-{m[3]}"))
    m = re.search(r"\b(Apr|Jul|Oct|Jan)\w*\s*-\s*(?:Jun|Sep|Dec|Mar)\w*,?\s*(\d{4})-(\d{2})\s*\(QTR\s*-\s*(\d)", head, re.I)
    if m:
        found.append(("cover QTR", f"Q{m[4]} FY {m[2]}-{m[3]}"))
        found.append(("cover months", f"{MONTH_Q[m[1][:3].lower()]} FY {m[2]}-{m[3]}"))
    m = re.search(r"\bQ([1-4])_(\d{4})-(\d{2})\b", head)
    if m:
        found.append(("running head", f"Q{m[1]} FY {m[2]}-{m[3]}"))
    if not found:
        return "report period not found in PDF text (image cover), taken from file name"
    bad = [f"{src} says {v}" for src, v in found if v != expect]
    return f"period check vs file name ({expect}): " + ", ".join(bad) if bad else None


def status_page_list(doc, texts):
    out = []
    for pno, t in enumerate(texts):
        if "Status of projects as on" in t and re.match(r"^(\s*\d{1,3}\s*\n)?\s*Sector\s*:", t):
            m = re.search(r"Sector\s*:\s*(.+)", t)
            out.append((pno, clean(m[1])))
    return out


def overview_summary(doc, texts, meta):
    """All overview/annex tables + highlights + sector status pages -> summary rows."""
    rows, notes, found = [], [], {}
    norm = [clean(t.replace("‐", "-")) for t in texts]
    wcache = {}

    def words(pno):
        if pno not in wcache:
            wcache[pno] = page_words(doc[pno]) if pno < doc.page_count else []
        return wcache[pno]

    for key, pat, dim, *variants in TABLE_SPECS:
        last = None
        scan = range(doc.page_count) if key == "state" else range(min(doc.page_count, 40))
        for pno in scan:
            if not re.search(pat, norm[pno], re.I) or re.search(r"Contents|\.{10,}", norm[pno]):
                continue
            title, metrics, trows, probs, restored = parse_label_table([words(pno), words(pno + 1)], pat,
                                                                        variants)
            if title is None:
                continue
            if not trows:
                last = f"{key} p{pno + 1}: " + "; ".join(probs[:2])
                continue
            srows = summary_rows_from_table(meta, pno + 1, key, title, dim, metrics, trows, restored)
            if key == "expenditure":
                srows, bad = check_expenditure_pct(srows)
                if bad:
                    notes.append(f"expenditure p{pno + 1}: {bad} '(%) of original cost' values dropped "
                                 "(match neither expenditure nor balance as % of original cost)")
            # a printed Total of 0 over non-zero rows (Table 8 'Total' columns, 2021-22) is a
            # source error: blank it rather than keep a wrong value
            sums = Counter()
            for r in srows:
                if r["dimension_value"] != "Total" and r["metric"].startswith("n_"):
                    sums[(r["metric"], r["sub_dimension_value"])] += r["value"]
            bad0 = [r for r in srows if r["dimension_value"] == "Total" and r["metric"].startswith("n_")
                    and r["value"] == 0 and sums[(r["metric"], r["sub_dimension_value"])] > 0]
            if bad0:
                srows = [r for r in srows if not any(r is b for b in bad0)]
                notes.append(f"{key} p{pno + 1}: {len(bad0)} Total cells printed as 0 over non-zero rows dropped")
            rows += srows
            found[key] = pno + 1
            tp = check_totals(trows, metrics)
            if tp or probs:
                notes.append(f"{key} p{pno + 1}: " + "; ".join((probs + tp)[:3]))
            break
        else:
            if last:
                notes.append(f"table not parsed: {last}")
    # highlights box
    for pno in range(min(doc.page_count, 30)):
        if re.search(r"Highlights", norm[pno], re.I) and "Total number of projects on the monitor" in norm[pno]:
            h = highlights(words(pno), meta, pno + 1)
            if h:
                rows += h
                found["highlights"] = pno + 1
                break
    # per-sector status pages
    n_status = 0
    for pno, sector in status_page_list(doc, texts):
        srows, probs = sector_status_page(doc[pno], sector, meta)
        rows += srows
        n_status += bool(srows)
        notes += probs
    found["sector_status_pages"] = n_status
    # the same table/sector printed twice (Q3 2022-23 repeats the PETROLEUM section): keep the first
    seen, out, dup = {}, [], Counter()
    for r in rows:
        k = (r["table_title"], r["dimension"], r["dimension_value"], r["sub_dimension_value"], r["metric"])
        if k in seen:
            dup["same value" if seen[k] == r["value"] else "different value"] += 1
            continue
        seen[k] = r["value"]
        out.append(r)
    if dup:
        notes.append("summary rows printed twice, first kept: " + ", ".join(f"{v} {k}" for k, v in dup.items()))
    return out, notes, found


def check_expenditure_pct(srows, tol=1.0):
    """Table 4 last column '(%) of Original Cost': cumulative expenditure / original cost in
    2021-22, balance expenditure / original cost in later reports, and a copy of the
    expenditure itself in Q1 2023-24. Keep a value only when it reproduces one of the two
    ratios (renamed accordingly); drop it otherwise."""
    val = {(r["dimension_value"], r["metric"]): r["value"] for r in srows}
    keep, bad = [], 0
    for r in srows:
        if r["metric"] == "expenditure_pct":
            d = r["dimension_value"]
            o = val.get((d, "cost_original_cr"))
            e, b = val.get((d, "expenditure_cr")), val.get((d, "balance_expenditure_cr"))
            if o and e is not None and abs(e / o * 100 - r["value"]) <= tol:
                pass
            elif o and b is not None and abs(b / o * 100 - r["value"]) <= tol:
                r = dict(r, metric="balance_expenditure_pct")
            else:
                bad += 1
                continue
        keep.append(r)
    return keep, bad


def dedupe_cards(rows, stated):
    """Codes printed twice (Q1 2021-22: the Mines cards repeated under FINANCE; Q3 2022-23:
    the PETROLEUM section printed a second time in place of POWER). Keep the copy whose
    sector still has room under the sector count printed in the report (Table 3), then the
    usual sector of the code prefix (N10..., 02...)."""
    pref = lambda c: c[1:3] if c.startswith("N") else c[:2]  # noqa: E731
    by = defaultdict(list)
    for r in rows:
        by[r["project_code"] or id(r)].append(r)
    major = defaultdict(Counter)
    used = Counter()
    for code, rs in by.items():
        for r in rs:
            if r["project_code"]:
                major[pref(r["project_code"])][r["sector_raw"]] += 1
        if len(rs) == 1:
            used[norm_sector(rs[0]["sector_raw"])] += 1
    demand = Counter(norm_sector(r["sector_raw"]) for rs in by.values() if len(rs) > 1
                     for r in {id(x): x for x in rs}.values())
    fits = {k: k in stated and stated[k][1] - used[k] >= n for k, n in demand.items()}
    keep, dropped = [], []
    for code, rs in by.items():
        if len(rs) == 1:
            keep.append(rs[0])
            continue

        def score(r):
            return (fits[norm_sector(r["sector_raw"])], major[pref(code)][r["sector_raw"]], -r["page"])
        pick = max(rs, key=score)
        keep.append(pick)
        dropped += [f"{code}@p{r['page']}({r['sector_raw']})" for r in rs if r is not pick]
    keep.sort(key=lambda r: r["page"])
    return keep, dropped


def sector_counts(summary):
    """norm sector -> (name, projects) from Table 3 (end of quarter), else the status pages."""
    out = {}
    for s in summary:
        if s["metric"] == "n_projects" and s["dimension"] == "sector" and s["sub_dimension_value"] is None \
                and re.search(r"added/dropped", s["table_title"], re.I) and s["dimension_value"] != "Total":
            out[norm_sector(s["dimension_value"])] = (s["dimension_value"], s["value"])
    if not out:
        for s in summary:
            if s["table_title"].startswith("Sector status") and s["metric"] == "n_projects" \
                    and s["sub_dimension_value"] == "Total":
                out.setdefault(norm_sector(s["dimension_value"]), (s["dimension_value"], s["value"]))
    return out


CROSS_FIELDS = ("doa_original", "cost_original_cr", "cost_anticipated_cr", "doc_original", "doc_anticipated",
                "expenditure_cum_cr", "delay_months")


def cross_check(card_rows, list_rows):
    """Field agreement between the project cards and the annexure-list entries of the same code."""
    n, diff, ex = 0, Counter(), []
    for r in card_rows:
        lr = list_rows.get(r["project_code"])
        if not lr:
            continue
        n += 1
        for f in CROSS_FIELDS:
            a, b = r.get(f), lr.get(f)
            if a is None or b is None:
                continue
            same = abs(a - b) <= 0.011 if isinstance(a, float) else a == b
            if not same:
                diff[f] += 1
                if len(ex) < 4:
                    ex.append(f"{r['project_code']} {f} card={a} list={b}")
    return n, diff, ex


def summary_value(summary, table_key_title, dimension, dval, metric, sub=None):
    for s in summary:
        if (re.search(table_key_title, s["table_title"] or "", re.I) and s["dimension"] == dimension
                and s["dimension_value"] == dval and s["metric"] == metric and s["sub_dimension_value"] == sub):
            return s["value"]
    return None


def norm_sector(s):
    s = re.sub(r"[^A-Z]", "", (s or "").upper().replace("&", "AND"))
    return {"FERTILIZERS": "FERTILISERS", "HEAVYINDUSTRIES": "HEAVYINDUSTRY"}.get(s, s)


def process(path, quarter, period, layout):
    src = rel(path)
    meta = {"report_period": period, "report_type": REPORT_TYPE, "fiscal_year": fiscal_year(period),
            "quarter": quarter, "source_file": src}
    doc = fitz.open(path)
    texts = [doc[i].get_text() for i in range(doc.page_count)]
    notes, problems = [], []
    pn = period_in_pdf(texts, quarter, period)
    if pn:
        notes.append(pn)
    projects, counts = [], Counter()
    missing_list = False

    summary, snotes, found = overview_summary(doc, texts, meta)
    problems += snotes

    if layout == "detail":
        cards = detail_cards(doc)
        rows = [card_row(c, meta) for c in cards]
        stated_sector = sector_counts(summary)
        rows, dropped = dedupe_cards(rows, stated_sector)
        if dropped:
            notes.append(f"{len(dropped)} duplicate cards dropped (same code printed twice): "
                         + ", ".join(dropped[:6]) + (" ..." if len(dropped) > 6 else ""))
        warn = Counter(w for c in cards for w in c["warnings"])
        prob = [f"p{c['page']} {c.get('code')}: {p}" for c in cards for p in c["problems"]]
        problems += prob
        if warn:
            notes.append("card layout warnings: " + ", ".join(f"{k} x{v}" for k, v in warn.items()))
        got = Counter(norm_sector(r["sector_raw"]) for r in rows)
        gaps = [f"{name}: {got.get(k, 0)} cards vs {v:g} in Table 3" for k, (name, v) in stated_sector.items()
                if abs(got.get(k, 0) - v) > 0]
        if gaps:
            notes.append("sector card count vs Table 3: " + ", ".join(gaps))
        # schedule-status annexure lists: cross-check the cards and fill projects without a card
        out, lpages, lpr = parse_lists(doc)
        problems += lpr
        list_rows = {}
        for kind, recs in out.items():
            if LIST_KINDS[kind][1] != "ongoing":        # name lists / derived lists
                continue
            for rec in recs:
                lr = list_record_row(rec, meta, "ongoing")
                if lr["project_code"]:
                    list_rows.setdefault(lr["project_code"], lr)
        if list_rows:
            n, diff, ex = cross_check(rows, list_rows)
            card_codes = {r["project_code"] for r in rows}
            extra = [lr for code, lr in list_rows.items() if code not in card_codes]
            for lr in extra:
                lr["remarks"] = "no project card printed in this report; fields from the schedule-status annexure list"
            notes.append(f"annexure lists hold {len(list_rows)} projects; {n} cards cross-checked, field "
                         f"disagreements: " + (", ".join(f"{k} {v}" for k, v in diff.items()) or "none")
                         + (" (e.g. " + ", ".join(ex) + ")" if ex else "")
                         + f", {len(card_codes - set(list_rows))} card codes not in the lists")
            if extra:
                notes.append(f"{len(extra)} ongoing rows added from the annexure lists for projects without a card "
                             f"(sectors: " + ", ".join(f"{k} {v}" for k, v in
                                                        Counter(r['sector_raw'] for r in extra).most_common()) + ")")
            rows += extra
        projects += rows
        counts["ongoing"] = len(rows)
        cpages = [i + 1 for i, t in enumerate(texts) if "List of projects completed in" in t]
        recs, pr = completed_list_old(doc, cpages)
        problems += pr
        crow = [completed_old_row(r, meta) for r in recs]
        projects += crow
        counts["completed"] = len(crow)
        apages = [i + 1 for i, t in enumerate(texts) if "List Of Additionally Delayed" in t]
        arecs, pr = additionally_delayed(doc, apages)
        problems += pr
        arow = [addl_row(r, meta) for r in arecs]
        projects += arow
        counts["other"] += len(arow)
        variant = "qpsir_cards_v1"
        if cpages:
            notes.append(f"completed list p{cpages[0]}-{cpages[-1]} is cumulative for the FY (remarks = quarter of "
                         "completion); project codes are not printed in it")
        if apages:
            notes.append(f"additionally delayed list p{apages[0]}-{apages[-1]} -> other:additionally_delayed "
                         "(no project codes printed)")
    elif layout == "lists":
        out, pages, pr = parse_lists(doc)
        problems += pr
        for kind, recs in out.items():
            lt = LIST_KINDS[kind][1]
            if kind in ("added", "completed"):
                for r in recs:
                    projects.append({**meta, "page": r["page"], "list_type": lt, "sector_raw": r["sector"],
                                     "project_name": clean(" ".join(r["name"])),
                                     "agency": clean(" ".join(r["agency"])) or None})
                counts["completed" if kind == "completed" else "other"] += len(recs)
            elif lt:
                rows = [list_record_row(r, meta, lt) for r in recs]
                projects += rows
                counts["ongoing"] += len(rows)
        # derived list 'Ongoing Projects having Both Time and Cost Overruns': not extra rows, it
        # only carries the per-project cost overrun % the schedule-status lists do not print
        cor = {}
        for r in out.get("time_cost", []):
            code = split_project_cell(" ".join(r["name"]))[1]
            v = to_num((r["vals"].get("cor_pct") or {}).get(1))
            if code and v is not None:
                cor[code] = v
        n_cor = 0
        for r in projects:
            if r["list_type"] == "ongoing" and r["project_code"] in cor:
                r["cost_overrun_pct"] = cor[r["project_code"]]
                n_cor += 1
        if cor:
            notes.append(f"cost_overrun_pct for {n_cor} ongoing rows from 'Details of Ongoing Projects having "
                         f"Both Time and Cost Overruns' ({len(cor)} codes, p{pages['time_cost'][0]}-"
                         f"{pages['time_cost'][-1]})")
        # added / completed name lists carry no code: take it from the same report's
        # annexure entry with the identical name (+ agency when printed there)
        key = lambda n: re.sub(r"[^A-Z0-9]", "", (n or "").upper())  # noqa: E731
        by_name = defaultdict(list)
        for r in projects:
            if r["list_type"] == "ongoing":
                by_name[key(r["project_name"])].append(r)
        matched = Counter()
        for r in projects:
            if r["list_type"] in ("completed", "newly_added"):
                cands = by_name.get(key(r["project_name"]), [])
                if len(cands) > 1:
                    cands = [c for c in cands if key(c["agency"]) == key(r["agency"])]
                if len(cands) == 1:
                    r["project_code"], r["state"] = cands[0]["project_code"], cands[0]["state"]
                    matched[r["list_type"]] += 1
                    if r["list_type"] == "completed":
                        cands[0]["remarks"] = "also in this report's List of Completed Projects"
        for lt in ("completed", "newly_added"):
            n = sum(1 for r in projects if r["list_type"] == lt)
            if n:
                notes.append(f"{lt}: {matched[lt]}/{n} codes looked up by exact name in this report's annexure "
                             "lists (codes are not printed in the added/completed lists)")
        if matched["completed"]:
            notes.append(f"the schedule-status lists (= projects on the monitor) include {matched['completed']} "
                         "projects completed this quarter, flagged in remarks")
        notes.append("ongoing = union of the schedule-status annexure lists: "
                     + ", ".join(f"{k} {len(v)} (p{pages[k][0]}-{pages[k][-1]})" for k, v in out.items()
                                 if LIST_KINDS[k][1] == "ongoing"))
        if "without_odc" not in out:
            missing_list = True
            notes.append("no 'List of projects without Original Date of Commissioning' in this report; "
                         "those projects are missing from the ongoing rows")
        if any(r.get("list_type") == "ongoing" and r.get("agency") is None for r in projects):
            notes.append("ahead / on-schedule lists truncate the project cell to 'NAME - [CODE' in some "
                         "reports: agency/state blank for those rows")
        variant = "qpsir_annexure_lists_v1"
    else:
        variant = "qpsir_part1_overview_v1"
        notes.append("Part I = overview text + annex tables only (summary); project lists are in Part_II")

    stated = (summary_value(summary, "Highlights", "overall", "All projects", "n_projects")
              or summary_value(summary, "added/dropped|Project summary", "sector", "Total", "n_projects"))
    if stated and layout != "overview":
        gap = (counts["ongoing"] - stated) / stated * 100
        notes.append(f"ongoing rows {counts['ongoing']} vs stated {stated:g} ({gap:+.1f}%)")
    notes.append("summary tables: " + ", ".join(f"{k}@p{v}" if k != "sector_status_pages" else f"{k}={v}"
                                               for k, v in found.items()))
    if problems:
        notes.append(f"{len(problems)} parse warnings: " + " | ".join(problems[:6]))
    ongoing_gap = abs(counts["ongoing"] - stated) / stated if stated and layout != "overview" else 0
    status = "ok" if ongoing_gap <= 0.02 and len(problems) <= 20 and not missing_list else "partial"
    man = {"source_file": src, "report_type": REPORT_TYPE, "report_period": period, "pages": doc.page_count,
           "parser_variant": variant, "stated_total_projects": stated, "rows_ongoing": counts["ongoing"],
           "rows_completed": counts["completed"], "rows_other": counts["other"], "rows_summary": len(summary),
           "status": status, "notes": "; ".join(n.replace("; ", ", ") for n in notes)}
    doc.close()
    return projects, summary, man, problems


def main():
    all_p, all_s, manifest = [], [], []
    stated_by_period = {}
    for path, quarter, period, layout in FILES:
        try:
            p, s, man, probs = process(path, quarter, period, layout)
        except Exception as e:  # noqa: BLE001 - one bad file must not stop the family
            manifest.append({"source_file": rel(path), "report_type": REPORT_TYPE, "report_period": period,
                             "status": "failed", "notes": f"{type(e).__name__}: {e}"})
            print(f"FAILED {path.name}: {e!r}")
            continue
        if man["stated_total_projects"]:
            stated_by_period[period] = man["stated_total_projects"]
        elif layout == "lists" and period in stated_by_period:
            # Q4 2023-24 Part_II: totals are printed in Part_I of the same report
            st = stated_by_period[period]
            man["stated_total_projects"] = st
            gap = (man["rows_ongoing"] - st) / st * 100
            man["notes"] += f"; ongoing rows {man['rows_ongoing']} vs {st:g} on the monitor per Part_I ({gap:+.1f}%)"
            if abs(gap) > 2:
                man["status"] = "partial"
        all_p += p
        all_s += s
        manifest.append(man)
        print(f"{path.name}: ongoing={man['rows_ongoing']} completed={man['rows_completed']} "
              f"other={man['rows_other']} summary={man['rows_summary']} stated={man['stated_total_projects']} "
              f"warnings={len(probs)} status={man['status']}")
    for name, rows, cols in (("projects", all_p, PROJECT_COLS), ("summary", all_s, SUMMARY_COLS),
                             ("manifest", manifest, MANIFEST_COLS)):
        print("wrote", write_part(rows, FAMILY, name, cols), len(rows))


def self_check():
    # project cell of the annexure lists
    assert split_project_cell("RAJASTHAN ATOMIC POWER PROJECT -7 AND 8 (2X700 MW) - [N02000027]NPCIL,RAJASTHAN") \
        == ("RAJASTHAN ATOMIC POWER PROJECT -7 AND 8 (2X700 MW)", "N02000027", "NPCIL", "RAJASTHAN")
    assert split_project_cell("MONIGRAM- NIMTITA - [N22000301]ER,MULTI STATE")[1:] == ("N22000301", "ER", "MULTI STATE")
    assert split_project_cell("BHANUPALI-BILASPUR BERI NL - [N22000273") == \
        ("BHANUPALI-BILASPUR BERI NL", "N22000273", None, None)
    # card grid: markers on one page, values under them; revised cost blank
    sp = lambda t, x, y, pno=0: {"t": t, "xc": x, "x0": x - 5, "x1": x + 5, "y0": y, "pno": pno}  # noqa: E731
    anchors = {n: (x, 167.9, 0) for n, x in zip(range(1, 8), (62, 138, 233, 323, 404, 480, 548))}
    card = {"anchors": anchors, "problems": [], "warnings": [],
            "vals": [sp("09/2003", 63, 181.2), sp("3492", 137, 181.2), sp("6,840.00", 137, 194.6),
                     sp("6840", 137, 208.2), sp("145", 486, 181.2), sp("5962.85", 407, 208.2)]}
    c = grid_cells(card)
    assert c == {(1, 1): "09/2003", (2, 1): "3492", (2, 2): "6,840.00", (2, 3): "6840", (6, 1): "145",
                 (5, 3): "5962.85"}, c
    # grid pushed to the next page: rows restart at the top margin
    card = {"anchors": anchors, "problems": [], "warnings": [],
            "vals": [sp("06/2016", 63, 70.6, 1), sp("412.24", 137, 70.6, 1), sp("412.24", 137, 97.6, 1)]}
    assert grid_cells(card) == {(1, 1): "06/2016", (2, 1): "412.24", (2, 3): "412.24"}
    # completed list: name / location / (STATE)
    meta = {"report_period": "2021-06"}
    rec = {"lines": [(356, "KAMENG HYDROELECTRIC PROJECT"), (367, "(NEEPCO)"), (379, "WEST KAMENG"),
                     (388, "(ARUNACHAL PRADESH)")], "vals": defaultdict(dict), "page": 1, "sector": "POWER",
           "agency": "NEEPCO"}
    r = completed_old_row(rec, meta)
    assert (r["project_name"], r["location"], r["state"]) == \
        ("KAMENG HYDROELECTRIC PROJECT (NEEPCO)", "WEST KAMENG", "ARUNACHAL PRADESH"), r
    rec["lines"] = [(186, "PUNE POL STORAGE DEPOT"), (207, "(MAHARASHTRA)")]
    r = completed_old_row(rec, meta)
    assert (r["project_name"], r["location"], r["state"]) == ("PUNE POL STORAGE DEPOT", None, "MAHARASHTRA")
    # overview tables: '74- 145' range and Excel 'Oct-51' artefact
    w = lambda t, x0, x1: {"t": t, "x0": x0, "x1": x1, "xc": (x0 + x1) / 2, "y0": 100}  # noqa: E731
    r = label_rows([[w("7", 82, 86), w("STEEL", 102, 124), w("9", 199, 202), w("74-", 524, 534),
                     w("145", 538, 549)]])[0]
    assert r["label"] == "STEEL" and r["serial"] and [v["t"] for v in r["vals"]] == ["9", "74 - 145"]
    assert is_value("Oct‐51") and to_num("9,52,54.36") == 95254.36
    print("self-check ok")


if __name__ == "__main__":
    self_check()
    main()
