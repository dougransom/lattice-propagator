# Example: Dynamic EV Power Budgeting & π-Calculus Link Mobility

Classical dataflow graphs and constraint networks feature a **static topology**: wires between computational cells are fixed before execution starts. 

However, real-world physical systems frequently require **dynamic topology**—where connections between producers, consumers, and actuators change at runtime based on environmental state, priority tokens, or physical movement.

This example demonstrates how [`MobileLinkPropagator`](file:///home/doug/code/lattice-propagator/docs/api/primitives.md) implements Robin Milner's **$\pi$-calculus link mobility** ($c?(y).\, y!\langle v \rangle$) over partial-information lattices to solve the **dynamic solar power budget allocation problem** for a dual-vehicle smart charging garage.

---

## 1. The Dynamic Solar Splitter Problem

A home has a solar photovoltaic (PV) array, varying household baseload, and a shared $40\,\text{A}$ ($9.6\,\text{kW}$ continuous @ $240\,\text{V}$) electrical feed in the garage. Two Electric Vehicles (EVs) are parked in the driveway:

1. **Rivian R1S:** High battery capacity ($135.0\,\text{kWh}$ pack), accepts up to $11.5\,\text{kW}$ on AC Level 2. Starts at **$67.0\%$ State of Charge (SOC)** ($90.45\,\text{kWh}$ stored), with a priority target threshold of **$75.0\%$ SOC**.
2. **Tesla Model Y:** Secondary commuter vehicle ($75.0\,\text{kWh}$ pack), accepts up to $7.6\,\text{kW}$ on AC Level 2. Starts depleted at **$20.0\%$ SOC** ($15.00\,\text{kWh}$ stored), with a target threshold of **$30.0\%$ SOC**.
3. **Guest EV:** Visiting vehicle connected to a mobile charger plug, which should receive remaining solar power only after both primary household vehicles have reached their target state of charge.

### Why Static Graphs Struggle
Under a static graph topology, you cannot simply wire the fluctuating solar surplus cell directly into both vehicle cells simultaneously, because:
- **Destructive Interference:** Summing or joining both vehicle inputs directly into the single circuit would violate the $9.6\,\text{kW}$ safety limit or create contradictory constraints when one car finishes charging.
- **Manual Cleanup Boilerplate:** In classical automation systems (like raw Home Assistant automations or Node-RED flows), switching charging from Car A to Car B requires imperative scripting to manually zero out Car A, stop its loop, calculate the new budget, and start Car B's loop. If any step fails, Car A is left with a stale, non-zero charging command.

### The $\pi$-Calculus Solution
In Milner's $\pi$-calculus, communication channels are first-class values: processes send **channel names** across channels ($c?(y).\, y!\langle v \rangle$). 

With [`MobileLinkPropagator`](file:///home/doug/code/lattice-propagator/docs/api/primitives.md):
- **Payload Cell ($v$):** The dynamically calculated solar surplus power envelope $[P_{\min}, P_{\max}]\,\text{kW}$.
- **Channel Cell ($y$):** The dispatcher cell carrying the active destination vehicle identifier (`FlatValue("rivian")`, `FlatValue("tesla")`, or a candidate set `DiscreteDomain`).
- **Automatic TMS Retraction:** When the channel moves from `"rivian"` to `"tesla"`, the propagator automatically calls `Cell.retract_source()` on the Rivian cell. The Rivian relaxes cleanly back to its unconstrained standby baseline $[0.0, 11.5]\,\text{kW}$, while the Tesla instantly refines to the new solar budget!
- **Dynamic Scope Extrusion ($(\nu y)$):** When a guest vehicle plugs in (`"guest_ev"`), setting `spawn_missing=True` dynamically allocates a brand-new cell in the network on the fly.

---

## 2. Network Architecture & Topology

```mermaid
flowchart TD
    subgraph PowerGeneration ["1. Upstream Power Budget & Safety Constraints"]
        Solar["solar_production<br/>[P_min, P_max] kW"]
        Baseload["home_baseload<br/>[B_min, B_max] kW"]
        Balance["AdderPropagator<br/>(baseload + surplus = solar)"]
        Surplus["solar_surplus<br/>[S_min, S_max] kW"]
        
        Solar --> Balance
        Baseload --> Balance
        Balance --> Surplus
    end

    subgraph PiMobilityCore ["2. π-Calculus Dynamic Dispatcher"]
        Channel["Channel Cell: active_vehicle<br/>Flat('rivian') → Flat('tesla')"]
        MobileLink["MobileLinkPropagator<br/>(c?(y) . y!⟨surplus⟩)"]
        
        Channel -- "Target Channel Name y" --> MobileLink
        Surplus -- "Mobile Payload v" --> MobileLink
    end

    subgraph TargetEVs ["3. Target Vehicle Cells & In-Vehicle Hardware Limits"]
        subgraph RivianNode ["Rivian R1S Node"]
            RivianPower["rivian_power<br/>Standby: [0.0, 11.5] kW"]
        end

        subgraph TeslaNode ["Tesla Model Y Node"]
            TeslaPower["tesla_power<br/>Standby: [0.0, 7.6] kW"]
        end

        subgraph DynamicNode ["Guest Node (Spawned on Demand via (ν y))"]
            GuestPower["guest_ev<br/>Dynamically Spawned Cell"]
        end
    end

    MobileLink == "Active Link (Assert Premise)" ==> RivianPower
    MobileLink -. "Vacated Link (TMS Retracted)" .-> TeslaPower
    MobileLink -. "Dynamic Spawning (ν y)" .-> GuestPower

    classDef cell fill:#2d3748,stroke:#cbd5e0,stroke-width:2px,color:#fff;
    classDef prop fill:#1a365d,stroke:#63b3ed,stroke-width:2px,color:#fff;
    classDef mobile fill:#744210,stroke:#f6ad55,stroke-width:2px,color:#fff;
    class Solar,Baseload,Surplus,Channel,RivianPower,TeslaPower,GuestPower cell;
    class Balance prop;
    class MobileLink mobile;
```

---

## 3. Hourly Simulation Overview

To illustrate the separation of inputs from autonomous network deductions, we divide the 6-hour simulation (11:00 to 16:00) into two views:

### A. Input Readings (Boundary Conditions)
These are the external sensor readings and environmental boundary conditions provided to the system each hour. Notice that **no vehicle names or switching decisions are specified in the inputs**:

| Hour | Solar Generation ($P_{\text{solar}}$) | Home Baseload ($P_{\text{base}}$) | Environmental Context |
| :---: | :---: | :---: | :--- |
| **11:00** | $[4.0, 4.5]\,\text{kW}$ | $[0.5, 0.7]\,\text{kW}$ | Morning solar ramp; clear skies |
| **12:00** | $[6.5, 7.5]\,\text{kW}$ | $[0.8, 1.0]\,\text{kW}$ | Solar peak; cooking lunch increases baseload |
| **13:00** | $[7.0, 7.5]\,\text{kW}$ | $[0.6, 0.8]\,\text{kW}$ | Early afternoon high solar window |
| **14:00** | $[5.5, 6.0]\,\text{kW}$ | $[0.7, 0.9]\,\text{kW}$ | Afternoon solar begins tapering |
| **15:00** | $[4.8, 5.4]\,\text{kW}$ | $[0.6, 0.8]\,\text{kW}$ | Late afternoon steady sun |
| **16:00** | $[3.5, 4.0]\,\text{kW}$ | $[0.5, 0.7]\,\text{kW}$ | Late afternoon lower solar angle |

### B. Network Deductions & Dynamic State Evolution (Outputs)
These are the autonomous outputs computed by the propagator network—the surplus power envelope, the dynamically evaluated active target channel (selected car), the allocated charging power, and the resulting integrated State of Charge (SOC):

| Hour | Solar Surplus ($P_{\text{surplus}}$) | Active Target Channel *(Active Car)* | Rivian Allocation & SOC *(Cap: $135\,\text{kWh}$, Target: $75\%$)* | Tesla Allocation & SOC *(Cap: $75\,\text{kWh}$, Target: $30\%$)* | Operational Event / $\pi$-Calculus Handoff |
| :---: | :---: | :---: | :---: | :---: | :--- |
| **11:00** | $[3.3, 4.0]\,\text{kW}$ | `"rivian"` | $[3.3, 4.0]\,\text{kW}$<br/>**SOC:** $[69.4\%, 70.0\%]$ | Standby ($[0.0, 7.6]\,\text{kW}$)<br/>**SOC:** $20.0\%$ | Rivian starts at $67.0\%$ and charges towards $75.0\%$ target. |
| **12:00** | $[5.5, 6.7]\,\text{kW}$ | `"rivian"` | $[5.5, 6.7]\,\text{kW}$<br/>**SOC:** $[73.5\%, 74.9\%]$ | Standby ($[0.0, 7.6]\,\text{kW}$)<br/>**SOC:** $20.0\%$ | Rivian continues charging toward $75.0\%$ target. |
| **13:00** | $[6.2, 6.9]\,\text{kW}$ | `"rivian"` | $[6.2, 6.9]\,\text{kW}$<br/>**SOC:** $[78.1\%, 80.0\%]$ | Standby ($[0.0, 7.6]\,\text{kW}$)<br/>**SOC:** $20.0\%$ | **Rivian reaches target ($\ge 75.0\%$)!** Battery is sufficiently charged. |
| **14:00** | $[4.6, 5.3]\,\text{kW}$ | `"tesla"` | Standby ($[0.0, 11.5]\,\text{kW}$)<br/>**SOC:** $[78.1\%, 80.0\%]$ | $[4.6, 5.3]\,\text{kW}$<br/>**SOC:** $[26.1\%, 27.1\%]$ | **$\pi$-Handoff 1:** Switched to Tesla because Rivian is satisfied! TMS retracts Rivian. |
| **15:00** | $[4.0, 4.8]\,\text{kW}$ | `"tesla"` | Standby ($[0.0, 11.5]\,\text{kW}$)<br/>**SOC:** $[78.1\%, 80.0\%]$ | $[4.0, 4.8]\,\text{kW}$<br/>**SOC:** $[31.5\%, 33.5\%]$ | **Tesla reaches target ($\ge 30.0\%$)!** Both primary vehicles are now satisfied. |
| **16:00** | $[2.8, 3.5]\,\text{kW}$ | `"guest_ev"` | Standby ($[0.0, 11.5]\,\text{kW}$)<br/>**SOC:** $[78.1\%, 80.0\%]$ | Standby ($[0.0, 7.6]\,\text{kW}$)<br/>**SOC:** $[31.5\%, 33.5\%]$ | **$\pi$-Handoff 2 & $(\nu y)$ Spawning:** Both household cars satisfied; power routes to Guest EV. |

---

## 4. Executable Python Implementation

```python
from lattice_propagator import (
    BOTTOM,
    AdderPropagator,
    DiscreteDomain,
    IntervalValue,
    MobileLinkPropagator,
    PropagatorNetwork,
)

# 1. Instantiate network and physical cells
net = PropagatorNetwork("SolarEVSplitter")

solar = net.add_cell("solar_production", unit="kW")
baseload = net.add_cell("home_baseload", unit="kW")
surplus = net.add_cell("solar_surplus", unit="kW")
channel = net.add_cell("active_vehicle")

# 2. Target vehicles with baseline hardware standby capabilities
rivian = net.add_cell("rivian_power", unit="kW")
tesla = net.add_cell("tesla_power", unit="kW")

rivian.set_value(IntervalValue(0.0, 11.5), source="hardware_envelope")
tesla.set_value(IntervalValue(0.0, 7.6), source="hardware_envelope")

# Battery pack capacities and initial state of charge (SOC)
CAP_RIVIAN = 135.0  # Rivian R1S (135 kWh pack)
CAP_TESLA = 75.0  # Tesla Model Y (75 kWh pack)

e_rivian = IntervalValue(CAP_RIVIAN * 0.67, CAP_RIVIAN * 0.67)  # Starts at 67.0% (90.45 kWh)
e_tesla = IntervalValue(CAP_TESLA * 0.20, CAP_TESLA * 0.20)  # Starts at 20.0% (15.00 kWh)

# 3. Upstream constraint: baseload + surplus = solar  (surplus = solar − baseload)
net.add_propagator(AdderPropagator("power_balance", baseload, surplus, solar))

# 4. π-Calculus Mobile Link Propagator
net.add_propagator(
    MobileLinkPropagator(
        "ev_dispatcher",
        channel_cell=channel,
        payload_cell=surplus,
        targets={"rivian": rivian, "tesla": tesla},
        spawn_missing=True,  # Enables (ν y) dynamic cell creation
    )
)

# 5. Hourly time series simulation inputs.
# External boundary conditions (pure physical weather/load inputs, NO vehicle names!):
#   • Column 1 (hour):     Time-of-day step identifier (e.g. "11:00")
#   • Column 2 (sol_val):  Solar PV generation power envelope [P_min, P_max] in kW
#   • Column 3 (base_val): Home baseload power consumption envelope [B_min, B_max] in kW
hourly_inputs = [
    #  Hour     Solar Generation (kW)   Home Baseload (kW)
    ("11:00", IntervalValue(4.0, 4.5), IntervalValue(0.5, 0.7)),
    ("12:00", IntervalValue(6.5, 7.5), IntervalValue(0.8, 1.0)),
    ("13:00", IntervalValue(7.0, 7.5), IntervalValue(0.6, 0.8)),
    ("14:00", IntervalValue(5.5, 6.0), IntervalValue(0.7, 0.9)),
    ("15:00", IntervalValue(4.8, 5.4), IntervalValue(0.6, 0.8)),
    ("16:00", IntervalValue(3.5, 4.0), IntervalValue(0.5, 0.7)),
]

RIVIAN_TARGET_SOC = 75.0  # Charge Rivian first until 75.0% target
TESLA_TARGET_SOC = 30.0  # Then charge Tesla until 30.0% target

for hour, sol_val, base_val in hourly_inputs:
    # Clear intermediate surplus cell for the new discrete time step
    surplus.set_value(BOTTOM, overwrite=True)
    solar.set_value(sol_val, overwrite=True)
    baseload.set_value(base_val, overwrite=True)

    # Autonomous priority ladder based on current state of charge:
    # 1. Charge Rivian until RIVIAN_TARGET_SOC (75.0%)
    # 2. Charge Tesla until TESLA_TARGET_SOC (30.0%)
    # 3. Route to Guest EV once both primary vehicles are satisfied
    curr_soc_r = e_rivian.min_val / CAP_RIVIAN * 100.0
    curr_soc_t = e_tesla.min_val / CAP_TESLA * 100.0

    if curr_soc_r < RIVIAN_TARGET_SOC:
        target_car = "rivian"
    elif curr_soc_t < TESLA_TARGET_SOC:
        target_car = "tesla"
    else:
        target_car = "guest_ev"

    channel.set_value(DiscreteDomain.single(target_car), overwrite=True)
    net.run()

    # Integrate 1 hour of energy: Delta_E = Power * 1.0h
    if target_car == "rivian":
        e_rivian = IntervalValue(
            e_rivian.min_val + rivian.value.min_val,
            e_rivian.max_val + rivian.value.max_val,
        )
    elif target_car == "tesla":
        e_tesla = IntervalValue(
            e_tesla.min_val + tesla.value.min_val,
            e_tesla.max_val + tesla.value.max_val,
        )

    # Compute State of Charge (SOC) intervals
    soc_r = IntervalValue(
        e_rivian.min_val / CAP_RIVIAN * 100.0,
        e_rivian.max_val / CAP_RIVIAN * 100.0,
    )
    soc_t = IntervalValue(
        e_tesla.min_val / CAP_TESLA * 100.0,
        e_tesla.max_val / CAP_TESLA * 100.0,
    )

    # Verify expected dynamic routing and automatic TMS relaxation
    if target_car == "rivian":
        assert rivian.value == surplus.value
        assert tesla.value == IntervalValue(0.0, 7.6)  # Tesla is in standby
    elif target_car == "tesla":
        assert rivian.value == IntervalValue(0.0, 11.5)  # Rivian relaxed back to standby
        assert tesla.value == surplus.value
    elif target_car == "guest_ev":
        assert rivian.value == IntervalValue(0.0, 11.5)
        assert tesla.value == IntervalValue(0.0, 7.6)
        assert "guest_ev" in net.cells
        assert net.cells["guest_ev"].value == surplus.value

    print(
        f"Hour {hour} | Target: {target_car:10} | Surplus: {surplus.value} | "
        f"Rivian SOC: [{soc_r.min_val:.1f}%, {soc_r.max_val:.1f}%] | "
        f"Tesla SOC: [{soc_t.min_val:.1f}%, {soc_t.max_val:.1f}%]"
    )
```

```text
Hour 11:00 | Target: rivian     | Surplus: [3.300, 4.000] | Rivian SOC: [69.4%, 70.0%] | Tesla SOC: [20.0%, 20.0%]
Hour 12:00 | Target: rivian     | Surplus: [5.500, 6.700] | Rivian SOC: [73.5%, 74.9%] | Tesla SOC: [20.0%, 20.0%]
Hour 13:00 | Target: rivian     | Surplus: [6.200, 6.900] | Rivian SOC: [78.1%, 80.0%] | Tesla SOC: [20.0%, 20.0%]
Hour 14:00 | Target: tesla      | Surplus: [4.600, 5.300] | Rivian SOC: [78.1%, 80.0%] | Tesla SOC: [26.1%, 27.1%]
Hour 15:00 | Target: tesla      | Surplus: [4.000, 4.800] | Rivian SOC: [78.1%, 80.0%] | Tesla SOC: [31.5%, 33.5%]
Hour 16:00 | Target: guest_ev   | Surplus: [2.800, 3.500] | Rivian SOC: [78.1%, 80.0%] | Tesla SOC: [31.5%, 33.5%]
```

---

## 5. Ambiguous Routing & Speculative Superposition

What happens if the energy management system has not yet decided which vehicle to prioritize, or wants to explore the speculative impact of charging either car?

By setting `propagate_ambiguous=True`, `MobileLinkPropagator` projects defeasible **`Assumption`** premises across all candidate targets:

```python
from lattice_propagator import (
    DiscreteDomain,
    IntervalValue,
    MobileLinkPropagator,
    NetworkTMS,
    PropagatorNetwork,
)

net = PropagatorNetwork("AmbiguousEVSplitter")
ntms = NetworkTMS(net)

surplus = net.add_cell("surplus", IntervalValue(3.0, 3.5))
channel = net.add_cell("channel")

rivian = net.add_cell("rivian_power")
tesla = net.add_cell("tesla_power")
ntms.get_or_create_cell_tms("rivian_power")
ntms.get_or_create_cell_tms("tesla_power")

rivian.set_value(IntervalValue(0.0, 11.5), source="hardware_limit")
tesla.set_value(IntervalValue(0.0, 7.6), source="hardware_limit")

net.add_propagator(
    MobileLinkPropagator(
        "ev_dispatcher",
        channel_cell=channel,
        payload_cell=surplus,
        targets={"rivian": rivian, "tesla": tesla},
        confidence=0.8,
        propagate_ambiguous=True,
    )
)

# Undecided between Rivian and Tesla:
channel.set_value(DiscreteDomain({"rivian", "tesla"}))
net.run()

# Both vehicles receive speculative bounds:
assert rivian.value == IntervalValue(3.0, 3.5)
assert tesla.value == IntervalValue(3.0, 3.5)

# Both bindings are marked as defeasible assumptions in the TMS:
assert rivian.tms.premises["ev_dispatcher@rivian"].is_assumption is True
assert tesla.tms.premises["ev_dispatcher@tesla"].is_assumption is True
```

If a downstream breaker limit or vehicle battery fault triggers a contradiction on either vehicle, `NetworkTMS.resolve_contradiction()` will trace the assumption back to `ev_dispatcher@...` and cleanly prune the invalid candidate branch.

---

## 6. Summary of Algebraic Properties

`MobileLinkPropagator` brings formal $\pi$-calculus guarantees to reactive constraint networks:

1. **Monotonicity with Scoped Retraction:** Information fusion within each active cell remains monotonic ($\sqcup$). When topological links move, non-monotonic belief revision is localized strictly to the source premise via the cell's `TruthMaintenanceSystem`.
2. **First-Class Channels:** Communication endpoints are ordinary lattice values (`FlatValue`, `DiscreteDomain`, `SetLattice`, `OrderedInterval`, or `BeliefMassValue`), enabling reasoning about routing paths using the same algebra as sensor data.
3. **No Dangling Wires:** Vacating a target automatically removes the asserted constraint, eliminating memory leaks and stale command states.

---

## 7. Deep Dive: Spatial Information Accumulation vs. Temporal Simulation

A natural question arises when viewing the hourly loop in [Section 4](#4-executable-python-implementation):

> *"In this simulation, aren't we just calculating values directly rather than accumulating partial information in cells?"*

At first glance, the discrete time loop looks like a conventional imperative script: we feed inputs for Hour $H$, run the network, and read the outputs. However, under the hood, cells are **not** passive variables or function return registers. They are **join-semilattice accumulators** operating across two fundamentally distinct physical dimensions:

1. **Spatial Constraint Accumulation (Within a Single Time Step)**
2. **Temporal State Accumulation vs. Instantaneous Flux (Across Time Steps)**

---

### Spatial Accumulation (Within a Single Time Step)

Within any given hour, no single component "calculates" the vehicle's charging power directly. Instead, multiple independent physical sources and regulatory envelopes **accumulate concurrently** into the target vehicle cell via lattice join ($\sqcup$ in information refinement order, corresponding to interval intersection $\sqcap$):

```mermaid
flowchart LR
    HW["Hardware Standby Limit<br/>[0.0, 11.5] kW<br/><i>source: hardware_envelope</i>"] -->|⊔| RivianCell["Rivian Power Cell<br/><b>Accumulated: [3.3, 3.8] kW</b>"]
    Circuit["Garage Circuit Feeder<br/>[0.0, 9.6] kW<br/><i>source: circuit_safety</i>"] -->|⊔| RivianCell
    Solar["π-Calculus Mobile Link<br/>[3.3, 4.0] kW<br/><i>source: ev_dispatcher@rivian</i>"] -->|⊔| RivianCell
    BMS["BMS Cold-Pack Pilot Limit<br/>[0.0, 3.8] kW<br/><i>source: bms_thermal</i>"] -->|⊔| RivianCell

    classDef cell fill:#2d3748,stroke:#cbd5e0,stroke-width:2px,color:#fff;
    classDef src fill:#1a365d,stroke:#63b3ed,stroke-width:2px,color:#fff;
    class RivianCell cell;
    class HW,Circuit,Solar,BMS src;
```

Mathematically, the cell computes:

$$[0.0, 11.5] \sqcap [0.0, 9.6] \sqcap [3.3, 4.0] \sqcap [0.0, 3.8] = [3.3, 3.8]\,\text{kW}$$

- **Decentralized & Multi-Directional:** The inverter did not need to know about the cold-pack BMS limit, nor did the solar splitter need to know about the circuit breaker. Each subsystem asserted its partial knowledge into the shared cell.
- **Monotonic Refinement:** As each new constraint arrives, information strictly refines ($x \sqsubseteq x \sqcup y$). The cell's bounds tighten monotonically until fixed-point quiescence is reached.

---

### Instantaneous Flux vs. State Accumulation (Across Time Steps)

Why does the simulation loop call `surplus.set_value(BOTTOM, overwrite=True)` at the beginning of each hour?

Physical variables fall into two distinct ontological categories:

| Dimension | Physical Nature | Units | Lattice Behavior Across Time | Examples |
| :--- | :--- | :---: | :--- | :--- |
| **Instantaneous Flux** | Rate of flow at time $t$ | $\text{kW}$, $\text{A}$, $\text{m/s}$ | **Non-accumulating across time.** Previous intervals are physically obsolete. Must be reset or updated for each discrete step. | Solar generation ($P_{\text{solar}}$), home baseload ($P_{\text{base}}$), charging power ($P_{\text{ev}}$) |
| **Integrated State** | Accumulated quantity over time ($Q = \int \Phi\,dt$) | $\text{kWh}$, $\text{Ah}$, $\text{m}$ | **Accumulating across time.** Monotonically aggregates or tracks state integrals. | Battery stored energy ($E$), State of Charge ($\text{SOC}$), odometer |

If instantaneous power flux were monotonically intersected across hours without resetting, the lattice would attempt to intersect disjoint intervals:

$$[3.3, 4.0]\,\text{kW}\ (11:00) \sqcap [5.5, 6.7]\,\text{kW}\ (12:00) = \top\quad (\text{Contradiction})$$

An empty interval contradiction would be declared because no physical constant power can simultaneously be both $3.5\,\text{kW}$ and $6.0\,\text{kW}$. 

Conversely, stored battery energy ($E$) **is** a true state accumulator. Across the 6-hour simulation, the Rivian energy cell integrated energy monotonically:

$$90.45\,\text{kWh}\ (67.0\%) \longrightarrow 94.10\,\text{kWh}\ (69.7\%) \longrightarrow 100.20\,\text{kWh}\ (74.2\%) \longrightarrow 106.75\,\text{kWh}\ (79.1\%)$$

---

### Truth Maintenance & Autonomous Relaxation

The combination of Milner's $\pi$-calculus link mobility with the Truth Maintenance System (TMS) provides an elegant solution to dynamic reconfiguration:

```mermaid
sequenceDiagram
    autonumber
    actor Sim as Simulation Step
    participant Disp as MobileLinkPropagator
    participant Riv as rivian_power (Cell)
    participant Tes as tesla_power (Cell)

    Note over Sim,Tes: Hour 13:00 (Rivian reaches 75% target)
    Sim->>Disp: active_vehicle = "tesla"
    Disp->>Riv: retract_source("ev_dispatcher@rivian")
    Note over Riv: TMS recalculates active premises:<br/>{hardware_envelope: [0.0, 11.5]}<br/>Rivian cleanly relaxes back to Standby!
    Disp->>Tes: assert_source("ev_dispatcher@tesla", [4.6, 5.3] kW)
    Note over Tes: TMS fuses:<br/>[0.0, 7.6] ⊓ [4.6, 5.3] = [4.6, 5.3] kW
```

In classical imperative control:
- To switch charging from Rivian to Tesla, a script must explicitly invoke `stop_charging(rivian)` or set `rivian_power = 0.0`.
- If that cleanup step fails, crashes, or is omitted, the Rivian remains stuck drawing power or locked in a stale state.

In `lattice-propagator`:
- The solar connection is an asserted **premise** (`ev_dispatcher@rivian`).
- When the active vehicle changes, `MobileLinkPropagator` simply retracts that premise.
- The Rivian cell's internal TMS automatically re-evaluates all remaining active premises (its `hardware_envelope`), cleanly relaxing the cell back to its standby bounds $[0.0, 11.5]\,\text{kW}$ with zero manual cleanup logic!


