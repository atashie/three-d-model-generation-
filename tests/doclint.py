"""Small, testable helpers behind tests/test_docs.py.

Kept separate so tests/test_doclint.py can prove each check catches what it claims to.
Known limits: reference-style links ([text][ref]) are not checked, and a backticked token
counts as a rule reference only if its first segment is a namespace the registry uses.
"""

from __future__ import annotations

import re
from pathlib import Path

FENCE = re.compile(r"^(```|~~~)")
COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
INLINE_LINK = re.compile(r"\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
TICKED = re.compile(r"`([a-z0-9_]+(?:\.[a-z0-9_]+)+)`")


def prose_lines(text: str) -> list[str]:
    """Lines outside HTML comments and fenced code blocks."""
    text = COMMENT.sub("", text)
    out, in_fence = [], False
    for line in text.splitlines():
        if FENCE.match(line.strip()):
            in_fence = not in_fence
            continue
        if not in_fence:
            out.append(line)
    return out


def headings(text: str, level: int | None = None) -> list[str]:
    found = []
    for line in prose_lines(text):
        m = HEADING.match(line)
        if m and (level is None or len(m.group(1)) == level):
            found.append(m.group(2))
    return found


def missing_or_out_of_order(text: str, template: list[str]) -> list[str]:
    """Template headings (level 2, matched by prefix) that are absent or out of order."""
    h2 = headings(text, level=2)
    problems, pos = [], 0
    for want in template:
        idx = next((i for i in range(pos, len(h2)) if h2[i].startswith(want)), None)
        if idx is None:
            problems.append(want)
        else:
            pos = idx + 1
    return problems


def rule_refs(text: str, namespaces: set[str]) -> set[str]:
    body = "\n".join(prose_lines(text))
    return {t for t in TICKED.findall(body) if t.split(".")[0] in namespaces}


def slug(heading: str) -> str:
    """GitHub-style anchor for a heading."""
    s = heading.strip().lower()
    s = re.sub(r"[^\w\- ]", "", s)
    return s.replace(" ", "-")


def anchors(text: str) -> set[str]:
    seen: dict[str, int] = {}
    out = set()
    for h in headings(text):
        base = slug(re.sub(r"`", "", h))
        n = seen.get(base, 0)
        out.add(base if n == 0 else f"{base}-{n}")
        seen[base] = n + 1
    return out


def broken_links(page: Path) -> list[str]:
    text = page.read_text(encoding="utf-8")
    broken = []
    for target in INLINE_LINK.findall("\n".join(prose_lines(text))):
        if "://" in target or target.startswith("mailto:"):
            continue
        path_part, _, frag = target.partition("#")
        dest = page if not path_part else (page.parent / path_part.replace("%20", " "))
        if not dest.exists() or frag and dest.suffix == ".md" and frag not in anchors(dest.read_text(encoding="utf-8")):
            broken.append(target)
    return broken
