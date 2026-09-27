# pipeline/identity — stable project keys across 20 years of reports

One project = one `PRJ-xxxxxx` key, forever. Every table downstream joins on it.
Printed OCMS/PAIMANA codes, names and spellings are evidence for finding the
key, never the key itself.

## What it guarantees

| Guarantee | How |
|---|---|
| Keys never change on rebuild | `projects.parquet` / `aliases.parquet` are read first; only never-seen rows mint |
| Same input → same keys, even from scratch | rows are sorted by (period, report type, row id) before minting |
| Re-running a month is a no-op | alias cache keyed by (report_type, period, row_id) |
| Wrong splits are fixable without breaking references | `merge(loser, winner)` keeps the loser with `merged_into`; `canonical()` resolves it |
| Uncertain matches never silently merge | `review_status="review"`, linked provisionally; training filters `accepted` |
| A printed code is never silently ignored | code match + compatible name → review link; code match + contradicting name → own key, review flag (`code_conflict`) |
| Humans win | `manual_links.csv` with a key or `NEW` overrides the resolver, idempotently |
| Every mint/merge/manual is logged | `audit.jsonl` with run_id |

## Files

```
pipeline/identity/
  config.py        column contract, weights, thresholds, paths
  normalize.py     name/code normalisation (extend ABBREV as you meet spellings)
  identity_map.py  IdentityMap: resolve_batch, merge, canonical, save, review_queue
  bundle.py        get_project_bundle(key): everything for one project via DuckDB
  checks.py        build invariants; raise IdentityCheckError → fail the build
pipeline/build_identity.py   example CLI: clean rows → keys → checks → manifest
tests/test_identity.py       7 tests (stability, determinism, wrong code, merge, manual, bundle, checks)
tests/stress_synthetic.py    speed + purity on synthetic panels
```

Dependencies: pandas ≥ 2, pyarrow, rapidfuzz, duckdb.

## Input contract

`resolve_batch(df)` reads these columns (rename yours in an adapter; see
`build_identity.py`). Only the first three are required per row.

| column | example |
|---|---|
| source_report_type | `monthly_2013_16`, `quarterly_2021_24`, `flash` |
| source_period | `2026-04-01` |
| source_row_id | unique inside one report file; deterministic |
| project_name | as printed |
| project_code | printed code or null |
| sector, state, agency, ministry | as printed or null |
| original_cost_cr | float or null |
| sanction_year | int or null |

Output: the same frame plus `project_key`, `match_score`, `match_method`
(`new`, `code_exact`, `name_attrs`, `code_conflict`, `manual`, `alias_cache`)
and `review_status` (`accepted`, `review`).

## How matching works

1. Candidates: projects sharing name tokens, ranked by IDF-weighted overlap (rare place names count, "road" doesn't), plus any project with the same code. Top 30 scored.
2. Score = weighted blend of name similarity (0.5), code equality (0.25), original-cost proximity (0.1), state (0.05), sector (0.05), agency (0.03), sanction year (0.02). Weights renormalise over the components present in the row, so missing sector/state don't punish.
3. Name similarity = 0.4 character-level + 0.6 fuzzy token Jaccard; differing package/phase numbers cap it at 0.6 ("Package 1" vs "Package 4" never auto-link).
4. ≥ 0.92 accepted · 0.75–0.92 review · else new. Thresholds in `config.py`.

Only **accepted** links enrich a project's stored attributes. That rule matters: a provisional link that injected its code into the wrong project cascaded into hundreds of wrong `code_exact` matches in testing.

## Integration

1. Run after `build_clean_projects.py`: `python pipeline/build_identity.py`.
2. Build `silver/observations.parquet` from `resolved_rows.parquet` keeping `review_status == "accepted"` for the training panel; keep review rows in a side table the app can show with a badge.
3. Add `run_all(...)` to the end of `make silver`; it fails the build on duplicate (key, period), unknown keys, merged keys still in use, or a portal row mapping to a shared key.
4. Work `review_queue.csv` occasionally: add confirmed rows to `manual_links.csv` (`project_key` = existing key or `NEW`), re-run. Merges found later: `IdentityMap.merge(loser, winner, reason)` then `save()`.
5. Serve: `get_project_bundle(key, idmap, BundlePaths(...))` is the source for `/projects/{key}`; it follows `merged_into`, so old links keep working.

## Measured on synthetic panels

4,000 projects, 60k rows, 30% spelling drift, 20% missing codes, 15% missing sector/state, ±3% cost noise:
75 s first build (≈ 1,000 rows/s → ~3 min for 165k rows), 7 s cached rerun,
0 projects split across keys, 7 keys holding two projects (0.2%), 0.5% rows to review.
Real names are more distinctive than the synthetic ones, so expect better; the
review queue is where the remainder surfaces.

## Tuning knobs you will actually touch

- `normalize.ABBREV` — add report-specific abbreviations as you find them.
- `Thresholds.accept` / `.review` — tighten if the queue is small and merges appear; loosen if the queue is large and links are right.
- `Thresholds.code_conflict_name_sim` (0.30) — below this, a matching code is treated as a printing error.
- `Weights.cost` — raise if two-package projects with identical names keep linking.
