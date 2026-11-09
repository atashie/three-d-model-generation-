from typer.testing import CliRunner

from tdmg import __version__
from tdmg.cli import app

runner = CliRunner()


def test_version():
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0 and __version__ in result.output


def test_rules_lists_every_rule():
    from tdmg.rules import load_rules

    result = runner.invoke(app, ["rules"])
    assert result.exit_code == 0
    for rule_id in load_rules():
        assert rule_id in result.output


def test_recipes_and_printers():
    assert "R1" in runner.invoke(app, ["recipes"]).output
    out = runner.invoke(app, ["printers"]).output
    assert "bambu-a1" in out and "up to 4 filaments" in out
