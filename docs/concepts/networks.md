# Reactive Cells & Propagator Networks

Propagator networks compute by reaching a **fixed point** across interconnected reactive cells.

---

## 1. The `Cell`

A `Cell` is the communication channel and memory unit of a propagator network:

- It holds a single `LatticeValue` (initially `Bottom`).
- When `set_value(new_val)` is called, the cell merges `new_val` with its existing content.
- If the merged value represents a strict information gain ($x_{\text{old}} \sqsubset x_{\text{new}}$), all connected propagators are enqueued for execution.
- If the merged value is identical to what the cell already knows, no propagators are triggered (**idempotence preventing infinite loops**).

```python
from lattice_propagator import Cell, FlatValue

temp_cell = Cell("living_room_temp")
print(temp_cell.value)  # ⊥(Bottom)

temp_cell.set_value(FlatValue(21.5))
print(temp_cell.value)  # Flat(21.5)
```

### Cell Unification (`cell_a.unify(cell_b)`)

In complex constraint networks, intermediate computations may produce two cells that are discovered to refer to the exact same physical quantity. 

`Cell.unify()` binds two cells together using a Disjoint Set Union (DSU / Union-Find) algorithm:
- Their values are merged.
- Their neighbor propagator lists are unified.
- Subsequent updates to either cell notify all connected propagators across both original cells.

---

## 2. Propagators

A `Propagator` is an autonomous computational unit. It:
1. Observes a set of input cells.
2. When triggered, examines their values.
3. Computes deductions.
4. Writes results to one or more output cells.

### Built-in Primitives

| Propagator | Description | Multi-directional? |
| :--- | :--- | :---: |
| `AdderPropagator(a, b, c)` | Enforces $a + b = c$ ($c = a + b, a = c - b, b = c - a$) | Yes |
| `MultiplierPropagator(a, b, c)` | Enforces $a \times b = c$ with zero-absorption and division | Yes |
| `SwitchPropagator(control, input, output, trigger)` | Routes `input` to `output` when `control == trigger` | Forward |
| `ConditionalPropagator(pred, cons, alt, out)` | Multiplexer with Sussman-Radul consensus optimization | Forward |
| `RatePropagator(source, rate, dt)` | First-order velocity/derivative estimation | Forward |
| `LagPropagator(input, output, tau, dt)` | First-order exponential lag filter (thermal inertia) | Forward |
| `KalmanEstimatorPropagator(...)` | Fuses noisy linear dynamics with noisy measurements ([Case study](../examples/sensor_fusion.md#why-a-propagator-instead-of-a-python-function)) | Dynamic |
| `DempsterShaferPropagator(...)` | Fuses multi-source evidential mass functions over subset lattices | Evidential |
| `AllDifferentPropagator(cells)` | Pairwise exclusion and hidden-single deduction | Multi |

!!! tip "Propagators vs. Functions"
    For a concrete case study comparing reactive lattice propagators against classical procedural Python functions (e.g. in Kalman filtering), see [Why a Propagator Instead of a Python Function?](../examples/sensor_fusion.md#why-a-propagator-instead-of-a-python-function).

---

## 3. The `PropagatorNetwork` Worklist Engine

The `PropagatorNetwork` manages an asynchronous worklist:

```python
from lattice_propagator import PropagatorNetwork

network = PropagatorNetwork()

# Attach cells/propagators to this network...
# Run until all cells reach equilibrium (quiescence):
network.run()
```

- When a cell updates, its observing propagators are queued.
- `network.run()` drains the queue iteratively until quiescence (no more cells change).
- Because all merge operations on join-semilattices are monotonic, the network is guaranteed to arrive at the **least fixed point** regardless of scheduling order.
