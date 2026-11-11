# API Reference Overview

The `lattice_propagator` API reference documents all public classes, functions, and lattice types across the library.

---

## Dual-Audience Architecture: Humans & Machines

The files in `docs/api/` serve a deliberate dual purpose:

1. **For Humans (The Documentation Website):**
   These pages use the `mkdocstrings` plugin. When MkDocs builds the website, it dynamically extracts Google-style docstrings, type annotations, signatures, parameters, and source code disclosures directly from the Python source code to produce full, interactive reference documentation.
2. **For AI Agents & LLMs:**
   In the raw repository source, these markdown files act as concise, token-efficient **symbol manifests**. They declare which public interfaces belong to which module without cluttering context windows with duplicate code implementations.

---

## Module Index

| Module | Description | Key Interfaces |
| :--- | :--- | :--- |
| **[`api/lattice.md`](lattice.md)** | Information semilattices and monotonic merge operations | `LatticeValue`, `Bottom`, `FlatValue`, `IntervalValue`, `GaussianValue`, `DiscreteDomain`, `IntegerDomain`, `SetLattice`, `MapLattice`, `Contradiction` |
| **[`api/primitives.md`](primitives.md)** | Reactive containers and constraint operators | `Cell`, `Propagator`, `PropagatorNetwork`, `AdderPropagator`, `MultiplierPropagator`, `SwitchPropagator`, `MobileLinkPropagator`, `lift_propagator`, `FunctionalRelation` |
| **[`api/boolean.md`](boolean.md)** | Multi-directional boolean logic gates & CNF constraints | `AndPropagator`, `OrPropagator`, `NotPropagator`, `XorPropagator`, `ClausePropagator` |
| **[`api/clpz.md`](clpz.md)** | CLP(Z) unbounded integer constraints ($\mathbb{Z} \cup \{-\infty, +\infty\}$) & reification | `IntRelationPropagator`, `IntLinearPropagator`, `IntMulPropagator`, `IntAbsPropagator`, `ReifiedIntRelationPropagator`, `IntAllDifferentPropagator` |
| **[`api/nonlinear.md`](nonlinear.md)** | Non-linear arithmetic and transcendental constraints | `PowerPropagator`, `SqrtPropagator`, `ExpPropagator`, `LogPropagator` |
| **[`api/terms.md`](terms.md)** | First-order terms and unification constraints | `TermValue`, `PairPropagator`, `UnifyPropagator` |
| **[`api/degenerate.md`](degenerate.md)** | Redundant multi-sensor estimation and fault isolation | `DegeneratePipeline`, `DegenerateBranch` |
| **[`api/tms.md`](tms.md)** | Truth Maintenance Systems & Dependency-Directed Backtracking | `TruthMaintenanceSystem`, `NetworkTMS`, `Premise`, `Assumption`, `Justification` |
| **[`api/graph.md`](graph.md)** | Graph analysis, cycle detection, and explanation walkers | `NetworkGraph`, `detect_cycles`, `walk_downstream`, `walk_upstream` |

