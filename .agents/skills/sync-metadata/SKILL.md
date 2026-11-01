---
name: sync-metadata
description: >-
  Synchronize codemeta.json and CITATION.cff from pyproject.toml whenever
  the package version, description, authors, or metadata change.
---

# Metadata Synchronization Protocol (`sync-metadata`)

## 1. Purpose & Standards

When developing scientific and academic software, repository metadata must remain synchronized across packaging and citation standards:
- **`pyproject.toml` (PEP 621)**: Authoritative source of truth for name, version, description, authors, and keywords.
- **`CITATION.cff` (Citation File Format 1.2.0)**: Software citation file used by GitHub, Zenodo, and academic publishers to generate bibtex/APA citations.
- **`codemeta.json` (CodeMeta 2.0 / Schema.org)**: JSON-LD machine-readable cross-platform software metadata.

---

## 2. Triggering Scenarios

Activate and run this protocol whenever:
1. The `version = "..."` in `pyproject.toml` is incremented.
2. Package authors, emails, license, or description in `pyproject.toml` are modified.
3. Preparing a release, building packages (`./scripts/dev.sh build`), or running pre-commit verification.

---

## 3. Execution Commands

The unified developer CLI (`lattice-dev`) provides built-in, zero-dependency synchronization using Python's standard library `tomllib` and `json`:

```bash
# 1. Generate / update codemeta.json and CITATION.cff
./scripts/dev.sh metadata
# or:
lattice-dev metadata

# 2. Verify synchronization without modifying files (used by CI and test suites)
./scripts/dev.sh metadata --check
# or:
lattice-dev metadata --check
```

---

## 4. Automatic Build & Verification Integration

- **Automatic on Build**: Whenever `./scripts/dev.sh build` (or `lattice-dev build`) is invoked, `cmd_metadata()` executes automatically before invoking `flit build`, guaranteeing distribution artifacts always match repository citation files.
- **Enforced in Test Suite**: `tests/test_docs_parity.py::test_metadata_files_are_synchronized_with_pyproject` runs on every `./scripts/dev.sh test` / `./scripts/dev.sh check` run, failing immediately if metadata files are missing or version numbers differ.
