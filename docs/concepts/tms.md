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
    Assumption,
    FlatValue,
    TruthMaintenanceSystem,
)

tms = TruthMaintenanceSystem(cell_id="climate_mode")

# Define hypotheses with confidence/priority:
hyp_heat = Assumption("mode_heat", value=FlatValue("heat"), confidence=0.8)
hyp_cool = Assumption("mode_cool", value=FlatValue("cool"), confidence=0.4)
```

---

## 2. Monotonic by Default vs. NetworkTMS

!!! note "Monotonic Core Design"
    The core `PropagatorNetwork` operates **purely monotonically** by default—it never silently deletes or mutates cell history when a contradiction occurs. Instead, a `Contradiction` value propagates forward, signaling conflict.

When non-monotonic belief revision is required:
1. Instantiate a `NetworkTMS`.
2. Assert defeasible hypotheses via `NetworkTMS.assume(...)` or configure heuristic propagators with `Propagator(..., confidence=..., is_assumption=True)`.
3. Every built-in `Propagator` uses `self.emit()` to automatically propagate upstream assumption `support` sets and weakest-link confidence ($\text{confidence} \times \min_i \text{conf}_i$) to downstream cells.
4. If a `Contradiction` ($\top$) is reached on any downstream cell, `NetworkTMS.resolve_contradiction()` traces the transitive `support` set back to the responsible assumptions, records a **Nogood**, and retracts the lowest-confidence assumption to restore consistency.

```python
from lattice_propagator import (
    AdderPropagator,
    Contradiction,
    IntervalValue,
    NetworkTMS,
    PropagatorNetwork,
)

net = PropagatorNetwork("SupportCascade")
ntms = NetworkTMS(net)

a = net.add_cell("a")
b = net.add_cell("b")
c = net.add_cell("c")
for cid in ("a", "b", "c"):
    ntms.get_or_create_cell_tms(cid)

# Assert a defeasible assumption on 'a' (conf=0.6) and a ground fact on 'b'
ntms.assume("a", "solar_forecast_high", IntervalValue(20.0, 22.0), confidence=0.6)
b.set_value(IntervalValue(5.0, 5.0), source="base_load")

# AdderPropagator automatically propagates 'solar_forecast_high' support & confidence to 'c'
net.add_propagator(AdderPropagator("sum_ab", a, b, c, confidence=0.9))
net.run()
assert c.tms.premises["sum_ab"].is_assumption is True
assert c.tms.premises["sum_ab"].confidence == 0.54

# Hard safety cap on 'c' triggers a contradiction, resolved by retracting 'solar_forecast_high'
c.set_value(IntervalValue(10.0, 20.0), source="breaker_limit")
assert isinstance(c.value, Contradiction)
retracted = ntms.resolve_contradiction(c.tms.active_sources)
assert retracted == "solar_forecast_high"
assert c.value == IntervalValue(10.0, 20.0)
```

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

---

## 4. Explanations & Localization (i18n)

TMS explanations decouple causal provenance from text rendering. Explanations can be retrieved as formatted strings or as structured `ExplanationNode` trees:

```python
from lattice_propagator import GaussianValue, TruthMaintenanceSystem, make_template_translator

tms = TruthMaintenanceSystem(cell_id="living_room_temp", unit="°C")
tms.assert_evidence("sensor.thermostat", GaussianValue(mean=21.2, variance=0.1))

# 1. Structured AST Node (suitable for Home Assistant entity attributes or JSON APIs)
node = tms.explain_node()
data = node.to_dict()
assert data["key"] == "tms.gaussian_fusion"

# 2. Translated / localized rendering via template dictionary
fr_translator = make_template_translator(
    {
        "tms.gaussian_fusion": "Combinaison de {sources} pour obtenir {mean:.1f}{unit} (±{spread:.2f}{unit}).{degraded_note}"
    }
)
translated = tms.explain(translator=fr_translator)
assert "Combinaison" in translated
```
