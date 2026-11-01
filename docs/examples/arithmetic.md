# Example: Bidirectional Arithmetic

Propagator networks eliminate the need to write separate forward and inverse functions. An arithmetic relation $A + B = C$ or $A \times B = C$ automatically computes any unknown variable as soon as the other two become available.

---

## 1. Bidirectional Adder

In this example, we observe both forward calculation ($A + B \implies C$) and backward deduction ($C - B \implies A$):

```python
import math
from lattice_propagator import (
    PropagatorNetwork,
    IntervalValue,
    AdderPropagator,
)

net = PropagatorNetwork("AdderDemo")
a = net.add_cell("A")
b = net.add_cell("B")
c = net.add_cell("C")

# Connect the multi-directional adder constraint
net.add_propagator(AdderPropagator("Add_A_B_C", a, b, c))

# Step 1: Forward propagation with intervals
a.set_value(IntervalValue(10.0, 20.0))
b.set_value(IntervalValue(5.0, 15.0))
net.run()

print(f"C: {c.value}")  # IntervalValue(15.0, 35.0)

# Step 2: Backward refinement
# Suppose an external sensor constrains C to [18.0, 22.0]
c.set_value(IntervalValue(18.0, 22.0))
net.run()

# The network automatically deduces A = C - B:
# [18 - 15, 22 - 5] = [3, 17] intersected with original [10, 20] -> [10, 17]
print(f"A refined: {a.value}")  # IntervalValue(10.0, 17.0)
```

---

## 2. Multiplier & Zero-Absorption

`MultiplierPropagator` handles multiplication and division, including zero-absorption:

```python
from lattice_propagator import (
    PropagatorNetwork,
    FlatValue,
    MultiplierPropagator,
)

net = PropagatorNetwork("MultDemo")
x = net.add_cell("X")
y = net.add_cell("Y")
z = net.add_cell("Z")

net.add_propagator(MultiplierPropagator("Mult_X_Y_Z", x, y, z))

# If X is 0, Z must be 0 regardless of Y:
x.set_value(FlatValue(0.0))
net.run()

print(f"Z: {z.value}")  # FlatValue(0.0)
```

---

## 3. Operator Overloading & Formulas

Cells support operator overloading (`+`, `-`, `*`, `/`) for constructing complex formulas declaratively:

```python
from lattice_propagator import Cell, PropagatorNetwork, FlatValue

net = PropagatorNetwork("FormulaDemo")

# Declarative construction of Pythagorean theorem: c_sq = a^2 + b^2
a = net.add_cell("a", FlatValue(3.0))
b = net.add_cell("b", FlatValue(4.0))

a_sq = a * a
b_sq = b * b
c_sq = a_sq + b_sq

net.run()
print(f"c^2 = {c_sq.value}")  # FlatValue(25.0)
```
