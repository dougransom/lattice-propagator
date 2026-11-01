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
    Cell,
    PropagatorNetwork,
    FlatValue,
    AdderPropagator,
)

# 1. Instantiate the propagation network
network = PropagatorNetwork()

# 2. Create reactive cells
a = Cell("a")
b = Cell("b")
c = Cell("c")

# 3. Attach an AdderPropagator constraint
AdderPropagator(a, b, c, network=network)

# 4. Add information to 'a' and 'b'
a.add_content(FlatValue(10))
b.add_content(FlatValue(25))

# 5. Run the network to reach a fixed point
network.run()

print(c.content)  # FlatValue(35)
```

### Multi-Directional Deduction

Now, clear the cells or instantiate a new network, and provide $c$ and $b$ instead:

```python
a2 = Cell("a2")
b2 = Cell("b2")
c2 = Cell("c2")
AdderPropagator(a2, b2, c2, network=network)

# Provide total and one summand:
c2.add_content(FlatValue(100))
b2.add_content(FlatValue(40))

network.run()

print(a2.content)  # FlatValue(60) — Deduced automatically!
```

---

## Operator Overloading

For rapid network construction, `Cell` overloads standard Python operators (`+`, `-`, `*`, `/`):

```python
from lattice_propagator import Cell, PropagatorNetwork, FlatValue

network = PropagatorNetwork()

x = Cell("x")
y = Cell("y")

# Creates an intermediate cell and attaches an AdderPropagator:
z = x + y

# Set values:
x.add_content(FlatValue(7))
y.add_content(FlatValue(14))
network.run()

print(z.content)  # FlatValue(21)
```

---

## Next Steps

- Explore [The Information Semilattice](concepts/lattices.md) to understand intervals, Gaussian distributions, and sets.
- Check out the [Examples & Tutorials](examples/arithmetic.md) for temperature conversion, sensor fusion, and solving puzzles.
- Inspect the [API Reference](api/primitives.md) for detailed signatures.
