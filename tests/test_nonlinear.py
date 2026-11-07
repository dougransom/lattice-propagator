"""Test suite for non-linear interval contraction propagators (Power, Sqrt, Exp, Log)."""

from __future__ import annotations

import math

from lattice_propagator.lattice import Contradiction, FlatValue, IntervalValue
from lattice_propagator.nonlinear import (
    ExpPropagator,
    LogPropagator,
    PowerPropagator,
    SqrtPropagator,
)
from lattice_propagator.primitives import PropagatorNetwork


def test_power_propagator_scalar() -> None:
    net = PropagatorNetwork("PowerScalar")
    x = net.add_cell("x")
    res = net.add_cell("res")
    PowerPropagator("pow_sq", x, 2, res)

    x.set_value(FlatValue(4.0))
    net.run()
    assert res.value == FlatValue(16.0)

    # Backward: res=25 -> x in [-5, 5]
    net2 = PropagatorNetwork("PowerScalarRev")
    a = net2.add_cell("a")
    r2 = net2.add_cell("r2")
    PowerPropagator("pow_rev", a, 2, r2)

    r2.set_value(FlatValue(25.0))
    net2.run()
    val_a = a.value
    assert isinstance(val_a, IntervalValue)
    assert math.isclose(val_a.min_val, -5.0)
    assert math.isclose(val_a.max_val, 5.0)


def test_power_propagator_even_interval_zero_crossing() -> None:
    net = PropagatorNetwork("PowerZeroCrossing")
    x = net.add_cell("x")
    res = net.add_cell("res")
    PowerPropagator("pow2", x, 2, res)

    # Base spans negative and positive: [-3, 2]
    # x^2 minimum is 0, maximum is (-3)^2 = 9
    x.set_value(IntervalValue(-3.0, 2.0))
    net.run()

    val_res = res.value
    assert isinstance(val_res, IntervalValue)
    assert math.isclose(val_res.min_val, 0.0)
    assert math.isclose(val_res.max_val, 9.0)


def test_power_propagator_odd_exponent() -> None:
    net = PropagatorNetwork("PowerOdd")
    x = net.add_cell("x")
    res = net.add_cell("res")
    PowerPropagator("pow3", x, 3, res)

    # Forward: [-2, 3] ** 3 -> [-8, 27]
    x.set_value(IntervalValue(-2.0, 3.0))
    net.run()

    val_res = res.value
    assert isinstance(val_res, IntervalValue)
    assert math.isclose(val_res.min_val, -8.0)
    assert math.isclose(val_res.max_val, 27.0)

    # Backward: [-8, 27] ** (1/3) -> [-2, 3]
    net2 = PropagatorNetwork("PowerOddRev")
    a = net2.add_cell("a")
    r = net2.add_cell("r", IntervalValue(-8.0, 27.0))
    PowerPropagator("pow3_rev", a, 3, r)
    net2.run()

    val_a = a.value
    assert isinstance(val_a, IntervalValue)
    assert math.isclose(val_a.min_val, -2.0, abs_tol=1e-6)
    assert math.isclose(val_a.max_val, 3.0, abs_tol=1e-6)


def test_power_propagator_even_negative_contradiction() -> None:
    net = PropagatorNetwork("PowerConflict")
    x = net.add_cell("x")
    res = net.add_cell("res", IntervalValue(-10.0, -1.0))
    PowerPropagator("pow_conflict", x, 2, res)

    net.run()
    assert isinstance(x.value, Contradiction)


def test_cell_pow_dunder_operator() -> None:
    net = PropagatorNetwork("DunderPow")
    x = net.add_cell("x")
    # y = x ** 2
    y = x**2

    x.set_value(IntervalValue(2.0, 4.0))
    net.run()

    val_y = y.value
    assert isinstance(val_y, IntervalValue)
    assert math.isclose(val_y.min_val, 4.0)
    assert math.isclose(val_y.max_val, 16.0)


def test_sqrt_propagator_bidirectional() -> None:
    net = PropagatorNetwork("SqrtTest")
    in_ = net.add_cell("in")
    out = net.add_cell("out")
    SqrtPropagator("sqrt1", in_, out)

    # Forward: [4, 9] -> [2, 3]
    in_.set_value(IntervalValue(4.0, 9.0))
    net.run()

    val_out = out.value
    assert isinstance(val_out, IntervalValue)
    assert math.isclose(val_out.min_val, 2.0)
    assert math.isclose(val_out.max_val, 3.0)

    # Backward: out in [3, 5] -> in_ in [9, 25]
    net2 = PropagatorNetwork("SqrtRev")
    p = net2.add_cell("p")
    q = net2.add_cell("q", IntervalValue(3.0, 5.0))
    SqrtPropagator("sqrt2", p, q)
    net2.run()

    val_p = p.value
    assert isinstance(val_p, IntervalValue)
    assert math.isclose(val_p.min_val, 9.0)
    assert math.isclose(val_p.max_val, 25.0)


def test_sqrt_propagator_negative_domain_contradiction() -> None:
    net = PropagatorNetwork("SqrtDomain")
    in_ = net.add_cell("in", IntervalValue(-10.0, -2.0))
    out = net.add_cell("out")
    SqrtPropagator("sqrt_err", in_, out)

    net.run()
    assert isinstance(out.value, Contradiction)


def test_exp_and_log_propagators() -> None:
    net = PropagatorNetwork("ExpTest")
    x = net.add_cell("x")
    y = net.add_cell("y")
    ExpPropagator("exp1", x, y)

    # Forward: exp(0) = 1
    x.set_value(FlatValue(0.0))
    net.run()
    assert math.isclose(float(y.value.val), 1.0)

    # Backward: y = e -> x = 1
    net2 = PropagatorNetwork("ExpRev")
    a = net2.add_cell("a")
    b = net2.add_cell("b", FlatValue(math.e))
    ExpPropagator("exp2", a, b)
    net2.run()
    assert math.isclose(float(a.value.val), 1.0)

    # Log propagator
    net3 = PropagatorNetwork("LogTest")
    p = net3.add_cell("p", FlatValue(1.0))
    q = net3.add_cell("q")
    LogPropagator("log1", p, q)
    net3.run()
    assert math.isclose(float(q.value.val), 0.0)


def test_joule_heating_power_dissipation_network() -> None:
    """Model electric power dissipation P = I² * R with multi-directional interval deduction."""
    net = PropagatorNetwork("JouleHeating")
    current = net.add_cell("current")  # I
    resistance = net.add_cell("resistance")  # R

    # P = I² * R
    i_sq = current**2
    power = i_sq * resistance

    # Forward: Current in [2, 3] A, Resistance = 10 Ohm
    # I² in [4, 9] A² => P in [40, 90] W
    current.set_value(IntervalValue(2.0, 3.0))
    resistance.set_value(IntervalValue(10.0, 10.0))
    net.run()

    val_p = power.value
    assert isinstance(val_p, IntervalValue)
    assert math.isclose(val_p.min_val, 40.0)
    assert math.isclose(val_p.max_val, 90.0)
