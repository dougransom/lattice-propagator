"""Unit tests for Bidirectional Arithmetic, Switches, Operator Overloading, and Cell Unification."""

import math

import pytest

from lattice_propagator.lattice import (
    BOTTOM,
    FlatValue,
    GaussianValue,
    IntervalValue,
)
from lattice_propagator.primitives import (
    AdderPropagator,
    ConditionalPropagator,
    MultiplierPropagator,
    PropagatorNetwork,
    SwitchPropagator,
    lift_propagator,
)


def test_adder_propagator_bidirectional_intervals():
    """Verify forward and backward deduction through AdderPropagator with intervals."""
    net = PropagatorNetwork("AdderTest")
    a = net.add_cell("A")
    b = net.add_cell("B")
    c = net.add_cell("C")

    adder = AdderPropagator("Add_A_B_C", a, b, c)
    net.add_propagator(adder)

    # 1. Forward: A + B -> C
    a.set_value(IntervalValue(10.0, 20.0))
    b.set_value(IntervalValue(5.0, 15.0))
    net.run()

    c_val = c.value
    assert isinstance(c_val, IntervalValue)
    assert math.isclose(c_val.min_val, 15.0)
    assert math.isclose(c_val.max_val, 35.0)

    # 2. Refinement backward: tighten C to [18.0, 22.0]
    # Expect A to be refined by C - B = [18 - 15, 22 - 5] = [3, 17] intersected with [10, 20] -> [10, 17]
    c.set_value(IntervalValue(18.0, 22.0))
    net.run()

    a_val = a.value
    assert isinstance(a_val, IntervalValue)
    assert math.isclose(a_val.min_val, 10.0)
    assert math.isclose(a_val.max_val, 17.0)


def test_adder_propagator_backward_from_scratch():
    """Verify backward deduction when C and B are known first."""
    net = PropagatorNetwork("BackwardAdder")
    a = net.add_cell("A")
    b = net.add_cell("B", IntervalValue(50.0, 50.0))
    c = net.add_cell("C", IntervalValue(150.0, 150.0))

    adder = AdderPropagator("Add", a, b, c)
    net.add_propagator(adder)
    net.run()

    assert isinstance(a.value, IntervalValue)
    assert math.isclose(a.value.min_val, 100.0)
    assert math.isclose(a.value.max_val, 100.0)


def test_adder_propagator_flat_and_gaussian():
    """Verify AdderPropagator on FlatValue and GaussianValue."""
    net = PropagatorNetwork("FlatAdder")
    a = net.add_cell("A", FlatValue(12))
    b = net.add_cell("B", FlatValue(8))
    c = net.add_cell("C")

    adder = AdderPropagator("FlatAdd", a, b, c)
    net.add_propagator(adder)
    net.run()

    assert c.value == FlatValue(20)

    # Backward deduction on FlatValue
    net2 = PropagatorNetwork("GaussianAdder")
    g_a = net2.add_cell("GA", GaussianValue(mean=10.0, variance=2.0))
    g_b = net2.add_cell("GB", GaussianValue(mean=20.0, variance=3.0))
    g_c = net2.add_cell("GC")

    adder_g = AdderPropagator("GAdd", g_a, g_b, g_c)
    net2.add_propagator(adder_g)
    net2.run()

    assert isinstance(g_c.value, GaussianValue)
    assert math.isclose(g_c.value.mean, 30.0)
    assert math.isclose(g_c.value.variance, 5.0)


def test_multiplier_propagator_bidirectional():
    """Verify MultiplierPropagator forward and backward."""
    net = PropagatorNetwork("MultiplierTest")
    x = net.add_cell("X")
    y = net.add_cell("Y")
    z = net.add_cell("Z")

    mult = MultiplierPropagator("Mult", x, y, z)
    net.add_propagator(mult)

    # 1. Forward
    x.set_value(IntervalValue(2.0, 4.0))
    y.set_value(IntervalValue(3.0, 5.0))
    net.run()

    assert isinstance(z.value, IntervalValue)
    assert math.isclose(z.value.min_val, 6.0)
    assert math.isclose(z.value.max_val, 20.0)

    # 2. Backward: if Z is known to be [12, 12] and Y is [3, 4] -> X = Z / Y = [12/4, 12/3] = [3, 4]
    net2 = PropagatorNetwork("MultBackward")
    x2 = net2.add_cell("X2")
    y2 = net2.add_cell("Y2", IntervalValue(3.0, 4.0))
    z2 = net2.add_cell("Z2", IntervalValue(12.0, 12.0))

    net2.add_propagator(MultiplierPropagator("Mult2", x2, y2, z2))
    net2.run()

    assert isinstance(x2.value, IntervalValue)
    assert math.isclose(x2.value.min_val, 3.0)
    assert math.isclose(x2.value.max_val, 4.0)


def test_cell_operator_overloading_temperature_conversion():
    """Verify bidirectional temperature conversion: F = C * 1.8 + 32."""
    # 1. Forward direction: Celsius -> Fahrenheit
    net = PropagatorNetwork("TempConversion")
    celsius = net.add_cell("Celsius")
    fahrenheit = celsius * 1.8 + 32

    celsius.set_value(IntervalValue(100.0, 100.0))
    net.run()

    assert isinstance(fahrenheit.value, IntervalValue)
    assert math.isclose(fahrenheit.value.min_val, 212.0)
    assert math.isclose(fahrenheit.value.max_val, 212.0)

    # 2. Backward direction on the same network structure: Fahrenheit -> Celsius
    net_rev = PropagatorNetwork("TempReverse")
    c_rev = net_rev.add_cell("C_Rev")
    f_rev = c_rev * 1.8 + 32

    # Assert Fahrenheit = 32 (freezing point)
    f_rev.set_value(IntervalValue(32.0, 32.0))
    net_rev.run()

    assert isinstance(c_rev.value, IntervalValue)
    assert math.isclose(c_rev.value.min_val, 0.0, abs_tol=1e-5)
    assert math.isclose(c_rev.value.max_val, 0.0, abs_tol=1e-5)


def test_switch_propagator():
    """Verify conditional gating with SwitchPropagator."""
    net = PropagatorNetwork("SwitchTest")
    control = net.add_cell("Control")
    sensor = net.add_cell("Sensor", IntervalValue(20.0, 25.0))
    output = net.add_cell("Output")

    sw = SwitchPropagator("Gate", control, sensor, output, on_value=True)
    net.add_propagator(sw)

    # Control is initially Bottom -> Output remains Bottom
    net.run()
    assert output.value == BOTTOM

    # Control set to False -> Output remains Bottom
    control.set_value(FlatValue(False))
    net.run()
    assert output.value == BOTTOM

    # Control set to True (overwrite) -> Output receives sensor value
    control.set_value(FlatValue(True), overwrite=True)
    net.run()
    assert output.value == IntervalValue(20.0, 25.0)


def test_conditional_propagator_and_sussman_optimization():
    """Verify if-then-else routing and Sussman's optimization when branches agree."""
    net = PropagatorNetwork("CondTest")
    cond = net.add_cell("Condition")
    true_b = net.add_cell("TrueBranch", IntervalValue(10.0, 20.0))
    false_b = net.add_cell("FalseBranch", IntervalValue(30.0, 40.0))
    out = net.add_cell("Output")

    mux = ConditionalPropagator("Mux", cond, true_b, false_b, out)
    net.add_propagator(mux)

    # 1. Unknown condition, differing branches -> Output remains Bottom
    net.run()
    assert out.value == BOTTOM

    # 2. Condition = True -> Output is [10, 20]
    cond.set_value(FlatValue(True))
    net.run()
    assert out.value == IntervalValue(10.0, 20.0)

    # 3. Sussman's optimization: both branches agree on the same value -> output produced even if condition is BOTTOM!
    net2 = PropagatorNetwork("AgreeTest")
    c2 = net2.add_cell("Cond2")  # remains BOTTOM
    t2 = net2.add_cell("T2", IntervalValue(42.0, 42.0))
    f2 = net2.add_cell("F2", IntervalValue(42.0, 42.0))
    out2 = net2.add_cell("Out2")

    net2.add_propagator(ConditionalPropagator("Mux2", c2, t2, f2, out2))
    net2.run()
    # Output receives [42, 42] even though condition is unknown!
    assert out2.value == IntervalValue(42.0, 42.0)


def test_cell_unification_union_find():
    """Verify cell aliasing / unification via Disjoint Set Union."""
    net = PropagatorNetwork("UnifyTest")
    x = net.add_cell("X", IntervalValue(10.0, 50.0))
    y = net.add_cell("Y", IntervalValue(30.0, 80.0))
    z = net.add_cell("Z")

    # Add a propagator watching Y: Z = Y + 5
    net.add_propagator(
        AdderPropagator("Z_Add", y, net.add_cell("Five", IntervalValue(5.0, 5.0)), z)
    )
    net.run()
    # Before unification, Y is [30, 80], Z is [35, 85]
    assert z.value == IntervalValue(35.0, 85.0)

    # Unify X and Y
    x.unify(y)
    net.run()

    # Merged value is [30, 50]
    assert x.value == IntervalValue(30.0, 50.0)
    assert y.value == IntervalValue(30.0, 50.0)
    # Propagators on Y should now have updated Z = [30+5, 50+5] = [35, 55]
    assert z.value == IntervalValue(35.0, 55.0)

    # Update X -> Y reflects it and triggers Z update
    x.set_value(IntervalValue(40.0, 45.0))
    net.run()
    assert y.value == IntervalValue(40.0, 45.0)
    assert z.value == IntervalValue(45.0, 50.0)


def test_lift_propagator():
    """Verify lifting an arbitrary pure function over cells into a propagator."""
    net = PropagatorNetwork("LiftTest")
    in1 = net.add_cell("In1", IntervalValue(2.0, 5.0))
    in2 = net.add_cell("In2", IntervalValue(10.0, 20.0))
    out = net.add_cell("Out")

    # Custom function: hypotenuse interval
    def hypot(a: IntervalValue, b: IntervalValue) -> IntervalValue:
        min_hypot = math.sqrt(a.min_val**2 + b.min_val**2)
        max_hypot = math.sqrt(a.max_val**2 + b.max_val**2)
        return IntervalValue(min_hypot, max_hypot)

    p = lift_propagator("HypotPropagator", hypot, [in1, in2], out)
    net.add_propagator(p)
    net.run()

    assert isinstance(out.value, IntervalValue)
    assert math.isclose(out.value.min_val, math.sqrt(4 + 100), abs_tol=1e-4)
    assert math.isclose(out.value.max_val, math.sqrt(25 + 400), abs_tol=1e-4)


def test_invalid_binary_op_validation():
    """Verify that unsupported binary operators are immediately rejected."""
    from lattice_propagator.primitives import Cell, _build_binary_op

    c1 = Cell("c1")
    c2 = Cell("c2")
    with pytest.raises(ValueError, match="Unsupported binary operator 'power'"):
        _build_binary_op(c1, c2, op="power")
