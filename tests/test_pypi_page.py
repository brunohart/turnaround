"""The PyPI page (`docs/pypi.md`) is read away from the repository, so nothing in it may
be relative, everything it points at in the repo must exist, and its images and links are
pinned to the tag of the version being released. 0.1.0 shipped the GitHub README and
every image on the project page was broken."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import turnaround

ROOT = Path(__file__).resolve().parents[1]
PAGE = (ROOT / "docs/pypi.md").read_text(encoding="utf-8")
PROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
TARGETS = re.findall(r'(?:src="|\]\()([^")\s]+)', PAGE)


def test_nothing_on_the_page_is_relative() -> None:
    assert PROJECT["readme"] == "docs/pypi.md"
    assert TARGETS
    for t in TARGETS:
        assert t.startswith("https://"), f"{t} would break on pypi.org"


def test_everything_it_points_at_in_the_repo_exists_at_this_versions_tag() -> None:
    tag = f"v{PROJECT['version']}"
    assert turnaround.__version__ == PROJECT["version"]
    repo = re.compile(
        r"https://(?:raw\.githubusercontent\.com/brunohart/turnaround/|"
        r"github\.com/brunohart/turnaround/blob/)([^/]+)/(.+)"
    )
    seen = 0
    for t in TARGETS:
        m = repo.match(t)
        if not m:
            continue
        ref, path = m.groups()
        assert ref in (tag, "main"), f"{t} is pinned to {ref}, not {tag}"
        assert (ROOT / path).exists(), f"{path} is not in the repository"
        seen += 1
    assert seen >= 6
