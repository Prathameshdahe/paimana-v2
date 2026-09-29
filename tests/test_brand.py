"""The PARAKH brand kit (brand/build_brand.py): the generated text files match the script and the stylesheet, the
dashboard's page links icons that exist, and the markup and parakh.css agree on the class names."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "brand"))
import build_brand  # noqa: E402

PUBLIC = ROOT / "frontend" / "public"


def test_generated_files_are_up_to_date():
    """Edit brand/build_brand.py or parakh.css, then run `python brand/build_brand.py`."""
    assert build_brand.main(["--check"]) == 0


def test_index_links_icons_that_exist():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    hrefs = re.findall(r'<link rel="(?:icon|apple-touch-icon|manifest)" href="/([^"]+)"', html)
    assert {"favicon.ico", "favicon.svg", "apple-touch-icon.png", "manifest.json"} <= set(hrefs)
    for h in hrefs:
        assert (PUBLIC / h).is_file(), h
    manifest = json.loads((PUBLIC / "manifest.json").read_text(encoding="utf-8"))
    for icon in manifest["icons"]:
        assert (PUBLIC / icon["src"].lstrip("/")).is_file(), icon["src"]
    # the alert tab icon the app swaps in (lib/useBeaconStatus.ts)
    assert (PUBLIC / "favicon-alert.svg").is_file()
    assert "<title>PARAKH" in html


def test_markup_and_stylesheet_agree():
    markup = build_brand.animated_inner()
    css = build_brand.CSS.read_text(encoding="utf-8")
    classes = set(re.findall(r'class="([^"]+)"', markup))
    names = {c for group in classes for c in group.split()}
    for name in names:
        assert f".{name}" in css, f"parakh.css has no rule for .{name}"
    # every id carries the per-instance placeholder, so two marks on a page never share a mask or a filter
    ids = re.findall(r'id="([^"]+)"', markup)
    assert ids and all(i.endswith("__UID__") for i in ids)
    assert "prefers-reduced-motion" in css
