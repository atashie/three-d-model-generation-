"""Where the registries live.

From a source checkout (including `uv sync`'s editable install), the YAML files are read
from the repo's `rules/` and `profiles/` folders, so edits take effect at once. From an
installed wheel, they are read from the copies packaged inside it (`tdmg/_data/`).
`REPO_ROOT` is only meaningful in a checkout; it is used by docs tooling and tests.
"""

from importlib.resources import files
from pathlib import Path

_PACKAGE_DIR = Path(__file__).resolve().parent
_CHECKOUT_ROOT = _PACKAGE_DIR.parents[1]  # src/tdmg -> repo root, in a checkout


def _in_checkout() -> bool:
    return (_CHECKOUT_ROOT / "pyproject.toml").is_file() and (_CHECKOUT_ROOT / "rules").is_dir()


if _in_checkout():
    REPO_ROOT = _CHECKOUT_ROOT
    RULES_DIR = REPO_ROOT / "rules"
    PROFILES_DIR = REPO_ROOT / "profiles"
else:
    _data = Path(str(files("tdmg") / "_data"))
    REPO_ROOT = None
    RULES_DIR = _data / "rules"
    PROFILES_DIR = _data / "profiles"

DOCS_DIR = REPO_ROOT / "docs" if REPO_ROOT else None
