# Agent Guidelines: Lattice Propagator

Architecture map, operational rules, and synchronization guardrails for AI coding assistants.

---

## 1. Architecture Map

- **`src/lattice_propagator/lattice.py`**: Join-semilattices of partial information (`Bottom`, `FlatValue`, `GaussianValue`, `IntervalValue`, `DiscreteDomain`, `SetLattice`, `MapLattice`, `Contradiction`, `merge_lattice`).
- **`src/lattice_propagator/primitives.py`**: Reactive `Cell` containers, unification via Union-Find (`cell.unify`), `Propagator` primitives (`Adder`, `Multiplier`, `KalmanEstimator`, `AllDifferent`), and the `PropagatorNetwork` worklist fixed-point engine.
- **`src/lattice_propagator/tms.py`**: Truth Maintenance System (`Premise`, defeasible `Assumption`, `Justification`, `TruthMaintenanceSystem`, `NetworkTMS` dependency-directed backtracking).
- **`docs/`**: MkDocs documentation website (guides, examples, and `mkdocstrings` API references).
- **`scripts/dev.sh` / `src/lattice_propagator/dev_cli.py`**: Unified developer CLI (`lattice-dev`).

---

## 2. Invariant Rules & Guardrails

### Rule 1: Interface-to-Docs & Example Synchronization
Whenever modifying or adding public classes, constructors, methods, or signatures in `src/lattice_propagator/`:
1. Update docstrings using **Google style** so `mkdocstrings` extracts clean documentation.
2. Update the corresponding API reference page in `docs/api/*.md`.
3. Update relevant examples in `docs/examples/*.md`.
4. If adding new pages, register them in `mkdocs.yml` under `nav:` to satisfy `tests/test_docs_parity.py`.

### Rule 2: Mandatory Verification Gate
Before completing any task, **always execute `./scripts/dev.sh check`** (or `lattice-dev check`).
- Runs Ruff linter and formatting checks.
- Runs pytest covering unit tests AND **executing all 20+ markdown documentation snippets** via `pytest-markdown-docs`.
- Runs `tests/test_docs_parity.py` to ensure zero undocumented symbols or orphan pages.
- Runs `mkdocs build --strict` to verify no broken links or syntax errors.

### Rule 3: Dependency Addition Policy (Guideline)
Strong preference for zero runtime dependencies.
- **Requirement**: **Do NOT add any new dependencies (runtime or dev) to `pyproject.toml` without explicit human confirmation and approval.**
- Always seek to implement functionality using Python 3.11+ standard library features.

### Rule 4: Algebraic Monotonicity
All lattice merge operations ($\sqcup$) must preserve join-semilattice algebraic laws:
- Associativity: $(x \sqcup y) \sqcup z = x \sqcup (y \sqcup z)$
- Commutativity: $x \sqcup y = y \sqcup x$
- Idempotence: $x \sqcup x = x$
- Monotonic refinement: values may only gain information; never silently mutate or retract values without explicit `NetworkTMS` backtracking.

---

## 3. Standard Developer Commands

```bash
./scripts/dev.sh check        # Full verification (lint + tests + doc execution + strict docs build)
./scripts/dev.sh test         # Run pytest suite (including markdown code blocks)
./scripts/dev.sh lint         # Check style with Ruff
./scripts/dev.sh format       # Autoformat code with Ruff
./scripts/dev.sh docs-serve   # Start local MkDocs preview server (http://127.0.0.1:8000)
./scripts/dev.sh docs-build   # Build static documentation site
./scripts/dev.sh build        # Build wheel and sdist packages via Flit
```
