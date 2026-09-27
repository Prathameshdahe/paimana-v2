"""Synthetic stress test: N projects × 5–25 reports with spelling drift,
missing codes/sector/state, ±3% cost noise. Reports speed and purity.

Run: python tests/stress_synthetic.py [n_projects]
"""
import pathlib
import random
import shutil
import sys
import tempfile
import time

import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from pipeline.identity import IdentityMap, IdentityConfig  # noqa: E402

N = int(sys.argv[1]) if len(sys.argv) > 1 else 4000
random.seed(1)
# realistic-ish: many place names (rare tokens) + a small set of type words (common tokens)
places = [f"place{i}" for i in range(1500)]
types = ["expressway", "railway doubling", "bridge", "canal", "irrigation", "thermal power",
         "port", "airport", "corridor", "transmission line", "refinery", "gas pipeline",
         "coal mine", "steel plant", "dam", "metro", "tunnel", "bypass", "4 laning", "6 laning"]
qual = ["package", "phase", "section", "zone", "stage"]
states = ["Maharashtra", "Gujarat", "Bihar", "UP", "MP", "Odisha", "Assam", "Karnataka"]
sectors = ["Road Transport", "Railways", "Power", "Petroleum", "Coal", "Water Resources",
           "Civil Aviation", "Steel"]

projects = []
for i in range(N):
    n = f"{random.choice(places)} {random.choice(places)} {random.choice(types)}"
    if random.random() < 0.5:
        n += f" {random.choice(qual)} {random.randint(1, 8)}"
    projects.append(dict(name=n, code=f"C{i:05d}" if random.random() < 0.7 else None,
                         state=random.choice(states), sector=random.choice(sectors),
                         cost=random.uniform(150, 20000), year=random.randint(2005, 2024)))
rows = []
periods = list(pd.date_range("2006-01-01", "2026-04-01", freq="QS"))
for pi, p in enumerate(projects):
    for per in sorted(random.sample(periods, random.randint(5, 25))):
        name = p["name"]
        if random.random() < 0.3:
            name = name.replace("expressway", "exp.").replace("package", "pkg").replace("railway", "rly")
        if random.random() < 0.1:
            name = name.upper()
        rows.append(dict(
            source_report_type="quarterly" if per.year < 2025 else "flash", source_period=per,
            source_row_id=f"{pi}-{per:%Y%m}", project_name=name,
            project_code=p["code"] if random.random() < 0.8 else None,
            sector=p["sector"] if random.random() < 0.85 else None,
            state=p["state"] if random.random() < 0.85 else None,
            agency=None, ministry=None,
            original_cost_cr=p["cost"] * random.uniform(0.97, 1.03) if random.random() < 0.9 else None,
            sanction_year=p["year"]))
df = pd.DataFrame(rows)
root = pathlib.Path(tempfile.gettempdir()) / "stress_idm"
shutil.rmtree(root, ignore_errors=True)
m = IdentityMap(IdentityConfig(root=root), run_id="stress")
t = time.time()
r = m.resolve_batch(df)
dt = time.time() - t
r["true"] = r.source_row_id.str.split("-").str[0]
acc = r[r.review_status == "accepted"]
print(f"rows={len(df)} projects={N} resolve={dt:.1f}s minted={len(list(m.keys()))}")
print("status", r.review_status.value_counts().to_dict())
print("method", r.match_method.value_counts().to_dict())
print("true projects split across >1 accepted key:", int((acc.groupby("true").project_key.nunique() > 1).sum()))
print("accepted keys holding >1 true project:", int((acc.groupby("project_key")["true"].nunique() > 1).sum()))
t = time.time(); m.save(); print(f"save={time.time()-t:.1f}s")
t = time.time(); m2 = IdentityMap(IdentityConfig(root=root)); r2 = m2.resolve_batch(df)
print(f"rerun={time.time()-t:.1f}s cached={set(r2.match_method) == {'alias_cache'}}")
