"""Configuration for the identity layer.

The resolver reads source rows through the column names in `Columns`.
Map your extractor output onto these names (rename in a thin adapter) rather
than editing the resolver.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Columns:
    """Input contract for `IdentityMap.resolve_batch`. All except the first
    three may be missing/null per row; missing components are simply left out
    of the score."""
    source_report_type: str = "source_report_type"   # e.g. "monthly_2013_16", "flash"
    source_period: str = "source_period"             # date-like (report month/quarter)
    source_row_id: str = "source_row_id"             # unique within one report file
    name: str = "project_name"
    code: str = "project_code"                       # printed OCMS/PAIMANA code
    sector: str = "sector"
    state: str = "state"
    agency: str = "agency"
    ministry: str = "ministry"
    original_cost_cr: str = "original_cost_cr"
    sanction_year: str = "sanction_year"


@dataclass(frozen=True)
class Weights:
    name: float = 0.50
    code: float = 0.25
    cost: float = 0.10
    state: float = 0.05
    sector: float = 0.05
    agency: float = 0.03
    year: float = 0.02


@dataclass(frozen=True)
class Thresholds:
    accept: float = 0.92
    review: float = 0.75
    # A code match with a name this dissimilar is treated as a printed-code
    # error (the "22 wrong codes" case) and capped at review.
    code_conflict_name_sim: float = 0.30
    # Blocking: candidates must share at least this many name tokens, unless
    # they share a code.
    min_shared_tokens: int = 1


@dataclass
class IdentityConfig:
    root: Path = Path("dataset/silver/identity")
    key_prefix: str = "PRJ-"
    key_width: int = 6
    columns: Columns = field(default_factory=Columns)
    weights: Weights = field(default_factory=Weights)
    thresholds: Thresholds = field(default_factory=Thresholds)

    @property
    def projects_path(self) -> Path:
        return self.root / "projects.parquet"

    @property
    def aliases_path(self) -> Path:
        return self.root / "aliases.parquet"

    @property
    def audit_path(self) -> Path:
        return self.root / "audit.jsonl"
