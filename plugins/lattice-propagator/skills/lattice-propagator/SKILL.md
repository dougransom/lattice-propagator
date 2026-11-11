---
name: lattice-propagator
description: >-
  Model and solve constraint satisfaction, CLP(Z) integer/finite-domain puzzles,
  bidirectional formulas, interval or Gaussian sensor fusion, scheduling,
  and truth-maintenance belief revision in Python using the zero-dependency
  lattice-propagator library. Activate whenever a problem involves multi-source
  evidence merging, multi-directional equations, combinatorial search/labeling,
  fault diagnosis, or Home Assistant / asyncio policy envelopes.
---

# Lattice Propagator Skill

`lattice-propagator` implements **monotonic constraint networks over partial-information lattices** with optional **chronological search (`ChoiceEngine`)** and **dependency-directed backtracking (`NetworkTMS`)**. It requires Python ≥ 3.11 and has **zero runtime dependencies** (`py.typed` included).

## 1. Environment Check

Verify availability in the active Python environment before importing:

```bash
python -c "import lattice_propagator; print(lattice_propagator.__file__)"
```

If missing, install cleanly (`uv add lattice-propagator` or `pip install lattice-propagator`).

## 2. Choose the Right Lattice & Pattern

| Problem Shape | Lattice / Primitive | Execution Model |
| :--- | :--- | :--- |
| Overlapping min/max envelopes or policies | `IntervalValue(lo, hi)` | `net.run()` (multiple writers to one `Cell`) |
| Noisy Gaussian sensor fusion | `GaussianValue(mean, variance)` | `net.run()` (precision-weighted join) |
| Multi-directional arithmetic / formulas | `Cell` (`+`, `-`, `*`, `/`, `**`) or `FunctionalRelation` | `net.run()` |
| One-way black-box Python callables | `lift_propagator` / `FunctionalPropagator` | `net.run()` |
| Finite discrete domains / uniqueness | `DiscreteDomain` + `AllDifferentPropagator` / `AllDistinctPropagator` | `net.run()` → `ChoiceEngine` |
| Unbounded integer constraints (Prolog CLP(Z)) | `IntegerDomain` + `int_cells`, `add_int_linear`, `add_int_rel`, `add_int_reified` | `net.run()` → `ChoiceEngine` |
| Ranked defaults, fault isolation, nogoods | `NetworkTMS` (`assume`, `resolve_contradiction`, `retract`) | `net.run()` + TMS |
| Runtime-switched targets / deferred loops | `MobileLinkPropagator` / `DelayedPropagator` | `net.run()` |

## 3. Constraint Propagation + Labeling (`ChoiceEngine`)

When monotonic propagation reaches quiescence with undetermined discrete or integer cells remaining, use `ChoiceEngine` (analogous to Prolog's `labeling([ff], Vars)`):
- `engine.first_solution()` → `bool` (populates `network.cells` with the first solution).
- `engine.iter_solutions()` → lazy generator yielding `{cell_id: LatticeValue}` snapshots.
- `engine.all_solutions(limit=...)` → list of solution snapshots (always pass `limit` for unbounded/large domains).

## 4. Essential Guardrails

- **No `if/else` sensor arbitration:** Let independent estimators write into the **same `Cell`**; the lattice join (`⊔`) fuses them automatically.
- **Avoid linear `sum(cells)` chains:** Use `tree_sum(cells, network=net)` / `tree_reduce(...)` for $O(\log N)$ propagation depth.
- **Element-wise transforms:** Use Python comprehensions (`[x * 2 for x in cells]`) rather than custom `map` wrappers.
- **`asyncio` hybrid boundary:** Keep `net.run()` synchronous; batch async I/O before `net.run()` and `await` outputs afterward. Offload heavy `ChoiceEngine` runs via `asyncio.to_thread(...)`.
- **CLP(Z) types:** Never pass Python `bool` where an `int` is expected in `clpz` helpers (`isinstance(True, int)` is rejected explicitly).
- **Visual debugging:** Call `net.generate_mermaid()` or `net.generate_dot()` to inspect topologies and contradictions.

## 5. References & Documentation Links

- Local references in this skill:
  - [CLP(Z) / Prolog Translation Map](./references/clpz_prolog_map.md)
  - [Starter Recipes](./references/recipes.md)
- Hosted & Repository Documentation:
  - **Getting Started:** https://dougransom.github.io/lattice-propagator/getting_started/ (`docs/getting_started.md`)
  - **API Reference Overview:** https://dougransom.github.io/lattice-propagator/api/ (`docs/api/index.md`)
  - **Design Guidelines (When to Use What):** https://dougransom.github.io/lattice-propagator/concepts/design_guidelines/ (`docs/concepts/design_guidelines.md`)
  - **Truth Maintenance (`NetworkTMS`):** https://dougransom.github.io/lattice-propagator/concepts/tms/ (`docs/concepts/tms.md`)
  - **Examples:** [Map Colouring](https://dougransom.github.io/lattice-propagator/examples/map_colouring/), [CLP(Z) Integers](https://dougransom.github.io/lattice-propagator/examples/clpz_integers/), [Sudoku](https://dougransom.github.io/lattice-propagator/examples/sudoku/), [N-Queens](https://dougransom.github.io/lattice-propagator/examples/n_queens/), [Circuit Diagnosis](https://dougransom.github.io/lattice-propagator/examples/circuit_diagnosis/)

