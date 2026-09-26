"""
Real fix for sector/state on the 2024-25 quarterly PDFs (the only PDFs we
have locally). Table:-7 "Ongoing Projects" prints State/Sector as their own
left-hand columns that ONLY show text when the value changes from the row
above (blank otherwise) and the label can wrap across 2-3 lines. We read
words by x-coordinate (not text-line scanning — that's what broke last time)
so we key off COLUMN POSITION, never lexical matching:
  x0 < 70   -> state column
  70-140    -> sector column
  >= 150    -> Sl No / project name / rest

For each page: cluster state-column words and sector-column words into
label blocks by vertical proximity, find which Sl No each block starts at,
then forward-fill state/sector across entries (and across pages) until the
next block changes it. Project entries are anchored by the "(N########)"
project-code line, which is the CSV's project_id.

Bronze CSVs are never modified. Output is a lookup CSV joined onto a copy.
"""
import pdfplumber
import pandas as pd
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PDF_DIR_1 = ROOT / "dataset" / "raw" / "pdf" / "2024-25"
PDF_DIR_2 = ROOT / "dataset" / "raw" / "pdf" / "2025-26"
CSV_DIR = ROOT / "dataset" / "raw" / "csv"
OUT_DIR = ROOT / "dataset" / "silver"
OUT_DIR.mkdir(parents=True, exist_ok=True)

PDF_FILES = [
    PDF_DIR_1 / "QPISR_1st_QTR_2024-25 PART2.pdf",
    PDF_DIR_1 / "QPISR_2nd_QTR_2024-25 PART2.pdf",
    PDF_DIR_1 / "QPISR_3rd_QTR_2024-25.pdf",
    PDF_DIR_1 / "QPISR_4th_QTR_2024-25.pdf",
    PDF_DIR_2 / "QPISR_QR_1st_2025-26.pdf",
]

STATE_X = (0, 70)
SECTOR_X = (70, 140)
CODE_RE = re.compile(r"^\((N\d{8})\)$")
SLNO_RE = re.compile(r"^\d+$")
LINE_GAP = 13  # points; consecutive wrapped lines of one label are closer than this


def cluster_column(words, x_range):
    """words already filtered to one column; group into label blocks by
    vertical proximity, return list of (top_start, top_end, text)."""
    ws = sorted([w for w in words if x_range[0] <= w["x0"] < x_range[1]], key=lambda w: w["top"])
    blocks = []
    cur = []
    last_top = None
    for w in ws:
        if last_top is not None and w["top"] - last_top > LINE_GAP:
            if cur:
                blocks.append(cur)
            cur = []
        cur.append(w)
        last_top = w["top"]
    if cur:
        blocks.append(cur)
    out = []
    for b in blocks:
        text = " ".join(w["text"] for w in b)
        out.append((b[0]["top"], b[-1]["top"], text))
    return out


def scan_pdf(path):
    """returns list of dicts: source_file, page, sl_no, project_id, sector, state
    in document order, with state/sector forward-filled."""
    rows = []
    cur_sector = None
    cur_state = None
    fname = path.name
    with pdfplumber.open(path) as pdf:
        for pno, page in enumerate(pdf.pages, start=1):
            words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
            if not words:
                continue
            state_blocks = cluster_column(words, STATE_X)
            sector_blocks = cluster_column(words, SECTOR_X)

            # entries: Sl No (isolated digit token at x0 in [150,175]) followed
            # somewhere below by "(N########)" -> project code
            slno_words = [w for w in words if 150 <= w["x0"] < 180 and SLNO_RE.match(w["text"])]
            code_words = [w for w in words if CODE_RE.match(w["text"])]

            # pair each code to the nearest preceding Sl No (by top) to get that entry's top
            slno_words.sort(key=lambda w: w["top"])
            code_words.sort(key=lambda w: w["top"])
            entries = []  # (entry_top, project_id)
            for cw in code_words:
                preceding = [s for s in slno_words if s["top"] <= cw["top"]]
                if not preceding:
                    continue
                entry_top = preceding[-1]["top"]
                entries.append((entry_top, cw["text"][1:-1]))

            for entry_top, pid in entries:
                # does a state/sector block START at this entry's top (+/- 2pt)?
                for top0, top1, text in state_blocks:
                    if abs(top0 - entry_top) <= 2:
                        cur_state = text
                        break
                for top0, top1, text in sector_blocks:
                    if abs(top0 - entry_top) <= 2:
                        cur_sector = text
                        break
                rows.append({
                    "source_file": fname, "page": pno, "project_id": pid,
                    "sector_pdf": cur_sector, "state_pdf": cur_state,
                })
    return rows


def main():
    all_rows = []
    for f in PDF_FILES:
        if not f.exists():
            print(f"MISSING: {f}")
            continue
        rows = scan_pdf(f)
        print(f"{f.name}: {len(rows)} project entries found")
        all_rows.extend(rows)

    fix = pd.DataFrame(all_rows).drop_duplicates(subset=["project_id"], keep="last")
    print(f"\ntotal unique project_id -> sector/state: {len(fix)}")
    fix.to_csv(OUT_DIR / "pdf_sector_state_fix.csv", index=False)

    for fy_file in ["project_monitoring_2024-25.csv", "project_monitoring_2025-26.csv"]:
        d = pd.read_csv(CSV_DIR / fy_file, dtype=str, keep_default_na=False)
        d2 = d.merge(fix[["project_id", "sector_pdf", "state_pdf"]], on="project_id", how="left")
        cov_sec = d2["sector_pdf"].notna().mean() * 100
        cov_st = d2["state_pdf"].notna().mean() * 100
        changed_sec = ((d2["sector_pdf"].notna()) & (d2["sector_pdf"] != d2["sector"])).mean() * 100
        print(f"{fy_file}: pdf-fix covers sector={cov_sec:.0f}% state={cov_st:.0f}% | differs from orig sector={changed_sec:.0f}%")
        d2.to_csv(OUT_DIR / f"{fy_file.replace('.csv','')}_pdf_fixed.csv", index=False)


if __name__ == "__main__":
    main()
