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

## 4. Documentation Development & Automated Deployment

Documentation is written in Markdown under the `docs/` directory and built with **MkDocs Material** and **`mkdocstrings`**.

### Local Preview (Live Server)
To browse and edit documentation locally with live hot-reloading:

```bash
# Start live reload preview server
lattice-dev docs-serve
# or
./scripts/dev.sh docs-serve
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in your browser. As you edit markdown files in `docs/` or docstrings in `src/lattice_propagator/`, the browser will update automatically.

### Local Static Build
To build the static HTML site locally without running a background server:

```bash
lattice-dev docs-build
# or
./scripts/dev.sh docs-build
```

This compiles all documentation, extracts docstrings, and outputs static HTML into the `site/` folder. You can view it offline by opening `site/index.html` in any web browser.

### Automated Deployment to GitHub Pages
Every release tag (e.g., `v0.1.0`) and merge to the `main` branch automatically triggers the [`.github/workflows/docs.yml`](https://github.com/dougransom/lattice-propagator/blob/main/.github/workflows/docs.yml) workflow:
1. Installs the environment and dev dependencies via `uv`.
2. Executes `mkdocs build --strict` to verify zero broken links or syntax errors.
3. Automatically deploys the site artifact to **GitHub Pages** at [https://dougransom.github.io/lattice-propagator/](https://dougransom.github.io/lattice-propagator/).

---

## 5. Building Distribution Packages

`lattice-propagator` uses [`flit`](https://flit.pypa.io/) as its PEP 517 build backend.

```bash
lattice-dev build
```

This generates `.whl` and `.tar.gz` packages in the `dist/` folder ready for PyPI publication.
