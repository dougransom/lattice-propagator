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
    GaussianValue,
    KalmanEstimatorPropagator,
    PropagatorNetwork,
)

net = PropagatorNetwork("KalmanTracking")

meas = net.add_cell("Observation")
state = net.add_cell("State")
rate = net.add_cell("Rate")

# Attach a 2-State Kalman filter propagator:
kf = KalmanEstimatorPropagator(
    name="ThermalKalman",
    measurement_cell=meas,
    output_state_cell=state,
    output_rate_cell=rate,
    process_noise_q=0.1,
)
net.add_propagator(kf)

# Feed a noisy measurement: 22.0°C with sensor noise variance 0.5
meas.set_value(GaussianValue(mean=22.0, variance=0.5))
net.run()

print(f"Updated State Estimate: {state.value}")
print(f"Updated Rate Estimate: {rate.value}")
```
