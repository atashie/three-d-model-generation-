"""Docs must agree with code: generated tables current, templates complete, references real."""

import re
import subprocess
import sys

import pytest

from tdmg.paths import DOCS_DIR, REPO_ROOT
from tdmg.rules import load_rules

TEMPLATE_HEADINGS = [
    "## What it is", "## When to use", "## Pipeline specifics", "## Parameters",
    "## Failure modes", "## Required checks", "## Calibration needed", "## Evidence", "## Open gaps",
]
TEMPLATED = sorted((DOCS_DIR / "print-types" / "attributes").glob("*.md")) + sorted(
    (DOCS_DIR / "print-types" / "recipes").glob("*.md"))
RULE_PREFIXES = ("format.", "slicer.", "vectorize.", "fdm.", "flat.", "template.", "relief.", "joint.")
LINK = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")


def test_generated_docs_are_current():
    result = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "gen_docs.py"), "--check"],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


def test_there_are_templated_pages():
    assert TEMPLATED, "expected attribute and recipe pages"


@pytest.mark.parametrize("page", TEMPLATED, ids=lambda p: p.name)
def test_page_has_every_template_heading(page):
    text = page.read_text(encoding="utf-8")
    missing = [h for h in TEMPLATE_HEADINGS if h not in text]
    assert not missing, f"{page.name} is missing {missing}"


def _docs_markdown():
    return sorted(DOCS_DIR.rglob("*.md")) + [REPO_ROOT / "README.md", REPO_ROOT / "CLAUDE.md"]


@pytest.mark.parametrize("page", _docs_markdown(), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_rule_ids_named_in_docs_exist(page):
    rules = load_rules()
    named = {t for t in re.findall(r"`([a-z0-9_.]+)`", page.read_text(encoding="utf-8"))
             if t.startswith(RULE_PREFIXES) and t.count(".") >= 2}
    unknown = sorted(named - set(rules))
    assert not unknown, f"{page.name} names unknown rules {unknown}"


@pytest.mark.parametrize("page", _docs_markdown(), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_relative_links_resolve(page):
    broken = []
    for target in LINK.findall(page.read_text(encoding="utf-8")):
        if "://" in target or target.startswith("mailto:"):
            continue
        if not (page.parent / target.replace("%20", " ")).exists():
            broken.append(target)
    assert not broken, f"{page.relative_to(REPO_ROOT)} has broken links {broken}"
