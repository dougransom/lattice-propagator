# Example: Time-of-Day Clock Intervals & Overnight Energy Scheduling

In home automation, energy management, and transit scheduling, time constraints frequently cross the midnight boundary (e.g. 23:00 to 07:00).

In standard linear interval arithmetic, intervals are strictly ordered with $min \le max$; an overnight window like $[23.0, 7.0]$ is considered invalid or inverted.

The lattice propagator framework solves this with [`CircularInterval`](file:///home/doug/code/lattice-propagator/docs/api/lattice.md) on the circle topology $S^1 / (24 \times \mathbb{Z})$:
- Represents directed arcs sweeping clockwise from $start$ to $end$ modulo a period (here $24.0\text{ hours}$).
- Preserves the join-semilattice algebraic laws (associativity, commutativity, idempotence, and monotonicity) under monotonic intersection ($\sqcap$).
- Seamlessly controls reactive actuators via [`SwitchPropagator`](file:///home/doug/code/lattice-propagator/docs/api/primitives.md).

---

## 1. The Overnight EV Charging Problem

An Electric Vehicle (EV) must be charged overnight subject to three independent real-world constraints:
1. **Super-Off-Peak Tariff Window:** Inexpensive overnight electricity rate runs from **23:00 to 07:00** ($[23.0, 7.0]\pmod{24}$, duration $8.0\text{ h}$).
2. **Vehicle Home Presence:** The homeowner arrives home at **21:30** and departs for work at **06:30** ($[21.5, 6.5]\pmod{24}$, duration $9.0\text{ h}$).
3. **Grid Demand-Response Curtailment:** The local utility issues a peak load-shedding hold until **00:30** (charging is only permitted in $[0.5, 18.0]\pmod{24}$).

The autonomous propagator network must fuse these partial policies, determine the exact allowed charging corridor across the midnight cut, and conditionally energize the EV charger.

---

## 2. 24-Hour Circular Dial & Architecture (Human View)

![24-Hour Circular EV Charging Interval Dial](../assets/circular_clock_ev.svg)

```mermaid
graph TD
    T["Tariff Window: [23:00, 07:00]"] -->|"source='tariff'"| C["Cell: charging_corridor<br/>[00:30, 06:30] (mod 24)"]
    P["Presence Window: [21:30, 06:30]"] -->|"source='presence'"| C
    G["Grid Policy: [00:30, 18:00]"] -->|"source='grid'"| C

    C -->|"contains(current_time)"| SW_CTRL["Cell: charger_enable<br/>(FlatValue: True / False)"]
    PWR["Nominal Rate: [7.0, 7.4] kW"] --> SW["SwitchPropagator: EV_Gating"]
    SW_CTRL --> SW
    SW --> OUT["Delivered Power: [7.0, 7.4] kW or 0 kW"]
```

---

## 3. 24-Hour Timeline Ribbon (LLM / Terminal View)

```text
24-Hour Circular Modulo-24 Timeline:
Hour:      00 01 02 03 04 05 06 07 08 09 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24
Tariff:    [===================]                                                 [===]
Presence:              [===]                                           [=============]
Grid:      . [====================================================]
Corridor:  . [===============] . . . . . . . . . . . . . . . . . . . . . . . . . . .
           ↑ 00:30       ↑ 06:30 (Charging Corridor: 6.0 h)
```

---

## 4. Executable Propagator Implementation

```python
from lattice_propagator import (
    CircularInterval,
    Contradiction,
    FlatValue,
    IntervalValue,
    PropagatorNetwork,
    SwitchPropagator,
)

# ==========================================
# Phase 1: Modular Interval Fusion in a Reactive Cell
# ==========================================
net = PropagatorNetwork("OvernightEVScheduler")

# Reactive cell holding the consolidated charging corridor
charging_cell = net.add_cell(
    "charging_corridor",
    unit="h",
    display_name="Consolidated Charging Corridor",
)

# 1. Assert utility off-peak tariff: 23:00 to 07:00 (wraps midnight)
charging_cell.set_value(
    CircularInterval(start=23.0, end=7.0, modulus=24.0),
    source="tariff_policy",
)

# 2. Assert vehicle presence: home at 21:30, depart at 06:30 (wraps midnight)
charging_cell.set_value(
    CircularInterval(start=21.5, end=6.5, modulus=24.0),
    source="homeowner_presence",
)

# 3. Assert utility demand-response hold: charging prohibited until 00:30
charging_cell.set_value(
    CircularInterval(start=0.5, end=18.0, modulus=24.0),
    source="grid_curtailment",
)

corridor = charging_cell.value
assert isinstance(corridor, CircularInterval)

print(f"Refined Charging Corridor: {corridor}")
print(f"Corridor Start: {corridor.start:.1f}h (00:30), End: {corridor.end:.1f}h (06:30)")
print(f"Available Charging Duration: {corridor.length:.1f} hours")

assert abs(corridor.start - 0.5) < 1e-4
assert abs(corridor.end - 6.5) < 1e-4
assert abs(corridor.length - 6.0) < 1e-4

# Inspect causal provenance explanation
print("\n--- TMS Fusion Explanation ---")
print(charging_cell.explain())

# ==========================================
# Phase 2: Actuation Control via SwitchPropagator
# ==========================================
# Nominal Level-2 charging power interval [7.0, 7.4] kW
nominal_power = net.add_cell("nominal_power", IntervalValue(7.0, 7.4), unit="kW")
enable_switch = net.add_cell("enable_switch", unit="")
delivered_power = net.add_cell("delivered_power", unit="kW")

# SwitchPropagator gates nominal_power to delivered_power only when enable_switch is True
net.add_propagator(
    SwitchPropagator(
        "EV_Contactor",
        control_cell=enable_switch,
        input_cell=nominal_power,
        output_cell=delivered_power,
        on_value=True,
    )
)

# Query Test 1: At 02:00 (inside charging corridor)
time_night = 2.0
is_active_night = corridor.contains(time_night)
enable_switch.set_value(FlatValue(is_active_night), overwrite=True)
net.run()

print(f"\nClock = {time_night:04.1f}h (Within Corridor):")
print(f"  Contactor Enabled: {is_active_night}")
print(f"  Delivered Charging Power: {delivered_power.value}")
assert is_active_night is True
assert isinstance(delivered_power.value, IntervalValue)
assert abs(delivered_power.value.min_val - 7.0) < 1e-4

# Query Test 2: At 22:00 (outside corridor, evening peak)
time_evening = 22.0
is_active_evening = corridor.contains(time_evening)
enable_switch.set_value(FlatValue(is_active_evening), overwrite=True)
delivered_power.value = IntervalValue(0.0, 0.0)
net.run()

print(f"\nClock = {time_evening:04.1f}h (Evening Peak):")
print(f"  Contactor Enabled: {is_active_evening}")
print(f"  Delivered Charging Power: {delivered_power.value}")
assert is_active_evening is False
assert delivered_power.value == IntervalValue(0.0, 0.0)

# Energy Delivered: 6.0 h × [7.0, 7.4] kW = [42.0, 44.4] kWh
min_energy = corridor.length * delivered_power.value.min_val
print(f"\nTotal Potential Energy Delivered during Corridor: {6.0 * 7.2:.1f} kWh")
```
