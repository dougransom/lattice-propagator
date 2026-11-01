# The Information Semilattice

In classical programming, variables hold exact, known values. In propagator networks, a cell's state is an element of a **join-semilattice** $(\mathcal{L}, \sqsubseteq, \sqcup)$ representing partial or uncertain information.

A join-semilattice satisfies three algebraic properties for its merge operation ($\sqcup$):

1. **Associativity**: $(x \sqcup y) \sqcup z = x \sqcup (y \sqcup z)$
2. **Commutativity**: $x \sqcup y = y \sqcup x$
3. **Idempotence**: $x \sqcup x = x$

This ensures that the order in which data arrives or propagators fire has **no impact** on the final equilibrium state.

---

## Lattice Types in `lattice-propagator`

### 1. `Bottom` ($\bot$)
Represents complete absence of information, an uninitialized sensor, or an offline device.
```python
from lattice_propagator import BOTTOM, FlatValue

# Bottom merged with any value X yields X:
result = BOTTOM.merge(FlatValue(42))
print(result)  # FlatValue(42)
```

### 2. `FlatValue(val)`
Represents an exact scalar value (`int`, `float`, `str`, `bool`, enum).
- Merging two identical flat values yields that value ($x \sqcup x = x$).
- Merging two distinct flat values yields a `Contradiction` ($\top$).

```python
from lattice_propagator import FlatValue

f1 = FlatValue(20.5)
f2 = FlatValue(20.5)
f3 = FlatValue(30.0)

print(f1.merge(f2))  # FlatValue(20.5)
print(f1.merge(f3))  # Contradiction: Conflicting premises
```

### 3. `GaussianValue(mean, variance)`
Represents a continuous statistical distribution $\mathcal{N}(\mu, \sigma^2)$, ideal for fusing readings from multiple noisy sensors.
- Merging two Gaussian distributions performs optimal **Bayesian sensor fusion**:
  $$\sigma_{\text{merged}}^2 = \frac{1}{\frac{1}{\sigma_1^2} + \frac{1}{\sigma_2^2}}, \quad \mu_{\text{merged}} = \sigma_{\text{merged}}^2 \left(\frac{\mu_1}{\sigma_1^2} + \frac{\mu_2}{\sigma_2^2}\right)$$

```python
from lattice_propagator import GaussianValue

# Sensor A: 21.0°C with variance 1.0
sensor_a = GaussianValue(mean=21.0, variance=1.0)

# Sensor B: 22.0°C with variance 0.5 (more accurate)
sensor_b = GaussianValue(mean=22.0, variance=0.5)

fused = sensor_a.merge(sensor_b)
print(f"Fused: {fused.mean:.2f}°C, variance: {fused.variance:.2f}")
# Output: Fused: 21.67°C, variance: 0.33
```

### 4. `IntervalValue(min, max)`
Represents bounding intervals $[a, b]$. Merging two intervals takes their **intersection** (refining the bounding envelope).
- If the intervals do not overlap, merging yields a `Contradiction`.
- Supports interval arithmetic: addition, subtraction, multiplication, and division.

```python
from lattice_propagator import IntervalValue

room_temp = IntervalValue(18.0, 24.0)
target_temp = IntervalValue(20.0, 26.0)

# Merge takes the intersection:
envelope = room_temp.merge(target_temp)
print(envelope)  # IntervalValue(20.0, 24.0)
```

### 5. `SetLattice(elements)`
Monotonically accumulating set lattice under set union. Merging two sets combines their elements ($S_1 \cup S_2$).

```python
from lattice_propagator import SetLattice

detected_tags = SetLattice(frozenset(["device_1", "device_2"]))
new_scans = SetLattice(frozenset(["device_2", "device_3"]))

print(detected_tags.merge(new_scans))
# SetLattice(frozenset({'device_1', 'device_2', 'device_3'}))
```

### 6. `MapLattice(mapping)`
A dictionary-like lattice that recursively merges overlapping keys using their respective lattice merge operators.

### 7. `Contradiction` ($\top$)
The top element of the lattice. Represents a conflict between irreconcilable premises or disjoint intervals. Holds details of the conflict and supports Truth Maintenance tracking.
