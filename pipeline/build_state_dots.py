"""
Generate one scatter point per project, placed randomly inside its state's
polygon, for the India map's dot-density layer. Run after build_real_projects.py.

Output goes to frontend/src/data/ (not public/): Vite won't let you import
files from public/ as JS modules, only files under src/.

Known limitation: the boundary file predates Telangana's 2014 split from
Andhra Pradesh and Ladakh's 2019 split from Jammu & Kashmir, so those states'
dots scatter inside the pre-split parent polygon, not their own exact shape.
"""
import json
import random
from pathlib import Path
from shapely.geometry import shape, Point

ROOT = Path(__file__).resolve().parents[1] / "frontend"
GEOJSON = ROOT / "public" / "india-states-simplified.geojson"
PROJECTS = ROOT / "src" / "mocks" / "real_projects.json"
OUT = ROOT / "src" / "data" / "state-dots.json"

ALIAS = {
    "odisha": "orissa",
    "uttarakhand": "uttaranchal",
    "telangana": "andhra pradesh",
    "ladakh": "jammu and kashmir",
    "andaman and nicobar islands": "andaman and nicobar",
}


def norm(name):
    return ALIAS.get(name.strip().lower(), name.strip().lower())


def random_point_in(poly, tries=60):
    minx, miny, maxx, maxy = poly.bounds
    for _ in range(tries):
        x, y = random.uniform(minx, maxx), random.uniform(miny, maxy)
        if poly.contains(Point(x, y)):
            return round(x, 3), round(y, 3)
    c = poly.representative_point()
    return round(c.x, 3), round(c.y, 3)


def main():
    geo = json.loads(GEOJSON.read_text(encoding="utf-8"))
    projects = json.loads(PROJECTS.read_text(encoding="utf-8"))
    polys = {f["properties"]["name"].strip().lower(): shape(f["geometry"]) for f in geo["features"]}

    by_state = {}
    for p in projects:
        by_state.setdefault(norm(p["state"]), []).append(p)

    random.seed(42)
    out, unmatched = {}, []
    for key, plist in by_state.items():
        poly = polys.get(key)
        if poly is None:
            unmatched.append((key, len(plist)))
            continue
        pts = []
        for p in plist:
            lon, lat = random_point_in(poly)
            pts.append({"lon": lon, "lat": lat, "tier": p["riskTier"], "id": p["id"]})
        out[key] = pts

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    print(f"states with dots: {len(out)}  total dots: {sum(len(v) for v in out.values())}")
    print(f"unmatched (no polygon, no dots — expected for Multi State/Unspecified): {unmatched}")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
