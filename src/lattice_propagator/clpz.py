"""CLP(Z)-Style Constraint Logic Programming over Unbounded Integer Domains.

Implements monotonic constraint propagation and reification over
:class:`~lattice_propagator.lattice.IntegerDomain` (``ℤ ∪ {-∞, +∞}``),
modeled after Prolog's ``library(clpz)`` / CLP(FD) solvers:

- **Integer Domain Lattice**: Unbounded ``(-∞ .. +∞)`` cells narrowing
  monotonically via disjoint integer interval intersections and hole removal.
- **Exact Integer Arithmetic & Inequalities**: ``IntRelationPropagator``,
  ``IntLinearPropagator`` (with Bézout GCD infeasibility checks and floor/ceil
  tightening), ``IntAddPropagator``, ``IntMulPropagator``, and ``IntAbsPropagator``.
- **Reification**: ``ReifiedIntRelationPropagator`` linking boolean
  ``FlatValue(bool)`` cells bidirectionally to integer relations (``B ⟺ (X < Y)``).
- **Global Uniqueness**: ``IntAllDifferentPropagator`` operating over both
  bounded and unbounded integer cells.

Primary Citations:
    - Triska, M. (2012). "The Finite Domain Constraint Solver of SWI-Prolog" /
      Scryer Prolog ``library(clpz)``. https://www.metalevel.at/clpz/
    - Apt, K. (2003). *Principles of Constraint Programming*. Cambridge University Press.
"""

from __future__ import annotations

import math
import operator
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from .lattice import (
    Bottom,
    Contradiction,
    FlatValue,
    IntBound,
    IntegerDomain,
    LatticeValue,
)
from .primitives import Cell, Propagator, PropagatorNetwork

_UNBOUNDED = IntegerDomain.unbounded()

_OP_ALIASES: dict[str, str] = {
    "=": "=",
    "==": "=",
    "#=": "=",
    "!=": "!=",
    "<>": "!=",
    "#\\=": "!=",
    "<": "<",
    "#<": "<",
    "<=": "<=",
    "#=<": "<=",
    ">": ">",
    "#>": ">",
    ">=": ">=",
    "#>=": ">=",
}

_NEGATED_OP: dict[str, str] = {
    "=": "!=",
    "!=": "=",
    "<": ">=",
    ">=": "<",
    "<=": ">",
    ">": "<=",
}

_SWAPPED_OP: dict[str, str] = {
    "=": "=",
    "!=": "!=",
    "<": ">",
    ">": "<",
    "<=": ">=",
    ">=": "<=",
}

# Maps inequality operators to (normalized_op, term_sign, rhs_offset) so that
# sum(terms) <op> rhs becomes sum(term_sign * terms) <= term_sign * rhs + rhs_offset.
_LINEAR_OP_NORM: dict[str, tuple[str, int, int]] = {
    "<": ("<=", 1, -1),
    ">=": ("<=", -1, 0),
    ">": ("<=", -1, -1),
}


def normalize_int_op(op: str) -> str:
    """Normalize SQL/Python/Prolog-style integer comparison operators.

    Args:
        op: Operator string such as ``'='``, ``'#='``, ``'!='``, ``'#\\='``,
            ``'<'``, ``'#<'``, ``'<='``, ``'#=<'``, ``'>'``, ``'#>'``, ``'>='``,
            or ``'#>='``.

    Returns:
        Canonical operator string in ``{'=', '!=', '<', '<=', '>', '>='}``.
    """
    canonical = _OP_ALIASES.get(op)
    if canonical is None:
        raise ValueError(f"Unsupported integer relation operator: {op!r}")
    return canonical


def _add_bound(a: IntBound, b: IntBound) -> IntBound:
    if a == -math.inf or b == -math.inf:
        if a == math.inf or b == math.inf:
            raise ValueError("Indeterminate bound addition (-∞ + +∞)")
        return -math.inf
    if a == math.inf or b == math.inf:
        return math.inf
    return int(a) + int(b)


def _neg_bound(a: IntBound) -> IntBound:
    return -a if math.isinf(a) else -int(a)


def _sub_bound(a: IntBound, b: IntBound) -> IntBound:
    return _add_bound(a, _neg_bound(b))


def _mul_bound(a: IntBound, b: IntBound) -> IntBound:
    if a == 0 or b == 0:
        return 0
    if math.isinf(a) or math.isinf(b):
        return math.inf if (a > 0) == (b > 0) else -math.inf
    return int(a) * int(b)


def _ceil_div_pos(num: IntBound, den: IntBound) -> IntBound:
    """Compute ceil(num / den) for den > 0 (supporting ±inf)."""
    if math.isinf(num):
        return num
    if den == math.inf:
        return 1 if num > 0 else 0
    return -((-int(num)) // int(den))


def _floor_div_pos(num: IntBound, den: IntBound) -> IntBound:
    """Compute floor(num / den) for den > 0 (supporting ±inf)."""
    if math.isinf(num):
        return num
    if den == math.inf:
        return -1 if num < 0 else 0
    return int(num) // int(den)


def _div_pos_range_bounds(
    z_lo: IntBound,
    z_hi: IntBound,
    y_lo: int,
    y_hi: IntBound,
) -> tuple[IntBound, IntBound] | None:
    """Compute tight integer bounds [x_lo, x_hi] for x*y in [z_lo, z_hi], y in [y_lo..y_hi] >= 1."""
    x_lo = _ceil_div_pos(z_lo, y_hi) if z_lo >= 0 else _ceil_div_pos(z_lo, y_lo)
    x_hi = _floor_div_pos(z_hi, y_lo) if z_hi >= 0 else _floor_div_pos(z_hi, y_hi)
    if x_lo > x_hi:
        return None
    return (x_lo, x_hi)


def _scale_domain(dom: IntegerDomain, coeff: int) -> IntegerDomain:
    """Compute exact outer or segment-wise scaling of an IntegerDomain by non-zero int."""
    if coeff == 0:
        return IntegerDomain.single(0)
    if coeff == 1:
        return dom
    if coeff == -1:
        return IntegerDomain(
            ranges=tuple((_neg_bound(hi), _neg_bound(lo)) for lo, hi in dom.ranges)
        )
    lo_src, hi_src = (dom.lo, dom.hi) if coeff > 0 else (dom.hi, dom.lo)
    return IntegerDomain.between(_mul_bound(lo_src, coeff), _mul_bound(hi_src, coeff))


def _clamp_scaled_domain(
    dom: IntegerDomain, coeff: int, target_lo: IntBound, target_hi: IntBound
) -> LatticeValue:
    """Clamp dom such that coeff * x lies within [target_lo .. target_hi] (exact integer bounds)."""
    if target_lo > target_hi:
        return Contradiction(reason="Empty target bounds in integer linear constraint")
    if coeff == 0:
        if target_lo <= 0 <= target_hi:
            return dom
        return Contradiction(reason=f"0 not in [{target_lo}..{target_hi}]")
    lo, hi, divisor = (
        (target_lo, target_hi, coeff)
        if coeff > 0
        else (_neg_bound(target_hi), _neg_bound(target_lo), -coeff)
    )
    bounds = _div_pos_range_bounds(lo, hi, divisor, divisor)
    if bounds is None:
        return Contradiction(
            reason=f"No integer x satisfies {coeff}*x ∈ [{target_lo}..{target_hi}]",
            conflicting_values=(dom,),
        )
    return dom.clamp(bounds[0], bounds[1])


def _read_int_domain(cell: Cell) -> IntegerDomain | Contradiction | None:
    """Return cell's IntegerDomain, treating Bottom as unbounded ℤ."""
    val = cell.value
    if isinstance(val, Contradiction):
        return val
    if isinstance(val, Bottom):
        return _UNBOUNDED
    if isinstance(val, IntegerDomain):
        return val
    if isinstance(val, FlatValue) and isinstance(val.val, int) and not isinstance(val.val, bool):
        return IntegerDomain.single(val.val)
    return None


def _emit_domain(
    prop: Propagator, cell: Cell, current: IntegerDomain, candidate: LatticeValue
) -> None:
    """Emit a narrowed IntegerDomain or Contradiction only if it strictly refines ``cell``."""
    if isinstance(candidate, Contradiction) or (
        isinstance(candidate, IntegerDomain)
        and (isinstance(cell.value, Bottom) or candidate != current)
    ):
        prop.emit(cell, candidate)


def _coerce_int_cell(val: Cell | int, network: PropagatorNetwork, role: str) -> Cell:
    """Coerce a Cell or Python int into a Cell holding an IntegerDomain."""
    if isinstance(val, Cell):
        if val.network is None:
            val.network = network
        if val.cell_id not in network.cells:
            network.cells[val.cell_id] = val
        return val
    if isinstance(val, int) and not isinstance(val, bool):
        cid = f"int_const_{val}".replace("-", "neg_")
        if cid in network.cells:
            return network.cells[cid]
        return network.add_cell(cid, IntegerDomain.single(val))
    raise TypeError(f"Expected Cell or int for {role}, got {val!r}")


def int_cell(
    network: PropagatorNetwork,
    cell_id: str,
    lo: IntBound = -math.inf,
    hi: IntBound = math.inf,
    *,
    values: Iterable[int] | None = None,
) -> Cell:
    """Create or register a Cell initialized to an IntegerDomain.

    Defaults to ``(-∞ .. +∞)`` (all integers ``ℤ``) when ``lo`` and ``hi`` are
    omitted, matching Prolog ``clpz`` unconstrained integer variables.

    Args:
        network: Target propagator network.
        cell_id: Unique cell identifier.
        lo: Lower bound (``int`` or ``-math.inf``).
        hi: Upper bound (``int`` or ``math.inf``).
        values: Optional explicit iterable of allowed integers.

    Returns:
        The newly registered ``Cell``.
    """
    dom = IntegerDomain.from_values(values) if values is not None else IntegerDomain.between(lo, hi)
    return network.add_cell(cell_id, dom)


def int_cells(
    network: PropagatorNetwork,
    cell_ids: Iterable[str],
    lo: IntBound = -math.inf,
    hi: IntBound = math.inf,
    *,
    values: Iterable[int] | None = None,
) -> list[Cell]:
    """Batch-create multiple ``IntegerDomain`` cells with shared initial bounds."""
    return [int_cell(network, cid, lo=lo, hi=hi, values=values) for cid in cell_ids]


@dataclass(frozen=True)
class IntExpr:
    """Immutable linear expression ``Σ w_i * x_i + offset`` over integer cells.

    Supports ``+``, ``-``, and scalar ``int * expr`` without colliding with
    ``Cell``'s built-in float/interval operator overloading.
    """

    terms: tuple[tuple[Cell, int], ...]
    offset: int = 0

    @classmethod
    def from_cell(cls, cell: Cell) -> IntExpr:
        """Wrap a single integer ``Cell`` as ``1 * cell + 0``."""
        return cls(terms=((cell, 1),), offset=0)

    @classmethod
    def const(cls, value: int) -> IntExpr:
        """Create a constant integer linear expression."""
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"IntExpr.const requires int, got {value!r}")
        return cls(terms=(), offset=value)

    def _combine(self, other: IntExpr | Cell | int, sign: int) -> IntExpr:
        if isinstance(other, int) and not isinstance(other, bool):
            return IntExpr(terms=self.terms, offset=self.offset + sign * other)
        rhs = IntExpr.from_cell(other) if isinstance(other, Cell) else other
        if not isinstance(rhs, IntExpr):
            return NotImplemented
        merged: dict[str, tuple[Cell, int]] = {c.cell_id: (c, w) for c, w in self.terms}
        for c, w in rhs.terms:
            prev_w = merged[c.cell_id][1] if c.cell_id in merged else 0
            new_w = prev_w + sign * w
            if new_w == 0:
                merged.pop(c.cell_id, None)
            else:
                merged[c.cell_id] = (c, new_w)
        return IntExpr(terms=tuple(merged.values()), offset=self.offset + sign * rhs.offset)

    def __add__(self, other: Any) -> IntExpr:
        return self._combine(other, 1)

    def __radd__(self, other: Any) -> IntExpr:
        return self._combine(other, 1)

    def __sub__(self, other: Any) -> IntExpr:
        return self._combine(other, -1)

    def __rsub__(self, other: Any) -> IntExpr:
        return (-self)._combine(other, 1)

    def __neg__(self) -> IntExpr:
        return IntExpr(terms=tuple((c, -w) for c, w in self.terms), offset=-self.offset)

    def __mul__(self, other: Any) -> IntExpr:
        if isinstance(other, int) and not isinstance(other, bool):
            if other == 0:
                return IntExpr(terms=(), offset=0)
            return IntExpr(
                terms=tuple((c, w * other) for c, w in self.terms),
                offset=self.offset * other,
            )
        return NotImplemented

    def __rmul__(self, other: Any) -> IntExpr:
        return self.__mul__(other)


def int_expr(val: Cell | int | IntExpr) -> IntExpr:
    """Convert a ``Cell``, ``int``, or ``IntExpr`` into an ``IntExpr``."""
    if isinstance(val, IntExpr):
        return val
    if isinstance(val, Cell):
        return IntExpr.from_cell(val)
    return IntExpr.const(val)


def _apply_ordered_bound(
    prop: Propagator,
    left: Cell,
    d_left: IntegerDomain,
    right: Cell,
    d_right: IntegerDomain,
    strict: bool,
) -> None:
    """Enforce left < right (strict=True) or left <= right (strict=False)."""
    gap = 1 if strict else 0
    if d_left.lo != -math.inf:
        _emit_domain(prop, right, d_right, d_right.clamp(_add_bound(d_left.lo, gap), math.inf))
    if d_right.hi != math.inf:
        _emit_domain(prop, left, d_left, d_left.clamp(-math.inf, _sub_bound(d_right.hi, gap)))


def _enforce_relation(
    prop: Propagator,
    left: Cell,
    d_left: IntegerDomain,
    op: str,
    right: Cell,
    d_right: IntegerDomain,
) -> None:
    """Apply canonical relation operator between two IntegerDomain cells."""
    if op == "=":
        joined = d_left.intersect(d_right)
        _emit_domain(prop, left, d_left, joined)
        _emit_domain(prop, right, d_right, joined)
    elif op == "!=":
        if d_left.is_determined and d_right.is_determined and d_left.value == d_right.value:
            prop.emit(
                left,
                Contradiction(
                    reason=f"Inequality violated: {left.cell_id} == {right.cell_id} == {d_left.value}",
                    conflicting_values=(d_left, d_right),
                ),
            )
            return
        for src_dom, dst_cell, dst_dom in ((d_left, right, d_right), (d_right, left, d_left)):
            if (
                src_dom.is_determined
                and src_dom.value is not None
                and dst_dom.contains(src_dom.value)
            ):
                _emit_domain(prop, dst_cell, dst_dom, dst_dom.without(src_dom.value))
    else:
        lo_cell, lo_dom, hi_cell, hi_dom = (
            (left, d_left, right, d_right) if op in ("<", "<=") else (right, d_right, left, d_left)
        )
        _apply_ordered_bound(prop, lo_cell, lo_dom, hi_cell, hi_dom, strict=op in ("<", ">"))


def _check_relation_entailment(
    d_left: IntegerDomain, op: str, d_right: IntegerDomain
) -> bool | None:
    """Return True if entailed, False if disentailed, or None if undecided."""
    if op == "=":
        if d_left.is_determined and d_right.is_determined:
            return d_left.value == d_right.value
        if isinstance(d_left.intersect(d_right), Contradiction):
            return False
        return None
    if op == "!=":
        inner = _check_relation_entailment(d_left, "=", d_right)
        return None if inner is None else not inner
    if op in ("<", "<="):
        entailed, disentailed = (
            (operator.lt, operator.ge) if op == "<" else (operator.le, operator.gt)
        )
        if entailed(d_left.hi, d_right.lo):
            return True
        if disentailed(d_left.lo, d_right.hi):
            return False
        return None
    return _check_relation_entailment(d_right, _SWAPPED_OP[op], d_left)


class IntRelationPropagator(Propagator):
    """Bidirectional integer relational constraint ``left <op> right``.

    Supports ``'='``, ``'!='``, ``'<'``, ``'<='``, ``'>'``, and ``'>='``
    (and Prolog aliases ``'#='``, ``'#\\='``, ``'#<'``, ``'#=<'``, ``'#>'``,
    ``'#>='``) over :class:`~lattice_propagator.lattice.IntegerDomain` cells,
    including semi-bounded and unbounded ``(-∞ .. +∞)`` domains.
    """

    def __init__(
        self,
        name: str,
        left: Cell,
        op: str,
        right: Cell,
        confidence: float = 1.0,
        is_assumption: bool = False,
    ) -> None:
        self.op = normalize_int_op(op)
        self.left = left
        self.right = right
        super().__init__(
            name,
            [left, right],
            [left, right],
            confidence=confidence,
            is_assumption=is_assumption,
        )

    def alert(self, network: PropagatorNetwork) -> None:
        """Propagate relational narrowing across ``left`` and ``right``."""
        d_left = _read_int_domain(self.left)
        d_right = _read_int_domain(self.right)
        if not isinstance(d_left, IntegerDomain) or not isinstance(d_right, IntegerDomain):
            return
        _enforce_relation(self, self.left, d_left, self.op, self.right, d_right)


class ReifiedIntRelationPropagator(Propagator):
    """Reified integer relation ``bool_cell ⟺ (left <op> right)``.

    Bidirectionally links a boolean ``FlatValue(bool)`` cell with an integer
    relational constraint:
    - When ``bool_cell`` is ``True``, enforces ``left <op> right``.
    - When ``bool_cell`` is ``False``, enforces ``¬(left <op> right)``.
    - When ``left`` and ``right`` entail or disentail the relation, emits
      ``FlatValue(True)`` or ``FlatValue(False)`` to ``bool_cell``.
    """

    def __init__(
        self,
        name: str,
        bool_cell: Cell,
        left: Cell,
        op: str,
        right: Cell,
        confidence: float = 1.0,
        is_assumption: bool = False,
    ) -> None:
        self.op = normalize_int_op(op)
        self.bool_cell = bool_cell
        self.left = left
        self.right = right
        super().__init__(
            name,
            [bool_cell, left, right],
            [bool_cell, left, right],
            confidence=confidence,
            is_assumption=is_assumption,
        )

    def alert(self, network: PropagatorNetwork) -> None:
        """Synchronize boolean truth value with relational constraint."""
        d_left = _read_int_domain(self.left)
        d_right = _read_int_domain(self.right)
        if not isinstance(d_left, IntegerDomain) or not isinstance(d_right, IntegerDomain):
            return

        b_val = self.bool_cell.value
        if isinstance(b_val, Contradiction):
            return

        if isinstance(b_val, FlatValue) and isinstance(b_val.val, bool):
            active_op = self.op if b_val.val else _NEGATED_OP[self.op]
            _enforce_relation(self, self.left, d_left, active_op, self.right, d_right)
            return

        if isinstance(b_val, Bottom):
            entailed = _check_relation_entailment(d_left, self.op, d_right)
            if entailed is not None:
                self.emit(self.bool_cell, FlatValue(entailed))


class IntLinearPropagator(Propagator):
    """Multi-term integer linear constraint ``Σ (coeff_i * x_i) <op> rhs``.

    Supports ``'='``, ``'!='``, ``'<'``, ``'<='``, ``'>'``, and ``'>='`` over
    arbitrary :class:`~lattice_propagator.lattice.IntegerDomain` cells (bounded
    or unbounded):
    - Uses exact integer floor/ceil division to narrow each variable's bounds.
    - Detects Diophantine infeasibility immediately via Bézout ``math.gcd``
      checks when ``op == '='``.
    - Normalizes ``'>'``, ``'>='``, and ``'<'`` uniformly into ``'<='``.
    """

    def __init__(
        self,
        name: str,
        terms: Sequence[tuple[int, Cell]],
        op: str,
        rhs: int,
        confidence: float = 1.0,
        is_assumption: bool = False,
    ) -> None:
        canonical_op = normalize_int_op(op)
        if isinstance(rhs, bool) or not isinstance(rhs, int):
            raise TypeError(f"rhs must be an int, got {rhs!r}")

        # Coalesce duplicate cells and validate coefficients
        grouped: dict[str, tuple[int, Cell]] = {}
        for coeff, cell in terms:
            if isinstance(coeff, bool) or not isinstance(coeff, int):
                raise TypeError(f"Term coefficient must be int, got {coeff!r}")
            if coeff == 0:
                continue
            prev = grouped[cell.cell_id][0] if cell.cell_id in grouped else 0
            new_c = prev + coeff
            if new_c == 0:
                grouped.pop(cell.cell_id, None)
            else:
                grouped[cell.cell_id] = (new_c, cell)

        # Normalize >, >=, < into <= uniformly via (norm_op, sign, rhs_offset)
        self.op, sign, rhs_offset = _LINEAR_OP_NORM.get(canonical_op, (canonical_op, 1, 0))
        self.rhs = sign * rhs + rhs_offset
        self.terms: list[tuple[int, Cell]] = [(sign * c, cell) for c, cell in grouped.values()]
        self._check_empty_terms()
        cells = [cell for _, cell in self.terms]
        super().__init__(name, cells, cells, confidence=confidence, is_assumption=is_assumption)

    def _check_empty_terms(self) -> bool:
        if self.terms:
            return False
        sat = {
            "=": 0 == self.rhs,
            "!=": 0 != self.rhs,
            "<=": 0 <= self.rhs,
        }[self.op]
        if not sat:
            raise ValueError(
                f"Constant linear constraint {0} {self.op} {self.rhs} is unsatisfiable"
            )
        return True

    def alert(self, network: PropagatorNetwork) -> None:
        """Tighten variable bounds and check Diophantine feasibility."""
        if not self.terms:
            return

        domains: list[IntegerDomain] = []
        for _, cell in self.terms:
            dom = _read_int_domain(cell)
            if not isinstance(dom, IntegerDomain):
                return
            domains.append(dom)

        if self.op == "!=":
            self._propagate_ne(domains)
            return

        # GCD divisibility check for exact linear equations
        if self.op == "=":
            rem_rhs = self.rhs
            undetermined_coeffs: list[int] = []
            for (coeff, _), dom in zip(self.terms, domains, strict=True):
                if dom.is_determined:
                    assert dom.value is not None
                    rem_rhs -= coeff * dom.value
                else:
                    undetermined_coeffs.append(abs(coeff))
            if not undetermined_coeffs:
                if rem_rhs != 0:
                    self.emit(
                        self.terms[0][1],
                        Contradiction(
                            reason=f"Linear equality {self.name} violated (residual {rem_rhs} != 0)"
                        ),
                    )
                return
            g = math.gcd(*undetermined_coeffs)
            if rem_rhs % g != 0:
                self.emit(
                    self.terms[0][1],
                    Contradiction(
                        reason=f"Diophantine infeasibility in {self.name}: gcd={g} does not divide {rem_rhs}"
                    ),
                )
                return

        scaled = [
            _scale_domain(dom, coeff) for (coeff, _), dom in zip(self.terms, domains, strict=True)
        ]

        # Compute prefix/suffix sums of term bounds in O(n)
        total_lo_inf = sum(1 for s in scaled if s.lo == -math.inf)
        total_hi_inf = sum(1 for s in scaled if s.hi == math.inf)
        finite_lo_sum = sum(int(s.lo) for s in scaled if s.lo != -math.inf)
        finite_hi_sum = sum(int(s.hi) for s in scaled if s.hi != math.inf)

        for idx, ((coeff, cell), dom, s) in enumerate(
            zip(self.terms, domains, scaled, strict=True)
        ):
            other_lo_inf = total_lo_inf - (1 if s.lo == -math.inf else 0)
            other_hi_inf = total_hi_inf - (1 if s.hi == math.inf else 0)
            other_lo: IntBound = (
                -math.inf
                if other_lo_inf > 0
                else finite_lo_sum - (0 if s.lo == -math.inf else int(s.lo))
            )
            other_hi: IntBound = (
                math.inf
                if other_hi_inf > 0
                else finite_hi_sum - (0 if s.hi == math.inf else int(s.hi))
            )

            # Upper bound on coeff * x_i: rhs - min(other terms)
            req_hi = _sub_bound(self.rhs, other_lo)
            req_lo: IntBound = _sub_bound(self.rhs, other_hi) if self.op == "=" else -math.inf
            candidate = _clamp_scaled_domain(dom, coeff, req_lo, req_hi)
            _emit_domain(self, cell, dom, candidate)
            if isinstance(candidate, Contradiction):
                return

    def _propagate_ne(self, domains: list[IntegerDomain]) -> None:
        undetermined: list[tuple[int, int, Cell, IntegerDomain]] = []
        fixed_sum = 0
        for idx, ((coeff, cell), dom) in enumerate(zip(self.terms, domains, strict=True)):
            if dom.is_determined:
                assert dom.value is not None
                fixed_sum += coeff * dom.value
            else:
                undetermined.append((idx, coeff, cell, dom))

        if not undetermined:
            if fixed_sum == self.rhs:
                self.emit(
                    self.terms[0][1],
                    Contradiction(
                        reason=f"Linear inequality {self.name} violated: sum == {self.rhs}"
                    ),
                )
            return

        if len(undetermined) == 1:
            _, coeff, cell, dom = undetermined[0]
            rem = self.rhs - fixed_sum
            if rem % coeff == 0:
                forbidden = rem // coeff
                if dom.contains(forbidden):
                    _emit_domain(self, cell, dom, dom.without(forbidden))


class IntAddPropagator(Propagator):
    """Bidirectional integer addition ``a + b = result`` over ``IntegerDomain``."""

    def __init__(
        self,
        name: str,
        a: Cell,
        b: Cell,
        result: Cell,
        confidence: float = 1.0,
        is_assumption: bool = False,
    ) -> None:
        self.a = a
        self.b = b
        self.result = result
        super().__init__(
            name,
            [a, b, result],
            [a, b, result],
            confidence=confidence,
            is_assumption=is_assumption,
        )

    @staticmethod
    def _combine_segments(
        x: IntegerDomain,
        y: IntegerDomain,
        fn: Callable[
            [tuple[IntBound, IntBound], tuple[IntBound, IntBound]], tuple[IntBound, IntBound]
        ],
    ) -> IntegerDomain:
        if len(x.ranges) * len(y.ranges) <= 64 and x.is_bounded and y.is_bounded:
            return IntegerDomain(ranges=tuple(fn(sx, sy) for sx in x.ranges for sy in y.ranges))
        lo, hi = fn((x.lo, x.hi), (y.lo, y.hi))
        return IntegerDomain.between(lo, hi)

    def alert(self, network: PropagatorNetwork) -> None:
        """Propagate sum and inverse differences across ``a``, ``b``, and ``result``."""
        da = _read_int_domain(self.a)
        db = _read_int_domain(self.b)
        dr = _read_int_domain(self.result)
        if not (
            isinstance(da, IntegerDomain)
            and isinstance(db, IntegerDomain)
            and isinstance(dr, IntegerDomain)
        ):
            return

        add_seg = lambda sa, sb: (_add_bound(sa[0], sb[0]), _add_bound(sa[1], sb[1]))
        sub_seg = lambda sr, sx: (_sub_bound(sr[0], sx[1]), _sub_bound(sr[1], sx[0]))

        _emit_domain(self, self.result, dr, dr.intersect(self._combine_segments(da, db, add_seg)))
        _emit_domain(self, self.a, da, da.intersect(self._combine_segments(dr, db, sub_seg)))
        _emit_domain(self, self.b, db, db.intersect(self._combine_segments(dr, da, sub_seg)))


class IntMulPropagator(Propagator):
    """Bidirectional integer multiplication ``a * b = result`` over ``IntegerDomain``.

    Handles ``±∞`` bounds (with ``0 * ±∞ = 0``), splits around zero during
    backward deduction, and uses exact floor/ceil division to eliminate
    non-integer solutions (e.g., ``2 * x = 5`` triggers ``Contradiction``).
    """

    def __init__(
        self,
        name: str,
        a: Cell,
        b: Cell,
        result: Cell,
        confidence: float = 1.0,
        is_assumption: bool = False,
    ) -> None:
        self.a = a
        self.b = b
        self.result = result
        super().__init__(
            name,
            [a, b, result],
            [a, b, result],
            confidence=confidence,
            is_assumption=is_assumption,
        )

    @staticmethod
    def _mul_bounds(da: IntegerDomain, db: IntegerDomain) -> IntegerDomain:
        corners = (
            _mul_bound(da.lo, db.lo),
            _mul_bound(da.lo, db.hi),
            _mul_bound(da.hi, db.lo),
            _mul_bound(da.hi, db.hi),
        )
        return IntegerDomain.between(min(corners), max(corners))

    @staticmethod
    def _solve_factor(dz: IntegerDomain, dy: IntegerDomain, dx: IntegerDomain) -> LatticeValue:
        """Deduce allowed values of x from x * y in dz, y in dy."""
        parts: list[IntegerDomain] = []
        if dy.contains(0) and dz.contains(0):
            return dx

        pos_y = dy.clamp(1, math.inf)
        if isinstance(pos_y, IntegerDomain):
            b_pos = _div_pos_range_bounds(dz.lo, dz.hi, int(pos_y.lo), pos_y.hi)
            if b_pos is not None:
                parts.append(IntegerDomain.between(*b_pos))

        neg_y = dy.clamp(-math.inf, -1)
        if isinstance(neg_y, IntegerDomain):
            b_neg = _div_pos_range_bounds(
                _neg_bound(dz.hi),
                _neg_bound(dz.lo),
                int(_neg_bound(neg_y.hi)),
                _neg_bound(neg_y.lo),
            )
            if b_neg is not None:
                parts.append(IntegerDomain.between(*b_neg))

        if not parts:
            return Contradiction(
                reason=f"No integer factor satisfies x * {dy} ∈ {dz}",
                conflicting_values=(dx, dy, dz),
            )
        union_dom = parts[0] if len(parts) == 1 else parts[0].union(parts[1])
        return dx.intersect(union_dom)

    def alert(self, network: PropagatorNetwork) -> None:
        """Propagate integer product bounds and exact inverse factor bounds."""
        da = _read_int_domain(self.a)
        db = _read_int_domain(self.b)
        dr = _read_int_domain(self.result)
        if not (
            isinstance(da, IntegerDomain)
            and isinstance(db, IntegerDomain)
            and isinstance(dr, IntegerDomain)
        ):
            return

        _emit_domain(self, self.result, dr, dr.intersect(self._mul_bounds(da, db)))
        _emit_domain(self, self.a, da, self._solve_factor(dr, db, da))
        _emit_domain(self, self.b, db, self._solve_factor(dr, da, db))


class IntAbsPropagator(Propagator):
    """Bidirectional integer absolute value constraint ``|x| = y``."""

    def __init__(
        self,
        name: str,
        x: Cell,
        y: Cell,
        confidence: float = 1.0,
        is_assumption: bool = False,
    ) -> None:
        self.x = x
        self.y = y
        super().__init__(
            name,
            [x, y],
            [x, y],
            confidence=confidence,
            is_assumption=is_assumption,
        )

    def alert(self, network: PropagatorNetwork) -> None:
        """Propagate non-negativity and mirrored bounds between ``x`` and ``y``."""
        dx = _read_int_domain(self.x)
        dy = _read_int_domain(self.y)
        if not isinstance(dx, IntegerDomain) or not isinstance(dy, IntegerDomain):
            return

        # y >= 0 always
        dy_nonneg = dy.clamp(0, math.inf)
        if isinstance(dy_nonneg, Contradiction):
            _emit_domain(self, self.y, dy, dy_nonneg)
            return

        # Forward: |x| bounds for y
        x_abs_segs = tuple(
            (_neg_bound(hi), _neg_bound(lo))
            if hi < 0
            else ((lo, hi) if lo > 0 else (0, max(_neg_bound(lo), hi)))
            for lo, hi in dx.ranges
        )
        fwd_y = IntegerDomain(ranges=x_abs_segs)
        new_y = dy_nonneg.intersect(fwd_y)
        _emit_domain(self, self.y, dy, new_y)
        if isinstance(new_y, Contradiction):
            return

        # Backward: x in (-new_y) U (+new_y)
        neg_y = IntegerDomain(
            ranges=tuple((_neg_bound(hi), _neg_bound(lo)) for lo, hi in new_y.ranges)
        )
        _emit_domain(self, self.x, dx, dx.intersect(new_y.union(neg_y)))


class IntAllDifferentPropagator(Propagator):
    """All-different constraint over ``IntegerDomain`` cells (bounded or unbounded).

    Performs forward singleton elimination across arbitrary (including infinite)
    integer domains, and hidden-singles deduction when all participating cells
    have small bounded domains.
    """

    def __init__(
        self,
        name: str,
        cells: Sequence[Cell],
        confidence: float = 1.0,
        is_assumption: bool = False,
    ) -> None:
        self.cells = list(cells)
        super().__init__(
            name,
            self.cells,
            self.cells,
            confidence=confidence,
            is_assumption=is_assumption,
        )

    def alert(self, network: PropagatorNetwork) -> None:
        """Eliminate singleton values from peers and deduce bounded hidden singles."""
        domains: dict[str, IntegerDomain] = {}
        determined: dict[int, Cell] = {}
        for cell in self.cells:
            dom = _read_int_domain(cell)
            if not isinstance(dom, IntegerDomain):
                return
            domains[cell.cell_id] = dom
            if dom.is_determined:
                val = dom.value
                assert val is not None
                if val in determined:
                    self.emit(
                        cell,
                        Contradiction(
                            reason=f"Duplicate integer {val} in {self.name} ({determined[val].cell_id} vs {cell.cell_id})",
                            conflicting_values=(determined[val].value, dom),
                        ),
                    )
                    return
                determined[val] = cell

        # Forward elimination across all peers (works even with ±inf!)
        for val, source_cell in determined.items():
            for peer in self.cells:
                if peer is not source_cell:
                    p_dom = domains[peer.cell_id]
                    if p_dom.contains(val):
                        updated = p_dom.without(val)
                        _emit_domain(self, peer, p_dom, updated)
                        if isinstance(updated, Contradiction):
                            return
                        assert isinstance(updated, IntegerDomain)
                        domains[peer.cell_id] = updated

        # Hidden singles when all domains are bounded and compact
        if all(d.is_bounded and d.size <= 64 for d in domains.values()):
            occurrences: dict[int, list[Cell]] = {}
            for cell in self.cells:
                dom = domains[cell.cell_id]
                if not dom.is_determined:
                    for cand in dom.iter_values():
                        if cand not in determined:
                            occurrences.setdefault(cand, []).append(cell)
            assigned: set[str] = set()
            for cand, owners in occurrences.items():
                if len(owners) == 1 and owners[0].cell_id not in assigned:
                    assigned.add(owners[0].cell_id)
                    _emit_domain(
                        self, owners[0], domains[owners[0].cell_id], IntegerDomain.single(cand)
                    )


# ---------------------------------------------------------------------------
# Convenience network builders
# ---------------------------------------------------------------------------


def add_int_rel(
    network: PropagatorNetwork,
    left: Cell | int,
    op: str,
    right: Cell | int,
    *,
    name: str | None = None,
) -> IntRelationPropagator:
    """Add an :class:`IntRelationPropagator` ``left <op> right`` to ``network``."""
    c_left = _coerce_int_cell(left, network, "left")
    c_right = _coerce_int_cell(right, network, "right")
    canon = normalize_int_op(op)
    prop_name = (
        name or f"IntRel_{c_left.cell_id}_{canon}_{c_right.cell_id}_{len(network.propagators)}"
    )
    prop = IntRelationPropagator(prop_name, c_left, canon, c_right)
    network.add_propagator(prop)
    return prop


def add_int_linear(
    network: PropagatorNetwork,
    terms: Sequence[tuple[int, Cell]] | IntExpr,
    op: str,
    rhs: int = 0,
    *,
    name: str | None = None,
) -> IntLinearPropagator:
    """Add an :class:`IntLinearPropagator` to ``network``.

    Accepts either a sequence of ``(coeff, cell)`` pairs or an :class:`IntExpr`
    (automatically folding any constant offset into ``rhs``).
    """
    term_list, eff_rhs = (
        ([(w, c) for c, w in terms.terms], rhs - terms.offset)
        if isinstance(terms, IntExpr)
        else (list(terms), rhs)
    )
    canon = normalize_int_op(op)
    prop_name = name or f"IntLinear_{canon}_{len(network.propagators)}"
    prop = IntLinearPropagator(prop_name, term_list, canon, eff_rhs)
    network.add_propagator(prop)
    return prop


def add_int_add(
    network: PropagatorNetwork,
    a: Cell | int,
    b: Cell | int,
    result: Cell | int,
    *,
    name: str | None = None,
) -> IntAddPropagator:
    """Add a bidirectional :class:`IntAddPropagator` ``a + b = result``."""
    ca = _coerce_int_cell(a, network, "a")
    cb = _coerce_int_cell(b, network, "b")
    cr = _coerce_int_cell(result, network, "result")
    prop_name = name or f"IntAdd_{ca.cell_id}_{cb.cell_id}_{cr.cell_id}_{len(network.propagators)}"
    prop = IntAddPropagator(prop_name, ca, cb, cr)
    network.add_propagator(prop)
    return prop


def add_int_mul(
    network: PropagatorNetwork,
    a: Cell | int,
    b: Cell | int,
    result: Cell | int,
    *,
    name: str | None = None,
) -> IntMulPropagator:
    """Add a bidirectional :class:`IntMulPropagator` ``a * b = result``."""
    ca = _coerce_int_cell(a, network, "a")
    cb = _coerce_int_cell(b, network, "b")
    cr = _coerce_int_cell(result, network, "result")
    prop_name = name or f"IntMul_{ca.cell_id}_{cb.cell_id}_{cr.cell_id}_{len(network.propagators)}"
    prop = IntMulPropagator(prop_name, ca, cb, cr)
    network.add_propagator(prop)
    return prop


def add_int_abs(
    network: PropagatorNetwork,
    x: Cell | int,
    y: Cell | int,
    *,
    name: str | None = None,
) -> IntAbsPropagator:
    """Add a bidirectional :class:`IntAbsPropagator` ``|x| = y``."""
    cx = _coerce_int_cell(x, network, "x")
    cy = _coerce_int_cell(y, network, "y")
    prop_name = name or f"IntAbs_{cx.cell_id}_{cy.cell_id}_{len(network.propagators)}"
    prop = IntAbsPropagator(prop_name, cx, cy)
    network.add_propagator(prop)
    return prop


def add_int_reified(
    network: PropagatorNetwork,
    bool_cell: Cell,
    left: Cell | int,
    op: str,
    right: Cell | int,
    *,
    name: str | None = None,
) -> ReifiedIntRelationPropagator:
    """Add a :class:`ReifiedIntRelationPropagator` ``bool_cell ⟺ (left <op> right)``."""
    c_left = _coerce_int_cell(left, network, "left")
    c_right = _coerce_int_cell(right, network, "right")
    canon = normalize_int_op(op)
    prop_name = name or f"Reify_{bool_cell.cell_id}_{c_left.cell_id}_{canon}_{c_right.cell_id}"
    prop = ReifiedIntRelationPropagator(prop_name, bool_cell, c_left, canon, c_right)
    network.add_propagator(prop)
    return prop


def add_int_all_different(
    network: PropagatorNetwork,
    cells: Sequence[Cell],
    *,
    name: str | None = None,
) -> IntAllDifferentPropagator:
    """Add an :class:`IntAllDifferentPropagator` across ``cells``."""
    prop_name = name or f"IntAllDiff_{len(network.propagators)}"
    prop = IntAllDifferentPropagator(prop_name, cells)
    network.add_propagator(prop)
    return prop
