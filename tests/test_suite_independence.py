"""The tests do not depend on the checkout's prints/ (restructure Task 9, after the
re-review): once real prints are finished there (prints/roadie-drop/, prints/roadie/),
the tests that make jobs of those names must still pass.

tests/conftest.py points the default library at an empty temporary folder in every test.
This file checks that, in this process and in a fresh pytest run of the job tests with a
fake checkout whose prints/ holds those names ($TDMG_TEST_FAKE_CHECKOUT).
"""

import os
import subprocess
import sys

import pytest
from conftest import FAKE_CHECKOUT_ENV, REAL_DEFAULT_LIBRARY
from selection_fixtures import roadie_like
from test_job_runner import _invoke, _plain, _png

import tdmg.cli

NAMES = ("roadie-drop", "roadie")
# The test files that make jobs with those names through tdmg job new.
JOB_TESTS = ("tests/test_jobs.py", "tests/test_job_runner.py", "tests/test_job_confirm.py")


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


@pytest.mark.skipif(os.environ.get(FAKE_CHECKOUT_ENV) is not None,
                    reason="already inside the fake-checkout run")
def test_the_job_tests_pass_with_those_prints_in_the_checkout(tmp_path):
    """The job test files, run in a fresh pytest with the fake checkout."""
    root = _fake_checkout(tmp_path / "checkout")
    env = {**os.environ, FAKE_CHECKOUT_ENV: str(root)}
    done = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                           *JOB_TESTS], cwd=tdmg.cli.REPO_ROOT, env=env,
                          capture_output=True, text=True, check=False, timeout=1800)
    tail = done.stdout.strip().splitlines()[-1:] or [done.stderr[-500:]]
    assert done.returncode == 0, "\n".join(done.stdout.splitlines()[-30:])
    assert " passed" in tail[0] and "failed" not in tail[0]
