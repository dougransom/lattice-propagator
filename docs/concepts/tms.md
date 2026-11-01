# Truth Maintenance & Backtracking

When solving complex constraint satisfaction problems, exploring speculative hypotheses, or diagnosing contradictory sensor readings, a system must know **why** a belief is held and how to resolve contradictions.

`lattice-propagator` provides two levels of Truth Maintenance:
1. **Cell-Level TMS**: Records justifications and dependency antecedents for every merged value.
2. **NetworkTMS (Optional / Opt-in)**: Coordinates defeasible **Assumptions** and resolves contradictions via **Dependency-Directed Backtracking (DDB)**.

---

## 1. Premises vs. Assumptions

- **Premise**: An indisputable fact (e.g., a physical constant or ground truth sensor reading). It cannot be retracted during contradiction resolution.
- **Assumption**: A defeasible hypothesis made during speculative exploration (e.g., "Assume switch 1 is ON" or "Assume square (3,4) is 7").

```python
from lattice_propagator import (
    Cell,
    PropagatorNetwork,
    FlatValue,
    Assumption,
    Premise,
    TruthMaintenanceSystem,
)

tms = TruthMaintenanceSystem()

# Define hypotheses with confidence/priority:
hyp_heat = Assumption("mode_heat", confidence=0.8)
hyp_cool = Assumption("mode_cool", confidence=0.4)
```

---

## 2. Monotonic by Default vs. NetworkTMS

!!! note "Monotonic Core Design"
    The core `PropagatorNetwork` operates **purely monotonically** by default—it never silently deletes or mutates cell history when a contradiction occurs. Instead, a `Contradiction` value propagates forward, signaling conflict.

When non-monotonic belief revision is required:
1. Instantiate a `NetworkTMS`.
2. Wrap defeasible assertions in `Assumption` objects.
3. If a `Contradiction` is reached, `NetworkTMS` traces the dependency provenance back to the set of responsible assumptions, creates a **Nogood** record, and retracts the lowest-confidence assumption to restore consistency.

---

## 3. ChoiceEngine & Speculative Search

For combinatorial search (such as constraint satisfaction problems, Sudoku, or scheduling):

```python
from lattice_propagator import ChoiceEngine, PropagatorNetwork

network = PropagatorNetwork()
engine = ChoiceEngine(network)

# Speculatively branches on candidate values, uses Minimum Remaining Values (MRV)
# heuristics, and backtracks upon contradiction until a valid assignment is found.
```
