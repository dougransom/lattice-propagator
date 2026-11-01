# Developer Guide

This guide covers setting up a local development environment, running tests, checking code quality, building the documentation site, and packaging releases for `lattice-propagator`.

---

## 1. Prerequisites & Environment Setup

`lattice-propagator` requires **Python 3.11+**. We recommend using [`uv`](https://github.com/astral-sh/uv) for fast and deterministic environment management.

```bash
# Clone the repository
git clone https://github.com/dougransom/lattice-propagator.git
cd lattice-propagator

# Create virtual environment and install all dependencies (dev, docs, build)
uv venv
uv pip install -e ".[all]"
```

Once installed, the unified development CLI command **`lattice-dev`** is directly available in your environment, or you can use the wrapper script `./scripts/dev.sh`.

---

## 2. The Unified Developer CLI (`lattice-dev`)

To prevent repetitive shell commands, all development workflows are unified behind `lattice-dev` (registered in `pyproject.toml`):

| Task | Command | Description |
| :--- | :--- | :--- |
| **All Checks (CI)** | `lattice-dev check` | Runs linting, test suite with coverage, and builds docs in `--strict` mode. |
| **Run Tests** | `lattice-dev test` | Runs `pytest`. Supports `--cov` for coverage report. |
| **Filter Tests** | `lattice-dev test -k "sudoku"` | Runs tests matching keyword expression. |
| **Lint & Check** | `lattice-dev lint` | Runs `ruff check` and `ruff format --check`. |
| **Autoformat** | `lattice-dev format` | Automatically fixes style violations and formats code via `ruff`. |
| **Live Docs Server** | `lattice-dev docs-serve` | Starts local MkDocs server with hot reload at `http://127.0.0.1:8000`. |
| **Build Docs** | `lattice-dev docs-build` | Builds static HTML documentation into `site/`. |
| **Package Distribution** | `lattice-dev build` | Builds wheel and source tarball into `dist/` via `flit`. |

!!! tip "Using `./scripts/dev.sh`"
    If you haven't activated your virtualenv, you can use the repository wrapper:
    ```bash
    ./scripts/dev.sh check
    ./scripts/dev.sh docs-serve
    ```

---

## 3. Running Tests

Run the full test suite with coverage:

```bash
lattice-dev test --cov
```

---

## 4. Documentation Development

Documentation is written in Markdown under the `docs/` directory and built with **MkDocs Material** and **`mkdocstrings`**:

```bash
# Start live reload preview server
lattice-dev docs-serve
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in your browser. As you edit markdown files in `docs/` or docstrings in `src/lattice_propagator/`, the page will reload automatically.

To test building production static assets (verifying broken links and docstring formatting):

```bash
lattice-dev docs-build
```

---

## 5. Building Distribution Packages

`lattice-propagator` uses [`flit`](https://flit.pypa.io/) as its PEP 517 build backend.

```bash
lattice-dev build
```

This generates `.whl` and `.tar.gz` packages in the `dist/` folder ready for PyPI publication.
