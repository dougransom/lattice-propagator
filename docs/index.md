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
    Cell,
    PropagatorNetwork,
    FlatValue,
    AdderPropagator,
    MultiplierPropagator,
)

# 9 * C = 5 * (F - 32)
# Set up reactive cells
celsius = Cell("celsius")
fahr = Cell("fahrenheit")

# Auxiliary cells and constants
f_sub_32 = Cell("f - 32")
const_32 = Cell("32", initial_value=FlatValue(32.0))
const_9 = Cell("9", initial_value=FlatValue(9.0))
const_5 = Cell("5", initial_value=FlatValue(5.0))
nine_c = Cell("9 * C")
five_f_sub_32 = Cell("5 * (F - 32)")

# Connect constraint propagators
network = PropagatorNetwork()
AdderPropagator(f_sub_32, const_32, fahr, network=network)  # (F - 32) + 32 = F
MultiplierPropagator(celsius, const_9, nine_c, network=network)  # C * 9 = 9C
MultiplierPropagator(f_sub_32, const_5, five_f_sub_32, network=network)  # (F - 32) * 5 = 5(F-32)

# Unify the equal cells (9C == 5(F-32))
nine_c.unify(five_f_sub_32)

# Compute Fahrenheit from Celsius:
celsius.add_content(FlatValue(100.0))
network.run()
print(f"100°C -> {fahr.content.value}°F")  # Output: 212.0°F

# Or compute Celsius from Fahrenheit automatically:
fahr_cell = Cell("f_new")
celsius_cell = Cell("c_new")
# Overloaded operators simplify network creation:
# 9 * C = 5 * (F - 32)
```

---

## Theoretical Foundations & Literature

1. **Radul, A., & Sussman, G. J. (2009)**. *"The Art of the Propagator"*. MIT Computer Science and Artificial Intelligence Laboratory Technical Report, MIT-CSAIL-TR-2009-002. [MIT DSpace](https://dspace.mit.edu/handle/1721.1/44215).
2. **Radul, A. (2009)**. *"Propagation Networks: A Flexible and Expressive Substrate for Computation"*. Doctoral Dissertation, Massachusetts Institute of Technology. [MIT DSpace](https://dspace.mit.edu/handle/1721.1/54635).
3. **Hanson, C., & Sussman, G. J. (2021)**. *"Software Design for Flexibility: How to Avoid Programming Yourself into a Corner"*. MIT Press. (Chapters 6 & 7: Layered Data, Truth Maintenance, and Propagators).
4. **Sussman, G. J., & Steele, G. L. (1980)**. *"CONSTRAINTS—A Language for Higher-Order Almost-Hierarchical Networks"*. Artificial Intelligence, 14(1), 1-39.
