"""What the repository does not carry, and how the tests cope with that.

dataset/, model/ and docs/ (but docs/HELP.md) stay on the owner's machine (.gitignore): a clone, and the CI, has
neither the data the app serves nor the trained models nor the internal write-ups. A test that needs one of them is
SKIPPED there, with the missing file named in the reason, and runs in full wherever the files exist. Nothing is
skipped on a machine that has them: the skipping only applies to a private tree that is absent altogether (its
marker file below), so a wrong path inside a tree that is present still fails.

Two ways in, both from tests/conftest.py and this module:
- automatically: a test or fixture that dies on a FileNotFoundError naming a path under an absent private tree is
  reported as skipped instead of failed (skip_if_absent);
- by hand: @needs("dataset") / needs("model") / needs("docs") on a test or module (pytestmark), for a test whose
  failure is an assertion over empty data rather than a missing file.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# a file that every copy of the private tree has; its absence means the whole tree is absent
MARKERS = {
    "dataset": "dataset/gold/manifest.json",
    "model": "model/registry.json",
    "docs": "docs/PROJECT_DOCUMENTATION.md",
}
PUBLIC = {"docs/HELP.md"}   # tracked: the public help text the assistant quotes at runtime


def present(tree: str) -> bool:
    return (ROOT / MARKERS[tree]).exists()


def needs(*trees: str):
    """Skip the test (or the module, as pytestmark) unless every named private tree is on this machine."""
    gone = [t for t in trees if not present(t)]
    return pytest.mark.skipif(bool(gone), reason=_reason(", ".join(f"{MARKERS[t]}" for t in gone)))


def require(*trees: str) -> None:
    """Skip from inside a fixture or at the top of a module (allow_module_level) when a private tree is absent."""
    gone = [t for t in trees if not present(t)]
    if gone:
        pytest.skip(_reason(", ".join(MARKERS[t] for t in gone)), allow_module_level=True)


def _reason(what: str) -> str:
    return f"needs {what}, which stays on the owner's machine (.gitignore)"


_PATH = re.compile(r"(?:^|[\s'\"(=])((?:[A-Za-z]:)?[^\s'\"()]*?/)?(dataset|model|docs)/([^\s'\"()]+)")


def _absent_tree_of(text: str) -> str | None:
    """The repository-relative path the text names under a private tree that is absent, else None. A relative path
    (dataset/gold/x) or an absolute one inside this repository counts; a folder of that name elsewhere (a tmp_path) not."""
    text = re.sub(r"[\\/]+", "/", text)   # one separator style, and repr's doubled backslashes folded
    root = ROOT.as_posix().lower() + "/"
    for m in _PATH.finditer(text):
        prefix, tree, tail = m.groups()
        if prefix and prefix.lower() != root:
            continue
        rel = f"{tree}/{tail}"
        if rel in PUBLIC or present(tree):
            continue
        return rel
    return None


def skip_if_absent(exc: BaseException | None) -> str | None:
    """The missing private path when the exception (or anything it was raised from) is a file error naming one."""
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, OSError):
            name = getattr(exc, "filename", None)
            hit = _absent_tree_of(str(name)) if name else None
            hit = hit or _absent_tree_of(str(exc))
            if hit:
                return hit
        exc = exc.__cause__ or exc.__context__
    return None
