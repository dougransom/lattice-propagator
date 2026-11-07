"""Test suite verifying documentation and build-system synchronization parity.

Ensures that:
1. Every public symbol exported in `lattice_propagator.__all__` is documented in `docs/api/`.
2. Every page in `docs/` is wired into `mkdocs.yml` navigation (no orphan documentation).
3. Every path in `mkdocs.yml` points to a real file on disk.
"""

import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

import lattice_propagator

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = REPO_ROOT / "docs"
MKDOCS_FILE = REPO_ROOT / "mkdocs.yml"


def _extract_nav_paths(nav_item: Sequence[Any] | Mapping[str, Any] | str) -> list[str]:
    """Recursively extract all target .md filepaths from mkdocs nav structure."""
    paths = []
    if isinstance(nav_item, str):
        paths.append(nav_item)
    elif isinstance(nav_item, Mapping):
        for value in nav_item.values():
            paths.extend(_extract_nav_paths(value))
    elif isinstance(nav_item, Sequence):
        for item in nav_item:
            paths.extend(_extract_nav_paths(item))
    return paths


def test_all_public_symbols_are_documented_in_api_reference() -> None:
    """Verify that every export in lattice_propagator.__all__ is documented in docs/api/."""
    api_dir = DOCS_DIR / "api"
    assert api_dir.is_dir(), "docs/api directory not found"

    # Collect all member lines across docs/api/*.md
    documented_members: set[str] = set()
    for api_file in api_dir.glob("*.md"):
        content = api_file.read_text(encoding="utf-8")
        matches = re.findall(r"^\s*-\s*([A-Za-z0-9_]+)\s*$", content, flags=re.MULTILINE)
        documented_members.update(matches)

    missing = set(lattice_propagator.__all__) - documented_members
    assert not missing, (
        f"Public symbols in __all__ are missing from docs/api/*.md reference members: {sorted(missing)}. "
        "Update docs/api/ to document all public interfaces."
    )


def test_mkdocs_nav_references_exist_on_disk() -> None:
    """Verify that every navigation path declared in mkdocs.yml points to an existing file."""
    assert MKDOCS_FILE.is_file(), "mkdocs.yml not found"
    config = yaml.safe_load(MKDOCS_FILE.read_text(encoding="utf-8"))
    nav = config.get("nav", [])
    paths = _extract_nav_paths(nav)

    assert paths, "mkdocs.yml nav must not be empty"
    for rel_path in paths:
        target = DOCS_DIR / rel_path
        assert target.is_file(), f"Path '{rel_path}' in mkdocs.yml does not exist on disk: {target}"


def test_no_orphan_markdown_files_in_docs() -> None:
    """Verify that all markdown files under docs/ are registered in mkdocs.yml."""
    config = yaml.safe_load(MKDOCS_FILE.read_text(encoding="utf-8"))
    nav = config.get("nav", [])
    registered_paths = set(_extract_nav_paths(nav))

    # All .md files relative to docs/
    disk_files = {p.relative_to(DOCS_DIR).as_posix() for p in DOCS_DIR.rglob("*.md")}

    orphans = disk_files - registered_paths
    assert not orphans, (
        f"Found orphan markdown files in docs/ that are not listed in mkdocs.yml nav: {sorted(orphans)}. "
        "Register them in mkdocs.yml to ensure they are built and rendered."
    )


def test_metadata_files_are_synchronized_with_pyproject() -> None:
    """Verify that codemeta.json and CITATION.cff exist and match pyproject.toml version."""
    import argparse

    from lattice_propagator.dev_cli import cmd_metadata

    res = cmd_metadata(argparse.Namespace(check=True))
    assert res == 0, (
        "codemeta.json and CITATION.cff are out of sync with pyproject.toml. "
        "Run 'lattice-dev metadata' or './scripts/dev.sh build'."
    )
