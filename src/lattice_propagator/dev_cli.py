"""Developer and Build CLI for lattice-propagator.

Provides unified commands for testing, linting, formatting,
documentation serving/building, and package artifact generation.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _run_cmd(cmd: list[str], cwd: Path = REPO_ROOT) -> int:
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


def cmd_build(args: argparse.Namespace) -> int:
    """Build wheel and sdist distribution packages."""
    # Prefer flit build or build module
    dist_dir = REPO_ROOT / "dist"
    dist_dir.mkdir(exist_ok=True)
    cmd = [sys.executable, "-m", "flit", "build"]
    return _run_cmd(cmd)


def cmd_check(args: argparse.Namespace) -> int:
    """Run all verification checks (lint, test, docs-build)."""
    print("\033[1;32m[1/3] Checking linting and formatting...\033[0m")
    args.fix = False
    if cmd_lint(args) != 0:
        return 1

    print("\n\033[1;32m[2/3] Running tests with coverage...\033[0m")
    args.coverage = True
    args.verbose = False
    args.k = None
    args.extra_args = []
    if cmd_test(args) != 0:
        return 1

    print("\n\033[1;32m[3/3] Building documentation (--strict)...\033[0m")
    args.strict = True
    if cmd_docs_build(args) != 0:
        return 1

    print("\n\033[1;32m✔ All checks passed successfully!\033[0m")
    return 0


def main(argv: list[str] | None = None) -> int:
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

    # build
    p_build = subparsers.add_parser("build", help="Build distribution wheel and sdist via flit.")
    p_build.set_defaults(func=cmd_build)

    # check
    p_check = subparsers.add_parser("check", help="Run lint, test, and docs-build in sequence.")
    p_check.set_defaults(func=cmd_check)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
