"""Non-linear continuous interval contraction propagators.

Provides multi-directional non-linear constraints operating monotonically over
intervals and scalar values (Box / Hull consistency):
- `PowerPropagator`: Bidirectional power constraint `base ** exponent = result`.
- `SqrtPropagator`: Bidirectional radical constraint `sqrt(in_) = out`.
- `ExpPropagator`: Bidirectional exponential constraint `exp(in_) = out`.
- `LogPropagator`: Bidirectional natural logarithm constraint `ln(in_) = out`.
- Helper functions `add_power_constraint`, `add_sqrt_constraint`, `add_exp_constraint`.
"""

from __future__ import annotations

import math

from .lattice import (
    Bottom,
    Contradiction,
    FlatValue,
    IntervalValue,
    LatticeValue,
)
from .primitives import (
    Cell,
    Propagator,
    PropagatorNetwork,
    _coerce_to_cell,
    _should_update_target,
    _to_interval_or_none,
    register_binary_op,
)


class PowerPropagator(Propagator):
    """Bidirectional power constraint enforcing `base ** exponent = result`.

    Supports integer and real exponents over intervals and scalar values:
      Forward:  `result = base ** exponent`
      Backward: `base = result ** (1 / exponent)` (with sign-aware hull consistency for even powers)
    """

    def __init__(
        self,
        name: str,
        base: Cell,
        exponent: float | Cell,
        result: Cell,
        confidence: float = 1.0,
        is_assumption: bool = False,
    ) -> None:
        net = base.network or (result.network if isinstance(result, Cell) else None)
        if net is None and isinstance(exponent, Cell):
            net = exponent.network
        if net is None:
            net = PropagatorNetwork()

        c_exp = (
            exponent if isinstance(exponent, Cell) else _coerce_to_cell(exponent, net, "exponent")
        )

        super().__init__(
            name,
            inputs=[base, c_exp, result],
            outputs=[base, result],
            confidence=confidence,
            is_assumption=is_assumption,
        )
        self.base = base
        self.exponent = c_exp
        self.result = result

    def alert(self, network: PropagatorNetwork) -> None:
        v_base = self.base.value
        v_exp = self.exponent.value
        v_res = self.result.value

        if isinstance(v_exp, (Bottom, Contradiction)):
            return

        # Extract scalar exponent if available
        exp_val: float | None = None
        if isinstance(v_exp, FlatValue) and isinstance(v_exp.val, (int, float)):
            exp_val = float(v_exp.val)
        elif isinstance(v_exp, IntervalValue) and math.isclose(
            v_exp.min_val, v_exp.max_val, rel_tol=1e-9
        ):
            exp_val = v_exp.min_val

        # 1. Forward propagation: base ** exp -> result
        if exp_val is not None and not isinstance(v_base, (Bottom, Contradiction)):
            cand_res = self._eval_forward(v_base, exp_val)
            if cand_res is not None and _should_update_target(v_res, cand_res):
                self.emit(
                    self.result,
                    cand_res,
                    antecedents=(self.base, self.exponent),
                )
                v_res = self.result.value

        # 2. Backward propagation: result ** (1/exp) -> base
        if exp_val is not None and not isinstance(v_res, (Bottom, Contradiction)):
            cand_base = self._eval_backward(v_res, exp_val)
            if cand_base is not None and _should_update_target(v_base, cand_base):
                self.emit(
                    self.base,
                    cand_base,
                    antecedents=(self.result, self.exponent),
                )

    def _eval_forward(self, base_val: LatticeValue, exp: float) -> LatticeValue | None:
        if isinstance(base_val, FlatValue) and isinstance(base_val.val, (int, float)):
            b = float(base_val.val)
            if b < 0 and not exp.is_integer():
                return Contradiction(f"Fractional power of negative base: {b} ** {exp}")
            return FlatValue(b**exp)

        i_base = _to_interval_or_none(base_val)
        if i_base is None:
            return None

        # Even integer exponent (e.g. x^2, x^4)
        if exp > 0 and exp.is_integer() and int(exp) % 2 == 0:
            if i_base.contains(0.0):
                min_r = 0.0
                max_r = max(abs(i_base.min_val) ** exp, abs(i_base.max_val) ** exp)
            else:
                p1 = i_base.min_val**exp
                p2 = i_base.max_val**exp
                min_r = min(p1, p2)
                max_r = max(p1, p2)
            return IntervalValue(min_r, max_r)

        # Odd integer exponent (e.g. x^3)
        if exp.is_integer() and int(exp) % 2 == 1:
            return IntervalValue(i_base.min_val**exp, i_base.max_val**exp)

        # Positive fractional exponent (requires non-negative base)
        if exp > 0:
            if i_base.max_val < 0:
                return Contradiction(
                    f"Power {self.name} invalid: base interval {i_base} strictly negative for exponent {exp}"
                )
            clamped_min = max(0.0, i_base.min_val)
            return IntervalValue(clamped_min**exp, i_base.max_val**exp)

        return None

    def _eval_backward(self, res_val: LatticeValue, exp: float) -> LatticeValue | None:
        if math.isclose(exp, 0.0):
            return None

        inv_exp = 1.0 / exp

        if isinstance(res_val, FlatValue) and isinstance(res_val.val, (int, float)):
            r = float(res_val.val)
            if exp > 0 and exp.is_integer() and int(exp) % 2 == 0:
                if r < 0:
                    return Contradiction(f"Even power cannot yield negative result: {r}")
                root = r**inv_exp
                # Even root symmetric interval hull: [-root, root]
                return IntervalValue(-root, root)
            if r < 0 and not inv_exp.is_integer():
                return Contradiction(f"Cannot extract fractional root of negative: {r}")
            return FlatValue(r**inv_exp)

        i_res = _to_interval_or_none(res_val)
        if i_res is None:
            return None

        # Even integer exponent: result must be non-negative
        if exp > 0 and exp.is_integer() and int(exp) % 2 == 0:
            if i_res.max_val < 0:
                return Contradiction(f"Even power result {i_res} strictly negative in {self.name}")
            clamped_min = max(0.0, i_res.min_val)
            max_root = i_res.max_val**inv_exp
            min_root = clamped_min**inv_exp

            # If base is known non-negative or non-positive, tighten to single branch
            i_base = _to_interval_or_none(self.base.value)
            if i_base is not None and i_base.min_val >= 0:
                return IntervalValue(min_root, max_root)
            if i_base is not None and i_base.max_val <= 0:
                return IntervalValue(-max_root, -min_root)
            return IntervalValue(-max_root, max_root)

        # Odd integer exponent
        if exp.is_integer() and int(exp) % 2 == 1:
            p1 = math.copysign(abs(i_res.min_val) ** inv_exp, i_res.min_val)
            p2 = math.copysign(abs(i_res.max_val) ** inv_exp, i_res.max_val)
            return IntervalValue(min(p1, p2), max(p1, p2))

        # Positive exponent with non-negative result
        if exp > 0:
            if i_res.max_val < 0:
                return Contradiction(f"Result {i_res} negative for exponent {exp}")
            clamped_min = max(0.0, i_res.min_val)
            return IntervalValue(clamped_min**inv_exp, i_res.max_val**inv_exp)

        return None


class SqrtPropagator(Propagator):
    """Bidirectional non-negative square root constraint enforcing `sqrt(in) = out`.

    Forward:  `out = sqrt(max(0, in_))`
    Backward: `in_ = out ** 2` (with domain assertion `out >= 0`)
    """

    def __init__(
        self,
        name: str,
        in_: Cell,
        out: Cell,
        confidence: float = 1.0,
        is_assumption: bool = False,
    ) -> None:
        super().__init__(
            name,
            inputs=[in_, out],
            outputs=[in_, out],
            confidence=confidence,
            is_assumption=is_assumption,
        )
        self.in_ = in_
        self.out = out

    def alert(self, network: PropagatorNetwork) -> None:
        v_in = self.in_.value
        v_out = self.out.value

        # 1. Forward: sqrt(in_) -> out
        if not isinstance(v_in, (Bottom, Contradiction)):
            if isinstance(v_in, FlatValue) and isinstance(v_in.val, (int, float)):
                val = float(v_in.val)
                if val < 0:
                    self.emit(
                        self.out,
                        Contradiction(f"Square root of negative number: {val}"),
                        antecedents=(self.in_,),
                    )
                    return
                cand_out = FlatValue(math.sqrt(val))
            else:
                i_in = _to_interval_or_none(v_in)
                if i_in is not None:
                    if i_in.max_val < 0:
                        self.emit(
                            self.out,
                            Contradiction(f"Square root domain violation: {i_in} < 0"),
                            antecedents=(self.in_,),
                        )
                        return
                    cand_out = IntervalValue(
                        math.sqrt(max(0.0, i_in.min_val)),
                        math.sqrt(max(0.0, i_in.max_val)),
                    )
                else:
                    cand_out = None

            if cand_out is not None and _should_update_target(v_out, cand_out):
                self.emit(self.out, cand_out, antecedents=(self.in_,))
                v_out = self.out.value

        # 2. Backward: out ** 2 -> in_
        if not isinstance(v_out, (Bottom, Contradiction)):
            if isinstance(v_out, FlatValue) and isinstance(v_out.val, (int, float)):
                val = float(v_out.val)
                if val < 0:
                    self.emit(
                        self.in_,
                        Contradiction(f"Principal square root out must be non-negative: {val}"),
                        antecedents=(self.out,),
                    )
                    return
                cand_in = FlatValue(val**2)
            else:
                i_out = _to_interval_or_none(v_out)
                if i_out is not None:
                    if i_out.max_val < 0:
                        self.emit(
                            self.in_,
                            Contradiction(f"Square root range strictly negative: {i_out}"),
                            antecedents=(self.out,),
                        )
                        return
                    clamped_min = max(0.0, i_out.min_val)
                    cand_in = IntervalValue(clamped_min**2, i_out.max_val**2)
                else:
                    cand_in = None

            if cand_in is not None and _should_update_target(v_in, cand_in):
                self.emit(self.in_, cand_in, antecedents=(self.out,))


class ExpPropagator(Propagator):
    """Bidirectional natural exponential constraint enforcing `exp(in) = out`.

    Forward:  `out = exp(in_)`
    Backward: `in_ = ln(out)` (with assertion `out > 0`)
    """

    def __init__(
        self,
        name: str,
        in_: Cell,
        out: Cell,
        confidence: float = 1.0,
        is_assumption: bool = False,
    ) -> None:
        super().__init__(
            name,
            inputs=[in_, out],
            outputs=[in_, out],
            confidence=confidence,
            is_assumption=is_assumption,
        )
        self.in_ = in_
        self.out = out

    def alert(self, network: PropagatorNetwork) -> None:
        v_in = self.in_.value
        v_out = self.out.value

        # 1. Forward: exp(in) -> out
        if not isinstance(v_in, (Bottom, Contradiction)):
            if isinstance(v_in, FlatValue) and isinstance(v_in.val, (int, float)):
                cand_out = FlatValue(math.exp(float(v_in.val)))
            else:
                i_in = _to_interval_or_none(v_in)
                cand_out = (
                    IntervalValue(math.exp(i_in.min_val), math.exp(i_in.max_val))
                    if i_in is not None
                    else None
                )

            if cand_out is not None and _should_update_target(v_out, cand_out):
                self.emit(self.out, cand_out, antecedents=(self.in_,))
                v_out = self.out.value

        # 2. Backward: ln(out) -> in
        if not isinstance(v_out, (Bottom, Contradiction)):
            if isinstance(v_out, FlatValue) and isinstance(v_out.val, (int, float)):
                val = float(v_out.val)
                if val <= 0:
                    self.emit(
                        self.in_,
                        Contradiction(f"Natural log undefined for non-positive: {val}"),
                        antecedents=(self.out,),
                    )
                    return
                cand_in = FlatValue(math.log(val))
            else:
                i_out = _to_interval_or_none(v_out)
                if i_out is not None:
                    if i_out.max_val <= 0:
                        self.emit(
                            self.in_,
                            Contradiction(f"Log domain violation: {i_out} <= 0"),
                            antecedents=(self.out,),
                        )
                        return
                    clamped_min = max(1e-15, i_out.min_val)
                    cand_in = IntervalValue(math.log(clamped_min), math.log(i_out.max_val))
                else:
                    cand_in = None

            if cand_in is not None and _should_update_target(v_in, cand_in):
                self.emit(self.in_, cand_in, antecedents=(self.out,))


class LogPropagator(Propagator):
    """Bidirectional natural logarithm constraint enforcing `ln(in) = out`.

    Inversion of ExpPropagator:
      Forward:  `out = ln(in_)` (domain `in_ > 0`)
      Backward: `in_ = exp(out)`
    """

    def __init__(
        self,
        name: str,
        in_: Cell,
        out: Cell,
        confidence: float = 1.0,
        is_assumption: bool = False,
    ) -> None:
        super().__init__(
            name,
            inputs=[in_, out],
            outputs=[in_, out],
            confidence=confidence,
            is_assumption=is_assumption,
        )
        self.in_ = in_
        self.out = out

    def alert(self, network: PropagatorNetwork) -> None:
        v_in = self.in_.value
        v_out = self.out.value

        # 1. Forward: ln(in) -> out
        if not isinstance(v_in, (Bottom, Contradiction)):
            if isinstance(v_in, FlatValue) and isinstance(v_in.val, (int, float)):
                val = float(v_in.val)
                if val <= 0:
                    self.emit(
                        self.out,
                        Contradiction(f"Natural log undefined for non-positive: {val}"),
                        antecedents=(self.in_,),
                    )
                    return
                cand_out = FlatValue(math.log(val))
            else:
                i_in = _to_interval_or_none(v_in)
                if i_in is not None:
                    if i_in.max_val <= 0:
                        self.emit(
                            self.out,
                            Contradiction(f"Log domain violation: {i_in} <= 0"),
                            antecedents=(self.in_,),
                        )
                        return
                    clamped_min = max(1e-15, i_in.min_val)
                    cand_out = IntervalValue(math.log(clamped_min), math.log(i_in.max_val))
                else:
                    cand_out = None

            if cand_out is not None and _should_update_target(v_out, cand_out):
                self.emit(self.out, cand_out, antecedents=(self.in_,))
                v_out = self.out.value

        # 2. Backward: exp(out) -> in
        if not isinstance(v_out, (Bottom, Contradiction)):
            if isinstance(v_out, FlatValue) and isinstance(v_out.val, (int, float)):
                cand_in = FlatValue(math.exp(float(v_out.val)))
            else:
                i_out = _to_interval_or_none(v_out)
                cand_in = (
                    IntervalValue(math.exp(i_out.min_val), math.exp(i_out.max_val))
                    if i_out is not None
                    else None
                )

            if cand_in is not None and _should_update_target(v_in, cand_in):
                self.emit(self.in_, cand_in, antecedents=(self.out,))


# --- Declarative Helper Builders ---


def add_power_constraint(
    network: PropagatorNetwork,
    base: Cell,
    exponent: float | Cell,
    result: Cell | None = None,
    name: str | None = None,
) -> tuple[Cell, PowerPropagator]:
    """Attach a bidirectional power constraint (`base ** exponent = result`) to the network."""
    c_exp = exponent if isinstance(exponent, Cell) else _coerce_to_cell(exponent, network, "exp")
    target_res = (
        result if result is not None else network.add_cell(f"({base.cell_id}**{c_exp.cell_id})")
    )
    prop_name = name or f"pow_{base.cell_id}_{c_exp.cell_id}"
    prop = PowerPropagator(prop_name, base, c_exp, target_res)
    network.add_propagator(prop)
    return target_res, prop


def add_sqrt_constraint(
    network: PropagatorNetwork,
    in_: Cell,
    out: Cell | None = None,
    name: str | None = None,
) -> tuple[Cell, SqrtPropagator]:
    """Attach a bidirectional square root constraint (`sqrt(in_) = out`) to the network."""
    target_out = out if out is not None else network.add_cell(f"sqrt({in_.cell_id})")
    prop_name = name or f"sqrt_{in_.cell_id}"
    prop = SqrtPropagator(prop_name, in_, target_out)
    network.add_propagator(prop)
    return target_out, prop


def add_exp_constraint(
    network: PropagatorNetwork,
    in_: Cell,
    out: Cell | None = None,
    name: str | None = None,
) -> tuple[Cell, ExpPropagator]:
    """Attach a bidirectional natural exponential constraint (`exp(in_) = out`) to the network."""
    target_out = out if out is not None else network.add_cell(f"exp({in_.cell_id})")
    prop_name = name or f"exp_{in_.cell_id}"
    prop = ExpPropagator(prop_name, in_, target_out)
    network.add_propagator(prop)
    return target_out, prop


# Register pow operator for Cell dunder method dispatch (**)
register_binary_op("pow", "**", PowerPropagator, False)
