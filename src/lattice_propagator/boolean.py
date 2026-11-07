"""Boolean logic gates and SAT constraint propagators.

Provides multi-directional boolean constraint primitives:
- `AndPropagator`: Multi-directional ternary AND gate.
- `OrPropagator`: Multi-directional ternary OR gate.
- `NotPropagator`: Bidirectional boolean inverter.
- `XorPropagator`: Multi-directional ternary XOR / parity gate.
- `Literal`: Typed boolean literal (Cell + polarity) for SAT clauses.
- `ClausePropagator`: Two-Watched-Literals disjunctive clause constraint for CDCL SAT.
- Helper functions `add_clause`, `add_and_gate`, `add_or_gate`, `add_not_gate`, `add_xor_gate`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .lattice import (
    Contradiction,
    FlatValue,
    LatticeValue,
)
from .primitives import (
    Cell,
    Propagator,
    PropagatorNetwork,
    register_binary_op,
    register_unary_op,
)


def _to_bool(val: LatticeValue) -> bool | None:
    """Extract a Python bool from a FlatValue, or None if unassigned/contradiction."""
    if isinstance(val, FlatValue) and isinstance(val.val, bool):
        return val.val
    return None


class AndPropagator(Propagator):
    """Multi-directional ternary boolean AND gate constraint enforcing `in1 ∧ in2 = out`.

    Deduction rules:
      - If `in1 == False` or `in2 == False` ⇒ `out = False`.
      - If `in1 == True` and `in2 == True` ⇒ `out = True`.
      - If `out == True` ⇒ `in1 = True` and `in2 = True`.
      - If `out == False` and `in1 == True` ⇒ `in2 = False`.
      - If `out == False` and `in2 == True` ⇒ `in1 = False`.
    """

    def __init__(
        self,
        name: str,
        in1: Cell,
        in2: Cell,
        out: Cell,
        confidence: float = 1.0,
        is_assumption: bool = False,
    ) -> None:
        super().__init__(
            name,
            inputs=[in1, in2, out],
            outputs=[in1, in2, out],
            confidence=confidence,
            is_assumption=is_assumption,
        )
        self.in1 = in1
        self.in2 = in2
        self.out = out

    def alert(self, network: PropagatorNetwork) -> None:
        b1 = _to_bool(self.in1.value)
        b2 = _to_bool(self.in2.value)
        bout = _to_bool(self.out.value)

        # 1. Forward deductions to out
        if b1 is False or b2 is False:
            ants = (self.in1,) if b1 is False else (self.in2,)
            if bout is True:
                self.emit(
                    self.out,
                    Contradiction(f"AND gate {self.name} conflict: inputs False but output True"),
                    antecedents=ants,
                )
                return
            if bout is None:
                self.emit(self.out, FlatValue(False), antecedents=ants)
                bout = False

        if b1 is True and b2 is True:
            if bout is False:
                self.emit(
                    self.out,
                    Contradiction(f"AND gate {self.name} conflict: inputs True but output False"),
                    antecedents=(self.in1, self.in2),
                )
                return
            if bout is None:
                self.emit(self.out, FlatValue(True), antecedents=(self.in1, self.in2))
                bout = True

        # 2. Backward deductions from out
        if bout is True:
            if b1 is False or b2 is False:
                conflict_ant = (self.in1,) if b1 is False else (self.in2,)
                self.emit(
                    self.out,
                    Contradiction(f"AND gate {self.name} conflict: output True but input False"),
                    antecedents=(self.out, *conflict_ant),
                )
                return
            if b1 is None:
                self.emit(self.in1, FlatValue(True), antecedents=(self.out,))
            if b2 is None:
                self.emit(self.in2, FlatValue(True), antecedents=(self.out,))

        elif bout is False:
            if b1 is True and b2 is True:
                self.emit(
                    self.out,
                    Contradiction(f"AND gate {self.name} conflict: output False but inputs True"),
                    antecedents=(self.out, self.in1, self.in2),
                )
                return
            if b1 is True and b2 is None:
                self.emit(self.in2, FlatValue(False), antecedents=(self.out, self.in1))
            elif b2 is True and b1 is None:
                self.emit(self.in1, FlatValue(False), antecedents=(self.out, self.in2))


class OrPropagator(Propagator):
    """Multi-directional ternary boolean OR gate constraint enforcing `in1 ∨ in2 = out`.

    Deduction rules:
      - If `in1 == True` or `in2 == True` ⇒ `out = True`.
      - If `in1 == False` and `in2 == False` ⇒ `out = False`.
      - If `out == False` ⇒ `in1 = False` and `in2 = False`.
      - If `out == True` and `in1 == False` ⇒ `in2 = True`.
      - If `out == True` and `in2 == False` ⇒ `in1 = True`.
    """

    def __init__(
        self,
        name: str,
        in1: Cell,
        in2: Cell,
        out: Cell,
        confidence: float = 1.0,
        is_assumption: bool = False,
    ) -> None:
        super().__init__(
            name,
            inputs=[in1, in2, out],
            outputs=[in1, in2, out],
            confidence=confidence,
            is_assumption=is_assumption,
        )
        self.in1 = in1
        self.in2 = in2
        self.out = out

    def alert(self, network: PropagatorNetwork) -> None:
        b1 = _to_bool(self.in1.value)
        b2 = _to_bool(self.in2.value)
        bout = _to_bool(self.out.value)

        # 1. Forward deductions to out
        if b1 is True or b2 is True:
            ants = (self.in1,) if b1 is True else (self.in2,)
            if bout is False:
                self.emit(
                    self.out,
                    Contradiction(f"OR gate {self.name} conflict: inputs True but output False"),
                    antecedents=ants,
                )
                return
            if bout is None:
                self.emit(self.out, FlatValue(True), antecedents=ants)
                bout = True

        if b1 is False and b2 is False:
            if bout is True:
                self.emit(
                    self.out,
                    Contradiction(f"OR gate {self.name} conflict: inputs False but output True"),
                    antecedents=(self.in1, self.in2),
                )
                return
            if bout is None:
                self.emit(self.out, FlatValue(False), antecedents=(self.in1, self.in2))
                bout = False

        # 2. Backward deductions from out
        if bout is False:
            if b1 is True or b2 is True:
                conflict_ant = (self.in1,) if b1 is True else (self.in2,)
                self.emit(
                    self.out,
                    Contradiction(f"OR gate {self.name} conflict: output False but input True"),
                    antecedents=(self.out, *conflict_ant),
                )
                return
            if b1 is None:
                self.emit(self.in1, FlatValue(False), antecedents=(self.out,))
            if b2 is None:
                self.emit(self.in2, FlatValue(False), antecedents=(self.out,))

        elif bout is True:
            if b1 is False and b2 is False:
                self.emit(
                    self.out,
                    Contradiction(f"OR gate {self.name} conflict: output True but inputs False"),
                    antecedents=(self.out, self.in1, self.in2),
                )
                return
            if b1 is False and b2 is None:
                self.emit(self.in2, FlatValue(True), antecedents=(self.out, self.in1))
            elif b2 is False and b1 is None:
                self.emit(self.in1, FlatValue(True), antecedents=(self.out, self.in2))


class NotPropagator(Propagator):
    """Bidirectional boolean inverter constraint enforcing `¬in = out`.

    Deduction rules:
      - If `in_` is known ⇒ `out = ¬in_`.
      - If `out` is known ⇒ `in_ = ¬out`.
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
        b_in = _to_bool(self.in_.value)
        b_out = _to_bool(self.out.value)

        if b_in is not None:
            expected = not b_in
            if b_out is not None and b_out != expected:
                self.emit(
                    self.out,
                    Contradiction(f"NOT inverter {self.name} conflict: {b_in} vs {b_out}"),
                    antecedents=(self.in_, self.out),
                )
                return
            if b_out is None:
                self.emit(self.out, FlatValue(expected), antecedents=(self.in_,))
                b_out = expected

        if b_out is not None and b_in is None:
            expected = not b_out
            self.emit(self.in_, FlatValue(expected), antecedents=(self.out,))


class XorPropagator(Propagator):
    """Multi-directional ternary boolean XOR / parity constraint enforcing `in1 ⊕ in2 = out`.

    Deduction rules (any two known values uniquely determine the third):
      - `out = in1 ⊕ in2`
      - `in1 = in2 ⊕ out`
      - `in2 = in1 ⊕ out`
    """

    def __init__(
        self,
        name: str,
        in1: Cell,
        in2: Cell,
        out: Cell,
        confidence: float = 1.0,
        is_assumption: bool = False,
    ) -> None:
        super().__init__(
            name,
            inputs=[in1, in2, out],
            outputs=[in1, in2, out],
            confidence=confidence,
            is_assumption=is_assumption,
        )
        self.in1 = in1
        self.in2 = in2
        self.out = out

    def alert(self, network: PropagatorNetwork) -> None:
        b1 = _to_bool(self.in1.value)
        b2 = _to_bool(self.in2.value)
        bout = _to_bool(self.out.value)

        # 1. in1 and in2 known -> out
        if b1 is not None and b2 is not None:
            expected = b1 ^ b2
            if bout is not None and bout != expected:
                self.emit(
                    self.out,
                    Contradiction(f"XOR gate {self.name} parity conflict: {b1} ^ {b2} != {bout}"),
                    antecedents=(self.in1, self.in2, self.out),
                )
                return
            if bout is None:
                self.emit(self.out, FlatValue(expected), antecedents=(self.in1, self.in2))
                bout = expected

        # 2. in1 and out known -> in2
        if b1 is not None and bout is not None and b2 is None:
            expected = b1 ^ bout
            self.emit(self.in2, FlatValue(expected), antecedents=(self.in1, self.out))
            b2 = expected

        # 3. in2 and out known -> in1
        if b2 is not None and bout is not None and b1 is None:
            expected = b2 ^ bout
            self.emit(self.in1, FlatValue(expected), antecedents=(self.in2, self.out))


@dataclass(frozen=True)
class Literal:
    """Boolean literal associating a Cell with positive or negative polarity.

    Attributes:
        cell: The reactive `Cell` representing the boolean variable.
        positive: True if positive literal (x), False if negated literal (¬x).
    """

    cell: Cell
    positive: bool = True

    @property
    def value(self) -> bool | None:
        """Return the current evaluated boolean value of this literal, or None if unassigned."""
        b = _to_bool(self.cell.value)
        if b is None:
            return None
        return b if self.positive else not b

    def is_satisfied(self) -> bool:
        """True if the literal evaluates to True under the cell's current assignment."""
        return self.value is True

    def is_falsified(self) -> bool:
        """True if the literal evaluates to False under the cell's current assignment."""
        return self.value is False

    def is_unassigned(self) -> bool:
        """True if the underlying cell has not yet received a boolean assignment."""
        return self.value is None

    def __invert__(self) -> Literal:
        """Return the negated literal with inverted polarity."""
        return Literal(self.cell, not self.positive)

    def __repr__(self) -> str:
        prefix = "" if self.positive else "¬"
        return f"{prefix}{self.cell.cell_id}"


class ClausePropagator(Propagator):
    """Two-Watched-Literals disjunctive clause propagator for CDCL SAT networks.

    Enforces that at least one literal in `(l_1 ∨ l_2 ∨ ... ∨ l_k)` evaluates to True.
    Maintains the Two-Watched-Literals invariant:
      - Tracks indices `watch1` and `watch2`.
      - When a watched literal becomes False, seeks an alternate non-falsified literal.
      - If no alternate exists and the other watched literal is unassigned, triggers
        unit propagation (deducing the remaining literal must be True).
      - If both watched literals are False and no alternates exist, detects contradiction.
    """

    def __init__(
        self,
        name: str,
        literals: Sequence[Literal | tuple[Cell, bool] | Cell],
        confidence: float = 1.0,
        is_assumption: bool = False,
    ) -> None:
        norm_lits: list[Literal] = []
        for item in literals:
            if isinstance(item, Literal):
                norm_lits.append(item)
            elif isinstance(item, tuple) and len(item) == 2:
                norm_lits.append(Literal(item[0], bool(item[1])))
            elif isinstance(item, Cell):
                norm_lits.append(Literal(item, True))
            else:
                raise TypeError(f"Invalid literal specification: {item!r}")

        cells = [lit.cell for lit in norm_lits]
        super().__init__(
            name,
            inputs=cells,
            outputs=cells,
            confidence=confidence,
            is_assumption=is_assumption,
        )
        self.literals: list[Literal] = norm_lits
        self.watch1: int = 0
        self.watch2: int = 1 if len(norm_lits) > 1 else 0

    def _find_alternate_watch(self, exclude: tuple[int, int]) -> int | None:
        """Find an alternate literal index that is not falsified."""
        for idx, lit in enumerate(self.literals):
            if idx not in exclude and not lit.is_falsified():
                return idx
        return None

    def alert(self, network: PropagatorNetwork) -> None:
        if not self.literals:
            return

        if len(self.literals) == 1:
            lit = self.literals[0]
            if lit.is_falsified():
                self.emit(
                    lit.cell,
                    Contradiction(f"Unit clause {self.name} violated: {lit} is False"),
                    antecedents=[lit.cell],
                )
            elif lit.is_unassigned():
                self.emit(lit.cell, FlatValue(lit.positive), antecedents=[])
            return

        # 1. If either watched literal is satisfied, clause is already true
        if self.literals[self.watch1].is_satisfied() or self.literals[self.watch2].is_satisfied():
            return

        # 2. Inspect watch1
        if self.literals[self.watch1].is_falsified():
            new_w1 = self._find_alternate_watch(exclude=(self.watch1, self.watch2))
            if new_w1 is not None:
                self.watch1 = new_w1
                if self.literals[self.watch1].is_satisfied():
                    return
            else:
                other = self.literals[self.watch2]
                if other.is_falsified():
                    falsified_cells = [lit.cell for lit in self.literals]
                    self.emit(
                        other.cell,
                        Contradiction(f"Clause {self.name} violated: all literals falsified"),
                        antecedents=falsified_cells,
                    )
                    return
                if other.is_unassigned():
                    antecedents = [
                        lit.cell for i, lit in enumerate(self.literals) if i != self.watch2
                    ]
                    self.emit(other.cell, FlatValue(other.positive), antecedents=antecedents)
                    return

        # 3. Inspect watch2
        if self.literals[self.watch2].is_falsified():
            new_w2 = self._find_alternate_watch(exclude=(self.watch1, self.watch2))
            if new_w2 is not None:
                self.watch2 = new_w2
                if self.literals[self.watch2].is_satisfied():
                    return
            else:
                other = self.literals[self.watch1]
                if other.is_falsified():
                    falsified_cells = [lit.cell for lit in self.literals]
                    self.emit(
                        other.cell,
                        Contradiction(f"Clause {self.name} violated: all literals falsified"),
                        antecedents=falsified_cells,
                    )
                    return
                if other.is_unassigned():
                    antecedents = [
                        lit.cell for i, lit in enumerate(self.literals) if i != self.watch1
                    ]
                    self.emit(other.cell, FlatValue(other.positive), antecedents=antecedents)
                    return


# --- Declarative Helper Builders ---


def add_and_gate(
    network: PropagatorNetwork,
    in1: Cell,
    in2: Cell,
    out: Cell | None = None,
    name: str | None = None,
) -> tuple[Cell, AndPropagator]:
    """Attach a multi-directional ternary AND gate to the network."""
    target_out = out if out is not None else network.add_cell(f"({in1.cell_id}&{in2.cell_id})")
    prop_name = name or f"and_{in1.cell_id}_{in2.cell_id}"
    prop = AndPropagator(prop_name, in1, in2, target_out)
    network.add_propagator(prop)
    return target_out, prop


def add_or_gate(
    network: PropagatorNetwork,
    in1: Cell,
    in2: Cell,
    out: Cell | None = None,
    name: str | None = None,
) -> tuple[Cell, OrPropagator]:
    """Attach a multi-directional ternary OR gate to the network."""
    target_out = out if out is not None else network.add_cell(f"({in1.cell_id}|{in2.cell_id})")
    prop_name = name or f"or_{in1.cell_id}_{in2.cell_id}"
    prop = OrPropagator(prop_name, in1, in2, target_out)
    network.add_propagator(prop)
    return target_out, prop


def add_not_gate(
    network: PropagatorNetwork,
    in_: Cell,
    out: Cell | None = None,
    name: str | None = None,
) -> tuple[Cell, NotPropagator]:
    """Attach a bidirectional NOT inverter gate to the network."""
    target_out = out if out is not None else network.add_cell(f"(~{in_.cell_id})")
    prop_name = name or f"not_{in_.cell_id}"
    prop = NotPropagator(prop_name, in_, target_out)
    network.add_propagator(prop)
    return target_out, prop


def add_xor_gate(
    network: PropagatorNetwork,
    in1: Cell,
    in2: Cell,
    out: Cell | None = None,
    name: str | None = None,
) -> tuple[Cell, XorPropagator]:
    """Attach a multi-directional ternary XOR gate to the network."""
    target_out = out if out is not None else network.add_cell(f"({in1.cell_id}^{in2.cell_id})")
    prop_name = name or f"xor_{in1.cell_id}_{in2.cell_id}"
    prop = XorPropagator(prop_name, in1, in2, target_out)
    network.add_propagator(prop)
    return target_out, prop


def add_clause(
    network: PropagatorNetwork,
    literals: Sequence[Literal | tuple[Cell, bool] | Cell],
    name: str | None = None,
) -> ClausePropagator:
    """Attach a Two-Watched-Literals SAT clause constraint to the network."""
    prop_name = name or f"clause_{len(network.propagators)}"
    prop = ClausePropagator(prop_name, literals)
    network.add_propagator(prop)
    return prop


# Register boolean operators for Cell dunder method dispatch (&, |, ^, ~)
register_binary_op("and", "&", AndPropagator, False)
register_binary_op("or", "|", OrPropagator, False)
register_binary_op("xor", "^", XorPropagator, False)
register_unary_op("not", "~", NotPropagator)
