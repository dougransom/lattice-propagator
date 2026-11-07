"""Test suite for first-order terms, pair deconstruction, and unification propagators."""

from __future__ import annotations

from lattice_propagator.lattice import Contradiction, FlatValue, merge_lattice
from lattice_propagator.primitives import PropagatorNetwork
from lattice_propagator.terms import (
    PairPropagator,
    Term,
    TermValue,
    UnifyPropagator,
    add_pair_constraint,
    add_unify_constraint,
)


def test_term_data_structure() -> None:
    t1 = Term("point", 10, 20)
    assert t1.functor == "point"
    assert t1.arity == 2
    assert t1.args == (10, 20)
    assert t1.is_ground()
    assert repr(t1) == "point(10, 20)"

    net = PropagatorNetwork("TermVarTest")
    x = net.add_cell("x")
    t2 = Term("f", x, 42)
    assert not t2.is_ground()
    assert "Cell(x)" in repr(t2)


def test_pair_propagator_forward_and_backward() -> None:
    net = PropagatorNetwork("PairTest")
    pair = net.add_cell("pair")
    head = net.add_cell("head")
    tail = net.add_cell("tail")
    PairPropagator("pair1", pair, head, tail)

    # 1. Forward: pair -> head, tail
    pair.set_value(FlatValue(("sensor_a", 21.5)))
    net.run()
    assert head.value == FlatValue("sensor_a")
    assert tail.value == FlatValue(21.5)

    # 2. Backward: head, tail -> pair
    net2 = PropagatorNetwork("PairBack")
    p2 = net2.add_cell("p2")
    h2 = net2.add_cell("h2")
    t2 = net2.add_cell("t2")
    PairPropagator("pair2", p2, h2, t2)

    h2.set_value(FlatValue("status"))
    t2.set_value(FlatValue(True))
    net2.run()
    assert p2.value == FlatValue(("status", True))


def test_pair_propagator_invalid_structure_contradiction() -> None:
    net = PropagatorNetwork("PairConflict")
    pair = net.add_cell("pair", FlatValue("not_a_tuple"))
    head = net.add_cell("head")
    tail = net.add_cell("tail")
    PairPropagator("pair_err", pair, head, tail)

    net.run()
    assert isinstance(pair.value, Contradiction)


def test_term_value_lattice_merge() -> None:
    tv1 = TermValue(Term("sensor", "temp", 100))
    tv2 = TermValue(Term("sensor", "temp", 100))
    merged = merge_lattice(tv1, tv2)
    assert merged == tv1

    # Clash on functor
    tv_clash = TermValue(Term("actuator", "temp", 100))
    clash_res = merge_lattice(tv1, tv_clash)
    assert isinstance(clash_res, Contradiction)


def test_unify_propagator_first_order_variables() -> None:
    net = PropagatorNetwork("UnifyTest")
    x = net.add_cell("X")
    y = net.add_cell("Y")

    cell_t1 = net.add_cell("T1")
    cell_t2 = net.add_cell("T2")

    UnifyPropagator("unify1", cell_t1, cell_t2)

    # T1 = f(X, 2)
    cell_t1.set_value(TermValue(Term("f", x, 2)))
    # T2 = f(1, Y)
    cell_t2.set_value(TermValue(Term("f", 1, y)))

    net.run()

    # Unification should deduce X = 1 and Y = 2!
    assert x.value == FlatValue(1)
    assert y.value == FlatValue(2)


def test_unify_propagator_nested_terms() -> None:
    net = PropagatorNetwork("UnifyNested")
    a = net.add_cell("A")
    b = net.add_cell("B")
    c = net.add_cell("C")

    t1 = net.add_cell("T1")
    t2 = net.add_cell("T2")
    UnifyPropagator("unify_nested", t1, t2)

    # T1 = p(f(A), g(B, 3))
    t1.set_value(TermValue(Term("p", Term("f", a), Term("g", b, 3))))
    # T2 = p(f(10), g("hello", C))
    t2.set_value(TermValue(Term("p", Term("f", 10), Term("g", "hello", c))))

    net.run()

    assert a.value == FlatValue(10)
    assert b.value == FlatValue("hello")
    assert c.value == FlatValue(3)


def test_unify_propagator_clash_contradiction() -> None:
    net = PropagatorNetwork("UnifyClash")
    t1 = net.add_cell("T1", TermValue(Term("f", 1)))
    t2 = net.add_cell("T2", TermValue(Term("g", 1)))
    UnifyPropagator("unify_clash", t1, t2)

    net.run()
    assert isinstance(t1.value, Contradiction)


def test_hindley_milner_type_unification() -> None:
    """Type reconstruction: inferring function argument and return types via term unification."""
    net = PropagatorNetwork("HMTypeInference")

    # Type variable cells
    t_arg = net.add_cell("T_arg")
    t_res = net.add_cell("T_res")

    fn_type = net.add_cell("FnType")
    target_type = net.add_cell("TargetType")

    UnifyPropagator("unify_fn_sig", fn_type, target_type)

    # FnType = arrow(T_arg, T_res)
    fn_type.set_value(TermValue(Term("arrow", t_arg, t_res)))

    # Known application site requires: arrow(int, bool)
    target_type.set_value(TermValue(Term("arrow", Term("int"), Term("bool"))))

    net.run()

    assert t_arg.value == TermValue(Term("int"))
    assert t_res.value == TermValue(Term("bool"))


def test_helper_builders() -> None:
    """Test add_pair_constraint and add_unify_constraint declarative helpers."""
    net = PropagatorNetwork("HelperBuilders")
    pair_cell = net.add_cell("p")
    h, t, _ = add_pair_constraint(net, pair_cell)

    pair_cell.set_value(FlatValue((100, 200)))
    net.run()

    assert h.value == FlatValue(100)
    assert t.value == FlatValue(200)

    u1 = net.add_cell("u1", TermValue(Term("tag", 1)))
    u2 = net.add_cell("u2")
    add_unify_constraint(net, u1, u2)
    net.run()

    assert u2.value == TermValue(Term("tag", 1))
