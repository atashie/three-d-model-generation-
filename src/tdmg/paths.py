"""Repository paths, resolved from this file so they work from any working directory."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RULES_DIR = REPO_ROOT / "rules"
PROFILES_DIR = REPO_ROOT / "profiles"
DOCS_DIR = REPO_ROOT / "docs"
