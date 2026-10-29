"""The learning documents must not rot: links resolve and drill numbers exist."""

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
# The drill catalog lives under scripts/; import it the way tests/drills does.
for folder in ("demo", "drills"):
    sys.path.insert(0, str(ROOT / "scripts" / folder))

from drill_catalog import CATALOG  # noqa: E402

DOCS = ("docs/aws-map.md", "docs/interview-checklist.md", "docs/demo.md", "docs/failure-drills.md")
LINK = re.compile(r"\]\(([^)\s]+)\)")
REPO_PATH = re.compile(r"`((?:src|docs|scripts|tests)/[^`\s*<>{}]+)`")
DRILL_REFERENCE = re.compile(r"\bDrills? (\d+)\b")


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


@pytest.mark.parametrize("relative", DOCS)
def test_every_relative_link_resolves_to_an_existing_path(relative):
    document = ROOT / relative
    assert document.is_file(), f"{relative} is missing"
    broken = []
    for target in LINK.findall(document.read_text(encoding="utf-8")):
        if re.match(r"^(https?:|mailto:|#)", target):
            continue
        path = target.split("#", 1)[0]
        if not (document.parent / path).resolve().exists():
            broken.append(target)
    assert not broken, f"{relative} has broken links: {broken}"


@pytest.mark.parametrize("relative", ("docs/aws-map.md", "docs/interview-checklist.md"))
def test_repository_paths_named_in_code_spans_exist(relative):
    missing = [p for p in REPO_PATH.findall(_text(relative)) if not (ROOT / p.rstrip("/.,:;")).exists()]
    assert not missing, f"{relative} names paths that do not exist: {missing}"


def test_drill_numbers_in_the_checklist_exist_in_the_catalog():
    known = {drill.number for drill in CATALOG}
    referenced = {int(n) for n in DRILL_REFERENCE.findall(_text("docs/interview-checklist.md"))}
    assert referenced, "the checklist should point at drills"
    assert referenced <= known, f"unknown drills: {sorted(referenced - known)}"
    assert known <= referenced, f"drills never mentioned: {sorted(known - referenced)}"


def test_readme_links_the_learning_assets():
    readme = _text("README.md")
    for target in ("docs/demo.md", "docs/failure-drills.md", "docs/aws-map.md", "docs/interview-checklist.md"):
        assert f"]({target})" in readme, f"README does not link {target}"
