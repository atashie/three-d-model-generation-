"""The tests do not depend on the checkout's prints/ (restructure Task 9, after the
re-review): once real prints are finished there (prints/roadie-drop/, prints/roadie/),
the tests that make jobs of those names must still pass.

tests/conftest.py points the default library at an empty temporary folder in every test.
This file checks that a checkout whose prints/ holds those names does not change what
tdmg job new does in a test.
"""

from conftest import REAL_DEFAULT_LIBRARY
from selection_fixtures import roadie_like
from test_job_runner import _invoke, _plain, _png

import tdmg.cli

NAMES = ("roadie-drop", "roadie")


def _fake_checkout(root):
    for name in NAMES:
        (root / "prints" / name).mkdir(parents=True)
        (root / "prints" / name / "COMPLETE").write_bytes(b"{}\n")
    return root


def test_a_checkout_holding_those_prints_does_not_change_a_test(tmp_path, monkeypatch):
    root = _fake_checkout(tmp_path / "checkout")
    monkeypatch.setattr(tdmg.cli, "REPO_ROOT", root)
    # The real default would refuse these names now ...
    assert REAL_DEFAULT_LIBRARY() == root / "prints"
    # ... but the tests' default library is the empty temporary one.
    assert tdmg.cli.default_library() != root / "prints"
    image = _png(tmp_path / "in" / "roadie.png", roadie_like())
    for name in NAMES:
        r = _invoke("job", "new", name, "--class", "flat-icon", "--image", image,
                    "--jobs-dir", tmp_path / "jobs")
        assert r.exit_code == 0, _plain(r.output)
