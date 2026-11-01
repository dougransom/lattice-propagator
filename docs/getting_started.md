# Getting Started

This guide walks through installing `lattice-propagator` and building your first reactive constraint network.

---

## Installation

`lattice-propagator` requires **Python 3.11+** and has zero mandatory runtime dependencies.

=== "Using uv (Recommended)"

    ```bash
    uv add lattice-propagator
    ```

=== "Using pip"

    ```bash
    pip install lattice-propagator
    ```

=== "From Source for Local Development"

    ```bash
    git clone https://github.com/dougransom/lattice-propagator.git
    cd lattice-propagator
    uv pip install -e ".[all]"
    ```

---

## Core Building Blocks

Every propagator system consists of three concepts:

1. **Information Lattice**: The type of information stored. Starts at ignorance (`Bottom`), and monotonically refines as information arrives.
2. **Cell**: A container holding a lattice value. Cells maintain their current content and notify connected propagators whenever merged information strictly refines what was already known.
3. **Propagator**: An autonomous operator observing one or more input cells and pushing deductions into target cells.

---

## Your First Propagator Network

Let's build a simple multi-directional adder:

$$a + b = c$$

```python
from lattice_propagator import (
    AdderPropagator,
    FlatValue,
    PropagatorNetwork,
)

# 1. Instantiate the propagation network
network = PropagatorNetwork("AdderExample")

# 2. Create reactive cells
a = network.add_cell("a")
b = network.add_cell("b")
c = network.add_cell("c")

# 3. Attach an AdderPropagator constraint (a + b = c)
network.add_propagator(AdderPropagator("Add_a_b_c", a, b, c))

# 4. Add information to 'a' and 'b'
a.set_value(FlatValue(10))
b.set_value(FlatValue(25))

# 5. Run the network to reach a fixed point
network.run()

print(c.value)  # Flat(35)
```

### Multi-Directional Deduction

Now, clear the cells or instantiate a new network, and provide $c$ and $b$ instead:

```python
from lattice_propagator import (
    AdderPropagator,
    FlatValue,
    PropagatorNetwork,
)

network = PropagatorNetwork("ReverseAdder")
a2 = network.add_cell("a2")
b2 = network.add_cell("b2")
c2 = network.add_cell("c2")
network.add_propagator(AdderPropagator("Add_a2_b2_c2", a2, b2, c2))

# Provide total and one summand:
c2.set_value(FlatValue(100))
b2.set_value(FlatValue(40))

network.run()

print(a2.value)  # Flat(60) — Deduced automatically!
```

---

## Operator Overloading

For rapid network construction, `Cell` overloads standard Python operators (`+`, `-`, `*`, `/`):

```python
from lattice_propagator import FlatValue, PropagatorNetwork

network = PropagatorNetwork("OverloadExample")

x = network.add_cell("x")
y = network.add_cell("y")

# Creates an intermediate cell and attaches an AdderPropagator:
z = x + y

# Set values:
x.set_value(FlatValue(7))
y.set_value(FlatValue(14))
network.run()

print(z.value)  # Flat(21)
```

---

## Next Steps

- Explore [The Information Semilattice](concepts/lattices.md) to understand intervals, Gaussian distributions, and sets.
- Check out the [Examples & Tutorials](examples/arithmetic.md) for temperature conversion, sensor fusion, and solving puzzles.
- Inspect the [API Reference](api/primitives.md) for detailed signatures.
