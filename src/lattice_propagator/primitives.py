"""Generalized Propagator Network Primitives and Constraint Engine.

Based on the propagator computational model by Alexey Radul and Gerald Jay Sussman:
- Radul, A., & Sussman, G. J. (2009). "The Art of the Propagator", MIT-CSAIL-TR-2009-002.
  https://dspace.mit.edu/handle/1721.1/44215
- Hanson, C., & Sussman, G. J. (2021). "Software Design for Flexibility", MIT Press, Chapter 7.
  https://draugus.github.io/pdf/Software%20Design%20for%20Flexibility%20-%20Chris%20Hanson.pdf
- Sussman, G. J., & Steele, G. L. (1980). "CONSTRAINTS", Artificial Intelligence 14(1).

Core building blocks for composing autonomous propagator networks:
- Cell: Reactive container holding lattice values with TMS dependency tracking.
- Propagator: Monotonic constraint operator linking input cells to output cells.
- Primitive Operators:
  * ArithmeticPropagator: Linear combinations, differences, and power balances.
  * RatePropagator: Derivative/velocity and time-to-threshold (ETA) intervals.
  * LagPropagator: First-order dynamic lag (RC thermal inertia / exponential smoothing).
  * BoundedLinearPropagator: Interval constraint modulation based on cost/solar signals.
  * ThresholdPropagator: Bounded threshold comparisons with hysteresis.
- PropagatorNetwork: Fixed-point relaxation engine with TMS justification tracking.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .lattice import (
    BOTTOM,
    BeliefMassValue,
    Bottom,
    Contradiction,
    DiscreteDomain,
    FlatValue,
    GaussianValue,
    IntervalValue,
    LatticeValue,
    merge_lattice,
)
from .tms import Justification


class Cell:
    """Reactive container holding an information lattice value with alias/unification support."""

    def __init__(
        self,
        cell_id: str,
        value: LatticeValue = BOTTOM,
        propagators: list[Propagator] | None = None,
        network: PropagatorNetwork | None = None,
        unit: str = "",
        display_name: str | None = None,
    ) -> None:
        self.cell_id = cell_id
        self._value = value
        self.propagators: list[Propagator] = propagators if propagators is not None else []
        self.network = network
        self.unit = unit
        self.display_name = display_name
        self.tms: Any = None
        self._alias_parent: Cell | None = None

    def _find(self) -> Cell:
        """Find the canonical root cell in the alias equivalence class (with path compression)."""
        curr = self
        while curr._alias_parent is not None:
            if curr._alias_parent._alias_parent is not None:
                curr._alias_parent = curr._alias_parent._alias_parent
            curr = curr._alias_parent
        return curr

    @property
    def value(self) -> LatticeValue:
        """Return the canonical value of this cell."""
        return self._find()._value

    @value.setter
    def value(self, new_value: LatticeValue) -> None:
        """Set the canonical value of this cell."""
        root = self._find()
        root._value = new_value

    def add_propagator(self, propagator: Propagator) -> None:
        """Register a propagator that observes this cell or its canonical representative."""
        root = self._find()
        if propagator not in root.propagators:
            root.propagators.append(propagator)

    def unify(self, other: Cell) -> None:
        """Unify this cell with another cell using Disjoint Set Union (Union-Find).

        Merges their lattice values, shares subscriptions, and aligns representations.
        """
        root_self = self._find()
        root_other = other._find()
        if root_self is root_other:
            return

        # 1. Merge values
        new_val = merge_lattice(root_self._value, root_other._value)
        root_self._value = new_val
        root_other._value = new_val

        # 2. Re-parent
        root_other._alias_parent = root_self

        # 3. Transfer propagators
        for p in root_other.propagators:
            root_self.add_propagator(p)
            p.inputs = [root_self if c is root_other else c for c in p.inputs]
            p.outputs = [root_self if c is root_other else c for c in p.outputs]

        # 4. Notify network
        net = root_self.network or root_other.network
        if net is not None:
            root_self.network = net
            net.notify_changed(root_self, source="unify")

    def get_or_create_tms(self) -> Any:
        """Get or create the Truth Maintenance System associated with this cell."""
        root = self._find()
        if root.tms is None:
            from .tms import TruthMaintenanceSystem

            root.tms = TruthMaintenanceSystem(
                cell_id=root.cell_id,
                default_prior=root._value,
                unit=root.unit,
                display_name=root.display_name,
                network=root.network,
            )
        return root.tms

    def explain(self, unit: str | None = None, depth: int | None = 1) -> str:
        """Generate a human-readable explanation for this cell's state and provenance."""
        return self.get_or_create_tms().explain(unit=unit, depth=depth)

    def set_value(
        self,
        new_value: LatticeValue,
        source: str | None = None,
        overwrite: bool = False,
        justification: Justification | None = None,
        confidence: float = 1.0,
        is_assumption: bool = False,
    ) -> bool:
        """Merge or update a value into this cell (or its canonical representative).

        Returns True if the cell's value was updated (information gained).
        """
        root = self._find()
        if source:
            tms = root.get_or_create_tms()
            tms.assert_evidence(
                source_id=source,
                value=new_value,
                justification=justification,
                confidence=confidence,
                is_assumption=is_assumption,
            )

        if overwrite or root._value == BOTTOM:
            if root._value == new_value:
                return False
            root._value = new_value
            if root.network:
                root.network.notify_changed(root, source=source)
            return True

        merged = merge_lattice(root._value, new_value)
        if merged == root._value:
            return False

        root._value = merged
        if root.network:
            root.network.notify_changed(root, source=source)
        return True

    def __add__(self, other: Any) -> Cell:
        return _build_binary_op(self, other, op="add")

    def __radd__(self, other: Any) -> Cell:
        return _build_binary_op(other, self, op="add")

    def __sub__(self, other: Any) -> Cell:
        return _build_binary_op(self, other, op="sub")

    def __rsub__(self, other: Any) -> Cell:
        return _build_binary_op(other, self, op="sub")

    def __mul__(self, other: Any) -> Cell:
        return _build_binary_op(self, other, op="mul")

    def __rmul__(self, other: Any) -> Cell:
        return _build_binary_op(other, self, op="mul")

    def __truediv__(self, other: Any) -> Cell:
        return _build_binary_op(self, other, op="div")

    def __rtruediv__(self, other: Any) -> Cell:
        return _build_binary_op(other, self, op="div")

    def __repr__(self) -> str:
        root = self._find()
        if root is not self:
            return f"Cell({self.cell_id} -> {root.cell_id}: {root._value})"
        return f"Cell({self.cell_id}: {self._value})"


class Propagator(ABC):
    """Abstract base class for all propagator operators."""

    def __init__(
        self,
        name: str,
        inputs: list[Cell],
        outputs: list[Cell],
    ) -> None:
        self.name = name
        self.inputs = inputs
        self.outputs = outputs
        for c in inputs:
            c.add_propagator(self)

    @abstractmethod
    def alert(self, network: PropagatorNetwork) -> None:
        """Execute propagation when an input cell updates."""


class ArithmeticPropagator(Propagator):
    """Computes a linear combination or difference: output = sum(w_i * x_i) + offset."""

    def __init__(
        self,
        name: str,
        inputs: list[Cell],
        output: Cell,
        weights: list[float] | None = None,
        offset: float = 0.0,
    ) -> None:
        super().__init__(name, inputs, [output])
        self.output = output
        self.weights = weights or [1.0] * len(inputs)
        self.offset = offset

    def alert(self, network: PropagatorNetwork) -> None:
        """Calculate weighted sum across input cells."""
        # Check if all inputs have values
        if any(isinstance(c.value, (Bottom, Contradiction)) for c in self.inputs):
            return

        # Case 1: Pure floats or Gaussians
        all_gaussian = all(isinstance(c.value, GaussianValue) for c in self.inputs)
        if all_gaussian:
            # Linear combination of Gaussians:
            # μ = sum(w_i * μ_i) + offset
            # σ² = sum(w_i² * σ_i²)
            mu = self.offset
            var = 0.0
            for c, w in zip(self.inputs, self.weights, strict=False):
                val = c.value
                assert isinstance(val, GaussianValue)
                mu += w * val.mean
                var += (w**2) * val.variance

            new_val = GaussianValue(mean=mu, variance=max(var, 1e-6))
            just = Justification(
                rule_name=self.__class__.__name__,
                antecedents=tuple(c.cell_id for c in self.inputs),
                parameters={"weights": self.weights, "offset": self.offset},
            )
            self.output.set_value(new_val, source=self.name, justification=just)
            return

        # Case 2: Intervals
        all_interval = all(isinstance(c.value, (IntervalValue, GaussianValue)) for c in self.inputs)
        if all_interval:
            min_sum = self.offset
            max_sum = self.offset
            for c, w in zip(self.inputs, self.weights, strict=False):
                if isinstance(c.value, IntervalValue):
                    c_min, c_max = c.value.min_val, c.value.max_val
                else:
                    assert isinstance(c.value, GaussianValue)
                    c_min, c_max = c.value.confidence_interval(0.95)

                if w >= 0:
                    min_sum += w * c_min
                    max_sum += w * c_max
                else:
                    min_sum += w * c_max
                    max_sum += w * c_min

            new_val = IntervalValue(min_val=min_sum, max_val=max_sum)
            just = Justification(
                rule_name=self.__class__.__name__,
                antecedents=tuple(c.cell_id for c in self.inputs),
                parameters={"weights": self.weights, "offset": self.offset},
            )
            self.output.set_value(new_val, source=self.name, justification=just)


def _to_interval_or_none(v: LatticeValue) -> IntervalValue | None:
    if isinstance(v, IntervalValue):
        return v
    if isinstance(v, FlatValue) and isinstance(v.val, (int, float)):
        return IntervalValue(float(v.val), float(v.val))
    if isinstance(v, GaussianValue):
        low, high = v.confidence_interval(0.95)
        return IntervalValue(low, high)
    return None


def _should_update_target(current: LatticeValue, candidate: LatticeValue) -> bool:
    """Determine if a candidate value refines or contradicts the target cell."""
    if isinstance(current, Bottom):
        return True
    if isinstance(current, IntervalValue) and isinstance(candidate, IntervalValue):
        tighter_min = candidate.min_val > current.min_val + 1e-9
        tighter_max = candidate.max_val < current.max_val - 1e-9
        disjoint = candidate.min_val > current.max_val or candidate.max_val < current.min_val
        return tighter_min or tighter_max or disjoint
    if isinstance(current, FlatValue) and isinstance(candidate, FlatValue):
        return current.val != candidate.val
    return isinstance(candidate, Contradiction)


def _add_values(v1: LatticeValue, v2: LatticeValue) -> LatticeValue | None:
    if isinstance(v1, (Bottom, Contradiction)) or isinstance(v2, (Bottom, Contradiction)):
        return None
    if isinstance(v1, GaussianValue) and isinstance(v2, GaussianValue):
        return GaussianValue(mean=v1.mean + v2.mean, variance=v1.variance + v2.variance)
    if (
        isinstance(v1, FlatValue)
        and isinstance(v2, FlatValue)
        and isinstance(v1.val, (int, float))
        and isinstance(v2.val, (int, float))
    ):
        return FlatValue(v1.val + v2.val)
    i1 = _to_interval_or_none(v1)
    i2 = _to_interval_or_none(v2)
    if i1 is not None and i2 is not None:
        return IntervalValue(min_val=i1.min_val + i2.min_val, max_val=i1.max_val + i2.max_val)
    return None


def _sub_values(v_total: LatticeValue, v_sub: LatticeValue) -> LatticeValue | None:
    if isinstance(v_total, (Bottom, Contradiction)) or isinstance(v_sub, (Bottom, Contradiction)):
        return None
    if isinstance(v_total, GaussianValue) and isinstance(v_sub, GaussianValue):
        return GaussianValue(
            mean=v_total.mean - v_sub.mean, variance=v_total.variance + v_sub.variance
        )
    if (
        isinstance(v_total, FlatValue)
        and isinstance(v_sub, FlatValue)
        and isinstance(v_total.val, (int, float))
        and isinstance(v_sub.val, (int, float))
    ):
        return FlatValue(v_total.val - v_sub.val)
    i_tot = _to_interval_or_none(v_total)
    i_sub = _to_interval_or_none(v_sub)
    if i_tot is not None and i_sub is not None:
        return IntervalValue(
            min_val=i_tot.min_val - i_sub.max_val, max_val=i_tot.max_val - i_sub.min_val
        )
    return None


def _mul_values(v1: LatticeValue, v2: LatticeValue) -> LatticeValue | None:
    if isinstance(v1, (Bottom, Contradiction)) or isinstance(v2, (Bottom, Contradiction)):
        return None
    if isinstance(v1, GaussianValue) and isinstance(v2, GaussianValue):
        m = v1.mean * v2.mean
        v = (v1.mean**2) * v2.variance + (v2.mean**2) * v1.variance + (v1.variance * v2.variance)
        return GaussianValue(mean=m, variance=max(v, 1e-6))
    if (
        isinstance(v1, FlatValue)
        and isinstance(v2, FlatValue)
        and isinstance(v1.val, (int, float))
        and isinstance(v2.val, (int, float))
    ):
        return FlatValue(v1.val * v2.val)
    i1 = _to_interval_or_none(v1)
    i2 = _to_interval_or_none(v2)
    if i1 is not None and i2 is not None:
        return i1 * i2
    return None


def _div_values(v_num: LatticeValue, v_den: LatticeValue) -> LatticeValue | None:
    if isinstance(v_num, (Bottom, Contradiction)) or isinstance(v_den, (Bottom, Contradiction)):
        return None
    if (
        isinstance(v_num, FlatValue)
        and isinstance(v_den, FlatValue)
        and isinstance(v_num.val, (int, float))
        and isinstance(v_den.val, (int, float))
    ):
        if v_den.val == 0:
            return Contradiction(
                reason="Division by zero in FlatValue", conflicting_values=(v_num, v_den)
            )
        return FlatValue(v_num.val / v_den.val)
    if isinstance(v_num, GaussianValue) and isinstance(v_den, GaussianValue):
        if math.isclose(v_den.mean, 0.0, abs_tol=1e-6):
            return None
        m = v_num.mean / v_den.mean
        v = (v_num.variance + (m**2) * v_den.variance) / (v_den.mean**2 + v_den.variance)
        return GaussianValue(mean=m, variance=max(v, 1e-6))
    i_num = _to_interval_or_none(v_num)
    i_den = _to_interval_or_none(v_den)
    if i_num is not None and i_den is not None:
        if i_den.contains(0.0):
            return None
        return i_num / i_den
    return None


def _coerce_to_cell(val: Any, network: PropagatorNetwork, role: str) -> Cell:
    if isinstance(val, Cell):
        if val.network is None:
            val.network = network
        if val.cell_id not in network.cells:
            network.cells[val.cell_id] = val
        return val
    if isinstance(val, (int, float)):
        val_str = str(val).replace(".", "_").replace("-", "neg_")
        cid = f"const_{val_str}"
        if cid in network.cells:
            return network.cells[cid]
        return network.add_cell(cid, IntervalValue(float(val), float(val)))
    if isinstance(val, LatticeValue):
        cid = f"const_{type(val).__name__}_{id(val)}"
        return network.add_cell(cid, val)
    raise TypeError(f"Cannot coerce object of type {type(val)} to Cell")


class AdderPropagator(Propagator):
    """Bidirectional adder constraint enforcing a + b = c.

    Propagates monotonically in all 3 directions:
      Forward:    c = a + b
      Backward A: a = c - b
      Backward B: b = c - a
    """

    def __init__(self, name: str, a: Cell, b: Cell, c: Cell) -> None:
        super().__init__(name, inputs=[a, b, c], outputs=[a, b, c])
        self.a = a
        self.b = b
        self.c = c

    def alert(self, network: PropagatorNetwork) -> None:
        val_a = self.a.value
        val_b = self.b.value
        val_c = self.c.value

        # 1. Forward: a + b -> c
        if not isinstance(val_a, (Bottom, Contradiction)) and not isinstance(
            val_b, (Bottom, Contradiction)
        ):
            cand_c = _add_values(val_a, val_b)
            if cand_c is not None and _should_update_target(val_c, cand_c):
                self.c.set_value(cand_c, source=self.name)
                val_c = self.c.value

        # 2. Backward A: c - b -> a
        if not isinstance(val_c, (Bottom, Contradiction)) and not isinstance(
            val_b, (Bottom, Contradiction)
        ):
            cand_a = _sub_values(val_c, val_b)
            if cand_a is not None and _should_update_target(val_a, cand_a):
                self.a.set_value(cand_a, source=self.name)
                val_a = self.a.value

        # 3. Backward B: c - a -> b
        if not isinstance(val_c, (Bottom, Contradiction)) and not isinstance(
            val_a, (Bottom, Contradiction)
        ):
            cand_b = _sub_values(val_c, val_a)
            if cand_b is not None and _should_update_target(val_b, cand_b):
                self.b.set_value(cand_b, source=self.name)


class MultiplierPropagator(Propagator):
    """Bidirectional multiplier constraint enforcing a * b = c.

    Propagates monotonically in all 3 directions with zero-absorption:
      Forward:    c = a * b
      Backward A: a = c / b (when 0 not in b)
      Backward B: b = c / a (when 0 not in a)
    """

    def __init__(self, name: str, a: Cell, b: Cell, c: Cell) -> None:
        super().__init__(name, inputs=[a, b, c], outputs=[a, b, c])
        self.a = a
        self.b = b
        self.c = c

    def alert(self, network: PropagatorNetwork) -> None:
        val_a = self.a.value
        val_b = self.b.value
        val_c = self.c.value

        # 1. Forward: a * b -> c
        if not isinstance(val_a, (Bottom, Contradiction)) and not isinstance(
            val_b, (Bottom, Contradiction)
        ):
            cand_c = _mul_values(val_a, val_b)
            if cand_c is not None and _should_update_target(val_c, cand_c):
                self.c.set_value(cand_c, source=self.name)
                val_c = self.c.value

        # 2. Backward A: c / b -> a
        if not isinstance(val_c, (Bottom, Contradiction)) and not isinstance(
            val_b, (Bottom, Contradiction)
        ):
            cand_a = _div_values(val_c, val_b)
            if cand_a is not None and _should_update_target(val_a, cand_a):
                self.a.set_value(cand_a, source=self.name)
                val_a = self.a.value

        # 3. Backward B: c / a -> b
        if not isinstance(val_c, (Bottom, Contradiction)) and not isinstance(
            val_a, (Bottom, Contradiction)
        ):
            cand_b = _div_values(val_c, val_a)
            if cand_b is not None and _should_update_target(val_b, cand_b):
                self.b.set_value(cand_b, source=self.name)


_BINARY_OPS: dict[str, tuple[str, type[Propagator], bool]] = {
    "add": ("+", AdderPropagator, False),
    "sub": ("-", AdderPropagator, True),
    "mul": ("*", MultiplierPropagator, False),
    "div": ("/", MultiplierPropagator, True),
}


def _build_binary_op(left: Any, right: Any, op: str) -> Cell:
    """Build a binary arithmetic operator cell using declarative dispatch."""
    spec = _BINARY_OPS.get(op)
    if spec is None:
        supported = ", ".join(repr(k) for k in _BINARY_OPS)
        raise ValueError(f"Unsupported binary operator {op!r}. Supported: {supported}")

    symbol, prop_cls, inverted = spec

    net = (
        left.network
        if isinstance(left, Cell) and left.network is not None
        else (
            right.network
            if isinstance(right, Cell) and right.network is not None
            else PropagatorNetwork()
        )
    )

    c_left = _coerce_to_cell(left, net, "left")
    c_right = _coerce_to_cell(right, net, "right")

    out = net.add_cell(f"({c_left.cell_id}{symbol}{c_right.cell_id})")
    args = (out, c_right, c_left) if inverted else (c_left, c_right, out)
    p = prop_cls(f"{op}_{c_left.cell_id}_{c_right.cell_id}", *args)
    net.add_propagator(p)
    return out


class SwitchPropagator(Propagator):
    """Conditional gate / switch propagator.

    Observes a control cell and an input cell. When the control cell matches
    on_value (by default True), it propagates the value of input_cell to output_cell.
    When the control is False or Bottom, nothing is propagated.
    """

    def __init__(
        self,
        name: str,
        control_cell: Cell,
        input_cell: Cell,
        output_cell: Cell,
        on_value: Any = True,
    ) -> None:
        super().__init__(name, inputs=[control_cell, input_cell], outputs=[output_cell])
        self.control_cell = control_cell
        self.input_cell = input_cell
        self.output_cell = output_cell
        self.on_value = on_value

    def alert(self, network: PropagatorNetwork) -> None:
        ctrl = self.control_cell.value
        if isinstance(ctrl, (Bottom, Contradiction)):
            return

        is_active = False
        if isinstance(ctrl, FlatValue):
            is_active = ctrl.val == self.on_value
        elif isinstance(ctrl, DiscreteDomain):
            is_active = ctrl.is_determined and ctrl.value == self.on_value
        elif isinstance(ctrl, IntervalValue):
            is_active = math.isclose(
                ctrl.min_val, float(self.on_value), abs_tol=1e-9
            ) and math.isclose(ctrl.max_val, float(self.on_value), abs_tol=1e-9)
        elif ctrl == self.on_value:
            is_active = True

        if is_active and not isinstance(self.input_cell.value, (Bottom, Contradiction)):
            self.output_cell.set_value(self.input_cell.value, source=self.name)


class ConditionalPropagator(Propagator):
    """Multiplexer / conditional propagator (if-then-else).

    Observes condition_cell, true_cell, and false_cell:
      - If condition is True -> output_cell receives true_cell.value
      - If condition is False -> output_cell receives false_cell.value
      - If true_cell and false_cell have the same value, output receives that
        value even if condition is still Bottom (Sussman's "Art of the Propagator").
    """

    def __init__(
        self,
        name: str,
        condition_cell: Cell,
        true_cell: Cell,
        false_cell: Cell,
        output_cell: Cell,
    ) -> None:
        super().__init__(
            name, inputs=[condition_cell, true_cell, false_cell], outputs=[output_cell]
        )
        self.condition_cell = condition_cell
        self.true_cell = true_cell
        self.false_cell = false_cell
        self.output_cell = output_cell

    def alert(self, network: PropagatorNetwork) -> None:
        cond = self.condition_cell.value
        t_val = self.true_cell.value
        f_val = self.false_cell.value

        # Sussman's optimization: if both branches agree and are not Bottom, output can be set!
        if not isinstance(t_val, (Bottom, Contradiction)) and t_val == f_val:
            self.output_cell.set_value(t_val, source=self.name)
            return

        if isinstance(cond, (Bottom, Contradiction)):
            return

        cond_bool: bool | None = None
        if isinstance(cond, FlatValue):
            cond_bool = bool(cond.val)
        elif isinstance(cond, DiscreteDomain) and cond.is_determined:
            cond_bool = bool(cond.value)
        elif isinstance(cond, IntervalValue):
            if math.isclose(cond.min_val, 1.0, abs_tol=1e-9) and math.isclose(
                cond.max_val, 1.0, abs_tol=1e-9
            ):
                cond_bool = True
            elif math.isclose(cond.min_val, 0.0, abs_tol=1e-9) and math.isclose(
                cond.max_val, 0.0, abs_tol=1e-9
            ):
                cond_bool = False

        if cond_bool is True and not isinstance(t_val, (Bottom, Contradiction)):
            self.output_cell.set_value(t_val, source=self.name)
        elif cond_bool is False and not isinstance(f_val, (Bottom, Contradiction)):
            self.output_cell.set_value(f_val, source=self.name)


class FunctionalPropagator(Propagator):
    """A generic propagator constructed by lifting an arbitrary pure function over cells."""

    def __init__(
        self,
        name: str,
        fn: Callable[..., LatticeValue],
        inputs: list[Cell],
        output: Cell,
        overwrite: bool = True,
    ) -> None:
        super().__init__(name, inputs=inputs, outputs=[output])
        self.fn = fn
        self.output = output
        self.overwrite = overwrite

    def alert(self, network: PropagatorNetwork) -> None:
        if any(isinstance(c.value, (Bottom, Contradiction)) for c in self.inputs):
            return
        args = [c.value for c in self.inputs]
        try:
            res = self.fn(*args)
            if isinstance(res, LatticeValue) and not isinstance(res, Bottom):
                self.output.set_value(res, source=self.name, overwrite=self.overwrite)
        except (TypeError, ValueError, ArithmeticError):
            pass


def lift_propagator(
    name: str,
    fn: Callable[..., LatticeValue],
    inputs: list[Cell],
    output: Cell,
    overwrite: bool = True,
) -> FunctionalPropagator:
    """Lift a function over lattice values into a reactive propagator."""
    return FunctionalPropagator(name, fn, inputs, output, overwrite=overwrite)


class RatePropagator(Propagator):
    """Computes rate of change and estimated time to reach a target threshold.

    rate = (x_now - x_prev) / delta_t
    eta = (x_now - threshold) / rate
    """

    def __init__(
        self,
        name: str,
        input_cell: Cell,
        output_rate_cell: Cell,
        output_eta_cell: Cell | None = None,
        threshold: float = 0.0,
    ) -> None:
        outputs = [output_rate_cell]
        if output_eta_cell:
            outputs.append(output_eta_cell)
        super().__init__(name, [input_cell], outputs)

        self.input_cell = input_cell
        self.output_rate = output_rate_cell
        self.output_eta = output_eta_cell
        self.threshold = threshold

        self._prev_val: float | None = None
        self._prev_time: float | None = None

    def update_observation(
        self, current_val: float, current_time: float, network: PropagatorNetwork
    ) -> None:
        """Push a timestamped scalar observation into the rate calculator."""
        if self._prev_val is not None and self._prev_time is not None:
            dt = current_time - self._prev_time
            if dt > 0:
                dx = current_val - self._prev_val
                rate = dx / dt
                self.output_rate.set_value(
                    GaussianValue(mean=rate, variance=max(abs(rate) * 0.1, 0.01)),
                    source=self.name,
                    overwrite=True,
                )

                if self.output_eta is not None:
                    dist_to_thresh = current_val - self.threshold
                    # Approaching threshold if rate and dist_to_thresh have opposite signs
                    if dist_to_thresh > 0 and rate < -1e-4:
                        eta_sec = abs(dist_to_thresh / rate)
                        # Bounds [eta * 0.85, eta * 1.2]
                        self.output_eta.set_value(
                            IntervalValue(min_val=eta_sec * 0.85, max_val=eta_sec * 1.2),
                            source=self.name,
                            overwrite=True,
                        )
                    elif dist_to_thresh <= 0:
                        self.output_eta.set_value(
                            IntervalValue(min_val=0.0, max_val=0.0),
                            source=self.name,
                            overwrite=True,
                        )

        self._prev_val = current_val
        self._prev_time = current_time

    def alert(self, network: PropagatorNetwork) -> None:
        """Triggered when input cell updates."""
        val = self.input_cell.value
        if isinstance(val, GaussianValue):
            scalar = val.mean
        elif isinstance(val, IntervalValue):
            scalar = val.center
        else:
            return

        import time

        self.update_observation(scalar, time.time(), network)


class LagPropagator(Propagator):
    """First-order dynamic lag filter (RC thermal model or exponential decay).

    x(t + dt) = x(t) + (dt / tau) * (target - x(t))
    """

    def __init__(
        self,
        name: str,
        target_cell: Cell,
        state_cell: Cell,
        output_cell: Cell,
        tau: float,  # Time constant (in seconds or hours)
    ) -> None:
        super().__init__(name, [target_cell, state_cell], [output_cell])
        self.target_cell = target_cell
        self.state_cell = state_cell
        self.output_cell = output_cell
        self.tau = max(tau, 1e-3)

    def step(self, dt: float) -> None:
        """Advance time by dt and propagate the dynamic lag."""
        t_val = self.target_cell.value
        s_val = self.state_cell.value

        if isinstance(t_val, (Bottom, Contradiction)) or isinstance(s_val, (Bottom, Contradiction)):
            return

        alpha = 1.0 - math.exp(-dt / self.tau)
        just = Justification(
            rule_name=self.__class__.__name__,
            antecedents=(self.target_cell.cell_id, self.state_cell.cell_id),
            parameters={"tau": self.tau, "dt": dt, "alpha": round(alpha, 4)},
        )

        if isinstance(t_val, GaussianValue) and isinstance(s_val, GaussianValue):
            next_mu = s_val.mean + alpha * (t_val.mean - s_val.mean)
            next_var = s_val.variance * (1 - alpha) ** 2 + t_val.variance * (alpha**2)
            self.output_cell.set_value(
                GaussianValue(mean=next_mu, variance=max(next_var, 1e-4)),
                source=self.name,
                overwrite=True,
                justification=just,
            )
        elif isinstance(t_val, IntervalValue) and isinstance(s_val, IntervalValue):
            next_min = s_val.min_val + alpha * (t_val.min_val - s_val.min_val)
            next_max = s_val.max_val + alpha * (t_val.max_val - s_val.max_val)
            self.output_cell.set_value(
                IntervalValue(min_val=next_min, max_val=next_max),
                source=self.name,
                overwrite=True,
                justification=just,
            )

    def alert(self, network: PropagatorNetwork) -> None:
        """Alerted when input changes; steps with dt=1.0 or user-driven simulation."""
        self.step(dt=1.0)


class KalmanEstimatorPropagator(Propagator):
    """Linear 2-State Kalman Filter Propagator.

    Tracks an internal continuous state vector [x, dx/dt]^T (e.g. [position, velocity]
    or [temperature, rate]) from noisy scalar observations, projecting marginal Gaussians
    onto individual output cells.
    """

    def __init__(
        self,
        name: str,
        measurement_cell: Cell,
        output_state_cell: Cell,
        output_rate_cell: Cell,
        process_noise_q: float = 0.1,
        default_measurement_noise_r: float = 1.0,
        initial_state: tuple[float, float] = (0.0, 0.0),
        initial_cov: tuple[float, float] = (100.0, 10.0),
    ) -> None:
        super().__init__(name, [measurement_cell], [output_state_cell, output_rate_cell])
        self.measurement_cell = measurement_cell
        self.output_state_cell = output_state_cell
        self.output_rate_cell = output_rate_cell
        self.q = max(process_noise_q, 1e-6)
        self.default_r = max(default_measurement_noise_r, 1e-6)

        # State vector [x, v]
        self.x: float = initial_state[0]
        self.v: float = initial_state[1]

        # Covariance matrix [[P00, P01], [P10, P11]] (P01 == P10)
        self.p00: float = initial_cov[0]
        self.p01: float = 0.0
        self.p11: float = initial_cov[1]

        self._last_time: float | None = None
        self._initialized: bool = False

    def reset(
        self,
        x: float = 0.0,
        v: float = 0.0,
        p00: float = 100.0,
        p11: float = 10.0,
    ) -> None:
        """Reset internal filter state."""
        self.x = x
        self.v = v
        self.p00 = p00
        self.p01 = 0.0
        self.p11 = p11
        self._last_time = None
        self._initialized = False

    def step(self, z: float, r: float | None = None, dt: float | None = None) -> None:
        """Perform predict and update step for observation z."""
        if not self._initialized:
            self.x = z
            self.v = 0.0
            self.p00 = r if r is not None else self.default_r
            self.p01 = 0.0
            self.p11 = self.q * 10.0
            self._initialized = True
            self._publish()
            return

        dt_val = max(dt if dt is not None else 1.0, 1e-4)
        meas_r = max(r if r is not None else self.default_r, 1e-6)

        # 1. Predict
        x_pred = self.x + self.v * dt_val
        v_pred = self.v

        dt2 = dt_val * dt_val
        dt3 = dt2 * dt_val
        p00_pred = self.p00 + 2.0 * dt_val * self.p01 + dt2 * self.p11 + self.q * (dt3 / 3.0)
        p01_pred = self.p01 + dt_val * self.p11 + self.q * (dt2 / 2.0)
        p11_pred = self.p11 + self.q * dt_val

        # 2. Update (H = [1, 0])
        y = z - x_pred
        s = p00_pred + meas_r

        k0 = p00_pred / s
        k1 = p01_pred / s

        self.x = x_pred + k0 * y
        self.v = v_pred + k1 * y

        self.p00 = max((1.0 - k0) * p00_pred, 1e-6)
        self.p01 = (1.0 - k0) * p01_pred
        self.p11 = max(p11_pred - k1 * p01_pred, 1e-6)

        self._publish()

    def _publish(self) -> None:
        """Project marginal distributions to output cells."""
        self.output_state_cell.set_value(
            GaussianValue(mean=self.x, variance=self.p00),
            source=self.name,
            overwrite=True,
        )
        self.output_rate_cell.set_value(
            GaussianValue(mean=self.v, variance=self.p11),
            source=self.name,
            overwrite=True,
        )

    def alert(self, network: PropagatorNetwork) -> None:
        """Handle new observation in measurement cell."""
        val = self.measurement_cell.value
        if isinstance(val, (Bottom, Contradiction)):
            return

        import time

        now = time.time()
        dt = (now - self._last_time) if self._last_time is not None else 1.0
        self._last_time = now

        if isinstance(val, GaussianValue):
            z = val.mean
            r = val.variance
        elif isinstance(val, IntervalValue):
            z = val.center
            sigma = max(val.width / 4.0, 1e-3)
            r = sigma * sigma
        else:
            return

        self.step(z, r=r, dt=dt)


@dataclass(frozen=True)
class SpatialZone:
    """Rectangular 2D bounding zone for a room or spatial region."""

    name: str
    x_min: float
    x_max: float
    y_min: float
    y_max: float

    def contains(self, x: float, y: float) -> bool:
        """Return True if coordinate (x, y) falls within this spatial zone."""
        return self.x_min <= x <= self.x_max and self.y_min <= y <= self.y_max


class DempsterShaferPropagator(Propagator):
    """Combines evidence from multiple source cells using Dempster's rule of combination.

    Observes N input cells holding BeliefMassValue (or Bottom). Whenever any input
    cell updates with new evidential mass, it combines all active evidence orthogonally
    and writes the resulting fused BeliefMassValue to output_cell.
    If conflict_cell is provided, it publishes the orthogonal conflict metric K in [0, 1].
    """

    def __init__(
        self,
        name: str,
        inputs: list[Cell],
        output: Cell,
        conflict_cell: Cell | None = None,
        conflict_threshold: float = 0.95,
    ) -> None:
        out_cells = [output] if conflict_cell is None else [output, conflict_cell]
        super().__init__(name, inputs=inputs, outputs=out_cells)
        self.output_cell = output
        self.conflict_cell = conflict_cell
        self.conflict_threshold = conflict_threshold

    def alert(self, network: PropagatorNetwork) -> None:
        """Combine active evidence across input cells."""
        active_masses: list[BeliefMassValue] = []
        for c in self.inputs:
            val = c.value
            if isinstance(val, BeliefMassValue):
                active_masses.append(val)
            elif isinstance(val, Contradiction):
                self.output_cell.set_value(val, source=self.name)
                return

        if not active_masses:
            return

        current: LatticeValue = active_masses[0]
        max_conflict = 0.0

        for nxt in active_masses[1:]:
            if isinstance(current, BeliefMassValue):
                k = current.conflict_with(nxt)
                max_conflict = max(max_conflict, k)
                current = current.combine(nxt)
                if isinstance(current, Contradiction):
                    break

        if self.conflict_cell is not None:
            self.conflict_cell.set_value(
                FlatValue(round(max_conflict, 4)),
                source=self.name,
                overwrite=True,
            )

        if max_conflict >= self.conflict_threshold and not isinstance(current, Contradiction):
            current = Contradiction(
                reason=(
                    f"High evidential conflict in DempsterShaferPropagator '{self.name}': "
                    f"K={max_conflict:.4f} >= threshold {self.conflict_threshold}"
                ),
                conflicting_values=tuple(active_masses),
            )

        self.output_cell.set_value(current, source=self.name, overwrite=True)


class BoundedLinearPropagator(Propagator):
    """Modulates a target within an acceptable tolerance interval based on a driving signal (e.g. price, solar).

    Target = clamp(Nominal + sensitivity * (Baseline - Signal), [Min, Max])
    """

    def __init__(
        self,
        name: str,
        signal_cell: Cell,
        output_cell: Cell,
        acceptable_range: IntervalValue,
        nominal_target: float,
        baseline_signal: float,
        sensitivity: float,
    ) -> None:
        super().__init__(name, [signal_cell], [output_cell])
        self.signal_cell = signal_cell
        self.output_cell = output_cell
        self.acceptable_range = acceptable_range
        self.nominal_target = nominal_target
        self.baseline_signal = baseline_signal
        self.sensitivity = sensitivity

    def alert(self, network: PropagatorNetwork) -> None:
        """Compute modulated target."""
        val = self.signal_cell.value
        if isinstance(val, (Bottom, Contradiction)):
            return

        sig = val.mean if isinstance(val, GaussianValue) else val.center
        # High signal (e.g. high price) lowers target; cheap signal raises target
        adjustment = self.sensitivity * (self.baseline_signal - sig)
        modulated = self.nominal_target + adjustment

        clamped = max(
            self.acceptable_range.min_val,
            min(self.acceptable_range.max_val, modulated),
        )

        self.output_cell.set_value(
            GaussianValue(mean=clamped, variance=0.04),
            source=self.name,
            overwrite=True,
        )


class ThresholdPropagator(Propagator):
    """Evaluates whether an input cell crosses a critical threshold."""

    def __init__(
        self,
        name: str,
        input_cell: Cell,
        output_bool_cell: Cell,
        threshold: float,
        below: bool = True,
    ) -> None:
        super().__init__(name, [input_cell], [output_bool_cell])
        self.input_cell = input_cell
        self.output_bool = output_bool_cell
        self.threshold = threshold
        self.below = below

    def alert(self, network: PropagatorNetwork) -> None:
        """Evaluate threshold predicate."""
        val = self.input_cell.value
        if isinstance(val, (Bottom, Contradiction)):
            return

        scalar = val.mean if isinstance(val, GaussianValue) else val.center
        is_triggered = (scalar < self.threshold) if self.below else (scalar > self.threshold)
        just = Justification(
            rule_name=self.__class__.__name__,
            antecedents=(self.input_cell.cell_id,),
            parameters={"threshold": self.threshold, "below": self.below},
        )
        # 1.0 = True, 0.0 = False in numeric interval
        self.output_bool.set_value(
            IntervalValue(
                min_val=1.0 if is_triggered else 0.0, max_val=1.0 if is_triggered else 0.0
            ),
            source=self.name,
            overwrite=True,
            justification=just,
        )


class AllDifferentPropagator(Propagator):
    """Enforces that all cells in a unit/group must take mutually distinct values from a DiscreteDomain.

    Performs:
    1. Forward Elimination (Naked Singles): When a cell resolves to a unique value {v}, eliminates v from
       all peers in the unit.
    2. Hidden Singles Deduction: When a candidate v occurs in exactly one undetermined cell in the unit,
       narrows that cell directly to {v}.
    3. Contradiction Detection: Signals Contradiction on duplicate determined values or exhausted domains.
    """

    def __init__(self, name: str, cells: list[Cell]) -> None:
        super().__init__(name, cells, cells)
        self.cells = cells

    def _collect_determined(self) -> dict[Any, Cell] | None:
        """Collect determined values, returning None and setting contradiction on duplicates."""
        determined: dict[Any, Cell] = {}
        for cell in self.cells:
            if isinstance(cell.value, DiscreteDomain) and cell.value.is_determined:
                v = cell.value.value
                if v in determined:
                    cell.set_value(
                        Contradiction(
                            reason=f"Duplicate value {v} in {self.name} between {determined[v].cell_id} and {cell.cell_id}",
                            conflicting_values=(determined[v].value, cell.value),
                        ),
                        source=self.name,
                    )
                    return None
                determined[v] = cell
        return determined

    def _eliminate_value_from_peers(self, v: Any, source_cell: Cell) -> tuple[bool, bool]:
        """Eliminate value v from all peer cells. Returns (did_change, has_conflict)."""
        changed = False
        for target in self.cells:
            if (
                target is not source_cell
                and isinstance(target.value, DiscreteDomain)
                and target.value.contains(v)
            ):
                remaining = target.value.candidates - {v}
                if not remaining:
                    target.set_value(
                        Contradiction(
                            reason=f"Cell {target.cell_id} exhausted all candidates by eliminating {v} in {self.name}",
                            conflicting_values=(target.value,),
                        ),
                        source=self.name,
                    )
                    return False, True
                if target.set_value(DiscreteDomain(candidates=remaining), source=self.name):
                    changed = True
        return changed, False

    def _forward_eliminate(self) -> bool:
        """Run forward elimination loop until local quiescence. Returns False on contradiction."""
        changed = True
        while changed:
            changed = False
            determined = self._collect_determined()
            if determined is None:
                return False

            for v, source_cell in list(determined.items()):
                did_change, has_conflict = self._eliminate_value_from_peers(v, source_cell)
                if has_conflict:
                    return False
                if did_change:
                    changed = True
        return True

    def _deduce_hidden_singles(self) -> None:
        """Deduce hidden singles where a candidate only appears in a single undetermined cell."""
        current_determined = {
            c.value.value
            for c in self.cells
            if isinstance(c.value, DiscreteDomain) and c.value.is_determined
        }
        candidate_occurrences: dict[Any, list[Cell]] = {}
        for cell in self.cells:
            if isinstance(cell.value, DiscreteDomain) and not cell.value.is_determined:
                for cand in cell.value.candidates:
                    if cand not in current_determined:
                        candidate_occurrences.setdefault(cand, []).append(cell)

        assigned_cell_ids: set[str] = set()
        for cand, containing_cells in candidate_occurrences.items():
            if len(containing_cells) == 1:
                target_cell = containing_cells[0]
                if target_cell.cell_id not in assigned_cell_ids:
                    assigned_cell_ids.add(target_cell.cell_id)
                    target_cell.set_value(
                        DiscreteDomain.single(cand),
                        source=f"{self.name}:hidden_single",
                    )

    def alert(self, network: PropagatorNetwork) -> None:
        """Run all-different constraint propagation across the cell group."""
        if self._forward_eliminate():
            self._deduce_hidden_singles()


class PropagatorNetwork:
    """Orchestrates cells and propagators, driving the network to fixed-point quiescence."""

    def __init__(self, name: str = "Network") -> None:
        self.name = name
        self.cells: dict[str, Cell] = {}
        self.propagators: list[Propagator] = []
        self._queue: deque[Propagator] = deque()
        self._sources_log: dict[str, list[str]] = {}

    def add_cell(
        self,
        cell_id: str,
        initial_value: LatticeValue = BOTTOM,
        unit: str = "",
        display_name: str | None = None,
    ) -> Cell:
        """Create or register a cell in this network."""
        if cell_id in self.cells:
            return self.cells[cell_id]
        cell = Cell(
            cell_id=cell_id,
            value=initial_value,
            network=self,
            unit=unit,
            display_name=display_name,
        )
        self.cells[cell_id] = cell
        return cell

    def add_propagator(self, propagator: Propagator) -> None:
        """Register a propagator in this network."""
        self.propagators.append(propagator)
        for c in propagator.inputs + propagator.outputs:
            if c.network is None:
                c.network = self
            if c.cell_id not in self.cells:
                self.cells[c.cell_id] = c
        # Trigger initial run
        self._queue.append(propagator)

    def unify_cells(self, cell_a: Cell, cell_b: Cell) -> None:
        """Unify two cells into an equivalence class via Disjoint Set Union (Union-Find)."""
        cell_a.unify(cell_b)

    def notify_changed(self, cell: Cell, source: str | None = None) -> None:
        """Enqueue all propagators watching the changed cell."""
        if source:
            self._sources_log.setdefault(cell.cell_id, []).append(source)
        for p in cell.propagators:
            if p not in self._queue:
                self._queue.append(p)

    def run(self, max_iterations: int = 100) -> int:
        """Run the propagation queue to fixed-point quiescence. Returns iterations taken."""
        iterations = 0
        while self._queue and iterations < max_iterations:
            propagator = self._queue.popleft()
            propagator.alert(self)
            iterations += 1
        return iterations

    def explain(
        self,
        cell_id: str,
        unit: str | None = None,
        depth: int | None = None,
    ) -> str:
        """Explain the state and causal provenance of a network cell."""
        if cell_id not in self.cells:
            raise KeyError(f"Cell '{cell_id}' not found in network.")
        return self.cells[cell_id].explain(unit=unit, depth=depth)

    def generate_mermaid(self) -> str:
        """Generate a Mermaid diagram representing the network structure and state."""
        lines = ["```mermaid", "graph LR"]
        for p in self.propagators:
            p_node = f'P_{p.name.replace(" ", "_")}["{p.name}"]'
            for in_c in p.inputs:
                c_node = f'C_{in_c.cell_id.replace(" ", "_")}["{in_c.cell_id}<br/>{in_c.value}"]'
                lines.append(f"  {c_node} --> {p_node}")
            for out_c in p.outputs:
                c_node = f'C_{out_c.cell_id.replace(" ", "_")}["{out_c.cell_id}<br/>{out_c.value}"]'
                lines.append(f"  {p_node} --> {c_node}")
        lines.append("```")
        return "\n".join(lines)


class ChoiceEngine:
    """Interleaves monotonic lattice propagation with speculative branching and backtracking.

    When constraint propagation reaches quiescence and discrete domain cells remain
    undetermined (multiple candidates), ChoiceEngine uses the MRV (Minimum Remaining Values)
    heuristic to select a choice point, branches on candidates, runs propagation to a fixed
    point, and backtracks upon encountering a Contradiction.
    """

    def __init__(self, network: PropagatorNetwork, max_depth: int = 100) -> None:
        self.network = network
        self.max_depth = max_depth

    def is_solved(self) -> bool:
        """Check if all cells in the network are non-bottom, determined, and contradiction-free."""
        for cell in self.network.cells.values():
            val = cell.value
            if isinstance(val, (Bottom, Contradiction)):
                return False
            if isinstance(val, DiscreteDomain) and not val.is_determined:
                return False
        return True

    def find_branching_cell(self) -> Cell | None:
        """Find an undetermined cell using First-Fail / MRV (Minimum Remaining Values) heuristic."""
        best_cell = None
        min_candidates = float("inf")
        for cell in self.network.cells.values():
            val = cell.value
            if (
                isinstance(val, DiscreteDomain)
                and not val.is_determined
                and 1 < len(val.candidates) < min_candidates
            ):
                min_candidates = len(val.candidates)
                best_cell = cell
        return best_cell

    def solve(self, max_iterations: int = 1000) -> bool:
        """Execute depth-first search interleaved with fixed-point lattice relaxation.

        Returns True if a consistent fixed-point solution was found.
        """
        # Run initial propagation
        self.network.run(max_iterations=max_iterations)

        # Check for immediate contradiction
        if any(isinstance(c.value, Contradiction) for c in self.network.cells.values()):
            return False

        if self.is_solved():
            return True

        return self._search_step(depth=0, max_iterations=max_iterations)

    def _search_step(self, depth: int, max_iterations: int) -> bool:
        if depth >= self.max_depth:
            return False

        cell = self.find_branching_cell()
        if cell is None:
            return self.is_solved()

        domain = cell.value
        assert isinstance(domain, DiscreteDomain)
        try:
            candidates = sorted(domain.candidates)
        except TypeError:
            candidates = sorted(domain.candidates, key=lambda x: str(x))

        # Snapshot current network state
        saved_state = {c.cell_id: c.value for c in self.network.cells.values()}

        for cand in candidates:
            # Restore state before trying candidate
            for cid, val in saved_state.items():
                self.network.cells[cid].value = val

            # Speculate: assert candidate
            cell.set_value(DiscreteDomain.single(cand), overwrite=True)
            self.network.run(max_iterations=max_iterations)

            # If no contradiction, recurse
            has_contradiction = any(
                isinstance(c.value, Contradiction) for c in self.network.cells.values()
            )
            if not has_contradiction and (
                self.is_solved() or self._search_step(depth + 1, max_iterations)
            ):
                return True

        # Backtrack: restore saved state
        for cid, val in saved_state.items():
            self.network.cells[cid].value = val
        return False
