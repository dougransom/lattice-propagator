"""First-order terms, structural deconstruction, and unification propagators.

Provides:
- `Term`: First-order symbolic term representation with functor and arguments.
- `TermValue`: LatticeValue wrapper embedding first-order terms into join-semilattices.
- `PairPropagator`: Bidirectional `cons`/`car`/`cdr` pair deconstruction/construction.
- `UnifyPropagator`: First-order term unification constraint over symbolic terms and cells.
- Helper functions `add_pair_constraint`, `add_unify_constraint`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .lattice import (
    Bottom,
    Contradiction,
    FlatValue,
    LatticeValue,
    merge_lattice,
    register_merge_handler,
)
from .primitives import (
    Cell,
    Propagator,
    PropagatorNetwork,
    _should_update_target,
)


@dataclass(frozen=True)
class Term:
    """First-order symbolic term consisting of a functor name and argument list.

    Arguments can be constants (int, str, bool, float), nested `Term` instances,
    or reactive `Cell` references.
    """

    functor: str
    args: tuple[Any, ...] = ()

    def __init__(self, functor: str, *args: Any) -> None:
        object.__setattr__(self, "functor", functor)
        # Flatten tuple if passed as single sequence argument
        if len(args) == 1 and isinstance(args[0], (list, tuple)):
            norm_args = tuple(args[0])
        else:
            norm_args = tuple(args)
        object.__setattr__(self, "args", norm_args)

    @property
    def arity(self) -> int:
        """Return number of arguments (arity) of this term."""
        return len(self.args)

    def is_ground(self) -> bool:
        """True if term contains no unassigned Cell arguments or Bottom values."""
        for arg in self.args:
            if isinstance(arg, Cell):
                if isinstance(arg.value, Bottom):
                    return False
            elif isinstance(arg, Term) and not arg.is_ground():
                return False
        return True

    def __repr__(self) -> str:
        if not self.args:
            return self.functor
        arg_strs: list[str] = []
        for a in self.args:
            if isinstance(a, Cell):
                arg_strs.append(f"Cell({a.cell_id})")
            else:
                arg_strs.append(repr(a))
        return f"{self.functor}({', '.join(arg_strs)})"


@dataclass(frozen=True)
class TermValue(LatticeValue):
    """Lattice value wrapping a first-order symbolic `Term`."""

    term: Term

    def __repr__(self) -> str:
        return f"TermValue({self.term!r})"


def _merge_term_values(a: TermValue, b: TermValue) -> LatticeValue:
    """Monotonic join of two TermValues over the Herbrand universe."""
    if a.term.functor != b.term.functor or a.term.arity != b.term.arity:
        return Contradiction(
            reason=f"Herbrand clash: {a.term.functor}/{a.term.arity} vs {b.term.functor}/{b.term.arity}",
            conflicting_values=(a, b),
        )
    merged_args: list[Any] = []
    for arg1, arg2 in zip(a.term.args, b.term.args, strict=False):
        if isinstance(arg1, LatticeValue) and isinstance(arg2, LatticeValue):
            m = merge_lattice(arg1, arg2)
            if isinstance(m, Contradiction):
                return m
            merged_args.append(m)
        elif arg1 != arg2:
            return Contradiction(
                reason=f"Constant clash in sub-term: {arg1!r} vs {arg2!r}",
                conflicting_values=(a, b),
            )
        else:
            merged_args.append(arg1)
    return TermValue(Term(a.term.functor, *merged_args))


register_merge_handler(TermValue, _merge_term_values)


class PairPropagator(Propagator):
    """Bidirectional pair structural constraint enforcing `pair = (head, tail)`.

    Forward:  `pair ⟶ head = pair[0], tail = pair[1]`
    Backward: `head, tail ⟶ pair = (head, tail)`
    """

    def __init__(
        self,
        name: str,
        pair: Cell,
        head: Cell,
        tail: Cell,
        confidence: float = 1.0,
        is_assumption: bool = False,
    ) -> None:
        super().__init__(
            name,
            inputs=[pair, head, tail],
            outputs=[pair, head, tail],
            confidence=confidence,
            is_assumption=is_assumption,
        )
        self.pair = pair
        self.head = head
        self.tail = tail

    def alert(self, network: PropagatorNetwork) -> None:
        v_pair = self.pair.value
        v_head = self.head.value
        v_tail = self.tail.value

        # 1. Forward: pair -> head, tail
        if not isinstance(v_pair, (Bottom, Contradiction)):
            extracted = self._extract_pair(v_pair)
            if isinstance(extracted, Contradiction):
                self.emit(self.pair, extracted, antecedents=(self.pair,))
                return
            if extracted is not None:
                h_val, t_val = extracted
                if _should_update_target(v_head, h_val):
                    self.emit(self.head, h_val, antecedents=(self.pair,))
                    v_head = self.head.value
                if _should_update_target(v_tail, t_val):
                    self.emit(self.tail, t_val, antecedents=(self.pair,))
                    v_tail = self.tail.value

        # 2. Backward: head, tail -> pair
        if not isinstance(v_head, (Bottom, Contradiction)) and not isinstance(
            v_tail, (Bottom, Contradiction)
        ):
            cand_pair = self._construct_pair(v_head, v_tail)
            if _should_update_target(v_pair, cand_pair):
                self.emit(self.pair, cand_pair, antecedents=(self.head, self.tail))

    def _extract_pair(
        self, val: LatticeValue
    ) -> tuple[LatticeValue, LatticeValue] | Contradiction | None:
        raw: Any = None
        if isinstance(val, FlatValue):
            raw = val.val
        elif (
            isinstance(val, TermValue)
            and val.term.functor in ("cons", "pair")
            and val.term.arity == 2
        ):
            raw = val.term.args

        if raw is None:
            return None

        if isinstance(raw, (tuple, list)) and len(raw) == 2:
            h, t = raw
            h_val = h if isinstance(h, LatticeValue) else FlatValue(h)
            t_val = t if isinstance(t, LatticeValue) else FlatValue(t)
            return h_val, t_val

        return Contradiction(f"Expected 2-tuple pair in {self.name}, got: {raw!r}")

    def _construct_pair(self, h: LatticeValue, t: LatticeValue) -> LatticeValue:
        raw_h = h.val if isinstance(h, FlatValue) else h
        raw_t = t.val if isinstance(t, FlatValue) else t
        return FlatValue((raw_h, raw_t))


class UnifyPropagator(Propagator):
    """First-order term unification constraint enforcing `term1 = term2`.

    Performs structural unification over symbolic `Term`s, `TermValue`s,
    and reactive `Cell` variables.
    """

    def __init__(
        self,
        name: str,
        term1: Cell,
        term2: Cell,
        confidence: float = 1.0,
        is_assumption: bool = False,
    ) -> None:
        super().__init__(
            name,
            inputs=[term1, term2],
            outputs=[term1, term2],
            confidence=confidence,
            is_assumption=is_assumption,
        )
        self.term1 = term1
        self.term2 = term2

    def alert(self, network: PropagatorNetwork) -> None:
        v1 = self.term1.value
        v2 = self.term2.value

        if isinstance(v1, Contradiction) or isinstance(v2, Contradiction):
            return

        # Case A: One side is Bottom, the other is known
        if isinstance(v1, Bottom) and not isinstance(v2, Bottom):
            self.emit(self.term1, v2, antecedents=(self.term2,))
            return

        if isinstance(v2, Bottom) and not isinstance(v1, Bottom):
            self.emit(self.term2, v1, antecedents=(self.term1,))
            return

        # Case B: Both sides have known values -> Unify structures
        t1 = self._to_term(v1)
        t2 = self._to_term(v2)

        if t1 is not None and t2 is not None:
            # Check functor and arity match
            if t1.functor != t2.functor or t1.arity != t2.arity:
                self.emit(
                    self.term1,
                    Contradiction(
                        f"Unification clash in {self.name}: {t1.functor}/{t1.arity} vs {t2.functor}/{t2.arity}"
                    ),
                    antecedents=(self.term1, self.term2),
                )
                return

            # Recursively unify corresponding arguments
            for idx, (arg1, arg2) in enumerate(zip(t1.args, t2.args, strict=False)):
                self._unify_args(arg1, arg2, network, path=f"{self.name}.arg{idx}")

        elif t1 is None and t2 is None:
            # Primitive lattice value unification
            merged = merge_lattice(v1, v2)
            if isinstance(merged, Contradiction):
                self.emit(self.term1, merged, antecedents=(self.term1, self.term2))
                self.emit(self.term2, merged, antecedents=(self.term1, self.term2))

    def _to_term(self, val: LatticeValue) -> Term | None:
        if isinstance(val, TermValue):
            return val.term
        if isinstance(val, FlatValue) and isinstance(val.val, Term):
            return val.val
        return None

    def _unify_args(self, arg1: Any, arg2: Any, network: PropagatorNetwork, path: str) -> None:
        # Cell and Cell: Unify directly via Union-Find
        if isinstance(arg1, Cell) and isinstance(arg2, Cell):
            arg1.unify(arg2)
            return

        # Cell and Value/Term: Propagate assignment into the cell
        if isinstance(arg1, Cell):
            val2 = self._wrap_arg(arg2)
            if _should_update_target(arg1.value, val2):
                arg1.set_value(val2, source=path)
            return

        if isinstance(arg2, Cell):
            val1 = self._wrap_arg(arg1)
            if _should_update_target(arg2.value, val1):
                arg2.set_value(val1, source=path)
            return

        # Nested Term and Term
        if isinstance(arg1, Term) and isinstance(arg2, Term):
            if arg1.functor != arg2.functor or arg1.arity != arg2.arity:
                self.emit(
                    self.term1,
                    Contradiction(
                        f"Sub-term clash at {path}: {arg1.functor}/{arg1.arity} vs {arg2.functor}/{arg2.arity}"
                    ),
                    antecedents=(self.term1, self.term2),
                )
                return
            for idx, (sub1, sub2) in enumerate(zip(arg1.args, arg2.args, strict=False)):
                self._unify_args(sub1, sub2, network, path=f"{path}.sub{idx}")
            return

        # Primitive constants
        if arg1 != arg2:
            self.emit(
                self.term1,
                Contradiction(f"Constant clash at {path}: {arg1!r} != {arg2!r}"),
                antecedents=(self.term1, self.term2),
            )

    def _wrap_arg(self, arg: Any) -> LatticeValue:
        if isinstance(arg, LatticeValue):
            return arg
        if isinstance(arg, Term):
            return TermValue(arg)
        return FlatValue(arg)


# --- Declarative Helper Builders ---


def add_pair_constraint(
    network: PropagatorNetwork,
    pair: Cell,
    head: Cell | None = None,
    tail: Cell | None = None,
    name: str | None = None,
) -> tuple[Cell, Cell, PairPropagator]:
    """Attach a bidirectional pair deconstruction constraint (`pair = (head, tail)`)."""
    c_head = head if head is not None else network.add_cell(f"head({pair.cell_id})")
    c_tail = tail if tail is not None else network.add_cell(f"tail({pair.cell_id})")
    prop_name = name or f"pair_{pair.cell_id}"
    prop = PairPropagator(prop_name, pair, c_head, c_tail)
    network.add_propagator(prop)
    return c_head, c_tail, prop


def add_unify_constraint(
    network: PropagatorNetwork,
    term1: Cell,
    term2: Cell,
    name: str | None = None,
) -> UnifyPropagator:
    """Attach a first-order term unification constraint (`term1 = term2`) to the network."""
    prop_name = name or f"unify_{term1.cell_id}_{term2.cell_id}"
    prop = UnifyPropagator(prop_name, term1, term2)
    network.add_propagator(prop)
    return prop
