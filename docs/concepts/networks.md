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

`Cell.unify()` permanently binds two cells together using a Disjoint Set Union (DSU / Union-Find) algorithm:
- Their values are merged ($v_a \sqcup v_b$).
- Their neighbor propagator lists are unified.
- Subsequent updates to either cell notify all connected propagators across both original cells.

---

## 2. Static vs. Dynamic Network Topology ($\pi$-Calculus Mobility)

Classical dataflow and propagator networks have a **static graph topology**: wires are fixed before execution begins. However, real-world systems often require **dynamic topology** where connections between cells change at runtime.

`lattice-propagator` provides three distinct topological mechanisms depending on whether a connection is permanent, gated, or mobile:

| Mechanism | Primitive | Semantics | Retracts on Change? |
| :--- | :--- | :--- | :---: |
| **Permanent Equivalence** | `cell_a.unify(cell_b)` | Merges two cells into a single equivalence class forever (Union-Find) | No (monotonic union) |
| **Static Gated Wire** | `SwitchPropagator` | Forwards `input` to a fixed `output` when `control == on_value` | No |
| **$\pi$-Calculus Mobile Link** | `MobileLinkPropagator` | Reads target channel name(s) $y$ from `channel_cell` and routes `payload_cell` to $y$ ($c?(y).\, y!\langle v \rangle$) | **Yes** (via `retract_source` when channel moves) |

### How `MobileLinkPropagator` Preserves Semilattice Discipline

In Robin Milner's **$\pi$-calculus**, processes reconfigure their communication graph by sending **channel names** over channels ($c?(y).\, y!\langle v \rangle$) and spawning fresh private channels via the **restriction operator** ($(\nu y)$).

`MobileLinkPropagator` embeds $\pi$-calculus link mobility directly into partial-information lattices:

1. **Channel Names as Lattice Values:**
   `channel_cell` can hold a single target name (`FlatValue("node_b")`), a multi-target set (`SetLattice({"node_a", "node_b"})`), or an uncertain candidate set (`DiscreteDomain`, `OrderedInterval`, or `BeliefMassValue`).
2. **TMS-Backed Link Handoff:**
   Instead of destructively overwriting a target cell, `MobileLinkPropagator` asserts `payload_cell.value` into each active target cell's `TruthMaintenanceSystem` under a link-specific source ID. When `channel_cell` moves to a new target (or resets to `Bottom` $\bot$), the propagator calls `target.retract_source(...)` on the vacated target, allowing it to relax cleanly back to its remaining active premises.
3. **Uncertainty-Aware Superposition (`propagate_ambiguous=True`):**
   When `channel_cell` holds multiple unresolved candidates (e.g. `DiscreteDomain({"node_a", "node_b"})`), setting `propagate_ambiguous=True` projects speculative `Assumption` premises (`is_assumption=True`) with scaled confidence across all candidate targets—allowing `NetworkTMS` to automatically retract any branch that causes a downstream `Contradiction` ($\top$).
4. **Dynamic $(\nu y)$ Cell Creation (`spawn_missing=True`):**
   If `channel_cell` resolves to a channel name not yet present in the network, `spawn_missing=True` dynamically allocates the new `Cell` on demand.

```python
from lattice_propagator import (
    DiscreteDomain,
    IntervalValue,
    MobileLinkPropagator,
    PropagatorNetwork,
)

net = PropagatorNetwork("PiMobilityDemo")

# Two target nodes with baseline operating envelopes [0.0, 100.0]
node_a = net.add_cell("node_a", IntervalValue(0.0, 100.0))
node_b = net.add_cell("node_b", IntervalValue(0.0, 100.0))

# Mobile payload [20.0, 30.0] and a channel cell holding the active destination name
payload = net.add_cell("payload", IntervalValue(20.0, 30.0))
route_channel = net.add_cell("route_channel")

net.add_propagator(
    MobileLinkPropagator(
        "mobile_link",
        channel_cell=route_channel,
        payload_cell=payload,
        targets={"a": node_a, "b": node_b},
    )
)

# 1. Bind channel to "a" → node_a refines to [0, 100] ⊔ [20, 30] = [20, 30]
route_channel.set_value(DiscreteDomain.single("a"), overwrite=True)
net.run()
print(f"node_a: {node_a.value}, node_b: {node_b.value}")
assert node_a.value == IntervalValue(20.0, 30.0)
assert node_b.value == IntervalValue(0.0, 100.0)

# 2. Move channel to "b" → node_a automatically relaxes to [0, 100], node_b refines to [20, 30]
route_channel.set_value(DiscreteDomain.single("b"), overwrite=True)
net.run()
print(f"node_a: {node_a.value}, node_b: {node_b.value}")
assert node_a.value == IntervalValue(0.0, 100.0)
assert node_b.value == IntervalValue(20.0, 30.0)
```

!!! info "Deep Dive: Event Buses, Node-RED, $\pi$-Calculus & Propagators"
    For a full architectural comparison of $\pi$-calculus link mobility (including Microsoft BizTalk XLANG, Kahn Process Networks, and smart-building zone handoff), see [Event Buses, Node-RED, $\pi$-Calculus & Propagators](../building_automation/paradigms_and_pi_calculus.md).

---

## 3. Propagators

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
| `MobileLinkPropagator(name, channel, payload, ...)` | $\pi$-calculus link mobility ($c?(y).\, y!\langle v \rangle$) with automatic TMS handoff | Dynamic |
| `ConditionalPropagator(pred, cons, alt, out)` | Multiplexer with Sussman-Radul consensus optimization | Forward |
| `RatePropagator(source, rate, dt)` | First-order velocity/derivative estimation | Forward |
| `LagPropagator(input, output, tau, dt)` | First-order exponential lag filter (thermal inertia) | Forward |
| `KalmanEstimatorPropagator(...)` | Fuses noisy linear dynamics with noisy measurements ([Case study](../examples/sensor_fusion.md#why-a-propagator-instead-of-a-python-function)) | Dynamic |
| `DempsterShaferPropagator(...)` | Fuses multi-source evidential mass functions over subset lattices | Evidential |
| `AllDifferentPropagator(cells)` | Pairwise exclusion and hidden-single deduction | Multi |

!!! tip "Propagators vs. Functions"
    For a concrete case study comparing reactive lattice propagators against classical procedural Python functions (e.g. in Kalman filtering), see [Why a Propagator Instead of a Python Function?](../examples/sensor_fusion.md#why-a-propagator-instead-of-a-python-function).

---

## 4. The `PropagatorNetwork` Worklist Engine

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
