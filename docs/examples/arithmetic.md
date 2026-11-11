# Example: Bidirectional Arithmetic

Propagator networks eliminate the need to write separate forward and inverse functions. An arithmetic relation $A + B = C$ or $A \times B = C$ automatically computes any unknown variable as soon as the other two become available.

> [!NOTE] Prerequisites
> This example builds on basic concepts introduced in the [Getting Started Guide](../getting_started.md).

---

## 1. Bidirectional Adder

In this example, we observe both forward calculation ($A + B \implies C$) and backward deduction ($C − B \implies A$):

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

# The network automatically deduces A = C − B:
# [18 − 15, 22 − 5] = [3, 17] ∩ [10, 20] → [10, 17]
print(f"A refined: {a.value}")  # IntervalValue(10.0, 17.0)

# Export and persist network diagrams
from pathlib import Path

assets_dir = Path("docs/assets")
if assets_dir.is_dir():
    (assets_dir / "arithmetic_adder.mmd").write_text(net.generate_mermaid(), encoding="utf-8")
    (assets_dir / "arithmetic_adder.dot").write_text(net.generate_dot(), encoding="utf-8")
```

### Adder Network Topology & Refined States

The multi-directional adder continuously maintains mutual consistency across all three directions. The diagram reflects the interval bounds after bidirectional relaxation:

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
  C_A["A<br/>[10.00, 17.00]"]:::interval
  C_B["B<br/>[5.00, 12.00]"]:::interval
  C_C["C<br/>[18.00, 22.00]"]:::interval
  P_Add_A_B_C["Add_A_B_C"]:::propagator
  C_A --> P_Add_A_B_C
  C_B --> P_Add_A_B_C
  C_C --> P_Add_A_B_C
  P_Add_A_B_C --> C_A
  P_Add_A_B_C --> C_B
  P_Add_A_B_C --> C_C
```

#### Downloadable Diagram Assets
- [Mermaid Diagram Source (`arithmetic_adder.mmd`)](../assets/arithmetic_adder.mmd)
- [Graphviz DOT Specification (`arithmetic_adder.dot`)](../assets/arithmetic_adder.dot)

---

## 2. Multiplier & Zero-Absorption

`MultiplierPropagator` handles multiplication and division ($X \times Y = Z$), including zero-absorption ($0 \times Y = 0$):

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

# If X is 0, Z must be 0 regardless of Y (0 × Y = 0):
x.set_value(FlatValue(0.0))
net.run()

print(f"Z: {z.value}")  # FlatValue(0.0)

# Export and persist network diagrams
from pathlib import Path

assets_dir = Path("docs/assets")
if assets_dir.is_dir():
    (assets_dir / "arithmetic_multiplier.mmd").write_text(net.generate_mermaid(), encoding="utf-8")
    (assets_dir / "arithmetic_multiplier.dot").write_text(net.generate_dot(), encoding="utf-8")
```

### Multiplier Network Topology

The diagram displays the assigned input $X = 0.0$ and unassigned ($\bot$) cells $Y$ and $Z$ with distinct dashed styling:

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
  C_X["X<br/>0.0"]:::value
  C_Y["Y<br/>⊥"]:::bottom
  C_Z["Z<br/>⊥"]:::bottom
  P_Mult_X_Y_Z["Mult_X_Y_Z"]:::propagator
  C_X --> P_Mult_X_Y_Z
  C_Y --> P_Mult_X_Y_Z
  C_Z --> P_Mult_X_Y_Z
  P_Mult_X_Y_Z --> C_X
  P_Mult_X_Y_Z --> C_Y
  P_Mult_X_Y_Z --> C_Z
```

#### Downloadable Diagram Assets
- [Mermaid Diagram Source (`arithmetic_multiplier.mmd`)](../assets/arithmetic_multiplier.mmd)
- [Graphviz DOT Specification (`arithmetic_multiplier.dot`)](../assets/arithmetic_multiplier.dot)

---

## 3. Operator Overloading & Formulas

Cells support operator overloading (`+`, `−`, `×`, `÷`) for constructing complex formulas declaratively:

```python
from lattice_propagator import Cell, PropagatorNetwork, FlatValue

net = PropagatorNetwork("FormulaDemo")

# Declarative construction of Pythagorean theorem: c² = a² + b²
a = net.add_cell("a", FlatValue(3.0))
b = net.add_cell("b", FlatValue(4.0))

a_sq = a * a
b_sq = b * b
c_sq = a_sq + b_sq

net.run()
print(f"c² = {c_sq.value}")  # FlatValue(25.0)

# Export and persist network diagrams
from pathlib import Path

assets_dir = Path("docs/assets")
if assets_dir.is_dir():
    (assets_dir / "arithmetic_pythagorean.mmd").write_text(net.generate_mermaid(), encoding="utf-8")
    (assets_dir / "arithmetic_pythagorean.dot").write_text(net.generate_dot(), encoding="utf-8")
```

### Synthesized Computational Graph ($c^2 = a^2 + b^2$)

Operator overloading builds intermediate anonymous cells `(a*a)` and `(b*b)` and connects them through `MultiplierPropagator` and `AdderPropagator` instances:

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
  C_a["a<br/>3.0"]:::value
  C_b["b<br/>4.0"]:::value
  C_node___a_a___b_b__["((a*a)+(b*b))<br/>25.0"]:::value
  C_node__a_a_["(a*a)<br/>9.0"]:::value
  C_node__b_b_["(b*b)<br/>16.0"]:::value
  P_add__a_a___b_b_["add_(a*a)_(b*b)"]:::propagator
  P_mul_a_a["mul_a_a"]:::propagator
  P_mul_b_b["mul_b_b"]:::propagator
  C_a --> P_mul_a_a
  C_a --> P_mul_a_a
  C_node__a_a_ --> P_mul_a_a
  P_mul_a_a --> C_a
  P_mul_a_a --> C_a
  P_mul_a_a --> C_node__a_a_
  C_b --> P_mul_b_b
  C_b --> P_mul_b_b
  C_node__b_b_ --> P_mul_b_b
  P_mul_b_b --> C_b
  P_mul_b_b --> C_b
  P_mul_b_b --> C_node__b_b_
  C_node__a_a_ --> P_add__a_a___b_b_
  C_node__b_b_ --> P_add__a_a___b_b_
  C_node___a_a___b_b__ --> P_add__a_a___b_b_
  P_add__a_a___b_b_ --> C_node__a_a_
  P_add__a_a___b_b_ --> C_node__b_b_
  P_add__a_a___b_b_ --> C_node___a_a___b_b__
```

#### Downloadable Diagram Assets
- [Mermaid Diagram Source (`arithmetic_pythagorean.mmd`)](../assets/arithmetic_pythagorean.mmd)
- [Graphviz DOT Specification (`arithmetic_pythagorean.dot`)](../assets/arithmetic_pythagorean.dot)
