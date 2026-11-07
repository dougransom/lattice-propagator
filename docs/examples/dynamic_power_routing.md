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

## 3. Hourly Time Series Simulation Overview

We simulate a 6-hour charging profile across the midday solar window (11:00 to 16:00):

| Hour | Solar Generation | Home Baseload | Solar Surplus | Active Target Channel<br/>*(prioritized vehicle to charge)* | Rivian Allocation & SOC | Tesla Allocation & SOC | Operational Event |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **11:00** | $[4.0, 4.5]\,\text{kW}$ | $[0.5, 0.7]\,\text{kW}$ | $[3.3, 4.0]\,\text{kW}$ | `"rivian"` | $[3.3, 4.0]\,\text{kW}$<br/>**SOC:** $[69.4\%, 70.0\%]$ | Standby ($[0.0, 7.6]\,\text{kW}$)<br/>**SOC:** $20.0\%$ | Morning solar ramp; Rivian prioritised (starts at $67.0\%$, target $75.0\%$). |
| **12:00** | $[6.5, 7.5]\,\text{kW}$ | $[0.8, 1.0]\,\text{kW}$ | $[5.5, 6.7]\,\text{kW}$ | `"rivian"` | $[5.5, 6.7]\,\text{kW}$<br/>**SOC:** $[73.5\%, 74.9\%]$ | Standby ($[0.0, 7.6]\,\text{kW}$)<br/>**SOC:** $20.0\%$ | Solar peak; Rivian continues charging toward $75.0\%$ target. |
| **13:00** | $[7.0, 7.5]\,\text{kW}$ | $[0.6, 0.8]\,\text{kW}$ | $[6.2, 6.9]\,\text{kW}$ | `"rivian"` | $[6.2, 6.9]\,\text{kW}$<br/>**SOC:** $[78.1\%, 80.0\%]$ | Standby ($[0.0, 7.6]\,\text{kW}$)<br/>**SOC:** $20.0\%$ | **Rivian reaches target ($\ge 75.0\%$)!** Battery is sufficiently charged. |
| **14:00** | $[5.5, 6.0]\,\text{kW}$ | $[0.7, 0.9]\,\text{kW}$ | $[4.6, 5.3]\,\text{kW}$ | `"tesla"` | Standby ($[0.0, 11.5]\,\text{kW}$)<br/>**SOC:** $[78.1\%, 80.0\%]$ | $[4.6, 5.3]\,\text{kW}$<br/>**SOC:** $[26.1\%, 27.1\%]$ | **$\pi$-Handoff 1:** Switched to Tesla because Rivian is satisfied! TMS retracts Rivian. |
| **15:00** | $[4.8, 5.4]\,\text{kW}$ | $[0.6, 0.8]\,\text{kW}$ | $[4.0, 4.8]\,\text{kW}$ | `"tesla"` | Standby ($[0.0, 11.5]\,\text{kW}$)<br/>**SOC:** $[78.1\%, 80.0\%]$ | $[4.0, 4.8]\,\text{kW}$<br/>**SOC:** $[31.5\%, 33.5\%]$ | **Tesla reaches target ($\ge 30.0\%$)!** Both primary vehicles now satisfied. |
| **16:00** | $[3.5, 4.0]\,\text{kW}$ | $[0.5, 0.7]\,\text{kW}$ | $[2.8, 3.5]\,\text{kW}$ | `"guest_ev"` | Standby ($[0.0, 11.5]\,\text{kW}$)<br/>**SOC:** $[78.1\%, 80.0\%]$ | Standby ($[0.0, 7.6]\,\text{kW}$)<br/>**SOC:** $[31.5\%, 33.5\%]$ | **$\pi$-Handoff 2 & $(\nu y)$ Spawning:** Both household cars satisfied; power routes to Guest EV. |

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

