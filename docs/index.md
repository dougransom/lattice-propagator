# Lattice Propagator

**Lattice Propagator** is a pure Python library implementing the **propagator computational paradigm** over partial-information join-semilattices with integrated Truth Maintenance Systems (TMS).

Pioneered by **Gerald Jay Sussman** and **Alexey Radul** at MIT, propagator networks replace traditional directional computation ($y = f(x)$) with autonomous, multi-directional constraint networks operating monotonically over partial information.

---

## Key Highlights

- **Pure Python, Zero Runtime Dependencies**: Engineered for safety, predictability, and embeddability in platforms like [Home Assistant](https://www.home-assistant.io).
- **Multi-Directional Deduction**: An arithmetic constraint between $A$, $B$, and $C$ ($A + B = C$) automatically computes $C$ when $A$ and $B$ arrive, or deduce $A$ when $B$ and $C$ arrive, without writing inverse functions.
- **Partial-Information Semilattices**: Supports unconstrained states (`Bottom`), scalar constants (`FlatValue`), statistical noise distributions (`GaussianValue`), interval ranges (`IntervalValue`), set accumulation (`SetLattice`), and hierarchical maps (`MapLattice`).
- **Truth Maintenance & Conflict Resolution**: Cell-level justifications and support-set provenance tracking, with optional Dependency-Directed Backtracking (DDB) via `NetworkTMS`.
- **Constraint Satisfaction & Choice Engine**: Branch-and-bound speculative search with Minimum Remaining Values (MRV) heuristics and backtracking (e.g., solving Sudoku and logical puzzles).

---

## Quick Example: Multidirectional Temperature Converter

```python
from lattice_propagator import (
    PropagatorNetwork,
    IntervalValue,
)

# 1. Forward calculation: Celsius -> Fahrenheit (F = C * 1.8 + 32)
net = PropagatorNetwork("TemperatureConversion")
celsius = net.add_cell("celsius")
fahrenheit = celsius * 1.8 + 32

celsius.set_value(IntervalValue(100.0, 100.0))
net.run()
print(f"100°C -> {fahrenheit.value.center}°F")  # Output: 212.0°F

# 2. Multi-directional backward deduction on the same network structure:
net_rev = PropagatorNetwork("ReverseTemp")
c_rev = net_rev.add_cell("celsius")
f_rev = c_rev * 1.8 + 32

# Set Fahrenheit to freezing point (32°F):
f_rev.set_value(IntervalValue(32.0, 32.0))
net_rev.run()
print(f"32°F -> {c_rev.value.center}°C")  # Output: 0.0°C (deduced automatically!)
```

---

## Theoretical Foundations & Literature

1. **Radul, A., & Sussman, G. J. (2009)**. *"The Art of the Propagator"*. MIT Computer Science and Artificial Intelligence Laboratory Technical Report, MIT-CSAIL-TR-2009-002. [MIT DSpace](https://dspace.mit.edu/handle/1721.1/44215).
2. **Radul, A. (2009)**. *"Propagation Networks: A Flexible and Expressive Substrate for Computation"*. Doctoral Dissertation, Massachusetts Institute of Technology. [MIT DSpace](https://dspace.mit.edu/handle/1721.1/54635).
3. **Hanson, C., & Sussman, G. J. (2021)**. *"Software Design for Flexibility: How to Avoid Programming Yourself into a Corner"*. MIT Press. (Chapters 6 & 7: Layered Data, Truth Maintenance, and Propagators).
4. **Sussman, G. J., & Steele, G. L. (1980)**. *"CONSTRAINTS—A Language for Higher-Order Almost-Hierarchical Networks"*. Artificial Intelligence, 14(1), 1-39.
