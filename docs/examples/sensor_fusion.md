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

### Mathematical Interpretation

The join operation $\mathcal{N}(\mu_1, \sigma_1^2) \sqcup \mathcal{N}(\mu_2, \sigma_2^2)$ implements optimal Bayesian inverse-variance fusion:

$$\frac{1}{\sigma_{\text{fused}}^2} = \frac{1}{\sigma_1^2} + \frac{1}{\sigma_2^2}, \quad \mu_{\text{fused}} = \sigma_{\text{fused}}^2 \left(\frac{\mu_1}{\sigma_1^2} + \frac{\mu_2}{\sigma_2^2}\right)$$

Notice that the resulting variance ($0.160$) is strictly less than either sensor's variance alone ($0.200$ and $0.800$), illustrating that combining independent partial information sources monotonically reduces uncertainty.

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

# 1. Initial measurement from Zigbee sensor at t=0: 22.0°C (sensor variance 0.5)
meas.set_value(GaussianValue(mean=22.0, variance=0.5))
net.run()

print(f"Initial State: {state.value}")
# Gaussian(μ=22.000, σ²=0.5000)
print(f"Initial Rate: {rate.value}")
# Gaussian(μ=0.000, σ²=1.0000)

# 2. Second measurement from Thermostat 2s later: 22.4°C (variance 0.2)
# The filter advances by dt=2.0s, fusing the new reading into state & rate:
kf.step(z=22.4, r=0.2, dt=2.0)

print(f"State after 2s: {state.value}")
# Gaussian(μ=22.384, σ²=0.1919)
print(f"Rate after 2s: {rate.value}")
# Gaussian(μ=0.177, σ²=0.2255)
```

### How Kalman Propagation Works

`KalmanEstimatorPropagator` bridges continuous dynamic state estimation with discrete reactive propagator networks:

1. **Initial Calibration on First Observation**:
   When the initial reading $z_1 = 22.0^\circ\text{C}$ ($\sigma^2 = 0.5000$) arrives, the propagator initializes its internal state vector $[x, \dot{x}]^T$:
   - **State ($\hat{x}_1$)**: Initialized directly to the observed temperature ($22.000^\circ\text{C}$) with initial covariance $P_{00} = 0.5000$.
   - **Rate ($\dot{x}_1$)**: Initialized with a neutral rate of change ($0.000^\circ\text{C}/\text{s}$) and variance scaled by process noise ($P_{11} = 10 \times Q = 1.0000$).
   - Both marginal Gaussians are immediately projected to the reactive output cells `State` and `Rate`.

2. **Predict-Update Cycle Across Time**:
   On each subsequent measurement received over elapsed time $\Delta t$, the filter advances through two phases:
   - **Predict**: Extrapolates state along the transition matrix $F = \begin{bmatrix} 1 & \Delta t \\ 0 & 1 \end{bmatrix}$ and accumulates process uncertainty $Q \cdot \Delta t$:
     $$\hat{x}_{k|k-1} = F x_{k-1}, \quad P_{k|k-1} = F P_{k-1} F^T + Q$$
   - **Update**: Computes the optimal Kalman gain $K = P_{k|k-1} H^T (H P_{k|k-1} H^T + R)^{-1}$, balancing model inertia against observation noise $R$:
     $$\hat{x}_k = \hat{x}_{k|k-1} + K (z_k - H \hat{x}_{k|k-1}), \quad P_k = (I - K H) P_{k|k-1}$$

3. **What Happens When Measurements Arrive Close in Time?**:
   - **Asynchronous updates with small $\Delta t$**: When a second reading arrives shortly after (e.g., $\Delta t = 2.0\,\text{s}$ or $\Delta t = 0.5\,\text{s}$), the predict step barely drifts because $v \cdot \Delta t$ is small and process noise accumulation ($Q \cdot \Delta t$) is minimal. The filter uses the small innovation $y = z - \hat{x}_{\text{pred}}$ to refine the physical rate estimate ($\dot{x}$) while reducing the state variance (here from $\sigma^2 = 0.5000$ down to $\sigma^2 = 0.1919$).
   - **Convergence to static fusion as $\Delta t \to 0$**: In the limit as $\Delta t \to 0$, $P_{k|k-1} \to P_{k-1}$, and the sequential Kalman update algebraically converges to the static Bayesian join ($x_1 \sqcup x_2$) from Section 1:
     $$\frac{1}{P_{\text{new}}} = \frac{1}{P_{\text{prev}}} + \frac{1}{R_{\text{new}}}$$
   - **Simultaneous updates ($\Delta t = 0$) via Lattice Merge**: If two sensors report in the exact same polling cycle, they can be merged directly into the `Observation` cell via lattice join ($\text{thermostat} \sqcup \text{zigbee}$). The Kalman filter then runs a single update on the pre-fused optimal reading $\mathcal{N}(21.62^\circ\text{C}, 0.160)$.

4. **Dual Lattice Support (Gaussians & Intervals)**:
   The measurement cell accepts both continuous `GaussianValue(mean, variance)` and bounded `IntervalValue(min_val, max_val)`. When provided with an interval, the estimator uses the midpoint as observation $z = \frac{a + b}{2}$ and derives variance from its width ($\sigma^2 \approx \left(\frac{b - a}{4}\right)^2$).

5. **Downstream Propagation with Uncertainty**:
   Because `State` and `Rate` contain standard `GaussianValue` objects, downstream propagators (such as heating threshold switches, safety interlocks, and dynamic scene controllers) can reason directly on both physical temperature and cooling/warming velocity with full probabilistic confidence bounds ($\mu \pm 1.96\sigma$).

### Why a Propagator Instead of a Python Function?

In classical software architectures, Kalman filters are typically implemented as procedural Python functions (e.g. `kalman_step(state, z, dt)`). In the Sussman & Radul propagator model, expressing state estimation as a **lattice propagator** provides critical architectural advantages:

1. **Autonomous Reactivity vs. Orchestration Plumbing**:
   A procedural function requires an external caller to coordinate timing ($\Delta t$), call `predict()` and `update()`, and manually forward outputs down the call stack. A propagator is autonomous: it sleeps until its input cell gains information ($x_{\text{old}} \sqsubset x_{\text{new}}$), then the network worklist engine awakens it automatically.

2. **Commutative Cell-Boundary Fusion**:
   If multiple sensors report concurrently, an imperative function is sensitive to caller invocation order. In a propagator network, independent sensors write directly to the `Observation` cell. The join operation ($\sqcup$) is associative, commutative, and idempotent:
   $$\text{Observation} = \text{Thermostat} \sqcup \text{Zigbee}$$
   Spatial fusion happens automatically before the Kalman estimator runs, eliminating caller ordering artifacts.

3. **Lattice Polymorphism & Partial Information**:
   A Python function expects concrete floats and crashes or requires branching if a sensor drops offline or reports an interval. A propagator handles `Bottom` ($\bot$, sleep), `IntervalValue` (tolerance bands), and `GaussianValue` (exact distributions) through the same uniform lattice interface.

4. **Decoupled Downstream Fan-Out with Uncertainty**:
   The estimator publishes marginal distributions directly to reactive output cells `State` and `Rate`. Downstream consumers (hysteresis switches, rate-of-rise alarms, safety envelopes) subscribe to those cells declaratively with full probabilistic confidence bounds ($\mu \pm 1.96\sigma$).

5. **Epistemic Provenance (TMS)**:
   A standard Kalman filter is numerically opaque: it outputs numbers without tracking *which* physical sensors contributed. Propagator cells retain epistemic provenance through the Truth Maintenance System, enabling human explanations (`cell.explain()`) and automatic contradiction diagnosis.

| Dimension | Procedural Python Function (`kalman_step(z, dt)`) | Lattice Propagator (`KalmanEstimatorPropagator`) |
| :--- | :--- | :--- |
| **Execution** | Imperative; caller coordinates timing and invocations | Reactive; wakes automatically on partial-information refinement |
| **Multi-Sensor** | Caller must handle ordering and pre-fusion | Automatic commutative join ($\sqcup$) at cell boundary |
| **Input Types** | Raw scalars only (fails on uncalibrated bounds) | Lattice values (`Bottom`, `IntervalValue`, `GaussianValue`) |
| **Downstream Flow** | Procedural return values; manual routing | Declarative fan-out to reactive output cells |
| **Explainability** | Black-box state vector $[\hat{x}, P]$ | Epistemic provenance, human explanations, and contradiction diagnosis |

---

## 3. Provenance & Explanations via the Truth Maintenance System (TMS)

Beyond mathematical fusion, real-world systems need to know **where** a fused value came from, diagnose sensor drop-outs, and explain estimates to human operators in plain language.

`lattice-propagator` integrates cell-level Truth Maintenance (`TruthMaintenanceSystem`) directly into sensor fusion:

```python
from lattice_propagator import (
    GaussianValue,
    PropagatorNetwork,
)

net = PropagatorNetwork("ExplainableFusion")
temp = net.add_cell("living_room_temp", unit="°C")

# Assert evidence tagged with source sensor IDs
temp.set_value(GaussianValue(mean=21.5, variance=0.2), source="thermostat")
temp.set_value(GaussianValue(mean=22.1, variance=0.8), source="zigbee")
net.run()

# Generate plain-English explanation of the fused belief:
print(temp.explain())
# Combining thermostat (21.5°C), zigbee (22.1°C) into 21.6°C (±0.78°C).

# Inspect data quality metrics:
tms = temp.get_or_create_tms()
print(f"Data Quality: {tms.data_quality * 100:.0f}%")  # 100%
print(f"Degraded: {tms.is_degraded}")  # False

# Handle sensor drop-out (e.g. Zigbee sensor battery dies):
tms.retract_evidence("zigbee", reason="battery depleted")
print(temp.explain())
# Combining thermostat (21.5°C) into 21.5°C (±0.88°C). Note: Degraded state; zigbee is offline.

print(f"Data Quality: {tms.data_quality * 100:.0f}%")  # 50%
print(f"Degraded: {tms.is_degraded}")  # True
```

### Explaining Contradictions & Sensor Faults

If an anomaly occurs (for example, a sensor fails or reports an implausible reading that conflicts with physical bounds or safety limits), the TMS identifies the contradictory premises and recommends actionable retractions:

```python
from lattice_propagator import (
    IntervalValue,
    TruthMaintenanceSystem,
)

safety_tms = TruthMaintenanceSystem("radiator_safety", unit="°C")

# Ground truth physical safety envelope (non-defeasible)
safety_tms.assert_evidence("safety_limit", IntervalValue(15.0, 35.0), is_assumption=False)

# Defeasible sensor hypothesis
safety_tms.assert_evidence(
    "faulty_sensor",
    IntervalValue(50.0, 60.0),
    is_assumption=True,
    confidence=0.3,
)

# The TMS immediately diagnoses the conflict and advises which hypothesis to retract:
print(safety_tms.explain())
```
