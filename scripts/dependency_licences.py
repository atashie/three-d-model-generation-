"""Print version and declared licence of each direct dependency, read from installed metadata.

    uv run python scripts/dependency_licences.py

Used to keep docs/reference/dependencies.md honest. Declared metadata can be incomplete
(for example it does not show licences of bundled native libraries), so the register adds
notes by hand where the metadata is not the whole story.
"""

import re
import tomllib
from importlib import metadata

from tdmg.paths import REPO_ROOT


def direct_requirements() -> list[str]:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    reqs = list(data["project"]["dependencies"])
    for extra in data["project"].get("optional-dependencies", {}).values():
        reqs += extra
    reqs += data.get("dependency-groups", {}).get("dev", [])
    reqs += ["cadquery-ocp-novtk"]  # transitive via build123d; carries the OpenCASCADE kernel
    return [re.split(r"[\s;<>=\[]", r, maxsplit=1)[0] for r in reqs]


def declared_licence(md: metadata.PackageMetadata) -> str:
    expr = md.get("License-Expression")
    if expr:
        return expr
    classifiers = [c.split(" :: ")[-1] for c in md.get_all("Classifier") or [] if c.startswith("License ::")]
    if classifiers:
        return "; ".join(classifiers)
    lic = (md.get("License") or "").strip().splitlines()
    return lic[0][:60] if lic else "not declared"


for name in direct_requirements():
    try:
        md = metadata.metadata(name)
        print(f"{name:26s} {md['Version']:14s} {declared_licence(md)}")
    except metadata.PackageNotFoundError:
        print(f"{name:26s} {'(not installed)':14s}")
