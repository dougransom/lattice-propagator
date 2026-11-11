# Starter Recipes

## 1. Multi-Source Interval Fusion (No `if/else` Arbitration)

```python
from lattice_propagator import IntervalValue, PropagatorNetwork

net = PropagatorNetwork("ThermalEnvelope")
target = net.add_cell("target")
target.set_value(IntervalValue(16.0, 28.0), source="safety")
target.set_value(IntervalValue(20.0, 24.0), source="comfort")
target.set_value(IntervalValue(21.5, 25.0), source="solar_gain")
# Automatically intersects to [21.500, 24.000]
```

## 2. Multi-Directional Formula

```python
from lattice_propagator import PropagatorNetwork

net = PropagatorNetwork("OhmsLaw")
net.v = net.i * net.r
net.v = 12.0
net.r = 4.0
net.run()
assert net.i.val == 3.0
```

## 3. CLP(Z) Constraint Propagation + Labeling

```python
from lattice_propagator import ChoiceEngine, PropagatorNetwork, add_int_rel, int_cells

net = PropagatorNetwork("MapColouring")
wa, nt, sa = int_cells(net, ["WA", "NT", "SA"], lo=1, hi=3)
for a, b in ((wa, nt), (wa, sa), (nt, sa)):
    add_int_rel(net, a, "#\\=", b)

solutions = ChoiceEngine(net, variables=[wa, nt, sa]).all_solutions()
assert len(solutions) == 6
```

## 4. Defeasible Assumptions & Contradiction Resolution (`NetworkTMS`)

```python
from lattice_propagator import AdderPropagator, IntervalValue, NetworkTMS, PropagatorNetwork

net = PropagatorNetwork("Budget")
ntms = NetworkTMS(net)
a, b, total = net.add_cell("a"), net.add_cell("b"), net.add_cell("total")
for cid in ("a", "b", "total"):
    ntms.get_or_create_cell_tms(cid)

ntms.assume("a", "forecast", IntervalValue(20.0, 22.0), confidence=0.6)
b.set_value(IntervalValue(5.0, 5.0), source="base_load")
net.add_propagator(AdderPropagator("sum", a, b, total))
net.run()

total.set_value(IntervalValue(10.0, 20.0), source="hard_cap")
retracted = ntms.resolve_contradiction(total.tms.active_sources)
assert retracted == "forecast"
```

