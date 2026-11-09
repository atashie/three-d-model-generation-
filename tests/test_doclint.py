"""Prove the docs checks catch the problems they claim to (negative fixtures)."""

from doclint import anchors, broken_links, missing_or_out_of_order, rule_refs, slug

T = ["What it is", "When to use", "Open gaps"]


def test_template_complete_and_ordered_passes():
    assert missing_or_out_of_order("## What it is\n## When to use / not\n## Open gaps\n", T) == []


def test_headings_inside_html_comments_do_not_count():
    text = "<!--\n## What it is\n## When to use\n## Open gaps\n-->\n"
    assert missing_or_out_of_order(text, T) == T


def test_headings_inside_code_fences_do_not_count():
    text = "```\n## What it is\n## When to use\n## Open gaps\n```\n"
    assert missing_or_out_of_order(text, T) == T


def test_reversed_order_is_caught():
    assert missing_or_out_of_order("## Open gaps\n## When to use\n## What it is\n", T)


def test_rule_ref_typos_are_caught_in_any_registry_namespace():
    refs = rule_refs("see `fdm.typo` and `gate.topology.nope` and `trimesh.creation`", {"fdm", "gate"})
    assert refs == {"fdm.typo", "gate.topology.nope"}


def test_github_slugs():
    assert slug("4. Pipeline stages and the gate contract") == "4-pipeline-stages-and-the-gate-contract"
    assert slug("11. Roadmap") == "11-roadmap"
    assert anchors("# A\n## A\n") == {"a", "a-1"}


def test_missing_anchor_and_titled_links_are_checked(tmp_path):
    (tmp_path / "t.md").write_text("# Real heading\n")
    page = tmp_path / "p.md"
    page.write_text('[ok](t.md#real-heading) [bad](t.md#nope) [titled](missing.md "a title")\n')
    assert broken_links(page) == ["t.md#nope", "missing.md"]
