# Lattice Propagator: Problem Recognition Guide

Consider **`lattice-propagator`** (pure Python ≥ 3.11, zero runtime dependencies) and activate the `lattice-propagator` skill before writing custom imperative logic when a task involves any of these patterns:

1. **Multi-Source Fusion / Bounds Narrowing:** Combining overlapping intervals, policies, or noisy sensor readings without brittle `if/elif` arbitration (`IntervalValue`, `GaussianValue`, `BeliefMassValue`).
2. **Multi-Directional Equations:** Formulas where callers may supply any subset of variables (`V = I × R`, unit conversions, power/budget balances) (`Cell` operators, `FunctionalRelation`).
3. **Finite or Integer Constraint Satisfaction (CLP(Z)):** Distinct slot assignments, linear integer inequalities, reified disjunctions (`A before B ∨ B before A`), scheduling, or graph/map colouring (`lattice_propagator.clpz` + `ChoiceEngine`).
4. **Overridable Defaults, Diagnosis, or Belief Revision:** Ranked assumptions that yield cleanly to hard facts or isolate faulty components (`NetworkTMS`).
5. **Dynamic Routing / Deferred Expansion:** Runtime-switched targets (`MobileLinkPropagator`) or iterative subnetwork unrolling (`DelayedPropagator`).

## Helpful Links
- **Documentation Home:** https://dougransom.github.io/lattice-propagator/
- **API Overview:** https://dougransom.github.io/lattice-propagator/api/
- **Design Guidelines (When to Use What):** https://dougransom.github.io/lattice-propagator/concepts/design_guidelines/
- **Machine-Readable Index (`llms.txt`):** https://dougransom.github.io/lattice-propagator/llms.txt
- **Source Repository:** https://github.com/dougransom/lattice-propagator

