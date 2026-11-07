# Example: Interval Envelopes & Bounds

Interval arithmetic bounds uncertainty within guarantees $[x_{\min}, x_{\max}]$. When multiple constraints or safety margins apply, propagator networks narrow interval envelopes monotonically.

---

## 1. Safety Tolerances & Envelopes

Consider calculating allowable power consumption bounds in a home energy system:

```python
from lattice_propagator import (
    PropagatorNetwork,
    IntervalValue,
    AdderPropagator,
)

net = PropagatorNetwork("EnergyEnvelope")

heat_pump = net.add_cell("heat_pump", IntervalValue(1200.0, 2500.0))  # 1.2 kW – 2.5 kW
ev_charger = net.add_cell("ev_charger", IntervalValue(3000.0, 7200.0))  # 3.0 kW – 7.2 kW
total_power = net.add_cell("total_power")

# Total power = Heat Pump + EV Charger
net.add_propagator(AdderPropagator("SumPower", heat_pump, ev_charger, total_power))
net.run()

print(f"Total Power Envelope: {total_power.value}")
# IntervalValue(4200.0, 9700.0)

# Suppose the main breaker limits total power to at most 8000W:
total_power.set_value(IntervalValue(0.0, 8000.0))
net.run()

print(f"Constrained Total: {total_power.value}")  # IntervalValue(4200.0, 8000.0)
print(f"EV Charger Max Allowed: {ev_charger.value}")  # IntervalValue(3000.0, 6800.0)

# Export and persist network diagrams
from pathlib import Path

assets_dir = Path("docs/assets")
if assets_dir.is_dir():
    (assets_dir / "intervals_energy_envelope.mmd").write_text(
        net.generate_mermaid(), encoding="utf-8"
    )
    (assets_dir / "intervals_energy_envelope.dot").write_text(net.generate_dot(), encoding="utf-8")
```

The network automatically deduced that the EV charger cannot exceed 6,800 Watts without violating the total service capacity.

### Energy Envelope Network Topology & Bounds

The multi-directional adder continuously propagates the service breaker restriction backward into the individual circuit allocations:

```mermaid
graph LR
  classDef bottom fill:#f8f9fa,stroke:#adb5bd,stroke-dasharray: 4 4,color:#6c757d;
  classDef contradiction fill:#fff5f5,stroke:#e53e3e,stroke-width:2px,color:#9b2c2c;
  classDef interval fill:#ebf8ff,stroke:#3182ce,stroke-width:1.5px;
  classDef gaussian fill:#f0fff4,stroke:#38a169,stroke-width:1.5px;
  classDef discrete fill:#faf5ff,stroke:#805ad5,stroke-width:1.5px;
  classDef cell fill:#edf2f7,stroke:#4a5568,stroke-width:1.5px;
  classDef value fill:#edf2f7,stroke:#4a5568,stroke-width:1.5px;
  classDef set fill:#faf5ff,stroke:#805ad5,stroke-width:1.5px;
  classDef belief fill:#f0fff4,stroke:#38a169,stroke-width:1.5px;
  classDef propagator fill:#f7fafc,stroke:#2d3748,stroke-width:1.5px;
  C_ev_charger["ev_charger<br/>[3000.00, 6800.00]"]:::interval
  C_heat_pump["heat_pump<br/>[1200.00, 2500.00]"]:::interval
  C_total_power["total_power<br/>[4200.00, 8000.00]"]:::interval
  P_SumPower["SumPower"]:::propagator
  C_heat_pump --> P_SumPower
  C_ev_charger --> P_SumPower
  C_total_power --> P_SumPower
  P_SumPower --> C_heat_pump
  P_SumPower --> C_ev_charger
  P_SumPower --> C_total_power
```

#### Downloadable Diagram Assets
- [Mermaid Diagram Source (`intervals_energy_envelope.mmd`)](../assets/intervals_energy_envelope.mmd)
- [Graphviz DOT Specification (`intervals_energy_envelope.dot`)](../assets/intervals_energy_envelope.dot)

---

## 2. Detecting Contradictions

If constraints become mutually unsatisfiable (for instance, if minimum demand exceeds maximum breaker limit), the merge operation yields `Contradiction`:

```python
from lattice_propagator import IntervalValue

safe_range = IntervalValue(10.0, 20.0)
required_power = IntervalValue(30.0, 50.0)

result = safe_range.merge(required_power)
print(result)  # ⊤(Contradiction: Disjoint intervals: [10.0, 20.0] and [30.0, 50.0])
```
