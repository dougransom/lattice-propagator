# Event Buses, Node-RED, $\pi$-Calculus & Lattice Propagators

Building and home automation platforms have evolved through distinct computational models. Understanding how **Event Buses** (Home Assistant Core), **Flow-Based Programming** (Node-RED / Kahn Process Networks), **$\pi$-Calculus Process Mobility** (Robin Milner / Microsoft BizTalk XLANG), and **Lattice Propagator Networks** relate—and where each hits architectural limits—clarifies why combining **partial-information lattices ($\sqcup$)** with **$\pi$-calculus link mobility** produces a uniquely resilient control plane for smart buildings.

---

## 1. Evolution of Building Automation Paradigms

### 1.1 Generation 1: Event Buses & Flat State Machines (Home Assistant Core)

At its core, **Home Assistant (`ha`)** is built around an asynchronous **`EventBus`** and a flat key-value **`StateMachine`**:

1. **Destructive Overwrite vs. Monotonic Join ($\sqcup$):**
   Every entity (`sensor.office_temp`, `climate.living_room`) stores a single string `state` and an `attributes` dictionary. When a new reading or service call arrives, `hass.states.async_set(entity_id, new_state)` **destructively overwrites** the previous state and emits a `state_changed` event.
   - If two room sensors disagree (`21.0 °C ± 0.5 °C` vs. `22.2 °C ± 1.5 °C`), Home Assistant has no native algebraic merge ($\sqcup$) on the entity itself; you must build a separate helper integration (`min_max`, `kalman`, or a template sensor).
   - If three automations (`comfort`, `solar_preheat`, `demand_response`) call `climate.set_temperature` on the same thermostat, **the last service call wins** and silently clobbers the others.
2. **Lack of Premise Retraction:**
   When a temporary condition ends (e.g., a window closes or peak-tariff shedding finishes), the state table does not remember *which* policies are still active. Automations must manually snapshot and restore state via ad-hoc `scene.create` workarounds—which break if another policy changed in the interim.
3. **One-Way Rules (`Trigger → Condition → Action`):**
   Home Assistant automations are imperative, one-way reactions to point-in-time events rather than bidirectional constraints ($P = V \times I$).
4. **No Fixed-Point Quiescence Barrier:**
   Cascading template sensors re-evaluate immediately as each upstream `state_changed` event fires, exposing transient intermediate "glitches" to downstream automations unless masked with arbitrary `for: 00:00:05` debounce timers.

---

### 1.2 Generation 2: Flow-Based Programming (Node-RED & Kahn Process Networks)

**Node-RED** implements J. Paul Morrison's **Flow-Based Programming (FBP)**, a cousin of Gilles Kahn's **Kahn Process Networks (KPN)**:

- **Visual Topology:** Unlike Home Assistant's flat list of YAML automations, Node-RED makes the dataflow graph explicit: black-box processing nodes connected by directed wires.
- **Stateless Wires & Ephemeral `msg` Packets:**
  In Node-RED, wires have **no memory**, and nodes do **not** hold a persistent lattice value. Instead, discrete JSON objects (`msg = { payload: 21.5, topic: "temp" }`) travel down wires as point-in-time impulses and vanish once consumed.

Because Node-RED routes *ephemeral packets* rather than maintaining *monotonic stateful cells*, four classic failure modes emerge in building automation:

1. **The Multi-Input Join Trap:**
   Because wires are stateless, a Node-RED node cannot simply inspect `input_a + input_b`. If a function node receives a `temperature` message on one wire and a `humidity` message on another, it only sees **one `msg` at a time**. To combine them, you must insert manual `Join` nodes or stash values in imperative `flow.set()` / `context.set()` variables—reintroducing mutable shared state and race conditions.
2. **Competing Flows Still Clobber Each Other:**
   If a "Presence Flow" sends `msg.payload = 21` and an "Eco Flow" sends `msg.payload = 18` into the same `call-service` node, the last packet to arrive overwrites the thermostat. There is no lattice join ($\sqcup$) intersecting `[20 °C, 24 °C] ⊔ [18 °C, 22 °C] → [20 °C, 22 °C]`, nor a [`Contradiction`](../api/lattice.md) ($\top$) detector when policies become mutually exclusive.
3. **Glitches & Diamond Topologies:**
   If one upstream event splits across two parallel branches of different lengths before converging on an actuator node, the actuator fires **twice**—once with a half-updated state and a millisecond later with the settled state—whereas [`PropagatorNetwork.run()`](../api/primitives.md) drains its internal worklist to a **quiescent fixed point** before actuating hardware.
4. **Static Graph Topology & Loop Fragility:**
   Feedback loops in Node-RED pass discrete messages around a cycle indefinitely unless manually guarded by `rbe` (Report by Exception) nodes. Even in pure **Kahn Process Networks** (where channels are unbounded FIFO queues with blocking reads, forming a Scott domain over prefix-ordered *event histories*), the **network topology is completely static** and wires remain 1-way point-to-point pipes.

---

### 1.3 Generation 3: Process Calculi & Link Mobility ($\pi$-Calculus & Microsoft BizTalk XLANG)

Why did **Microsoft BizTalk Server** use Robin Milner's **$\pi$-calculus** (via the **XLANG** orchestration engine designed by Satish Thatte) instead of standard Flow-Based Programming?

In a classical **Kahn Process Network** or **Node-RED** flow, the wiring diagram is fixed at design time. In distributed enterprise workflows—and in physical smart buildings—**who talks to whom changes dynamically at runtime**:

- **The $\pi$-Calculus Core Idea (Link Mobility):**
  In Milner's $\pi$-calculus, there is no distinction between "data values" and "channel names" (wires). Processes communicate by sending channel names *over* channels:
  - $c!\langle x \rangle . P$: Send the channel name $x$ over channel $c$, then continue as $P$.
  - $c?(y) . Q$: Receive a channel name on $c$, bind it to $y$, and now $Q$ can communicate directly over $y$—**dynamically rewiring the network graph at runtime**.
  - $(\nu x) P$: **Restriction (Name Creation)**—mint a brand-new, private channel $x$ scoped to a new session or interaction.

- **What BizTalk Server Actually Did with $\pi$-Calculus:**
  1. **Dynamic Partner Binding (Port Passing):** A purchasing orchestration didn't hardcode a wire to a specific shipper. A supplier replied with a callback endpoint reference ($c!\langle \text{shipper\_port} \rangle$), and the orchestration dynamically bound its shipping port to that reference.
  2. **$(\nu x)$ Session Spawning & Correlation Sets:** When 10,000 purchase orders arrived over the same HTTP port, BizTalk spawned a fresh orchestration instance with a restricted correlation token $(\nu\,\text{order\_id})$—routing subsequent invoices and shipping notices to that specific stateful instance.
  3. **Long-Running Hydration & Compensation:** Because business processes wait days for human approval, BizTalk serialized process state to SQL Server ("dehydration") and defined compensating transactions when downstream steps failed.

- **Why Smart Buildings Have $\pi$-Calculus Topology:**
  A physical building is full of **mobile processes** that move between **spatial zones**:
  - **Occupant Mobility:** When `person.doug` walks from the `office` to the `kitchen`, the room presence sensor (`room.office.occupants`) emits the entity name `"doug"`. The office's comfort target should **bind** to `doug.preferred_temp` while Doug is present, and **unbind** the instant Doug walks into the kitchen.
  - **EV & Smart Appliance Plug-In ($(\nu x)$ Restriction):** When an electric vehicle plugs into `charger_bay_2`, the bay discovers a vehicle (`"rivian_r1s"`), dynamically spawns its state cells (`rivian_r1s.target_soc`, `rivian_r1s.current`), and splices them into the garage sub-panel's bidirectional amperage constraint.

---

### 1.4 Generation 4: Lattice Propagator Networks with $\pi$-Calculus Mobility

By elevating **channel names** into the partial-information lattice inside [`MobileLinkPropagator`](../api/primitives.md), `lattice-propagator` unifies **Milner's $\pi$-calculus link mobility** with **Sussman & Radul's monotonic lattice propagators** and **Truth Maintenance (`NetworkTMS`)**:

| Architectural Dimension | Home Assistant (`EventBus` + `StateMachine`) | Node-RED (Flow-Based Programming) | BizTalk / $\pi$-Calculus (XLANG) | `lattice-propagator` (Propagators + $\pi$-Mobility + TMS) |
| :--- | :--- | :--- | :--- | :--- |
| **Primary Abstraction** | Event bus + flat key-value state table | Directed graph of nodes passing ephemeral `msg` packets | Concurrent processes passing channel names ($c!\langle x\rangle$) | Stateful [`Cell`](../api/primitives.md)s holding lattices ($\sqcup$) wired by multidirectional [`Propagator`](../api/primitives.md)s |
| **State Merge Semantics** | Destructive overwrite (`last-write-wins`) | Stateless wires; manual `Join` or mutable `flow.context` | Message correlation into isolated process state | Monotonic algebraic join ($x \sqcup y$: interval $\cap$, precision-weighted Gaussian, Dempster-Shafer $\oplus$) |
| **Directionality** | 1-way (`Trigger → Condition → Action`) | 1-way directed wires (`Input → Output`) | 2-way request/response & callback ports | **Multidirectional constraints** ($a + b = c$ solves for $a$, $b$, or $c$) |
| **Dynamic Topology (Mobility)** | Static entity IDs; manual template indirection | Static wiring diagram drawn in editor | **Native link mobility** ($c!\langle x \rangle$) & $(\nu x)$ session spawning | **Lattice-driven link mobility** ([`MobileLinkPropagator`](../api/primitives.md)) over exact, uncertain, or multi-target cells |
| **Ambiguous Routing** | Impossible (single string state) | Manual `Switch` cloning packets | Non-deterministic single choice ($P + Q$) | **Superposition routing** (`DiscreteDomain({"office", "kitchen"})` links *both* zones with TMS assumptions) |
| **Rollback & Conflict Resolution** | Manual `scene.create` snapshots | Manual state tracking nodes | Explicit compensation blocks | Automatic **Premise Retraction** ([`retract_source`](../api/primitives.md)) & **Dependency-Directed Backtracking** ([`NetworkTMS`](../api/tms.md)) |
| **Execution Barrier** | Immediate event cascades (glitches) | Immediate packet forwarding | Step-by-step orchestration | **Worklist fixed-point quiescence** ([`net.run()`](../api/primitives.md)) before hardware actuation |

---

## 2. Core Architectural Patterns in Code

The following executable examples demonstrate how `lattice-propagator` solves building automation problems that require intricate workarounds in Home Assistant YAML or Node-RED flows.

### 2.1 $\pi$-Calculus Occupant Mobility & Multi-Policy Zone Arbitration

In $\pi$-calculus, when a room's occupancy channel receives an occupant identifier $c?(y)$, the room links its comfort constraint to $y$'s personal thermal preference cell. Even better, if **multiple occupants** (`{"doug", "alice"}`) enter the same room (`SetLattice` or `DiscreteDomain`), [`MobileLinkPropagator`](../api/primitives.md) binds **both** occupants' preference envelopes simultaneously and intersects them ($\sqcup$) with the building's safety bounds—automatically unbinding each occupant when they leave the room:

```python
from lattice_propagator import (
    BOTTOM,
    DiscreteDomain,
    IntervalValue,
    MobileLinkPropagator,
    PropagatorNetwork,
)

net = PropagatorNetwork("SmartHomePiMobility")

# 1. Room target temperature cells with always-active building Eco/Safety bounds [16.0°C, 28.0°C]
office_target = net.add_cell("zone.office", unit="°C")
kitchen_target = net.add_cell("zone.kitchen", unit="°C")
office_target.set_value(IntervalValue(16.0, 28.0), source="policy.eco_safety")
kitchen_target.set_value(IntervalValue(16.0, 28.0), source="policy.eco_safety")

# 2. Occupant preference profiles & BLE location channels
doug_pref = net.add_cell("person.doug.temp_pref", IntervalValue(20.0, 23.0), unit="°C")
doug_loc = net.add_cell("person.doug.location")

alice_pref = net.add_cell("person.alice.temp_pref", IntervalValue(21.5, 24.5), unit="°C")
alice_loc = net.add_cell("person.alice.location")

# 3. π-Calculus Mobile Links: route each occupant's comfort envelope to their current room
zones = {"office": office_target, "kitchen": kitchen_target}
net.add_propagator(MobileLinkPropagator("link.doug", doug_loc, doug_pref, targets=zones))
net.add_propagator(MobileLinkPropagator("link.alice", alice_loc, alice_pref, targets=zones))

# Step A: Doug enters the office alone → Office binds to Doug's [20.0°C, 23.0°C]
doug_loc.set_value(DiscreteDomain.single("office"), overwrite=True)
net.run()
print(f"Office (Doug only): {office_target.value}")
assert office_target.value == IntervalValue(20.0, 23.0)

# Step B: Alice joins Doug in the office → Office intersects Doug ⊔ Alice = [21.5°C, 23.0°C]
alice_loc.set_value(DiscreteDomain.single("office"), overwrite=True)
net.run()
print(f"Office (Doug ⊔ Alice): {office_target.value}")
assert office_target.value == IntervalValue(21.5, 23.0)

# Step C: Doug moves to the kitchen and Alice leaves the building (⊥)
# → Office automatically retracts back to [16.0°C, 28.0°C] Eco bounds, Kitchen binds to Doug!
doug_loc.set_value(DiscreteDomain.single("kitchen"), overwrite=True)
alice_loc.set_value(BOTTOM, overwrite=True)
net.run()

print(f"Office (Vacated): {office_target.value}")
print(f"Kitchen (Doug entered): {kitchen_target.value}")
assert office_target.value == IntervalValue(16.0, 28.0)
assert kitchen_target.value == IntervalValue(20.0, 23.0)
```

---

### 2.2 Uncertainty-Aware Link Mobility & Defeasible Pre-Conditioning

Indoor Bluetooth Low Energy (BLE) RSSI triangulation is noisy near walls. Suppose an ESPHome BLE proxy narrows `doug_loc` to a [`DiscreteDomain`](../api/lattice.md) of `{"office", "server_room"}`, and we want to **speculatively pre-condition** candidate rooms (`propagate_ambiguous=True`) without violating strict equipment cooling limits in the server room (`[15.0 °C, 19.0 °C]`):

- When [`MobileLinkPropagator`](../api/primitives.md) sees an ambiguous channel (`len(candidates) > 1`) with `propagate_ambiguous=True`, it automatically projects speculative premises as defeasible assumptions (`is_assumption=True`) with scaled confidence (`confidence / len(candidates)`).
- In the `office`, Doug's `[21.0 °C, 23.0 °C]` preference merges cleanly with the office's `[16.0 °C, 28.0 °C]` eco envelope.
- In the `server_room`, Doug's `[21.0 °C, 23.0 °C]` preference collides with the hard `[15.0 °C, 19.0 °C]` equipment cooling requirement, raising a [`Contradiction`](../api/lattice.md) ($\top$) that [`NetworkTMS.resolve_contradiction()`](../api/tms.md) immediately resolves by retracting the speculative assumption while keeping the ground cooling policy intact!

```python
from lattice_propagator import (
    Contradiction,
    DiscreteDomain,
    IntervalValue,
    MobileLinkPropagator,
    NetworkTMS,
    PropagatorNetwork,
)

net = PropagatorNetwork("SpeculativePreconditioning")
ntms = NetworkTMS(net)

# Two adjacent rooms with very different base policies
office_temp = net.add_cell("room.office.temp", unit="°C")
server_temp = net.add_cell("room.server_room.temp", unit="°C")
ntms.get_or_create_cell_tms("room.office.temp")
ntms.get_or_create_cell_tms("room.server_room.temp")

office_temp.set_value(IntervalValue(16.0, 28.0), source="policy.office_eco")
server_temp.set_value(IntervalValue(15.0, 19.0), source="policy.server_cooling_safety")

# Doug's comfort preference: [21.0°C, 23.0°C] & ambiguous BLE location cell
doug_pref = net.add_cell("person.doug.pref", IntervalValue(21.0, 23.0), unit="°C")
doug_loc = net.add_cell("ble.doug_location")

net.add_propagator(
    MobileLinkPropagator(
        "link.doug",
        channel_cell=doug_loc,
        payload_cell=doug_pref,
        targets={"office": office_temp, "server_room": server_temp},
        confidence=0.8,
        propagate_ambiguous=True,
    )
)

# BLE proxy reports Doug is near the wall between office and server_room
doug_loc.set_value(DiscreteDomain({"office", "server_room"}), overwrite=True)
net.run()

# Office pre-warms to [21.0°C, 23.0°C], while Server Room flags a Contradiction (⊤)
print(f"Office pre-conditioned: {office_temp.value}")
print(f"Server Room before TMS resolution: {server_temp.value}")
assert office_temp.value == IntervalValue(21.0, 23.0)
assert isinstance(server_temp.value, Contradiction)

# NetworkTMS automatically blames the speculative mobile link into server_room
victim = ntms.resolve_contradiction(server_temp.tms.active_sources)
print(f"Retracted assumption: {victim} → Server Room restored to: {server_temp.value}")
assert victim == "link.doug@server_room"
assert server_temp.value == IntervalValue(15.0, 19.0)
assert office_temp.value == IntervalValue(21.0, 23.0)
```

---

### 2.3 Dynamic $(\nu x)$ Session Spawning & Bidirectional Panel Load Budgeting

In $\pi$-calculus, the restriction operator $(\nu x) P$ dynamically allocates a fresh channel $x$ when a new session begins. Setting `spawn_missing=True` on [`MobileLinkPropagator`](../api/primitives.md) brings $(\nu x)$ cell creation to `lattice-propagator`, while [`AdderPropagator`](../api/primitives.md) enforces **bidirectional** electrical load balancing ($I_{\text{panel}} = I_{\text{heat\_pump}} + I_{\text{ev\_bay}}$):

- Unlike a 1-way Home Assistant automation or Node-RED flow, the **same** [`AdderPropagator`](../api/primitives.md) both:
  1. **Deduces the maximum safe EV charging current** backward from the 40 A main breaker limit and the heat pump's current draw ($I_{\text{ev\_bay}} = I_{\text{panel}} - I_{\text{heat\_pump}}$), and
  2. **Pushes that dynamically computed amperage budget into the newly spawned EV session cell** `ev.rivian_r1s.max_amps` via the mobile link!

```python
from lattice_propagator import (
    AdderPropagator,
    FlatValue,
    IntervalValue,
    MobileLinkPropagator,
    PropagatorNetwork,
)

net = PropagatorNetwork("DynamicEVLoadBudget")

# 1. Electrical sub-panel constraint: I_heat_pump + I_ev_bay = I_panel
panel_amps = net.add_cell("panel.total_amps", IntervalValue(0.0, 40.0), unit="A")
heat_pump_amps = net.add_cell("hvac.heat_pump_amps", IntervalValue(12.0, 16.0), unit="A")
ev_bay_budget = net.add_cell("evse.bay_1_budget", IntervalValue(0.0, 32.0), unit="A")

net.add_propagator(AdderPropagator("panel_load_balance", heat_pump_amps, ev_bay_budget, panel_amps))

# 2. π-Calculus (νx) Mobile Link: when an EV plugs into Bay 1, spawn its session cell
#    and route the bay's dynamically deduced amperage budget to the vehicle
plugged_vehicle = net.add_cell("evse.bay_1_vehicle_id")

net.add_propagator(
    MobileLinkPropagator(
        "ev_session_spawner",
        channel_cell=plugged_vehicle,
        payload_cell=ev_bay_budget,
        spawn_missing=True,
    )
)

# Plug in "ev.rivian_r1s.max_amps" → dynamically spawns the cell in net.cells and computes safe current
plugged_vehicle.set_value(FlatValue("ev.rivian_r1s.max_amps"), source="evse.plug_sense")
net.run()

rivian_cell = net.cells["ev.rivian_r1s.max_amps"]
print(f"Spawned session cell '{rivian_cell.cell_id}': {rivian_cell.value}")
# Panel [0, 40] A − Heat Pump [12, 16] A = [0, 28] A (intersected with [0, 32] A bay limit)
assert rivian_cell.value == IntervalValue(0.0, 28.0)

# When the heat pump ramps up to [20.0 A, 24.0 A] during a cold snap,
# the EV session budget automatically tightens to [0.0 A, 20.0 A]:
heat_pump_amps.set_value(IntervalValue(20.0, 24.0), source="hvac.cold_snap_stage2", overwrite=True)
net.run()
print(f"EV budget during heat pump stage 2: {rivian_cell.value}")
assert rivian_cell.value == IntervalValue(0.0, 20.0)
```
