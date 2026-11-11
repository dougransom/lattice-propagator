# Agent Guidelines: Lattice Propagator

Architecture map, operational rules, and synchronization guardrails for AI coding assistants.

---

## 1. Architecture Map

- **`src/lattice_propagator/lattice.py`**: Join-semilattices of partial information (`Bottom`, `FlatValue`, `GaussianValue`, `IntervalValue`, `DiscreteDomain`, `SetLattice`, `MapLattice`, `Contradiction`, `merge_lattice`).
- **`src/lattice_propagator/primitives.py`**: Reactive `Cell` containers, unification via Union-Find (`cell.unify`), $\pi$-calculus link mobility (`MobileLinkPropagator`), `Propagator` primitives (`Adder`, `Multiplier`, `KalmanEstimator`, `AllDifferent`), and the `PropagatorNetwork` worklist fixed-point engine.
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

### Rule 5: Version & Metadata Parity
Whenever bumping `version` or modifying project metadata in `pyproject.toml`:
- Run `./scripts/dev.sh metadata` (or activate the `sync-metadata` skill) to regenerate `codemeta.json` and `CITATION.cff`.
- Note: `./scripts/dev.sh build` automatically runs metadata synchronization prior to packaging.

### Rule 6: Rich Typography in Examples & Documentation
When writing or adding examples, docstrings, or markdown documentation:
- Prefer rich typography and mathematical Unicode characters over ASCII approximations:
  - Exponents/powers: `c²`, `a² + b²`, `σ²` (in strings, cell names, comments, print statements, and markdown formulas; keep Python variable identifiers ASCII like `c_sq` since superscripts are invalid Python identifier characters).
  - Operations & relations: `×`, `÷`, `−`, `±`, `√`, `≤`, `≥`, `≠`, `≈`, `∈`, `∉`.
  - Lattice operations & states: `⊔` (join), `⊓` (meet), `⊥` (bottom), `⊤` (top/contradiction), `⊑` (refinement / partial order).
  - Logic & arrows: `→`, `⇒`, `⟺`, `∩`, `∪`.
  - Units & symbols: `°C`, `μ`, `σ`.

### Rule 7: Idiomatic Python Collections & Reduction Trees
When designing or implementing collection patterns over cells:
- **Do NOT introduce redundant `map_cells` / element-wise wrappers:** Rely on idiomatic Python list/dict comprehensions combined with `Cell` operator overloading (e.g. `[x * 2 for x in cells]`). `_build_binary_op` / `build_binary_op` already auto-synthesizes intermediate cells and wires multi-directional constraints seamlessly.
- **Prefer tree-structured reductions over linear chains:** Standard `sum(cells)` or `functools.reduce()` creates a degenerate $O(N)$ depth chain of propagators. When aggregating collections of cells, prefer balanced binary reduction trees (`tree_reduce` / `tree_sum`) with $O(\log N)$ propagation depth to minimize worklist queue churn and backward deduction latency.
- **Dynamic/deferred collections:** When a collection of elements is unknown at network construction time (e.g. held inside a cell as a `SetLattice` or list), use `DelayedPropagator` to unroll the sub-network dynamically once the collection is populated.

---

## 3. Standard Developer Commands

```bash
./scripts/dev.sh check        # Full verification (metadata + lint + tests + docs build)
./scripts/dev.sh test         # Run pytest suite (including markdown code blocks & parity tests)
./scripts/dev.sh lint         # Check style with Ruff
./scripts/dev.sh format       # Autoformat code with Ruff
./scripts/dev.sh docs-serve   # Start local MkDocs preview server (http://127.0.0.1:8000)
./scripts/dev.sh docs-build   # Build static documentation site
./scripts/dev.sh metadata     # Generate/sync codemeta.json and CITATION.cff from pyproject.toml
./scripts/dev.sh build        # Sync metadata + build wheel and sdist packages via Flit
```
