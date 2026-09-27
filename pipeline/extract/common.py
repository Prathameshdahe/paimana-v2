"""
Shared schema and parsing helpers for the PDF extractors in pipeline/extract/.

Every extractor writes its part files to dataset/clean/_parts/<family>/ with
write_part(), which forces the column order below so the merge step can
concat all families without guessing. Blank cells mean "not printed in the
source", never zero.
"""
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "Dataset drive folder" / "Dataset"
PARTS = ROOT / "dataset" / "clean" / "_parts"

# One row per (report, indicator, period_type) from the performance review
# Annexure-A style tables.
PERF_COLS = [
    "report_month", "fiscal_year", "source_file", "page",
    "sector", "indicator_group", "indicator", "unit", "is_total",
    "period_type",            # month | cumulative
    "period_start", "period_end",
    "annual_target", "target", "actual", "prev_year_actual",
    "pct_var_target", "pct_var_prev_year", "pct_achievement",
    "dq_note",                # ';'-joined data-quality flags, e.g. carried_forward:2025-12
]

# Any other table in a performance report, in long form.
PERF_DETAIL_COLS = [
    "report_month", "fiscal_year", "source_file", "page",
    "sector", "table_title", "row_group", "row_label", "column_label",
    "period_start", "period_end", "value", "value_text", "unit",
    "dq_note",
]

# One row per project per report.
PROJECT_COLS = [
    "report_period", "report_type", "fiscal_year", "quarter", "source_file", "page",
    "list_type",              # ongoing | completed | newly_added | dropped | other:<name>
    "project_code", "project_code_alt",   # alt = other printed IDs, 'SYSTEM:ID;...' e.g. OCMS:N18000296;PMG:1234
    "project_name", "sector_raw", "ministry", "agency",
    "state", "location", "capacity",
    "doa_original", "doa_revised",
    "cost_original_cr", "cost_revised_cr", "cost_anticipated_cr",
    "cost_overrun_cr", "cost_overrun_pct",
    "expenditure_cum_cr", "expenditure_upto", "outlay_current_fy_cr",
    "doc_original", "doc_revised", "doc_anticipated",
    "delay_months", "additional_delay_months",
    "physical_progress_pct", "date_completed_actual", "remarks",
    "dq_note",
]

# Aggregate tables as printed in project reports (sector-wise, ministry-wise,
# state-wise summaries), in long form.
SUMMARY_COLS = [
    "report_period", "report_type", "fiscal_year", "quarter", "source_file", "page",
    "table_title", "dimension",   # sector | ministry | state | state_sector | ministry_sector | overall | ...
    "dimension_value", "sub_dimension_value",
    "metric", "value", "unit",
    "dq_note",
]

# One row per source PDF processed by a family.
MANIFEST_COLS = [
    "source_file", "report_type", "report_period", "pages", "parser_variant",
    "stated_total_projects", "rows_ongoing", "rows_completed", "rows_other",
    "rows_summary", "rows_perf", "rows_perf_detail", "status", "notes",
]

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
MONTHS.update({"sept": 9, "fev": 2, "june": 6, "july": 7, "march": 3, "april": 4})

_NUM_BLANK = {"", "-", "--", "na", "n.a.", "n.a", "nr", "n.r.", "n.r", "nil", "*", "..", "none"}


def to_num(s):
    """'1,89,176' -> 189176.0, '(12.5)' -> -12.5, 'NA'/'-'/'N.R.' -> None."""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return None if pd.isna(s) else float(s)
    t = str(s).strip().replace("−", "-").replace("`", "").replace("₹", "")
    if t.lower().rstrip("%").strip() in _NUM_BLANK:
        return None
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()").replace(",", "").replace("%", "").strip()
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


def to_ym(s):
    """Month-precision date -> 'YYYY-MM'. Handles 07/2015, 7/15, 31/12/2026,
    Jul-15, July 2015, July'15, 2015-07. Returns None if unparseable."""
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return None
    t = str(s).strip().lower().replace("’", "'").replace(",", " ")
    if t in _NUM_BLANK:
        return None
    m = re.fullmatch(r"(\d{4})-(\d{1,2})(?:-\d{1,2})?", t)
    if m:
        y, mo = int(m[1]), int(m[2])
    else:
        m = re.fullmatch(r"(?:(\d{1,2})[/.-])?(\d{1,2})[/.-](\d{2}|\d{4})", t)
        if m:
            mo, y = int(m[2]), int(m[3])
        else:
            m = re.fullmatch(r"([a-z]+)[\s'.-]*(\d{2}|\d{4})", t)
            if not m or m[1][:3] not in MONTHS:
                return None
            mo, y = MONTHS.get(m[1], MONTHS[m[1][:3]]), int(m[2])
    if y < 100:
        y += 2000 if y < 60 else 1900
    if not (1 <= mo <= 12 and 1950 <= y <= 2100):
        return None
    return f"{y:04d}-{mo:02d}"


def fiscal_year(ym):
    """'2015-07' -> '2015-16', '2016-02' -> '2015-16'."""
    y, m = int(ym[:4]), int(ym[5:7])
    start = y if m >= 4 else y - 1
    return f"{start}-{str(start + 1)[2:]}"


def rel(path):
    """Source path relative to the Dataset folder, forward slashes."""
    return Path(path).resolve().relative_to(DATASET.resolve()).as_posix()


def write_part(rows, family, name, cols):
    """Write rows (list of dicts or DataFrame) to _parts/<family>/<name>.csv
    with exactly `cols`, in that order. Unknown keys are an error."""
    df = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    extra = set(df.columns) - set(cols)
    if extra:
        raise ValueError(f"{family}/{name}: unknown columns {sorted(extra)}")
    df = df.reindex(columns=cols)
    out = PARTS / family / f"{name}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False, encoding="utf-8")
    return out


if __name__ == "__main__":
    assert to_num("1,89,176") == 189176.0
    assert to_num("(12.5)") == -12.5
    assert to_num("N.R.") is None and to_num("-") is None
    assert to_ym("07/2015") == "2015-07"
    assert to_ym("31/12/2026") == "2026-12"
    assert to_ym("Jul-15") == "2015-07"
    assert to_ym("September 2015") == "2015-09"
    assert to_ym("2015-7") == "2015-07"
    assert fiscal_year("2016-02") == "2015-16"
    print("ok")
