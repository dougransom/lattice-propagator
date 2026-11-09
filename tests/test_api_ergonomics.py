"""Tests for Phase 1 API ergonomics: coercion, unwrapping, binding, and dynamic attributes."""

from __future__ import annotations

import pytest

from lattice_propagator import (
    BOTTOM,
    AdderPropagator,
    Cell,
    Contradiction,
    DiscreteDomain,
    FlatValue,
    IntervalValue,
    MapLattice,
    PropagatorNetwork,
    SetLattice,
    coerce_to_lattice_value,
)


def test_coerce_to_lattice_value() -> None:
    """Verify conversion of Python primitives to appropriate LatticeValue subtypes."""
    # Already a LatticeValue
    fv = FlatValue(42)
    assert coerce_to_lattice_value(fv) is fv

    # None -> BOTTOM
    assert coerce_to_lattice_value(None) == BOTTOM

    # bool -> FlatValue
    assert coerce_to_lattice_value(True) == FlatValue(True)
    assert coerce_to_lattice_value(False) == FlatValue(False)

    # int / float / str -> FlatValue
    assert coerce_to_lattice_value(10) == FlatValue(10)
    assert coerce_to_lattice_value(3.14) == FlatValue(3.14)
    assert coerce_to_lattice_value("hello") == FlatValue("hello")

    # tuple -> IntervalValue
    iv = coerce_to_lattice_value((10, 20))
    assert isinstance(iv, IntervalValue)
    assert iv.min_val == 10.0 and iv.max_val == 20.0

    # set / frozenset -> SetLattice
    s = coerce_to_lattice_value({1, 2, 3})
    assert isinstance(s, SetLattice)
    assert s.elements == frozenset({1, 2, 3})

    # dict -> MapLattice
    m = coerce_to_lattice_value({"key": "val"})
    assert isinstance(m, MapLattice)
    assert m.mapping == {"key": "val"}


def test_cell_value_setter_propagates() -> None:
    """Verify that cell.value = x invokes set_value and wakes downstream propagators."""
    net = PropagatorNetwork("SetterTest")
    a = net.add_cell("a")
    b = net.add_cell("b")
    c = net.add_cell("c")
    net.add_propagator(AdderPropagator("add", a, b, c))

    # Setting a.value = 15 should coerce and enqueue propagator
    a.value = 15
    b.value = 25
    net.run()

    assert c.value == FlatValue(40)
    assert c.val == 40
    assert c.raw == 40


def test_cell_val_and_raw_unwrapping() -> None:
    """Verify cell.val / cell.raw unwrap lattice values to Python primitives."""
    net = PropagatorNetwork("UnwrapTest")
    c1 = net.add_cell("c1", 42)
    assert c1.val == 42
    assert c1.raw == 42

    c2 = net.add_cell("c2", (5.0, 15.0))
    assert c2.val == (5.0, 15.0)

    c3 = net.add_cell("c3", DiscreteDomain({"red", "green"}))
    assert c3.val == frozenset({"red", "green"})

    c4 = net.add_cell("c4", {1, 2})
    assert c4.val == frozenset({1, 2})

    c_bottom = net.add_cell("c_bot", BOTTOM)
    assert c_bottom.val is None

    c_contra = net.add_cell("c_contra", Contradiction("test clash"))
    assert c_contra.val is None


def test_cell_bind_and_lshift() -> None:
    """Verify cell.bind() and cell << expr unification sugar."""
    net = PropagatorNetwork("BindTest")
    a = net.add_cell("a", 100)
    b = net.add_cell("b", 25)
    c = net.add_cell("c")

    # c << (a - b)
    c << (a - b)
    net.run()
    assert c.val == 75

    # Reverse propagation test via bind
    net2 = PropagatorNetwork("BindRevTest")
    x = net2.add_cell("x")
    y = net2.add_cell("y", 40)
    total = net2.add_cell("total", 100)
    total.bind(x + y)
    net2.run()
    assert x.val == 60


def test_network_attribute_and_mapping_access() -> None:
    """Verify dynamic attribute access and dictionary protocols on PropagatorNetwork."""
    net = PropagatorNetwork("DynNet")

    # Attribute assignment creates / sets cells
    net.x = 12
    net.y = 8
    assert net.x.val == 12
    assert net.y.val == 8

    # Expression assignment unifies cell
    net.z = net.x + net.y
    net.run()
    assert net.z.val == 20

    # Dict access
    assert net["z"].val == 20
    net["w"] = 50
    assert net.w.val == 50

    # Containment, length, and iteration
    assert "x" in net
    assert "y" in net
    assert "nonexistent" not in net
    assert len(net) >= 4
    cell_ids = {c.cell_id for c in net}
    assert "x" in cell_ids and "y" in cell_ids

    # Deletion
    del net["w"]
    assert "w" not in net
    with pytest.raises(KeyError):
        _ = net["w"]

    # Dynamic cell auto-creation on attribute read
    missing_cell = net.missing
    assert isinstance(missing_cell, Cell)
    assert missing_cell.cell_id == "missing"
    assert "missing" in net

    # Private attributes raise AttributeError
    with pytest.raises(AttributeError):
        _ = net._nonexistent

    # Overwrite value attribute safely
    net.x = 100
    # Overwrite triggers update
    assert net.x.val == 100


def test_scoped_assumption_context_manager() -> None:
    """Verify scoped assumption entry and automatic retraction on exit."""
    net = PropagatorNetwork("HypotheticalNet")
    net.temp = 20.0
    net.alarm = False
    alarm_prop = AdderPropagator(
        "temp_offset", net.temp, net.add_cell("offset", 0.0), net.add_cell("monitored")
    )
    net.add_propagator(alarm_prop)
    net.run()
    assert net.monitored.val == 20.0

    # Enter hypothetical assumption scope
    with net.assume("hyp_overheat", cell=net.temp, value=45.0, confidence=0.7):
        net.run()
        assert net.temp.val == 45.0
        assert net.monitored.val == 45.0

    # Upon context exit, assumption is automatically retracted and network re-propagated
    assert net.temp.val == 20.0
    assert net.monitored.val == 20.0


def test_declarative_propagator_model() -> None:
    """Verify class-based component DSL using PropagatorModel and CellDescriptor."""
    from lattice_propagator import CellDescriptor, PropagatorModel

    class VoltageDivider(PropagatorModel):
        v_in = CellDescriptor(unit="V")
        r1 = CellDescriptor(default=1000.0, unit="Ω")
        r2 = CellDescriptor(default=2000.0, unit="Ω")
        v_out = CellDescriptor(unit="V")

        def setup(self) -> None:
            # v_out << v_in * (r2 / (r1 + r2))
            self.v_out << (self.v_in * (self.r2 / (self.r1 + self.r2)))

    divider = VoltageDivider("Divider1")
    assert "v_in" in divider
    assert "r1" in divider
    assert divider.r1.val == 1000.0
    assert divider.r2.val == 2000.0

    divider.v_in = 12.0
    divider.run()
    assert abs(divider.v_out.val - 8.0) < 1e-4

    # Reverse calculation: Provide v_out and deduce v_in
    divider2 = VoltageDivider("Divider2")
    divider2.v_out = 6.0
    divider2.run()
    assert abs(divider2.v_in.val - 9.0) < 1e-4


def test_functional_relation_decorator() -> None:
    """Verify @relation and @rel.invert decorator syntax for multi-directional propagation."""
    net = PropagatorNetwork("TempConversion")

    @net.relation(inputs=["c"], outputs=["f"])
    def c_to_f(c: float) -> float:
        return c * 9.0 / 5.0 + 32.0

    @c_to_f.invert(inputs=["f"], outputs=["c"])
    def f_to_c(f: float) -> float:
        return (f - 32.0) * 5.0 / 9.0

    # 1. Forward propagation
    net.c = 100.0
    net.run()
    assert abs(net.f.val - 212.0) < 1e-4

    # 2. Reverse propagation in a fresh network
    net2 = PropagatorNetwork("TempReverse")
    c_to_f.attach(net2)
    net2.f = 32.0
    net2.run()
    assert abs(net2.c.val - 0.0) < 1e-4
