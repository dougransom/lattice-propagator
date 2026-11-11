# Dynamic Topology & π-Calculus Mobility: Architectural Trade-Offs

A central design choice in `lattice-propagator` is the inclusion of **$\pi$-calculus link mobility** ([`MobileLinkPropagator`](file:///home/doug/code/lattice-propagator/docs/api/primitives.md)). 

This introduces an essential architectural question:

> *"Is $\pi$-calculus link mobility genuinely beneficial, or is it merely added conceptual complexity? Couldn't dynamic routing be accomplished with simple switches, multiplexers, or imperative control scripts?"*

The short answer: **For small, closed, static graphs (such as toggling a single relay between two lights), $\pi$-calculus mobility is indeed overkill. However, for open-world physical systems governed by join-semilattices, link mobility solves a fundamental mathematical dilemma that static graphs cannot resolve without violating monotonicity or discarding network state.**

---

## 1. The Monotonicity Dilemma: You Cannot "Disconnect" a Pure Lattice Wire

In classical imperative code (Python, C++, JavaScript), routing is achieved through destructive variable reassignment:

```text
# Imperative paradigm: destructive mutation
car_a.charging_power = 0.0
car_b.charging_power = available_surplus
```

In Gerald Jay Sussman and Alexey Radul's propagator model, execution is strictly **monotonic refinement** ($\sqsubseteq$). A cell's value represents accumulated partial knowledge; information only increases ($x \sqcup y \ge x$).

This creates a fundamental dilemma for constraint networks: **How do you disconnect a wire in a monotonic lattice?**

```mermaid
flowchart LR
    Surplus["solar_surplus<br/>[3.3, 4.0] kW"]
    
    subgraph StaticDilemma ["Static Graph Disconnect Dilemma"]
        CarA["Rivian Cell<br/>Standby: [0.0, 11.5] kW<br/>Solar: [3.3, 4.0] kW"]
    end
    
    Surplus -->|Monotonic Wire| CarA
```

In a static graph, once `solar_surplus` ($[3.3, 4.0]\,\text{kW}$) flows into `CarA`, that information is fused into the cell. When solar priorities shift to `CarB`, how do you "turn off" `CarA`?

### Failure Mode 1: Clamping to Zero via a Static Switch

If you insert a static switch that asserts $[0.0, 0.0]\,\text{kW}$ when disabled:

$$[0.0, 11.5] \sqcap [0.0, 0.0] = [0.0, 0.0]\,\text{kW}$$

- **The Problem:** $[0.0, 0.0]$ is an **active, restrictive constraint**, not an *unconstrained standby state*.
- If `CarA` has an auxiliary source (e.g., its own portable solar panel, a secondary Level 1 wall plug, or an internal vehicle battery schedule demanding $[1.0, 2.0]\,\text{kW}$), clamping the cell to zero causes an immediate, artificial `Contradiction` ($\top$):
  $$[1.0, 2.0] \sqcap [0.0, 0.0] = \top\quad (\text{Contradiction})$$
- You intended `CarA` to be *unconstrained by the garage solar splitter*, but instead you locked it to zero.

### Failure Mode 2: Resetting the Network (`net.reset()`)

If you imperatively clear the cell or reset the network:
- You discard all integrated state (such as accumulated battery energy $\int P\,dt$).
- You wipe out multi-sensor fused estimates (Kalman filter states, thermal envelopes).
- You erase learned nogood sets and Truth Maintenance dependency histories across the entire home.

### The $\pi$-Calculus + TMS Resolution

In Robin Milner's $\pi$-calculus ($c?(y).\, y!\langle v \rangle$), communication channels are first-class values. 

`MobileLinkPropagator` bridges $\pi$-calculus with Truth Maintenance:

1. When the mobile link connects `solar_surplus` to `rivian`, it asserts the bound under a **defeasible premise**:
   $$\text{Premise: } \texttt{dispatcher@rivian} \implies [3.3, 4.0]\,\text{kW}$$
2. When the channel moves to `"tesla"`, `MobileLinkPropagator` calls `Cell.retract_source("dispatcher@rivian")`.
3. The Rivian cell’s internal TMS immediately re-evaluates all remaining active premises (its baseline `hardware_envelope`).
4. The cell cleanly **relaxes** back to $[0.0, 11.5]\,\text{kW}$ without any manual zeroing command or network reset!

### 1.1 Introductory Example: Dynamic Target Handoff

The following minimal example illustrates how `MobileLinkPropagator` dynamically redirects an interval payload between two target nodes based on the value in `route_channel`. When the destination moves, the vacated node automatically relaxes back to its initial unconstrained baseline:

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

---

## 2. Static Multiplexers vs. $\pi$-Calculus Link Mobility

Why not build a static multiplexer cell instead? The table below highlights the architectural trade-offs:

| Architectural Metric | Static Multiplexer / Switch Network | $\pi$-Calculus Link Mobility (`MobileLinkPropagator`) |
| :--- | :--- | :--- |
| **Wiring Complexity** | **$O(M \times N)$ permanent wires.** If $M$ energy sources can route to $N$ sinks, the network must instantiate $M \times N$ switch propagators and cells permanently resident in memory. | **$O(M)$ mobile dispatchers.** A single dispatcher dynamically addresses whichever target is named in the channel cell. |
| **The "Open World" Problem** | **Closed World Only.** Cannot route power to a device that did not exist when `net = PropagatorNetwork(...)` was constructed. | **Open World (Scope Extrusion $(\nu y)$).** Setting `spawn_missing=True` allows guest EVs, new battery packs, or discovered Zigbee plugs to allocate fresh cells dynamically at runtime. |
| **Reasoning Over Routing** | Routing is an external control flag outside the constraint algebra. | The destination identifier itself is a first-class lattice value (`DiscreteDomain`, `FlatValue`, `SetLattice`). The network can reason about *which route is feasible* using ordinary constraints. |
| **Speculative Pruning (DDB)** | Cannot easily project hypothetical bounds down uncommitted branches. | Setting `propagate_ambiguous=True` projects defeasible `Assumption`s across candidate targets. If downstream breaker limits trigger a contradiction, Dependency-Directed Backtracking (DDB) automatically prunes the invalid target. |

---

## 3. Deep Dive: Speculative Routing & Constraint Backtracking

The most compelling technical advantage of $\pi$-calculus link mobility appears when routing decisions are **uncertain or under-constrained**.

Consider a smart home where available solar surplus is $[3.0, 3.5]\,\text{kW}$, and the energy manager has not yet committed between charging the Rivian or the Tesla:

```python
from lattice_propagator import (
    Contradiction,
    DiscreteDomain,
    IntervalValue,
    MobileLinkPropagator,
    NetworkTMS,
    PropagatorNetwork,
)

net = PropagatorNetwork("SpeculativeRouter")
ntms = NetworkTMS(net)

surplus = net.add_cell("surplus", IntervalValue(3.0, 3.5))
channel = net.add_cell("channel")

rivian = net.add_cell("rivian_power")
tesla = net.add_cell("tesla_power")
ntms.get_or_create_cell_tms("rivian_power")
ntms.get_or_create_cell_tms("tesla_power")

# Baseline hardware capability limits:
rivian.set_value(IntervalValue(0.0, 11.5), source="hardware_limit")
tesla.set_value(IntervalValue(0.0, 7.6), source="hardware_limit")

net.add_propagator(
    MobileLinkPropagator(
        "ev_dispatcher",
        channel_cell=channel,
        payload_cell=surplus,
        targets={"rivian": rivian, "tesla": tesla},
        propagate_ambiguous=True,  # Enables speculative branching
    )
)

# 1. Routing is in a superposition of candidates:
channel.set_value(DiscreteDomain({"rivian", "tesla"}))
net.run()

# Both vehicles simultaneously receive speculative bounds as TMS assumptions:
assert rivian.value == IntervalValue(3.0, 3.5)
assert tesla.value == IntervalValue(3.0, 3.5)
assert rivian.tms.premises["ev_dispatcher@rivian"].is_assumption is True
assert tesla.tms.premises["ev_dispatcher@tesla"].is_assumption is True

# 2. Suppose Rivian's BMS suddenly asserts a minimum pilot threshold [5.0, 11.5] kW:
rivian.set_value(IntervalValue(5.0, 11.5), source="bms_thermal_min")

# Immediate contradiction detected: [3.0, 3.5] ⊓ [5.0, 11.5] = ⊤
assert isinstance(rivian.value, Contradiction)

# 3. Dependency-Directed Backtracking (DDB) traces the contradiction to the assumption:
retracted = ntms.resolve_contradiction(rivian.tms.active_sources)
assert retracted == "ev_dispatcher@rivian"

# Rivian relaxes back to its thermal window; Tesla retains the budget!
assert rivian.value == IntervalValue(5.0, 11.5)
assert tesla.value == IntervalValue(3.0, 3.5)
```

In a traditional imperative or static switch architecture, implementing this behavior requires complex procedural logic:
1. Attempt routing to Rivian.
2. Check for faults.
3. Catch exceptions.
4. Issue imperative cancel commands.
5. Attempt routing to Tesla.

With `MobileLinkPropagator` and `NetworkTMS`, **speculation and fault pruning fall out naturally from the algebra of lattices and Truth Maintenance**.

---

## 4. Pragmatic Boundaries: When Is Link Mobility Overkill?

To maintain engineering discipline, $\pi$-calculus link mobility should not be applied everywhere. It introduces indirection and requires Truth Maintenance tracking.

### Do NOT Use Link Mobility When:

1. **The Topology Is Closed and Static:**
   If a home has one solar inverter and one water heater with a physical on/off contactor, a simple `SwitchPropagator` or `AdderPropagator` is far simpler and easier to audit.
2. **Devices Never Leave, Arrive, or Reconfigure:**
   If all consumers are permanent, hardwired electrical circuits with fixed roles, static graph wiring is optimal.
3. **Execution Is Strictly Feed-Forward:**
   If data flows strictly from sensors to actuators without any need for bidirectional inference, hypothetical branching, or diagnostic backtracking.

---

## 5. Architectural Decision Matrix

Use the matrix below to select the appropriate topological mechanism in `lattice-propagator`:

| Mechanism | Representative Use Case | Retracts on Change? | Creates New Cells? |
| :--- | :--- | :---: | :---: |
| **Direct Propagator Wiring** (`AdderPropagator`, `MultiplierPropagator`) | Fixed mathematical physics ($P = V \times I$, energy balance $P_{\text{base}} + P_{\text{surplus}} = P_{\text{solar}}$) | No (Permanent) | No |
| **Cell Unification** (`cell_a.unify(cell_b)`) | Discovered identity (discovering that two sensor probes measure the same physical water pipe) | No (Monotonic DSU) | No |
| **Static Gated Wire** (`SwitchPropagator`) | Gated binary actuators with fixed wiring (furnace enable switch) | No | No |
| **$\pi$-Calculus Mobile Link** (`MobileLinkPropagator`) | Dynamic resource routing, priority scheduling, EV fleets, open-world device discovery, speculative CSP branch pruning | **Yes (via TMS)** | **Yes (via $(\nu y)$)** |

---

## 6. Concrete Comparison: The Dual-EV Network Implemented with Static Switches

To see the architectural contrast concretely, we can reimplement the **Dual-EV Solar Splitter network** from [Example Section 2](file:///home/doug/code/lattice-propagator/docs/examples/dynamic_power_routing.md#2-network-architecture--topology) **without using `MobileLinkPropagator`**, relying strictly on static [`SwitchPropagator`](file:///home/doug/code/lattice-propagator/docs/api/primitives.md) instances.

### 6.1 Redrawn Architecture Diagram (Static Switches)

```mermaid
flowchart TD
    subgraph PowerGeneration ["1. Upstream Power Budget & Safety Constraints"]
        Solar["solar_production: [P_min, P_max] kW"]
        Baseload["home_baseload: [B_min, B_max] kW"]
        Balance["AdderPropagator (baseload + surplus = solar)"]
        Surplus["solar_surplus: [S_min, S_max] kW"]
        
        Solar --> Balance
        Baseload --> Balance
        Balance --> Surplus
    end

    subgraph StaticSwitchMatrix ["2. Static Switch Matrix (Without MobileLink)"]
        CtrlRivian["Control Cell: ctrl_rivian (Boolean)"]
        CtrlTesla["Control Cell: ctrl_tesla (Boolean)"]
        CtrlGuest["Control Cell: ctrl_guest (Boolean)"]
        
        SwRivian["SwitchPropagator: sw_rivian"]
        SwTesla["SwitchPropagator: sw_tesla"]
        SwGuest["SwitchPropagator: sw_guest"]
        
        CtrlRivian --> SwRivian
        CtrlTesla --> SwTesla
        CtrlGuest --> SwGuest
        
        Surplus --> SwRivian
        Surplus --> SwTesla
        Surplus --> SwGuest
    end

    subgraph TargetEVs ["3. Pre-Allocated Target Vehicle Cells"]
        RivianPower["rivian_power: Standby [0.0, 11.5] kW"]
        TeslaPower["tesla_power: Standby [0.0, 7.6] kW"]
        GuestPower["guest_power: Standby [0.0, 11.5] kW (Must be pre-allocated)"]
    end

    SwRivian --> RivianPower
    SwTesla --> TeslaPower
    SwGuest --> GuestPower

    classDef cell fill:#2d3748,stroke:#cbd5e0,stroke-width:2px,color:#fff;
    classDef prop fill:#1a365d,stroke:#63b3ed,stroke-width:2px,color:#fff;
    classDef sw fill:#4a5568,stroke:#a0aec0,stroke-width:2px,color:#fff;
    class Solar,Baseload,Surplus,CtrlRivian,CtrlTesla,CtrlGuest,RivianPower,TeslaPower,GuestPower cell;
    class Balance prop;
    class SwRivian,SwTesla,SwGuest sw;
```

---

### 6.2 Python Implementation: Building the Network with Static Switches

Here is the exact code required to instantiate the static network (corresponding to Steps 1–4 of the solar splitter, without the multi-hour time series simulation):

```python
from lattice_propagator import (
    AdderPropagator,
    FlatValue,
    IntervalValue,
    PropagatorNetwork,
    SwitchPropagator,
)

# 1. Instantiate network and physical power cells
net = PropagatorNetwork("StaticSwitchSolarEVSplitter")

solar = net.add_cell("solar_production", unit="kW")
baseload = net.add_cell("home_baseload", unit="kW")
surplus = net.add_cell("solar_surplus", unit="kW")

# 2. Target vehicles with baseline hardware standby capabilities
# Note: Without (ν y) dynamic spawning, the guest vehicle must be pre-allocated statically
rivian = net.add_cell("rivian_power", unit="kW")
tesla = net.add_cell("tesla_power", unit="kW")
guest = net.add_cell("guest_power", unit="kW")

rivian.set_value(IntervalValue(0.0, 11.5), source="hardware_envelope")
tesla.set_value(IntervalValue(0.0, 7.6), source="hardware_envelope")
guest.set_value(IntervalValue(0.0, 11.5), source="hardware_envelope")

# 3. Upstream constraint: baseload + surplus = solar
net.add_propagator(AdderPropagator("power_balance", baseload, surplus, solar))

# 4. Static Switch Gates (Alternative to MobileLinkPropagator):
# Each target requires its own dedicated boolean control cell and SwitchPropagator
ctrl_rivian = net.add_cell("ctrl_rivian")
ctrl_tesla = net.add_cell("ctrl_tesla")
ctrl_guest = net.add_cell("ctrl_guest")

net.add_propagator(SwitchPropagator("sw_rivian", ctrl_rivian, surplus, rivian, on_value=True))
net.add_propagator(SwitchPropagator("sw_tesla", ctrl_tesla, surplus, tesla, on_value=True))
net.add_propagator(SwitchPropagator("sw_guest", ctrl_guest, surplus, guest, on_value=True))

# Initial verification of single fixed-point computation:
solar.set_value(IntervalValue(5.0, 6.0))
baseload.set_value(IntervalValue(1.0, 1.0))
ctrl_rivian.set_value(FlatValue(True))
ctrl_tesla.set_value(FlatValue(False))
ctrl_guest.set_value(FlatValue(False))

net.run()

# Verified deductions:
assert surplus.value == IntervalValue(4.0, 5.0)
assert rivian.value == IntervalValue(4.0, 5.0)
assert tesla.value == IntervalValue(0.0, 7.6)  # Remained unconstrained in standby
assert guest.value == IntervalValue(0.0, 11.5)  # Remained unconstrained in standby
```

---

### 6.3 What Breaks When We Advance to Hour 2? (The Retraction Deficit)

While building the static network is straightforward, attempting to run the multi-hour switching sequence exposes the core limitation of static switches in monotonic lattices:

1. **Wiring Proliferation:** We had to allocate three separate control cells (`ctrl_rivian`, `ctrl_tesla`, `ctrl_guest`) and three separate `SwitchPropagator` instances. In a fleet with $N$ vehicles, the static graph requires $N$ switches and $N$ control lines.
2. **Loss of Scope Extrusion ($(\nu y)$):** The guest vehicle cannot be dynamically allocated when it arrives. It must be anticipated and hardwired into the topology from day one.
3. **The Non-Retraction Trap:** When Hour 2 arrives and charging switches from Rivian to Tesla, setting `ctrl_rivian = False` causes `sw_rivian` to stop propagating. **However, `rivian_power` retains $[4.0, 5.0]\,\text{kW}$!** Because `SwitchPropagator` does not manage TMS premise retraction, the Rivian cell is never relaxed back to standby $[0.0, 11.5]\,\text{kW}$. 

To make the static network work over time, the host application must either:
- Manually track premise sources and call `rivian.retract_source(...)` outside the network for every route change.
- Or imperatively overwrite `rivian.set_value(..., overwrite=True)` in a procedural loop.

`MobileLinkPropagator` eliminates this manual orchestration by packaging the routing address into a first-class channel value and automating TMS premise retraction on vacated endpoints.

---

## 7. Summary

To see the architectural contrast concretely, we can reimplement the **Dual-EV Solar Splitter network** from [Example Section 2](file:///home/doug/code/lattice-propagator/docs/examples/dynamic_power_routing.md#2-network-architecture--topology) **without using `MobileLinkPropagator`**, relying strictly on static [`SwitchPropagator`](file:///home/doug/code/lattice-propagator/docs/api/primitives.md) instances.

### 6.1 Redrawn Architecture Diagram (Static Switches)

```mermaid
flowchart TD
    subgraph PowerGeneration ["1. Upstream Power Budget & Safety Constraints"]
        Solar["solar_production: [P_min, P_max] kW"]
        Baseload["home_baseload: [B_min, B_max] kW"]
        Balance["AdderPropagator (baseload + surplus = solar)"]
        Surplus["solar_surplus: [S_min, S_max] kW"]
        
        Solar --> Balance
        Baseload --> Balance
        Balance --> Surplus
    end

    subgraph StaticSwitchMatrix ["2. Static Switch Matrix (Without MobileLink)"]
        CtrlRivian["Control Cell: ctrl_rivian (Boolean)"]
        CtrlTesla["Control Cell: ctrl_tesla (Boolean)"]
        CtrlGuest["Control Cell: ctrl_guest (Boolean)"]
        
        SwRivian["SwitchPropagator: sw_rivian"]
        SwTesla["SwitchPropagator: sw_tesla"]
        SwGuest["SwitchPropagator: sw_guest"]
        
        CtrlRivian --> SwRivian
        CtrlTesla --> SwTesla
        CtrlGuest --> SwGuest
        
        Surplus --> SwRivian
        Surplus --> SwTesla
        Surplus --> SwGuest
    end

    subgraph TargetEVs ["3. Pre-Allocated Target Vehicle Cells"]
        RivianPower["rivian_power: Standby [0.0, 11.5] kW"]
        TeslaPower["tesla_power: Standby [0.0, 7.6] kW"]
        GuestPower["guest_power: Standby [0.0, 11.5] kW (Must be pre-allocated)"]
    end

    SwRivian --> RivianPower
    SwTesla --> TeslaPower
    SwGuest --> GuestPower

    classDef cell fill:#2d3748,stroke:#cbd5e0,stroke-width:2px,color:#fff;
    classDef prop fill:#1a365d,stroke:#63b3ed,stroke-width:2px,color:#fff;
    classDef sw fill:#4a5568,stroke:#a0aec0,stroke-width:2px,color:#fff;
    class Solar,Baseload,Surplus,CtrlRivian,CtrlTesla,CtrlGuest,RivianPower,TeslaPower,GuestPower cell;
    class Balance prop;
    class SwRivian,SwTesla,SwGuest sw;
```

---

### 6.2 Python Implementation: Building the Network with Static Switches

Here is the exact code required to instantiate the static network (corresponding to Steps 1–4 of the solar splitter, without the multi-hour time series simulation):

```python
from lattice_propagator import (
    AdderPropagator,
    FlatValue,
    IntervalValue,
    PropagatorNetwork,
    SwitchPropagator,
)

# 1. Instantiate network and physical power cells
net = PropagatorNetwork("StaticSwitchSolarEVSplitter")

solar = net.add_cell("solar_production", unit="kW")
baseload = net.add_cell("home_baseload", unit="kW")
surplus = net.add_cell("solar_surplus", unit="kW")

# 2. Target vehicles with baseline hardware standby capabilities
# Note: Without (ν y) dynamic spawning, the guest vehicle must be pre-allocated statically
rivian = net.add_cell("rivian_power", unit="kW")
tesla = net.add_cell("tesla_power", unit="kW")
guest = net.add_cell("guest_power", unit="kW")

rivian.set_value(IntervalValue(0.0, 11.5), source="hardware_envelope")
tesla.set_value(IntervalValue(0.0, 7.6), source="hardware_envelope")
guest.set_value(IntervalValue(0.0, 11.5), source="hardware_envelope")

# 3. Upstream constraint: baseload + surplus = solar
net.add_propagator(AdderPropagator("power_balance", baseload, surplus, solar))

# 4. Static Switch Gates (Alternative to MobileLinkPropagator):
# Each target requires its own dedicated boolean control cell and SwitchPropagator
ctrl_rivian = net.add_cell("ctrl_rivian")
ctrl_tesla = net.add_cell("ctrl_tesla")
ctrl_guest = net.add_cell("ctrl_guest")

net.add_propagator(SwitchPropagator("sw_rivian", ctrl_rivian, surplus, rivian, on_value=True))
net.add_propagator(SwitchPropagator("sw_tesla", ctrl_tesla, surplus, tesla, on_value=True))
net.add_propagator(SwitchPropagator("sw_guest", ctrl_guest, surplus, guest, on_value=True))

# Initial verification of single fixed-point computation:
solar.set_value(IntervalValue(5.0, 6.0))
baseload.set_value(IntervalValue(1.0, 1.0))
ctrl_rivian.set_value(FlatValue(True))
ctrl_tesla.set_value(FlatValue(False))
ctrl_guest.set_value(FlatValue(False))

net.run()

# Verified deductions:
assert surplus.value == IntervalValue(4.0, 5.0)
assert rivian.value == IntervalValue(4.0, 5.0)
assert tesla.value == IntervalValue(0.0, 7.6)  # Remained unconstrained in standby
assert guest.value == IntervalValue(0.0, 11.5)  # Remained unconstrained in standby
```

---

### 6.3 What Breaks When We Advance to Hour 2? (The Retraction Deficit)

While building the static network is straightforward, attempting to run the multi-hour switching sequence exposes the core limitation of static switches in monotonic lattices:

1. **Wiring Proliferation:** We had to allocate three separate control cells (`ctrl_rivian`, `ctrl_tesla`, `ctrl_guest`) and three separate `SwitchPropagator` instances. In a fleet with $N$ vehicles, the static graph requires $N$ switches and $N$ control lines.
2. **Loss of Scope Extrusion ($(\nu y)$):** The guest vehicle cannot be dynamically allocated when it arrives. It must be anticipated and hardwired into the topology from day one.
3. **The Non-Retraction Trap:** When Hour 2 arrives and charging switches from Rivian to Tesla, setting `ctrl_rivian = False` causes `sw_rivian` to stop propagating. **However, `rivian_power` retains $[4.0, 5.0]\,\text{kW}$!** Because `SwitchPropagator` does not manage TMS premise retraction, the Rivian cell is never relaxed back to standby $[0.0, 11.5]\,\text{kW}$. 

To make the static network work over time, the host application must either:
- Manually track premise sources and call `rivian.retract_source(...)` outside the network for every route change.
- Or imperatively overwrite `rivian.set_value(..., overwrite=True)` in a procedural loop.

`MobileLinkPropagator` eliminates this manual orchestration by packaging the routing address into a first-class channel value and automating TMS premise retraction on vacated endpoints.

---

## 7. Summary

Robin Milner’s $\pi$-calculus is not academic decoration in `lattice-propagator`. It is the mathematical mechanism that allows **monotonic constraint networks** to operate in **dynamically changing physical worlds**. 

By pairing channel mobility ($c?(y).\, y!\langle v \rangle$) with defeasible Truth Maintenance retraction, the network gains the ability to dynamically reconfigure physical connections without mutating state, risking dangling wires, or violating semilattice monotonicity.
