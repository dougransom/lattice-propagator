"""Developer and Build CLI for lattice-propagator.

Provides unified commands for testing, linting, formatting,
documentation serving/building, and package artifact generation.
"""

from __future__ import annotations

import argparse
import datetime
import json
import subprocess
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _run_cmd(cmd: Sequence[str], cwd: Path = REPO_ROOT) -> int:
    """Run a subprocess command within the repo root and stream output."""
    cmd_str = " ".join(cmd)
    print(f"\033[1;34m==>\033[0m \033[1m{cmd_str}\033[0m")
    try:
        proc = subprocess.run(cmd, cwd=cwd, check=False)
        return proc.returncode
    except FileNotFoundError as err:
        print(
            f"\033[1;31mError:\033[0m Command not found: {err.filename}. Are dependencies installed?",
            file=sys.stderr,
        )
        return 1


def cmd_test(args: argparse.Namespace) -> int:
    """Run test suite via pytest with optional coverage."""
    cmd = [sys.executable, "-m", "pytest"]
    if args.coverage:
        cmd.extend(["--cov=lattice_propagator", "--cov-report=term-missing"])
    if args.verbose:
        cmd.append("-v")
    if args.k:
        cmd.extend(["-k", args.k])
    if args.extra_args:
        cmd.extend(args.extra_args)
    return _run_cmd(cmd)


def cmd_lint(args: argparse.Namespace) -> int:
    """Run code linter and formatting checks via ruff."""
    fix_flag = ["--fix"] if args.fix else []
    rc = _run_cmd([sys.executable, "-m", "ruff", "check", "."] + fix_flag)
    if rc != 0:
        return rc
    format_flags = [] if args.fix else ["--check"]
    return _run_cmd([sys.executable, "-m", "ruff", "format", "."] + format_flags)


def cmd_format(args: argparse.Namespace) -> int:
    """Format and autofix code via ruff."""
    args.fix = True
    return cmd_lint(args)


def cmd_docs_serve(args: argparse.Namespace) -> int:
    """Start local MkDocs development server with hot-reloading."""
    cmd = [
        sys.executable,
        "-m",
        "mkdocs",
        "serve",
        "-a",
        f"{args.host}:{args.port}",
    ]
    return _run_cmd(cmd)


def cmd_docs_build(args: argparse.Namespace) -> int:
    """Build static documentation site using MkDocs."""
    cmd = [sys.executable, "-m", "mkdocs", "build"]
    if args.strict:
        cmd.append("--strict")
    return _run_cmd(cmd)


def generate_metadata_contents(repo_root: Path = REPO_ROOT) -> tuple[str, str]:
    """Extract metadata from pyproject.toml and produce (codemeta.json, CITATION.cff)."""
    pyproject_file = repo_root / "pyproject.toml"
    with open(pyproject_file, "rb") as f:
        pyproject = tomllib.load(f)

    project = pyproject.get("project", {})
    name = project.get("name", "lattice-propagator")
    version = project.get("version", "0.0.1")
    description = project.get("description", "")
    license_str = project.get("license", {}).get("text", "MIT")
    keywords = project.get("keywords", [])
    raw_authors = project.get("authors", [])

    authors_cff: list[dict[str, str]] = []
    authors_codemeta: list[dict[str, str]] = []
    for a in raw_authors:
        author_name = a.get("name", "")
        email = a.get("email", "")
        parts = author_name.strip().rsplit(" ", 1)
        given = parts[0] if parts else ""
        family = parts[1] if len(parts) > 1 else ""

        cff_entry: dict[str, str] = {}
        if family:
            cff_entry["family-names"] = family
        if given:
            cff_entry["given-names"] = given
        if email:
            cff_entry["email"] = email
        authors_cff.append(cff_entry)

        codemeta_entry: dict[str, str] = {
            "@type": "Person",
            "givenName": given,
            "familyName": family,
        }
        if email:
            codemeta_entry["email"] = email
        authors_codemeta.append(codemeta_entry)

    # 1. codemeta.json
    codemeta_dict = {
        "@context": "https://doi.org/10.5063/schema/codemeta-2.0",
        "@type": "SoftwareSourceCode",
        "identifier": name,
        "name": name,
        "version": version,
        "description": description,
        "license": f"https://spdx.org/licenses/{license_str}",
        "codeRepository": "https://github.com/dougransom/lattice-propagator",
        "programmingLanguage": "Python",
        "runtimePlatform": "Python 3.11+",
        "author": authors_codemeta,
        "keywords": keywords,
        "citation": [
            "https://dspace.mit.edu/handle/1721.1/44215",
            "https://dspace.mit.edu/handle/1721.1/54635",
        ],
    }
    codemeta_content = json.dumps(codemeta_dict, indent=2) + "\n"

    # 2. CITATION.cff
    today = datetime.date.today().isoformat()
    lines = [
        "cff-version: 1.2.0",
        'message: "If you use this software, please cite it as below."',
        f'title: "{name}"',
        f'version: "{version}"',
        f'date-released: "{today}"',
        f'abstract: "{description}"',
        'repository-code: "https://github.com/dougransom/lattice-propagator"',
        f'license: "{license_str}"',
        "authors:",
    ]
    for a in authors_cff:
        lines.append(f'  - family-names: "{a.get("family-names", "")}"')
        lines.append(f'    given-names: "{a.get("given-names", "")}"')
        if "email" in a:
            lines.append(f'    email: "{a["email"]}"')
    if keywords:
        lines.append("keywords:")
        for kw in keywords:
            lines.append(f'  - "{kw}"')
    lines.extend(
        [
            "references:",
            "  - type: report",
            "    authors:",
            '      - family-names: "Radul"',
            '        given-names: "Alexey"',
            '      - family-names: "Sussman"',
            '        given-names: "Gerald Jay"',
            '    title: "The Art of the Propagator"',
            "    institution:",
            '      name: "MIT CSAIL"',
            "    year: 2009",
            '    url: "https://dspace.mit.edu/handle/1721.1/44215"',
        ]
    )
    citation_content = "\n".join(lines) + "\n"

    return codemeta_content, citation_content


def cmd_metadata(args: argparse.Namespace) -> int:
    """Generate or verify codemeta.json and CITATION.cff from pyproject.toml."""
    codemeta_path = REPO_ROOT / "codemeta.json"
    citation_path = REPO_ROOT / "CITATION.cff"
    codemeta_content, citation_content = generate_metadata_contents(REPO_ROOT)

    if getattr(args, "check", False):
        if not codemeta_path.is_file() or not citation_path.is_file():
            print(
                "\033[1;31mError:\033[0m codemeta.json or CITATION.cff is missing. Run 'lattice-dev metadata' to generate.",
                file=sys.stderr,
            )
            return 1

        # Check version match
        existing_cm = json.loads(codemeta_path.read_text(encoding="utf-8"))
        expected_cm = json.loads(codemeta_content)
        if existing_cm.get("version") != expected_cm.get("version"):
            print(
                f"\033[1;31mError:\033[0m codemeta.json version ({existing_cm.get('version')}) "
                f"does not match pyproject.toml ({expected_cm.get('version')}). Run 'lattice-dev metadata'.",
                file=sys.stderr,
            )
            return 1

        existing_cff = citation_path.read_text(encoding="utf-8")
        if f'version: "{expected_cm.get("version")}"' not in existing_cff:
            print(
                "\033[1;31mError:\033[0m CITATION.cff version does not match pyproject.toml. Run 'lattice-dev metadata'.",
                file=sys.stderr,
            )
            return 1
        print(
            "\033[1;32m✔ codemeta.json and CITATION.cff are synchronized with pyproject.toml.\033[0m"
        )
        return 0

    # Write files
    codemeta_path.write_text(codemeta_content, encoding="utf-8")
    citation_path.write_text(citation_content, encoding="utf-8")
    print("\033[1;32m✔ Generated codemeta.json and CITATION.cff from pyproject.toml.\033[0m")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    """Build wheel and sdist distribution packages after synchronizing metadata."""
    # Synchronize codemeta.json and CITATION.cff
    meta_args = argparse.Namespace(check=False)
    if cmd_metadata(meta_args) != 0:
        return 1

    dist_dir = REPO_ROOT / "dist"
    dist_dir.mkdir(exist_ok=True)
    cmd = [sys.executable, "-m", "flit", "build"]
    return _run_cmd(cmd)


def cmd_schematics(args: argparse.Namespace) -> int:
    """Generate circuit schematic SVGs for documentation using schemdraw."""
    from .schematics import main as schematics_main

    extra = args.extra_args if hasattr(args, "extra_args") else []
    return schematics_main(extra)


def check_hac_compliance(repo_root: Path = REPO_ROOT) -> int:
    """Verify Home Assistant Core import compliance rules (REQ-HAC)."""
    errors = []
    pyproject_file = repo_root / "pyproject.toml"
    with open(pyproject_file, "rb") as f:
        pyproject = tomllib.load(f)

    # 1. Zero runtime dependencies
    deps = pyproject.get("project", {}).get("dependencies", None)
    if deps != []:
        errors.append(f"REQ-HAC-2 violation: 'dependencies' must be empty ([]), got: {deps}")

    # 2. PEP 561 py.typed marker
    py_typed = repo_root / "src" / "lattice_propagator" / "py.typed"
    if not py_typed.is_file():
        errors.append(f"REQ-HAC-3 violation: Missing PEP 561 marker file: {py_typed}")

    # 3. License
    license_text = pyproject.get("project", {}).get("license", {}).get("text", "")
    if license_text != "MIT":
        errors.append(f"REQ-HAC-6 violation: License must be 'MIT', got: {license_text}")

    if errors:
        for err in errors:
            print(f"\033[1;31m✖ {err}\033[0m")
        return 1

    print("\033[1;32m✔ Home Assistant Core import compliance (REQ-HAC) verified:\033[0m")
    print("  • Zero runtime dependencies: dependencies = []")
    print("  • PEP 561 type marker: src/lattice_propagator/py.typed present")
    print("  • License: MIT")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    """Run all verification checks (HAC compliance, metadata, lint, test, docs-build)."""
    print("\033[1;32m[1/5] Checking Home Assistant Core import compliance (REQ-HAC)...\033[0m")
    if check_hac_compliance() != 0:
        return 1

    print(
        "\n\033[1;32m[2/5] Checking metadata synchronization (codemeta.json & CITATION.cff)...\033[0m"
    )
    meta_args = argparse.Namespace(check=True)
    if cmd_metadata(meta_args) != 0:
        return 1

    print("\n\033[1;32m[3/5] Checking linting and formatting...\033[0m")
    args.fix = False
    if cmd_lint(args) != 0:
        return 1

    print("\n\033[1;32m[4/5] Running tests with coverage...\033[0m")
    args.coverage = True
    args.verbose = False
    args.k = None
    args.extra_args = []
    if cmd_test(args) != 0:
        return 1

    print("\n\033[1;32m[5/5] Building documentation (--strict)...\033[0m")
    args.strict = True
    if cmd_docs_build(args) != 0:
        return 1

    print("\n\033[1;32m✔ All checks passed successfully!\033[0m")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Parse CLI arguments and dispatch commands."""
    parser = argparse.ArgumentParser(
        prog="lattice-dev",
        description="Unified development, testing, and documentation CLI for lattice-propagator.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # test
    p_test = subparsers.add_parser("test", help="Run pytest suite.")
    p_test.add_argument(
        "--cov", dest="coverage", action="store_true", help="Enable test coverage report."
    )
    p_test.add_argument("-v", "--verbose", action="store_true", help="Verbose pytest output.")
    p_test.add_argument("-k", type=str, help="Filter tests by expression.")
    p_test.add_argument("extra_args", nargs="*", help="Extra arguments passed directly to pytest.")
    p_test.set_defaults(func=cmd_test)

    # lint
    p_lint = subparsers.add_parser("lint", help="Check code style and formatting with ruff.")
    p_lint.add_argument(
        "--fix", action="store_true", help="Automatically apply linter and format fixes."
    )
    p_lint.set_defaults(func=cmd_lint)

    # format
    p_format = subparsers.add_parser("format", help="Autoformat and fix code with ruff.")
    p_format.set_defaults(func=cmd_format)

    # docs-serve
    p_dserve = subparsers.add_parser(
        "docs-serve", help="Serve MkDocs documentation locally with live reload."
    )
    p_dserve.add_argument("--host", default="127.0.0.1", help="Host address (default: 127.0.0.1).")
    p_dserve.add_argument("--port", default=8000, type=int, help="Port (default: 8000).")
    p_dserve.set_defaults(func=cmd_docs_serve)

    # docs-build
    p_dbuild = subparsers.add_parser(
        "docs-build", help="Build static documentation into site/ directory."
    )
    p_dbuild.add_argument(
        "--strict", action="store_true", default=True, help="Treat warnings as errors."
    )
    p_dbuild.add_argument("--no-strict", dest="strict", action="store_false")
    p_dbuild.set_defaults(func=cmd_docs_build)

    # metadata
    p_meta = subparsers.add_parser(
        "metadata", help="Generate or verify codemeta.json and CITATION.cff from pyproject.toml."
    )
    p_meta.add_argument(
        "--check",
        action="store_true",
        help="Verify metadata files match pyproject.toml without writing.",
    )
    p_meta.set_defaults(func=cmd_metadata)

    # build
    p_build = subparsers.add_parser("build", help="Build distribution wheel and sdist via flit.")
    p_build.set_defaults(func=cmd_build)

    # check
    p_check = subparsers.add_parser("check", help="Run lint, test, and docs-build in sequence.")
    p_check.set_defaults(func=cmd_check)

    # schematics
    p_schem = subparsers.add_parser(
        "schematics", help="Generate circuit schematics with schemdraw."
    )
    p_schem.add_argument("extra_args", nargs="*", help="Extra arguments passed to schematics CLI.")
    p_schem.set_defaults(func=cmd_schematics)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
