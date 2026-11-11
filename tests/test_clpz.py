"""Tests for IntegerDomain lattice and CLP(Z) unbounded integer constraints."""

from __future__ import annotations

import math

import pytest

from lattice_propagator import (
    BOTTOM,
    ChoiceEngine,
    Contradiction,
    FlatValue,
    IntegerDomain,
    PropagatorNetwork,
    add_int_abs,
    add_int_add,
    add_int_all_different,
    add_int_linear,
    add_int_mul,
    add_int_reified,
    add_int_rel,
    add_or_gate,
    int_cell,
    int_cells,
    int_expr,
    merge_lattice,
)


def test_integer_domain_coalescing_and_bounds() -> None:
    d = IntegerDomain(ranges=((5, 10), (1, 4), (15, 15)))
    assert d.ranges == ((1, 10), (15, 15))
    assert d.lo == 1
    assert d.hi == 15
    assert d.is_bounded
    assert not d.is_determined
    assert d.size == 11
    assert d.contains(1)
    assert d.contains(10)
    assert not d.contains(11)
    assert d.contains(15)
    assert not d.contains(True)
    assert list(d.iter_values()) == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 15]


def test_integer_domain_infinities_and_huge_ints() -> None:
    z = IntegerDomain.unbounded()
    assert z.ranges == ((-math.inf, math.inf),)
    assert not z.is_bounded
    assert z.size == math.inf
    assert z.contains(0)
    assert z.contains(10**100)
    assert z.contains(-(10**100))

    no_zero = z.without(0)
    assert isinstance(no_zero, IntegerDomain)
    assert no_zero.ranges == ((-math.inf, -1), (1, math.inf))
    assert not no_zero.contains(0)
    assert no_zero.contains(-1)
    assert no_zero.contains(1)

    comp = no_zero.complement()
    assert comp == IntegerDomain.single(0)


def test_integer_domain_lattice_laws() -> None:
    a = IntegerDomain.between(-math.inf, 10)
    b = IntegerDomain.between(0, math.inf)
    c = IntegerDomain(((2, 5), (8, 20)))

    # Bottom identity
    assert merge_lattice(BOTTOM, a) == a
    assert merge_lattice(a, BOTTOM) == a

    # Idempotence
    assert merge_lattice(a, a) == a
    assert merge_lattice(c, c) == c

    # Commutativity
    assert merge_lattice(a, b) == merge_lattice(b, a)
    assert merge_lattice(a, c) == merge_lattice(c, a)

    # Associativity
    lhs = merge_lattice(merge_lattice(a, b), c)
    rhs = merge_lattice(a, merge_lattice(b, c))
    assert lhs == rhs
    assert lhs == IntegerDomain(((2, 5), (8, 10)))

    # Disjoint -> Contradiction
    disjoint = merge_lattice(IntegerDomain.at_most(0), IntegerDomain.at_least(1))
    assert isinstance(disjoint, Contradiction)


def test_integer_domain_validation_errors() -> None:
    with pytest.raises(TypeError):
        IntegerDomain.single(True)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        IntegerDomain.between(1.5, 5)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        IntegerDomain.between(10, 5)
    with pytest.raises(ValueError):
        IntegerDomain.between(math.inf, math.inf)


def test_int_relation_unbounded_tightening_and_gap_removal() -> None:
    net = PropagatorNetwork("IntRel")
    x = int_cell(net, "x")  # (-∞ .. +∞)
    y = int_cell(net, "y", lo=5)  # [5 .. +∞)
    z = int_cell(net, "z", hi=7)  # (-∞ .. 7]

    add_int_rel(net, x, "#>", y)
    add_int_rel(net, x, "#=<", z)
    add_int_rel(net, x, "#\\=", 6)
    net.run()

    assert x.value == IntegerDomain.single(7)
    assert y.value == IntegerDomain.between(5, 6)
    assert z.value == IntegerDomain.single(7)


def test_int_linear_unbounded_to_bounded_and_gcd_contradiction() -> None:
    net = PropagatorNetwork("LinearSemiBounded")
    x = int_cell(net, "x", lo=0)
    y = int_cell(net, "y", lo=0)
    add_int_linear(net, [(1, x), (1, y)], "<=", 10)
    add_int_linear(net, [(2, x), (1, y)], ">=", 15)
    net.run()

    # x + y <= 10 and 2x + y >= 15 => x >= 5, x <= 10, y <= 5
    assert isinstance(x.value, IntegerDomain)
    assert isinstance(y.value, IntegerDomain)
    assert x.value == IntegerDomain.between(5, 10)
    assert y.value == IntegerDomain.between(0, 5)

    # Bézout GCD infeasibility on completely unbounded variables: 2x + 4y = 5
    net_unsat = PropagatorNetwork("GCDUnsat")
    ux, uy = int_cells(net_unsat, ["ux", "uy"])
    add_int_linear(net_unsat, 2 * int_expr(ux) + 4 * int_expr(uy), "=", 5)
    net_unsat.run()
    assert any(isinstance(c.value, Contradiction) for c in net_unsat.cells.values())


def test_int_linear_floor_ceil_tightening_and_ne() -> None:
    net = PropagatorNetwork("FloorCeil")
    x = int_cell(net, "x")
    y = int_cell(net, "y", lo=3, hi=9)
    # 2x - y = 0 => 2x in [3..9] => x in [2..4], then y in [4..8]
    add_int_linear(net, 2 * int_expr(x) - int_expr(y), "=", 0)
    net.run()
    assert x.value == IntegerDomain.between(2, 4)
    assert y.value == IntegerDomain.between(4, 8)

    # Linear != forbids remaining value
    net2 = PropagatorNetwork("LinearNE")
    a = int_cell(net2, "a", lo=4, hi=4)
    b = int_cell(net2, "b", lo=5, hi=7)
    add_int_linear(net2, [(1, a), (1, b)], "!=", 10)
    net2.run()
    assert b.value == IntegerDomain(((5, 5), (7, 7)))


def test_int_add_mul_abs_propagators() -> None:
    # Add with finite holes
    net = PropagatorNetwork("AddMulAbs")
    a = int_cell(net, "a", values=[1, 3])
    b = int_cell(net, "b", values=[10, 20])
    s = int_cell(net, "s")
    add_int_add(net, a, b, s)
    net.run()
    assert s.value == IntegerDomain.from_values([11, 13, 21, 23])

    # Mul exact integer division and 0 * inf = 0
    net_m = PropagatorNetwork("Mul")
    z0 = int_cell(net_m, "z0", lo=0, hi=0)
    inf_cell = int_cell(net_m, "inf_cell")
    prod0 = int_cell(net_m, "prod0")
    add_int_mul(net_m, z0, inf_cell, prod0)

    k = int_cell(net_m, "k", lo=-2, hi=-2)
    x = int_cell(net_m, "x")
    p = int_cell(net_m, "p", lo=-6, hi=-4)
    add_int_mul(net_m, k, x, p)
    net_m.run()
    assert prod0.value == IntegerDomain.single(0)
    assert x.value == IntegerDomain.between(2, 3)

    # Abs bidirectional
    net_abs = PropagatorNetwork("Abs")
    ax = int_cell(net_abs, "ax")
    ay = int_cell(net_abs, "ay", lo=2, hi=4)
    add_int_abs(net_abs, ax, ay)
    net_abs.run()
    assert ax.value == IntegerDomain(((-4, -2), (2, 4)))


def test_int_mul_infeasible_division_contradiction() -> None:
    net = PropagatorNetwork("MulContradiction")
    two = int_cell(net, "two", lo=2, hi=2)
    x = int_cell(net, "x")
    five = int_cell(net, "five", lo=5, hi=5)
    add_int_mul(net, two, x, five)
    net.run()
    assert isinstance(x.value, Contradiction)


def test_reified_relation_and_disjunctive_scheduling() -> None:
    # Entailment & disentailment
    net = PropagatorNetwork("ReifyEntail")
    x = int_cell(net, "x", lo=1, hi=3)
    y = int_cell(net, "y", lo=5, hi=10)
    b_lt = net.add_cell("b_lt")
    b_eq = net.add_cell("b_eq")
    add_int_reified(net, b_lt, x, "<", y)
    add_int_reified(net, b_eq, x, "=", y)
    net.run()
    assert b_lt.value == FlatValue(True)
    assert b_eq.value == FlatValue(False)

    # False reification enforces negation (not(x < y) => x >= y)
    net2 = PropagatorNetwork("ReifyNegate")
    rx = int_cell(net2, "rx", lo=0, hi=10)
    ry = int_cell(net2, "ry", lo=6, hi=10)
    b = net2.add_cell("b", FlatValue(False))
    add_int_reified(net2, b, rx, "<", ry)
    net2.run()
    assert rx.value == IntegerDomain.between(6, 10)

    # Disjunctive scheduling with OrPropagator: (end_a <= start_b) OR (end_b <= start_a)
    sched = PropagatorNetwork("DisjunctiveSchedule")
    start_a = int_cell(sched, "start_a", lo=0, hi=0)
    end_a = int_cell(sched, "end_a", lo=5, hi=5)
    start_b = int_cell(sched, "start_b", lo=2, hi=8)
    end_b = int_cell(sched, "end_b", lo=4, hi=10)

    a_before_b = sched.add_cell("a_before_b")
    b_before_a = sched.add_cell("b_before_a")
    out_true = sched.add_cell("must_not_overlap", FlatValue(True))
    add_int_reified(sched, a_before_b, end_a, "<=", start_b)
    add_int_reified(sched, b_before_a, end_b, "<=", start_a)
    add_or_gate(sched, a_before_b, b_before_a, out_true)
    sched.run()

    # end_b >= 4 > start_a = 0 disentails b_before_a -> forces a_before_b -> start_b >= 5!
    assert b_before_a.value == FlatValue(False)
    assert a_before_b.value == FlatValue(True)
    assert start_b.value == IntegerDomain.between(5, 8)


def test_clpz_send_more_money_single_linear_equation() -> None:
    net = PropagatorNetwork("SendMoreMoneyCLPZ")
    letters = int_cells(net, ["S", "E", "N", "D", "M", "O", "R", "Y"], lo=0, hi=9)
    s, e, n, d, m, o, r, y = letters

    add_int_rel(net, s, "!=", 0)
    add_int_rel(net, m, "!=", 0)
    add_int_all_different(net, letters)

    lhs = (
        1000 * int_expr(s)
        + 100 * int_expr(e)
        + 10 * int_expr(n)
        + int_expr(d)
        + 1000 * int_expr(m)
        + 100 * int_expr(o)
        + 10 * int_expr(r)
        + int_expr(e)
    )
    rhs = (
        10000 * int_expr(m)
        + 1000 * int_expr(o)
        + 100 * int_expr(n)
        + 10 * int_expr(e)
        + int_expr(y)
    )
    add_int_linear(net, lhs - rhs, "=", 0)

    engine = ChoiceEngine(net, variables=letters)
    assert engine.first_solution()

    vals = {c.cell_id: c.value.value for c in letters}
    assert vals == {"S": 9, "E": 5, "N": 6, "D": 7, "M": 1, "O": 0, "R": 8, "Y": 2}


def test_choice_engine_unbounded_diophantine_and_large_bisection() -> None:
    # Unbounded Diophantine: 2x + 3y = 7
    net_dio = PropagatorNetwork("Diophantine")
    x, y = int_cells(net_dio, ["x", "y"])  # both (-∞ .. +∞)
    add_int_linear(net_dio, 2 * int_expr(x) + 3 * int_expr(y), "=", 7)

    engine = ChoiceEngine(net_dio, variables=[x, y])
    sols = engine.all_solutions(limit=3)
    assert len(sols) == 3
    pairs = {(s["x"].value, s["y"].value) for s in sols}
    assert len(pairs) == 3
    assert all(2 * xv + 3 * yv == 7 for xv, yv in pairs)

    assert engine.first_solution()
    xv, yv = x.value.value, y.value.value
    assert isinstance(xv, int) and isinstance(yv, int)
    assert 2 * xv + 3 * yv == 7

    # Large finite domain bisection: [0 .. 1_000_000]
    net_big = PropagatorNetwork("BigBisect")
    bx = int_cell(net_big, "bx", lo=0, hi=1_000_000)
    by = int_cell(net_big, "by", lo=0, hi=1_000_000)
    add_int_linear(net_big, 7 * int_expr(bx) + 11 * int_expr(by), "=", 9_000_007)
    add_int_rel(net_big, bx, ">=", 500_000)
    add_int_rel(net_big, by, ">=", 400_000)

    engine_big = ChoiceEngine(net_big, variables=[bx, by], max_depth=120)
    assert engine_big.first_solution()
    bxv, byv = bx.value.value, by.value.value
    assert isinstance(bxv, int) and isinstance(byv, int)
    assert 7 * bxv + 11 * byv == 9_000_007
    assert bxv >= 500_000 and byv >= 400_000
