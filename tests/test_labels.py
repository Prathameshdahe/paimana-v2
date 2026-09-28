"""backend/labels.py mirrors the frontend's label maps: the same keys on both sides, the same fallback words."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend import labels, serving  # noqa: E402
from ml import risk_profile  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TS_KEY = re.compile(r"^\s*(\w+):\s*(?:'([^']*)'|\{\s*label:\s*'([^']*)')", re.M)


def ts_map(path: str, name: str) -> dict[str, str]:
    """The entries of one `const NAME ... = { key: 'label' | { label: '...' } }` block of a TypeScript file."""
    text = (ROOT / path).read_text(encoding="utf-8")
    block = re.search(rf"const {name}\b[^=]*=\s*\{{(.*?)^\}}", text, re.S | re.M)
    assert block, f"{name} not found in {path}"
    return {m[1]: m[2] or m[3] for m in TS_KEY.finditer(block[1])}


def test_feature_labels_match_the_frontend():
    ts = ts_map("frontend/src/lib/featureLabels.ts", "FEATURE_LABELS")
    assert ts.keys() == labels.FEATURE_LABELS.keys()
    assert ts == labels.FEATURE_LABELS  # the words too, so a driver reads the same in the chat and on the page


def test_dimension_labels_match_the_checklist_and_the_frontend():
    ts = ts_map("frontend/src/lib/riskPalette.ts", "RISK_DIMENSION")
    assert ts == labels.DIMENSION_LABELS
    assert list(labels.DIMENSION_LABELS) == risk_profile.DIMENSIONS
    assert set(serving.PLAIN_RISK) == set(labels.DIMENSION_LABELS)


def test_factor_labels_match_the_external_factors():
    text = (ROOT / "frontend/src/lib/riskPalette.ts").read_text(encoding="utf-8")
    block = re.search(r"EXTERNAL_FACTORS\b.*?= \[(.*?)^\]", text, re.S | re.M)[1]
    ts = dict(re.findall(r"key: '(\w+)', label: '([^']*)'", block))
    assert ts == labels.FACTOR_LABELS
    assert set(labels.FACTOR_LABELS) == set(serving.EXT_FACTORS)


def test_source_labels_cover_every_risk_profile_source_and_agree_with_the_frontend():
    """Every source ml/risk_profile.py writes has a label (a row never shows 'news_research'); the frontend's
    SOURCE_LABEL uses the same words and, once unit C adds news_research and parivesh_portal, the same keys."""
    written = set(re.findall(r"\"(model|silver|report|sector_context|agency_stats|bhoomi_rashi|parivesh_rules|"
                             r"parivesh_portal|external_composite|news_research)\"",
                             (ROOT / "ml/risk_profile.py").read_text(encoding="utf-8")))
    assert {"news_research", "parivesh_portal", "model", "silver", "report"} <= written <= set(labels.SOURCE_LABELS)
    gold = sorted((ROOT / "dataset/gold").glob("risk_profile_*.parquet"))
    if gold:
        import pandas as pd
        seen = set(pd.read_parquet(gold[-1], columns=["source"])["source"].dropna().unique())
        assert seen <= set(labels.SOURCE_LABELS), seen - set(labels.SOURCE_LABELS)
    ts = ts_map("frontend/src/views/project-studio/RiskChecklist.tsx", "SOURCE_LABEL")
    assert ts.keys() <= labels.SOURCE_LABELS.keys() and {"model", "report", "bhoomi_rashi"} <= ts.keys()
    assert all(labels.SOURCE_LABELS[k] == v for k, v in ts.items())
    assert labels.source_label("news_research") == "web research" and labels.source_label(None) == "source unknown"
    assert labels.source_label("some_new_source") == "some new source"


def test_fallbacks_read_like_the_frontend():
    assert labels.feature_label("spi") == "Schedule performance index"
    assert labels.feature_label("ext_open_land") == "Open land issue in remarks"
    assert labels.feature_label("ext_ever_forest_env") == "forest env issue ever reported"
    assert labels.feature_label("some_new_feature") == "Some new feature"
    assert labels.dimension_label("land_acquisition") == "Land acquisition"
    assert labels.dimension_label("new_check") == "New check"


def test_direction_words():
    assert labels.direction(0.4) == "raises the risk"
    assert labels.direction(-0.2) == "lowers the risk"
    assert labels.direction(0) == labels.direction(None) == "no effect"
