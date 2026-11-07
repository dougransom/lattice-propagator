# Example: Kinematic Reachability Envelopes

In robotics, autonomous driving, and industrial automation, safety guarantees require verifying that an actuator can reach a safe state or stop before reaching an obstacle boundary.

Using partial-information lattices:
- Unknown or uncertain physical quantities are bounded by [`IntervalValue`](file:///home/doug/code/lattice-propagator/docs/api/lattice.md) $[x_{min}, x_{max}]$.
- Dynamic tracking is handled by [`RatePropagator`](file:///home/doug/code/lattice-propagator/docs/api/primitives.md), which computes rate of change $\dot{x}$ and Estimated Time of Arrival (ETA) intervals to a safety threshold.
- Kinematic stopping distances $\Delta x_{stop} = \frac{v^2}{2a}$ provide guaranteed bounds over partial knowledge.

---

## 1. Timeline & Reachability Corridor (Human View)

```mermaid
gantt
    title Kinematic Braking Corridor & Safety Envelopes
    dateFormat X
    axisFormat %s s

    section Radar Tracking
    Sensor Detection (100 m)  :active, 0, 1
    Velocity Estimation (-20 m/s) :crit, 1, 1

    section Stopping Envelope
    Reaction Interval (0.5 - 0.8s) : 1, 2
    Deceleration to Stop (3.4 - 4.8s) : 2, 5
```

---

## 2. Executable Propagator Implementation

```python
from lattice_propagator import (
    GaussianValue,
    IntervalValue,
    PropagatorNetwork,
    RatePropagator,
)

net = PropagatorNetwork("KinematicRadarTracking")

# Radar distance to approaching obstacle (meters)
dist = net.add_cell("dist", unit="m")

# Estimated approach velocity (m/s) and time to impact threshold (0.0 m)
velocity = net.add_cell("velocity", unit="m/s")
eta_collision = net.add_cell("eta_collision", unit="s")

# Register RatePropagator watching distance to zero-distance threshold
tracker = RatePropagator(
    "RadarTracker",
    input_cell=dist,
    output_rate_cell=velocity,
    output_eta_cell=eta_collision,
    threshold=0.0,
)
net.add_propagator(tracker)

# Observation 1: at t = 0.0 s, distance is measured at 100.0 m
tracker.update_observation(current_val=100.0, current_time=0.0, network=net)

# Observation 2: at t = 1.0 s, distance is measured at 80.0 m
tracker.update_observation(current_val=80.0, current_time=1.0, network=net)
net.run()

# Text output for LLMs & inspection
print(f"Computed approach velocity: {velocity.value}")
print(f"Collision ETA interval: {eta_collision.value}")

assert isinstance(velocity.value, GaussianValue)
assert abs(velocity.value.mean - (-20.0)) < 1e-4

assert isinstance(eta_collision.value, IntervalValue)
# For approaching velocity rate=-20 m/s from 80 m, baseline ETA = 4.0 s
# Spread envelope covers [3.4 s, 4.8 s]
print(f"Safe braking margin: minimum {eta_collision.value.min_val:.2f} s remaining.")
assert 3.0 <= eta_collision.value.min_val <= 3.5
assert 4.5 <= eta_collision.value.max_val <= 5.0

# Export and persist network diagrams
from pathlib import Path

assets_dir = Path("docs/assets")
if assets_dir.is_dir():
    (assets_dir / "kinematics_radar_tracker.mmd").write_text(
        net.generate_mermaid(), encoding="utf-8"
    )
    (assets_dir / "kinematics_radar_tracker.dot").write_text(net.generate_dot(), encoding="utf-8")
```

---

## 3. Kinematic Radar Network Topology & Live Visualization

The `RatePropagator` estimates the approach velocity distribution (as a `GaussianValue`) and projects collision ETA bounds (as an `IntervalValue`):

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
  C_dist["dist<br/>⊥"]:::bottom
  C_eta_collision["eta_collision<br/>[3.40, 4.80]s"]:::interval
  C_velocity["velocity<br/>-20.00 ± 2.77m/s"]:::gaussian
  P_RadarTracker["RadarTracker"]:::propagator
  C_dist --> P_RadarTracker
  P_RadarTracker --> C_velocity
  P_RadarTracker --> C_eta_collision
```

### Downloadable Diagram Assets
- [Mermaid Diagram Source (`kinematics_radar_tracker.mmd`)](../assets/kinematics_radar_tracker.mmd)
- [Graphviz DOT Specification (`kinematics_radar_tracker.dot`)](../assets/kinematics_radar_tracker.dot)
