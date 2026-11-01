# Example: Sensor Fusion & Kalman Filtering

Real-world sensors (temperature, humidity, presence, energy meters) produce noisy, incomplete, and asynchronous readings. `lattice-propagator` provides mathematically rigorous fusion over Gaussian lattices.

---

## 1. Static Sensor Fusion with `GaussianValue`

When two sensors observe the same physical quantity (e.g., room temperature from an HVAC thermostat and an IoT battery sensor), their estimates can be joined via Gaussian merging:

```python
from lattice_propagator import (
    PropagatorNetwork,
    GaussianValue,
    Cell,
)

net = PropagatorNetwork("SensorFusion")

# Thermostat with accurate sensor: 21.5°C, variance 0.2
thermostat = GaussianValue(mean=21.5, variance=0.2)

# Zigbee sensor with cheaper sensing element: 22.1°C, variance 0.8
zigbee = GaussianValue(mean=22.1, variance=0.8)

# Merging computes optimal inverse-variance weighted fusion:
fused = thermostat.merge(zigbee)

print(f"Fused Mean: {fused.mean:.2f}°C")  # 21.62°C
print(
    f"Fused Variance: {fused.variance:.3f}"
)  # 0.160 (Lower uncertainty than either sensor alone!)
```

---

## 2. Dynamic State Estimation with `KalmanEstimatorPropagator`

In dynamic systems, physical state changes over time according to a linear transition model, while sensors provide periodic noisy observations:

$$\hat{x}_{k|k-1} = F x_{k-1} + B u, \quad P_{k|k-1} = F P_{k-1} F^T + Q$$

```python
from lattice_propagator import (
    PropagatorNetwork,
    GaussianValue,
    KalmanEstimatorPropagator,
)

net = PropagatorNetwork("KalmanTracking")

state_cell = net.add_cell("state", GaussianValue(mean=20.0, variance=1.0))
measurement_cell = net.add_cell("measurement")
output_cell = net.add_cell("estimated_state")

# Attach a 1D discrete Kalman filter propagator:
# Process noise Q = 0.05, transition factor F = 1.0 (random walk)
kalman = KalmanEstimatorPropagator(
    name="ThermalKalman",
    state_cell=state_cell,
    measurement_cell=measurement_cell,
    output_cell=output_cell,
    f_factor=1.0,
    q_noise=0.05,
)
net.add_propagator(kalman)

# Feed a noisy measurement: 22.0°C with sensor noise R = 0.5
measurement_cell.set_value(GaussianValue(mean=22.0, variance=0.5))
net.run()

print(f"Updated Estimate: {output_cell.value}")
```
