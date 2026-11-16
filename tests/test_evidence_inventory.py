"""scripts/evidence_inventory.py, on a small temporary tree (not the repo)."""

import evidence_inventory as ei  # scripts/ is on the pytest pythonpath (pyproject.toml)

V = "research/verification"
NOTES = "research_notes/Image to printable 3D model landscape"

TREE = {
    # records
    f"{V}/2026-01-01-cited-by-rule/README.md": "Measured.\n",
    f"{V}/2026-01-02-cited-by-profile/README.md": "Pinned.\n",
    f"{V}/2026-01-03-cited-by-test/results.txt": "rows\n",
    f"{V}/2026-01-04-doc-only/README.md": (
        "See [me](README.md) and research/verification/2026-01-04-doc-only/x.txt.\n"),
    f"{V}/2026-01-05-nothing/README.md": "Alone.\n",
    f"{V}/2026-01-06-wrapped-name/README.md": "Wrapped.\n",
    "research/reviews/2026-01-01-review/README.md": (
        "Reviewed [the plan](../../../docs/plans/2026-01-01-plan.md).\n"),
    "docs/plans/2026-01-01-plan.md": "A plan.\n",
    "docs/plans/2026-01-02-unused.md": "Unused.\n",
    "reports/Image to printable 3D model landscape.md": "Report.\n",
    f"{NOTES}/fdm.md": "Notes.\n",
    # referrers
    "rules/fdm.yaml": (
        "rules:\n"
        f"  - ref: \"{NOTES}/fdm.md\"\n"
        f"  - ref: {V}/2026-01-01-cited-by-rule/README.md\n"),
    "profiles/slicers/x.yaml": f"record: {V}/2026-01-02-cited-by-profile/README.md\n",
    "tests/test_x.py": (
        'RECORD = ROOT / "research" / "verification" / "2026-01-03-cited-by-test"\n'
        'BASE = ROOT / "research" / "verification"\n'
        "# a wrapped mention (research/verification/2026-01-06-wrapped-\n"
        "# name/README.md) still counts\n"),
    "src/tdmg/strip.py": 'SOURCE = "docs/plans/2026-01-01-plan.md"\n',
    "docs/guide/page.md": (
        "Read [the record](../../research/verification/2026-01-04-doc-only/README.md),\n"
        "[the report](../../reports/Image%20to%20printable%203D%20model%20landscape.md),\n"
        "a Windows path research\\verification\\2026-01-04-doc-only\\README.md,\n"
        "a missing one research/verification/2026-09-09-gone/README.md,\n"
        "and the roots research/ and docs/plans/.\n"
        "Two links: [a](../../research/verification/2026-01-01-cited-by-rule/README.md) and "
        "[b](../../research/verification/2026-01-02-cited-by-profile/README.md).\n"),
    "docs/STATUS.md": ("Next: [plan](plans/2026-01-01-plan.md).\n"
                       "Reviews: `research/reviews/2026-01-07-*`.\n"),
    # reviews cited by name only
    "research/reviews/2026-01-05-alpha/README.md": "Alpha.\n",
    "research/reviews/2026-01-07-beta/README.md": "Beta.\n",
    "research/reviews/2026-01-07-gamma/README.md": "Gamma.\n",
    "src/tdmg/named.py": (
        "# Codex review 7, finding 1: fixed.\n"
        "# fixed after the (Codex review\n"
        "# 2026-01-05, finding 2).\n"
        "# Codex review 2026-01-07, finding 1.\n"
        "# Codex finding 4: no date, no number.\n"
        "# The Codex review's cases (research/reviews/2026-01-07-beta/README.md).\n"),
    # a name citation in a doc does not decide anything, so it is not scanned
    "docs/guide/names.md": "Codex review 2026-01-05 said so.\n",
    "CLAUDE.md": "Reviews live in `research/reviews/`.\n",
}


def _scan(tmp_path, extra=None):
    tree = {**TREE, **(extra or {})}
    for rel, text in tree.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
    return ei.scan(tmp_path, sorted(tree), aliases={"7": "research/reviews/2026-01-07-beta"})


def _refs(inv, unit):
    return sorted((r.file, r.line, r.category) for r in inv.refs[unit])


def test_finds_a_yaml_ref(tmp_path):
    inv = _scan(tmp_path)
    assert ("rules/fdm.yaml", 3, "rule") in _refs(inv, f"{V}/2026-01-01-cited-by-rule")


def test_two_relative_links_on_one_line_resolve_separately(tmp_path):
    inv = _scan(tmp_path)
    assert ("docs/guide/page.md", 6, "doc") in _refs(inv, f"{V}/2026-01-01-cited-by-rule")
    assert ("docs/guide/page.md", 6, "doc") in _refs(inv, f"{V}/2026-01-02-cited-by-profile")
    assert not [u for u in inv.unresolved if u.line == 6]


def test_finds_a_ref_with_spaces_in_the_name(tmp_path):
    inv = _scan(tmp_path)
    assert _refs(inv, NOTES) == [("rules/fdm.yaml", 2, "rule")]


def test_finds_a_profile_record(tmp_path):
    inv = _scan(tmp_path)
    assert ("profiles/slicers/x.yaml", 1, "profile") in _refs(
        inv, f"{V}/2026-01-02-cited-by-profile")


def test_finds_a_python_constructed_path_and_a_string_constant(tmp_path):
    inv = _scan(tmp_path)
    assert _refs(inv, f"{V}/2026-01-03-cited-by-test") == [("tests/test_x.py", 1, "test")]
    assert ("src/tdmg/strip.py", 1, "code") in _refs(inv, "docs/plans/2026-01-01-plan.md")


def test_a_constructed_path_that_stops_at_a_root_is_unresolved(tmp_path):
    inv = _scan(tmp_path)
    assert [(u.file, u.line) for u in inv.unresolved if u.reason.startswith("constructed")] == [
        ("tests/test_x.py", 2)]


def test_a_path_wrapped_onto_the_next_line_is_joined(tmp_path):
    inv = _scan(tmp_path)
    assert _refs(inv, f"{V}/2026-01-06-wrapped-name") == [("tests/test_x.py", 3, "test")]


def test_finds_markdown_links_relative_encoded_and_windows_paths(tmp_path):
    inv = _scan(tmp_path)
    assert _refs(inv, f"{V}/2026-01-04-doc-only") == [
        ("docs/guide/page.md", 1, "doc"), ("docs/guide/page.md", 3, "doc")]
    assert _refs(inv, "reports/Image to printable 3D model landscape.md") == [
        ("docs/guide/page.md", 2, "doc")]
    assert ("docs/STATUS.md", 1, "status") in _refs(inv, "docs/plans/2026-01-01-plan.md")
    assert ("research/reviews/2026-01-01-review/README.md", 1, "record") in _refs(
        inv, "docs/plans/2026-01-01-plan.md")


def test_self_references_do_not_count(tmp_path):
    inv = _scan(tmp_path)
    files = {r.file for r in inv.refs[f"{V}/2026-01-04-doc-only"]}
    assert f"{V}/2026-01-04-doc-only/README.md" not in files


def test_roots_and_missing_records(tmp_path):
    inv = _scan(tmp_path)
    assert sorted((r.file, r.line) for r in inv.root_refs["research"]) == [
        ("docs/guide/page.md", 5)]
    assert sorted((r.file, r.line) for r in inv.root_refs["docs/plans"]) == [
        ("docs/guide/page.md", 5)]
    assert [(r.file, r.line) for r in inv.root_refs["research/reviews"]] == [("CLAUDE.md", 1)]
    missing = [(u.file, u.line, u.text) for u in inv.unresolved if u.reason.startswith("names")]
    assert missing == [("docs/guide/page.md", 4, f"{V}/2026-09-09-gone/README.md")]


def test_status_of_each_unit(tmp_path):
    status = {u: ei.status(u, _scan(tmp_path)) for u in ei.units_in(sorted(TREE))}
    assert status[f"{V}/2026-01-01-cited-by-rule"] == "cited"
    assert status[f"{V}/2026-01-02-cited-by-profile"] == "cited"
    assert status[f"{V}/2026-01-03-cited-by-test"] == "cited"
    assert status[f"{V}/2026-01-04-doc-only"] == "uncited"
    assert status[f"{V}/2026-01-05-nothing"] == "uncited, no references"
    assert status["docs/plans/2026-01-01-plan.md"] == "cited"
    assert status["docs/plans/2026-01-02-unused.md"] == "uncited, no references"
    assert status["research/reviews/2026-01-01-review"] == "uncited, no references"


def _how(inv, unit):
    return sorted((r.file, r.line, r.how) for r in inv.refs[unit])


def test_a_numbered_review_name_maps_through_the_alias_table(tmp_path):
    inv = _scan(tmp_path)
    assert ("src/tdmg/named.py", 1, "name") in _how(inv, "research/reviews/2026-01-07-beta")


def test_a_dated_review_name_maps_to_the_one_folder_of_that_date(tmp_path):
    inv = _scan(tmp_path)
    # broken over two lines; the doc's mention of the same date is not scanned
    assert _how(inv, "research/reviews/2026-01-05-alpha") == [("src/tdmg/named.py", 2, "name")]


def test_a_date_shared_by_two_folders_is_ambiguous_not_guessed(tmp_path):
    inv = _scan(tmp_path)
    assert ("src/tdmg/named.py", 4, "ambiguous name") in _how(
        inv, "research/reviews/2026-01-07-beta")
    assert ("src/tdmg/named.py", 4, "ambiguous name") in _how(
        inv, "research/reviews/2026-01-07-gamma")
    assert [(a.file, a.line, a.candidates) for a in inv.ambiguous] == [
        ("src/tdmg/named.py", 4, ("research/reviews/2026-01-07-beta",
                                  "research/reviews/2026-01-07-gamma"))]


def test_a_review_mention_with_no_date_or_number_is_listed(tmp_path):
    inv = _scan(tmp_path)
    assert [(u.file, u.line) for u in inv.unattributed] == [("src/tdmg/named.py", 5)]


def test_a_date_inside_a_path_is_not_a_name_citation(tmp_path):
    inv = _scan(tmp_path)
    assert ("src/tdmg/named.py", 6, "path") in _how(inv, "research/reviews/2026-01-07-beta")
    assert ("src/tdmg/named.py", 6, "ambiguous name") not in _how(
        inv, "research/reviews/2026-01-07-gamma")


def test_a_glob_is_expanded_to_the_records_it_matches(tmp_path):
    inv = _scan(tmp_path)
    for unit in ("research/reviews/2026-01-07-beta", "research/reviews/2026-01-07-gamma"):
        assert ("docs/STATUS.md", 2, "glob") in _how(inv, unit)
    assert not [u for u in inv.unresolved if u.file == "docs/STATUS.md"]


def test_name_citations_give_their_own_statuses(tmp_path):
    inv = _scan(tmp_path)
    assert ei.status("research/reviews/2026-01-05-alpha", inv) == "cited by name"
    assert ei.status("research/reviews/2026-01-07-beta", inv) == "cited"   # line 6, by path
    assert ei.status("research/reviews/2026-01-07-gamma", inv) == "possibly cited (ambiguous name)"
    assert all(ei.counts_as_cited(s) for s in ("cited", "cited by name",
                                               "possibly cited (ambiguous name)"))
    assert not ei.counts_as_cited("uncited")


def test_linked_from_docs(tmp_path):
    inv = _scan(tmp_path)
    assert ei.linked_from_docs(f"{V}/2026-01-04-doc-only", inv) == "doc"
    assert ei.linked_from_docs("docs/plans/2026-01-01-plan.md", inv) == "status"
    assert ei.linked_from_docs(f"{V}/2026-01-05-nothing", inv) == ""


def test_every_alias_is_justified_by_text_in_the_repo():
    root = ei.Path(ei.__file__).resolve().parents[1]
    for number, (unit, ref, locator) in ei.NAME_ALIASES.items():
        assert (root / unit).is_dir(), number
        text = " ".join((root / ref).read_text(encoding="utf-8").split())
        assert " ".join(locator.split()) in text, (number, ref, locator)


def test_binary_files_are_skipped_and_undecodable_files_reported(tmp_path):
    inv = _scan(tmp_path, {"research/verification/2026-01-05-nothing/img.png": b"\x89PNG\x00\x01",
                           "docs/latin1.md": "caf\xe9 research/".encode("latin-1")})
    assert inv.undecodable == ["docs/latin1.md"]
    assert "research/verification/2026-01-05-nothing/img.png" not in inv.undecodable


def test_render_is_deterministic_and_lists_both_groups(tmp_path):
    inv = _scan(tmp_path)
    text = ei.render(inv, ei.units_in(sorted(TREE)))
    assert text == ei.render(_scan(tmp_path), ei.units_in(sorted(TREE)))
    assert text.startswith("<!-- GENERATED by scripts/evidence_inventory.py")
    assert "kept in place (design section 6)" in text
    assert f"`{V}/2026-01-05-nothing`" in text
