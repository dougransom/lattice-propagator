# Example: CLP(Z) Unbounded Integer Constraints ($\mathbb{Z} \cup \{-\infty, +\infty\}$)

Modeled after Prolog's `library(clpz)` (Markus Triska), [`IntegerDomain`](file:///home/doug/code/lattice-propagator/docs/api/lattice.md) represents arbitrary sets of integers as sorted unions of closed intervals over $\mathbb{Z} \cup \{-\infty, +\infty\}$.

Unlike finite-enumeration sets ([`DiscreteDomain`](file:///home/doug/code/lattice-propagator/docs/api/lattice.md)) or continuous float envelopes ([`IntervalValue`](file:///home/doug/code/lattice-propagator/docs/api/lattice.md)), CLP(Z) propagators:
- Start variables completely unconstrained at `(-∞ .. +∞)` and narrow monotonically as inequalities arrive.
- Perform exact integer floor/ceil division tightening ($\lceil a/b \rceil \le x \le \lfloor c/d \rfloor$) and detect Diophantine infeasibility immediately via Bézout $\gcd$ checks.
- Punch discrete holes via `!=` (`without`), link boolean cells via reification ($B \Longleftrightarrow (X \le Y)$), and search huge or unbounded domains via midpoint bisection and windowed splitting in [`ChoiceEngine`](file:///home/doug/code/lattice-propagator/docs/api/primitives.md).

---

## 1. Unbounded Domains, Inequalities & Diophantine Contradictions

Even before any finite upper bound is given, linear inequalities and divisibility constraints narrow `(-∞ .. +∞)` cells and immediately prove infeasibility when no integer solution exists:

```python
from lattice_propagator import (
    Contradiction,
    IntegerDomain,
    PropagatorNetwork,
    add_int_linear,
    add_int_rel,
    int_cell,
    int_cells,
    int_expr,
)

# 1. Semi-bounded linear constraints narrow (-∞ .. +∞) to finite ranges
net = PropagatorNetwork("CLPZ_Inequalities")
x = int_cell(net, "x", lo=0)  # [0 .. +∞)
y = int_cell(net, "y", lo=0)  # [0 .. +∞)

add_int_linear(net, int_expr(x) + int_expr(y), "#=<", 10)
add_int_linear(net, 2 * int_expr(x) + int_expr(y), "#>=", 15)
add_int_rel(net, x, "#\\=", 6)
net.run()

print(f"x ∈ {x.value}")  # ℤ([5] ∪ [7..10])
print(f"y ∈ {y.value}")  # ℤ([0..5])
assert x.value == IntegerDomain(((5, 5), (7, 10)))
assert y.value == IntegerDomain.between(0, 5)

# 2. Bézout GCD check catches 2x + 4y = 5 on completely unbounded cells (-∞ .. +∞)
unsat = PropagatorNetwork("DiophantineUnsat")
ux, uy = int_cells(unsat, ["ux", "uy"])
add_int_linear(unsat, 2 * int_expr(ux) + 4 * int_expr(uy), "#=", 5)
unsat.run()

assert any(isinstance(c.value, Contradiction) for c in unsat.cells.values())
print("2x + 4y = 5 detected Contradiction immediately on (-∞ .. +∞)!")
```

---

## 2. Reified Constraints & Disjunctive Scheduling

Reification ([`ReifiedIntRelationPropagator`](file:///home/doug/code/lattice-propagator/docs/api/clpz.md)) links a boolean cell $B \in \{\bot, \text{True}, \text{False}, \top\}$ bidirectionally to an integer relation, enabling disjunctive constraints ($A \text{ before } B \lor B \text{ before } A$) using standard boolean gates:

```python
from lattice_propagator import (
    FlatValue,
    IntegerDomain,
    PropagatorNetwork,
    add_int_reified,
    add_or_gate,
    int_cell,
)

sched = PropagatorNetwork("DisjunctiveSchedule")

# Task A runs fixed at [0 .. 5]; Task B starts in [2 .. 8] and ends in [4 .. 10]
end_a = int_cell(sched, "end_a", lo=5, hi=5)
start_a = int_cell(sched, "start_a", lo=0, hi=0)
start_b = int_cell(sched, "start_b", lo=2, hi=8)
end_b = int_cell(sched, "end_b", lo=4, hi=10)

a_before_b = sched.add_cell("a_before_b")
b_before_a = sched.add_cell("b_before_a")
non_overlapping = sched.add_cell("non_overlapping", FlatValue(True))

add_int_reified(sched, a_before_b, end_a, "#=<", start_b)
add_int_reified(sched, b_before_a, end_b, "#=<", start_a)
add_or_gate(sched, a_before_b, b_before_a, non_overlapping)
sched.run()

print(f"b_before_a = {b_before_a.value.val}")
print(f"a_before_b = {a_before_b.value.val}")
print(f"start_b ∈ {start_b.value}")
assert b_before_a.value == FlatValue(False)
assert a_before_b.value == FlatValue(True)
assert start_b.value == IntegerDomain.between(5, 8)
```

---

## 3. Solving Unbounded & Large-Domain Systems with `ChoiceEngine`

When propagation reaches quiescence with unbounded or huge integer intervals remaining, [`ChoiceEngine`](file:///home/doug/code/lattice-propagator/docs/api/primitives.md) switches automatically between windowed splitting (for $\pm\infty$ bounds) and binary midpoint bisection (for large finite bounds):

```python
from lattice_propagator import (
    ChoiceEngine,
    PropagatorNetwork,
    add_int_linear,
    add_int_rel,
    int_cell,
    int_cells,
    int_expr,
)

# 1. Completely unbounded linear Diophantine equation: 2x + 3y = 7
dio = PropagatorNetwork("UnboundedDiophantine")
x, y = int_cells(dio, ["x", "y"])
add_int_linear(dio, 2 * int_expr(x) + 3 * int_expr(y), "#=", 7)

engine_dio = ChoiceEngine(dio, variables=[x, y])
assert engine_dio.first_solution()
print(f"Unbounded Diophantine solution: x = {x.value.value}, y = {y.value.value}")
assert 2 * x.value.value + 3 * y.value.value == 7

# 2. Large-domain bisection over [0 .. 1,000,000]
big = PropagatorNetwork("LargeBisection")
bx = int_cell(big, "bx", lo=0, hi=1_000_000)
by = int_cell(big, "by", lo=0, hi=1_000_000)
add_int_linear(big, 7 * int_expr(bx) + 11 * int_expr(by), "#=", 9_000_007)
add_int_rel(big, bx, "#>=", 500_000)
add_int_rel(big, by, "#>=", 400_000)

engine_big = ChoiceEngine(big, variables=[bx, by], max_depth=120)
assert engine_big.first_solution()
print(f"Large-domain solution: bx = {bx.value.value}, by = {by.value.value}")
assert 7 * bx.value.value + 11 * by.value.value == 9_000_007
```
