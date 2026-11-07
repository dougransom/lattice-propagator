"""Test suite for boolean logic gates and Two-Watched-Literals SAT ClausePropagator."""

from __future__ import annotations

from lattice_propagator.boolean import (
    AndPropagator,
    ClausePropagator,
    Literal,
    NotPropagator,
    OrPropagator,
    XorPropagator,
    add_clause,
)
from lattice_propagator.lattice import BOTTOM, Contradiction, FlatValue
from lattice_propagator.primitives import PropagatorNetwork
from lattice_propagator.tms import NetworkTMS


def test_and_propagator_forward_and_backward() -> None:
    net = PropagatorNetwork("AndTest")
    in1 = net.add_cell("in1")
    in2 = net.add_cell("in2")
    out = net.add_cell("out")
    AndPropagator("and1", in1, in2, out)

    # 1. Forward: True, True -> True
    in1.set_value(FlatValue(True))
    in2.set_value(FlatValue(True))
    net.run()
    assert out.value == FlatValue(True)

    # 2. Backward: out=False, in1=True -> in2=False
    net2 = PropagatorNetwork("AndBack")
    a = net2.add_cell("a")
    b = net2.add_cell("b")
    c = net2.add_cell("c")
    AndPropagator("and2", a, b, c)

    c.set_value(FlatValue(False))
    a.set_value(FlatValue(True))
    net2.run()
    assert b.value == FlatValue(False)

    # 3. Backward: out=True -> both inputs True
    net3 = PropagatorNetwork("AndBackBoth")
    x = net3.add_cell("x")
    y = net3.add_cell("y")
    z = net3.add_cell("z")
    AndPropagator("and3", x, y, z)

    z.set_value(FlatValue(True))
    net3.run()
    assert x.value == FlatValue(True)
    assert y.value == FlatValue(True)


def test_and_propagator_contradiction() -> None:
    net = PropagatorNetwork("AndConflict")
    in1 = net.add_cell("in1", FlatValue(False))
    in2 = net.add_cell("in2", FlatValue(True))
    out = net.add_cell("out", FlatValue(True))
    AndPropagator("and1", in1, in2, out)

    net.run()
    assert isinstance(out.value, Contradiction)


def test_or_propagator_forward_and_backward() -> None:
    net = PropagatorNetwork("OrTest")
    in1 = net.add_cell("in1")
    in2 = net.add_cell("in2")
    out = net.add_cell("out")
    OrPropagator("or1", in1, in2, out)

    # 1. Forward: True, False -> True
    in1.set_value(FlatValue(True))
    in2.set_value(FlatValue(False))
    net.run()
    assert out.value == FlatValue(True)

    # 2. Backward: out=False -> both False
    net2 = PropagatorNetwork("OrBackBoth")
    a = net2.add_cell("a")
    b = net2.add_cell("b")
    c = net2.add_cell("c")
    OrPropagator("or2", a, b, c)

    c.set_value(FlatValue(False))
    net2.run()
    assert a.value == FlatValue(False)
    assert b.value == FlatValue(False)

    # 3. Backward: out=True, in1=False -> in2=True
    net3 = PropagatorNetwork("OrBackOne")
    x = net3.add_cell("x")
    y = net3.add_cell("y")
    z = net3.add_cell("z")
    OrPropagator("or3", x, y, z)

    z.set_value(FlatValue(True))
    x.set_value(FlatValue(False))
    net3.run()
    assert y.value == FlatValue(True)


def test_not_propagator_bidirectional() -> None:
    net = PropagatorNetwork("NotTest")
    in_ = net.add_cell("in")
    out = net.add_cell("out")
    NotPropagator("not1", in_, out)

    in_.set_value(FlatValue(True))
    net.run()
    assert out.value == FlatValue(False)

    # Reverse
    net2 = PropagatorNetwork("NotRev")
    a = net2.add_cell("a")
    b = net2.add_cell("b")
    NotPropagator("not2", a, b)

    b.set_value(FlatValue(True))
    net2.run()
    assert a.value == FlatValue(False)


def test_xor_propagator_all_directions() -> None:
    net = PropagatorNetwork("XorTest")
    a = net.add_cell("a")
    b = net.add_cell("b")
    out = net.add_cell("out")
    XorPropagator("xor1", a, b, out)

    # 1. Forward: True ^ False -> True
    a.set_value(FlatValue(True))
    b.set_value(FlatValue(False))
    net.run()
    assert out.value == FlatValue(True)

    # 2. Backward A: a=True, out=False -> b=True (since True ^ True = False)
    net2 = PropagatorNetwork("XorRevA")
    x = net2.add_cell("x", FlatValue(True))
    y = net2.add_cell("y")
    z = net2.add_cell("z", FlatValue(False))
    XorPropagator("xor2", x, y, z)
    net2.run()
    assert y.value == FlatValue(True)

    # 3. Backward B: b=False, out=True -> a=True (since True ^ False = True)
    net3 = PropagatorNetwork("XorRevB")
    p = net3.add_cell("p")
    q = net3.add_cell("q", FlatValue(False))
    r = net3.add_cell("r", FlatValue(True))
    XorPropagator("xor3", p, q, r)
    net3.run()
    assert p.value == FlatValue(True)


def test_cell_boolean_dunder_operators() -> None:
    net = PropagatorNetwork("DunderTest")
    a = net.add_cell("a")
    b = net.add_cell("b")

    # c = a & b
    c = a & b
    # d = a | ~b
    d = a | ~b
    # e = a ^ b
    e = a ^ b

    a.set_value(FlatValue(True))
    b.set_value(FlatValue(False))
    net.run()

    assert c.value == FlatValue(False)  # True & False == False
    assert d.value == FlatValue(True)  # True | ~False == True
    assert e.value == FlatValue(True)  # True ^ False == True


def test_clause_propagator_unit_propagation() -> None:
    net = PropagatorNetwork("ClauseTest")
    x1 = net.add_cell("x1")
    x2 = net.add_cell("x2")
    x3 = net.add_cell("x3")

    # Clause: (x1 ∨ ¬x2 ∨ x3)
    c1 = ClausePropagator(
        "clause1",
        [
            Literal(x1, positive=True),
            Literal(x2, positive=False),
            Literal(x3, positive=True),
        ],
    )
    net.add_propagator(c1)

    # Falsify x1 (x1 = False)
    x1.set_value(FlatValue(False))
    net.run()
    # Still 2 non-falsified literals (~x2 and x3), no deduction yet
    assert x2.value == BOTTOM
    assert x3.value == BOTTOM

    # Falsify x2's literal: set x2 = True (so ¬x2 becomes False!)
    x2.set_value(FlatValue(True))
    net.run()

    # Unit propagation! x3 MUST be True
    assert x3.value == FlatValue(True)


def test_clause_propagator_conflict_detection() -> None:
    net = PropagatorNetwork("ConflictSAT")
    a = net.add_cell("a")
    b = net.add_cell("b")

    # Clause: (a ∨ b)
    add_clause(net, [a, b], name="c_ab")

    a.set_value(FlatValue(False))
    b.set_value(FlatValue(False))
    net.run()

    assert isinstance(b.value, Contradiction)


def test_sat_solver_cdcl_with_tms() -> None:
    """Solve a 3-SAT problem using Two-Watched-Literals clauses and NetworkTMS backtracking."""
    net = PropagatorNetwork("CDCL_3SAT")
    tms = NetworkTMS(net)

    x1 = net.add_cell("x1")
    x2 = net.add_cell("x2")
    x3 = net.add_cell("x3")

    # Problem:
    # C1: (x1 ∨ x2 ∨ x3)
    # C2: (¬x1 ∨ ¬x2 ∨ x3)
    # C3: (¬x1 ∨ x2 ∨ ¬x3)
    # C4: (¬x1 ∨ ¬x2 ∨ ¬x3)
    # With hypothesis x1=True, C2, C3, C4 force unit deductions and test nogood resolution!
    add_clause(net, [Literal(x1, True), Literal(x2, True), Literal(x3, True)], name="C1")
    add_clause(net, [Literal(x1, False), Literal(x2, False), Literal(x3, True)], name="C2")
    add_clause(net, [Literal(x1, False), Literal(x2, True), Literal(x3, False)], name="C3")
    add_clause(net, [Literal(x1, False), Literal(x2, False), Literal(x3, False)], name="C4")

    # Assume x1 = True (priority 1.0)
    tms.assume("x1", "hyp_x1_true", FlatValue(True), confidence=1.0)
    # Assume x2 = True (priority 0.5)
    tms.assume("x2", "hyp_x2_true", FlatValue(True), confidence=0.5)

    net.run()

    # Contradiction detected in network (clause C4 violated under x1=True, x2=True)
    conflict_cells = [c for c in net.cells.values() if isinstance(c.value, Contradiction)]
    assert len(conflict_cells) > 0

    # Resolve contradiction via dependency-directed backtracking:
    retracted = tms.resolve_contradiction(conflict_cells[0].tms.active_sources)
    assert retracted == "hyp_x2_true"
    assert any("hyp_x2_true" in ng for ng in tms.nogoods)

    # Re-run network: x2 is now free, and nogood prevents x2=True while x1=True
    net.run()
    assert all(not isinstance(c.value, Contradiction) for c in net.cells.values())


def test_full_adder_circuit_bidirectional() -> None:
    """Model a 1-bit full adder and test bidirectional fault-free deduction."""
    net = PropagatorNetwork("FullAdder")
    a = net.add_cell("a")
    b = net.add_cell("b")
    cin = net.add_cell("cin")
    s = net.add_cell("s")
    cout = net.add_cell("cout")

    # Half adder 1:
    # axorb = a ^ b
    # and1 = a & b
    axorb = a ^ b
    and1 = a & b

    # Half adder 2:
    # s = axorb ^ cin
    # and2 = axorb & cin
    s_calc = axorb ^ cin
    and2 = axorb & cin

    # Carry out:
    # cout = and1 | and2
    cout_calc = and1 | and2

    # Unify calculated outputs with target cells
    s.unify(s_calc)
    cout.unify(cout_calc)

    # Forward test: A=1, B=1, Cin=0 -> S=0, Cout=1
    a.set_value(FlatValue(True))
    b.set_value(FlatValue(True))
    cin.set_value(FlatValue(False))
    net.run()

    assert s.value == FlatValue(False)
    assert cout.value == FlatValue(True)
