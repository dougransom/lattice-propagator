#!/usr/bin/env bash
# Quick-wrapper for developer tasks in lattice-propagator.
# Usage:
#   ./scripts/dev.sh test
#   ./scripts/dev.sh lint
#   ./scripts/dev.sh format
#   ./scripts/dev.sh docs-serve
#   ./scripts/dev.sh docs-build
#   ./scripts/dev.sh metadata
#   ./scripts/dev.sh build
#   ./scripts/dev.sh check

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

if command -v uv >/dev/null 2>&1; then
    exec uv run lattice-dev "$@"
elif [ -f "${REPO_ROOT}/.venv/bin/lattice-dev" ]; then
    exec "${REPO_ROOT}/.venv/bin/lattice-dev" "$@"
else
    echo "Error: Neither 'uv' nor '.venv/bin/lattice-dev' was found." >&2
    echo "Run: uv pip install -e '.[all]'" >&2
    exit 1
fi
