"""Docs must agree with code: generated tables current, templates complete, references real."""

import subprocess
import sys

import pytest
from doclint import broken_links, missing_or_out_of_order, rule_refs

from tdmg.paths import DOCS_DIR, REPO_ROOT
from tdmg.rules import load_rules

TEMPLATE_HEADINGS = [
    "What it is", "When to use", "Pipeline specifics", "Parameters",
    "Failure modes", "Required checks", "Calibration needed", "Evidence", "Open gaps",
]
TEMPLATED = sorted((DOCS_DIR / "print-types" / "attributes").glob("*.md")) + sorted(
    (DOCS_DIR / "print-types" / "recipes").glob("*.md"))
RULES = load_rules()
NAMESPACES = {rid.split(".")[0] for rid in RULES}


def _docs_markdown():
    return sorted(DOCS_DIR.rglob("*.md")) + [REPO_ROOT / "README.md", REPO_ROOT / "CLAUDE.md"]


def test_generated_docs_are_current():
    result = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "gen_docs.py"), "--check"],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


def test_there_are_templated_pages():
    assert TEMPLATED, "expected attribute and recipe pages"


@pytest.mark.parametrize("page", TEMPLATED, ids=lambda p: p.name)
def test_page_has_every_template_heading_in_order(page):
    problems = missing_or_out_of_order(page.read_text(encoding="utf-8"), TEMPLATE_HEADINGS)
    assert not problems, f"{page.name}: missing or out of order: {problems}"


@pytest.mark.parametrize("page", _docs_markdown(), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_rule_ids_named_in_docs_exist(page):
    unknown = sorted(rule_refs(page.read_text(encoding="utf-8"), NAMESPACES) - set(RULES))
    assert not unknown, f"{page.name} names unknown rules {unknown}"


@pytest.mark.parametrize("page", _docs_markdown(), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_links_and_anchors_resolve(page):
    broken = broken_links(page)
    assert not broken, f"{page.relative_to(REPO_ROOT)} has broken links {broken}"
