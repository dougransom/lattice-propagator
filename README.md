# Lattice Propagator

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![CI](https://github.com/dougransom/lattice-propagator/actions/workflows/ci.yml/badge.svg)](https://github.com/dougransom/lattice-propagator/actions/workflows/ci.yml)
[![Python: 3.11+](https://img.shields.io/badge/Python-3.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue)](https://www.python.org/)
[![Zero Runtime Dependencies](https://img.shields.io/badge/dependencies-0%20runtime-success)](pyproject.toml)
[![PEP 561: py.typed](https://img.shields.io/badge/PEP%20561-py.typed-blue)](src/lattice_propagator/py.typed)

**Lattice Propagator** is a pure Python implementation of the **propagator computational paradigm** over partial-information join-semilattices with integrated Truth Maintenance Systems (TMS).

Pioneered by Gerald Jay Sussman and Alexey Radul at MIT, propagator networks replace traditional directional computation (y = f(x)) with autonomous, multi-directional constraint networks operating monotonically over partial information.

Originally developed for sensor fusion, thermal dynamics, and fuzzy control in [Home Assistant](https://www.home-assistant.io), this library is completely standalone with **zero runtime dependencies**.

---

## 1. Theoretical Foundations & Citations

1. **Radul, A., & Sussman, G. J. (2009)**. *"The Art of the Propagator"*. MIT Computer Science and Artificial Intelligence Laboratory Technical Report, MIT-CSAIL-TR-2009-002. [DSpace MIT](https://dspace.mit.edu/handle/1721.1/44215).
2. **Radul, A. (2009)**. *"Propagation Networks: A Flexible and Expressive Substrate for Computation"*. Doctoral Dissertation, Massachusetts Institute of Technology. [DSpace MIT](https://dspace.mit.edu/handle/1721.1/54635).
3. **Hanson, C., & Sussman, G. J. (2021)**. *"Software Design for Flexibility: How to Avoid Programming Yourself into a Corner"*. MIT Press. (Chapters 6 & 7: Layered Data, Truth Maintenance, and Propagators). [PDF](https://draugus.github.io/pdf/Software%20Design%20for%20Flexibility%20-%20Chris%20Hanson.pdf).
4. **Sussman, G. J., & Steele, G. L. (1980)**. *"CONSTRAINTS—A Language for Higher-Order Almost-Hierarchical Networks"*. Artificial Intelligence, 14(1), 1-39.

---

## 2. Core Concepts

### A. The Information Semilattice
Information within a Cell is structured as a join-semilattice (L, <=, merge), ensuring that merging partial evidence is associative, commutative, and idempotent:
- **Bottom**: Complete ignorance / offline / missing measurement.
- **FlatValue(val)**: Exact scalar constants and states (`bool`, `str`, `int`, `enum`).
- **GaussianValue(mean, variance)**: Statistical sensor fusion with variance weighting.
- **IntervalValue(min, max)**: Bounding intervals and constraint envelopes (supports `+`, `-`, `*`, `/`).
- **SetLattice(elements)**: Monotonically accumulating set lattice under set union.
- **MapLattice(mapping)**: Monotonically merging key-value map lattice with recursive value joins.
- **CircularInterval(min, max)**: Periodic domains (e.g., wind bearing 0-360 deg).
- **DiscreteDomain(allowed)**: Finite domain constraint sets.
- **Contradiction**: Mutually exclusive assertions with full TMS conflict attribution.

### B. Reactive Cells & Propagators
- **Cell**: Reactive container holding an information lattice value. Notifies connected propagators whenever merged information strictly refines existing content.
  * Supports natural operator overloading (`+`, `-`, `*`, `/`) to build bidirectional constraint networks declaratively.
  * Supports cell unification (`cell_a.unify(cell_b)`) via Disjoint Set Union (DSU / Union-Find).
- **Propagator**: Autonomous operator linking input cells to output cells.
- **PropagatorNetwork**: Asynchronous worklist engine computing least fixed points.
- **ChoiceEngine**: Interleaved constraint propagation and search with speculative branching, MRV variable selection, and backtracking.

### C. Primitive Operators
- **AdderPropagator**: Multidirectional constraint box enforcing $a + b = c$ ($c = a + b, a = c - b, b = c - a$).
- **MultiplierPropagator**: Multidirectional constraint box enforcing $a \times b = c$ with zero-absorption and division.
- **SwitchPropagator**: Conditional gate routing data when a control cell matches an active state.
- **ConditionalPropagator**: Multiplexer (if-then-else) with Sussman-Radul consensus optimization when branches agree.
- **FunctionalPropagator** / **lift_propagator**: Higher-order functional propagator lifting any pure function over lattice values.
- **ArithmeticPropagator**: Linear combinations, differences, and multidirectional power balances.
- **RatePropagator**: Derivative/velocity estimation and time-to-threshold intervals.
- **LagPropagator**: First-order dynamic lag (RC thermal inertia / exponential decay).
- **KalmanEstimatorPropagator**: Real-time state estimation fusing noisy sensors and linear dynamics.
- **ThresholdPropagator**: Bounded comparisons with hysteresis.
- **BoundedLinearPropagator**: Constraint modulation within acceptable intervals based on driving signals.
- **AllDifferentPropagator**: Non-overlapping constraint deduction with hidden single elimination (e.g. Sudoku).

### D. Truth Maintenance & Belief Revision (TMS / DDB)
- **TruthMaintenanceSystem**: Cell-level justifications and support-set provenance tracking.
- **NetworkTMS (Optional / Opt-in)**: Network-level belief revision with Dependency-Directed Backtracking (DDB).
  * The core `PropagatorNetwork` operates **purely monotonically** by default—it never automatically retracts information on contradiction.
  * When explicitly opted into, `NetworkTMS` coordinates defeasible **Assumptions** with priority/confidence scores and records **Nogood** sets to resolve speculative contradictions.

---

## 3. Development & Documentation

All developer tasks (testing, linting, building docs, packaging) are managed via the unified CLI `lattice-dev` (or the `./scripts/dev.sh` wrapper):

```bash
# 1. Install editable package with all dev & documentation tools
uv pip install -e ".[all]"

# 2. Run test suite with coverage
lattice-dev test --cov

# 3. Serve interactive documentation locally (hot-reload at http://127.0.0.1:8000)
lattice-dev docs-serve

# 4. Build static HTML documentation
lattice-dev docs-build

# 5. Build distribution packages (.whl, .tar.gz)
lattice-dev build

# 6. Run full verification pipeline (lint + test + docs-build)
lattice-dev check
```

For detailed contributor guides, see [DEVELOPMENT.md](DEVELOPMENT.md) and [CONTRIBUTING.md](CONTRIBUTING.md).

---

## 4. Home Assistant Core Import Compliance (`REQ-HAC`)

`lattice-propagator` is engineered to satisfy all architectural and packaging requirements for direct importation into Home Assistant Core integrations:

| Requirement | Standard | Status | Verified By |
| :--- | :--- | :---: | :--- |
| **Zero Event-Loop Blocking** | Pure in-memory computation; zero synchronous disk, subprocess, or network I/O | :white_check_mark: Compliant | Unit test suite & memory audits |
| **Zero Runtime Dependencies** | `dependencies = []` in `pyproject.toml` (standard library only) | :white_check_mark: Compliant | `./scripts/dev.sh check` |
| **PEP 561 Type Completeness** | Strict type annotations with `src/lattice_propagator/py.typed` marker | :white_check_mark: Compliant | `ruff check` & `dev_cli.py` gate |
| **Stateless Re-entrancy** | Zero mutable module globals; multi-coordinator network isolation | :white_check_mark: Compliant | Integration test suite |
| **Immutable Values** | Thread-safe, hashable lattice values (`frozen=True` or tuples) | :white_check_mark: Compliant | Data structure assertions |
| **OSI Permissive License** | MIT License (compatible with Home Assistant Apache-2.0 core) | :white_check_mark: Compliant | `LICENSE` file |
| **Universal Pure-Python Wheel** | Built via PEP 517/518 (`flit_core`) producing `py3-none-any.whl` | :white_check_mark: Compliant | `flit build` & GitHub Actions |
| **Active Python Matrix** | Compatibility across Python 3.11, 3.12, 3.13, and 3.14 | :white_check_mark: Compliant | GitHub Actions CI matrix |

For formal specifications, see [docs/requirements.md (Section 5: REQ-HAC)](docs/requirements.md#5-home-assistant-core-import-compliance-req-hac).

---

## 5. License
MIT License. Copyright (c) Doug Ransom.
