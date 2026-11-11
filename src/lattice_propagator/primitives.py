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
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .graph import NetworkGraph

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
    MapLattice,
    OrderedInterval,
    SetLattice,
    coerce_to_lattice_value,
    merge_lattice,
)
from .tms import ExplanationNode, Justification, Translator


class Cell:
    """Reactive container holding an information lattice value with alias/unification support."""

    def __init__(
        self,
        cell_id: str,
        value: Any = BOTTOM,
        propagators: Sequence[Propagator] | None = None,
        network: PropagatorNetwork | None = None,
        unit: str = "",
        display_name: str | None = None,
    ) -> None:
        self.cell_id = cell_id
        self._value = value if isinstance(value, LatticeValue) else coerce_to_lattice_value(value)
        self.propagators: list[Propagator] = list(propagators) if propagators is not None else []
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
    def value(self, new_value: Any) -> None:
        """Set or overwrite the canonical value of this cell, notifying network observers."""
        coerced = (
            new_value if isinstance(new_value, LatticeValue) else coerce_to_lattice_value(new_value)
        )
        self.set_value(coerced, overwrite=True)

    @property
    def val(self) -> Any:
        """Extract the unwrapped Python primitive from the canonical lattice value."""
        v = self.value
        if isinstance(v, FlatValue):
            return v.val
        if isinstance(v, IntervalValue):
            return (v.min_val, v.max_val)
        if isinstance(v, DiscreteDomain):
            return v.candidates
        if isinstance(v, SetLattice):
            return v.elements
        if isinstance(v, MapLattice):
            return v.mapping
        if isinstance(v, (Bottom, Contradiction)):
            return None
        return v

    @property
    def raw(self) -> Any:
        """Alias for self.val."""
        return self.val

    def bind(self, other: Cell) -> None:
        """Unify/bind this cell with another cell (alias for unify)."""
        self.unify(other)

    def __lshift__(self, other: Cell) -> Cell:
        """Bind this cell to another cell or expression: `c << (a + b)`."""
        self.unify(other)
        return self

    def add_propagator(self, propagator: Propagator) -> None:
        """Register a propagator that observes this cell or its canonical representative."""
        root = self._find()
        if propagator not in root.propagators:
            root.propagators.append(propagator)

    def remove_propagator(self, propagator: Propagator) -> None:
        """Unregister a propagator observing this cell or its canonical representative."""
        root = self._find()
        if propagator in root.propagators:
            root.propagators.remove(propagator)
        if propagator in self.propagators:
            self.propagators.remove(propagator)

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

            ntms = getattr(root.network, "tms", None) if root.network else None
            root.tms = TruthMaintenanceSystem(
                cell_id=root.cell_id,
                default_prior=root._value,
                unit=root.unit,
                display_name=root.display_name,
                network=root.network,
                network_tms=ntms,
            )
            if ntms is not None:
                ntms.cell_tms[root.cell_id] = root.tms
        return root.tms

    def explain(
        self,
        unit: str | None = None,
        depth: int | None = 1,
        translator: Translator | None = None,
    ) -> str:
        """Generate a human-readable explanation for this cell's state and provenance."""
        return self.get_or_create_tms().explain(unit=unit, depth=depth, translator=translator)

    def explain_node(
        self,
        unit: str | None = None,
        depth: int | None = 1,
    ) -> ExplanationNode:
        """Generate a structured, localizable explanation node for this cell's state."""
        return self.get_or_create_tms().explain_node(unit=unit, depth=depth)

    def walk_downstream(
        self,
        max_depth: int | None = None,
    ) -> Iterator[Cell | Propagator]:
        """Traverse downstream from this cell through observing propagators and consequences.

        Args:
            max_depth: Maximum traversal depth.

        Returns:
            Iterator over cells and propagators in breadth-first causal order.
        """
        from .graph import walk_downstream

        return walk_downstream(self, max_depth=max_depth)

    def walk_upstream(
        self,
        max_depth: int | None = None,
    ) -> Iterator[Cell | Propagator]:
        """Traverse upstream from this cell back to governing propagators and antecedent cells.

        Args:
            max_depth: Maximum traversal depth.

        Returns:
            Iterator over cells and propagators in upstream causal cone order.
        """
        from .graph import walk_upstream

        return walk_upstream(self, max_depth=max_depth)

    def set_value(
        self,
        new_value: LatticeValue | Any,
        source: str | None = None,
        overwrite: bool = False,
        justification: Justification | None = None,
        confidence: float = 1.0,
        is_assumption: bool = False,
        support: frozenset[str] | None = None,
    ) -> bool:
        """Merge or update a value into this cell (or its canonical representative).

        Returns True if the cell's value was updated (information gained).
        """
        coerced = (
            new_value if isinstance(new_value, LatticeValue) else coerce_to_lattice_value(new_value)
        )
        root = self._find()
        if source:
            tms = root.get_or_create_tms()
            tms.assert_evidence(
                source_id=source,
                value=coerced,
                justification=justification,
                confidence=confidence,
                is_assumption=is_assumption,
                support=support,
            )

        if overwrite or root._value == BOTTOM:
            if root._value == coerced:
                return False
            root._value = coerced
            if root.network:
                root.network.notify_changed(root, source=source)
            return True

        merged = merge_lattice(root._value, coerced)
        if merged == root._value:
            return False

        root._value = merged
        if root.network:
            root.network.notify_changed(root, source=source)
        return True

    def retract_source(self, source: str, reason: str = "retracted") -> bool:
        """Retract a source premise from this cell's TMS and recompute its fused value.

        Args:
            source: Identifier of the premise source to retract.
            reason: Reason for retraction (e.g. 'retracted', 'link_moved', 'unavailable').

        Returns:
            True if the cell's canonical value changed after retraction.
        """
        root = self._find()
        tms = root.get_or_create_tms()
        if source not in tms.premises or not tms.premises[source].is_active:
            return False
        tms.retract_evidence(source, reason=reason)
        if tms.network_tms is not None and source in tms.network_tms.assumptions:
            tms.network_tms.assumptions[source].is_active = False
            tms.network_tms.assumptions[source].status_reason = reason
        recomputed = tms.compute_fused_value()
        if root._value == recomputed:
            return False
        root._value = recomputed
        if root.network:
            root.network.notify_changed(root, source=f"retract:{source}")
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

    def __and__(self, other: Any) -> Cell:
        return _build_binary_op(self, other, op="and")

    def __rand__(self, other: Any) -> Cell:
        return _build_binary_op(other, self, op="and")

    def __or__(self, other: Any) -> Cell:
        return _build_binary_op(self, other, op="or")

    def __ror__(self, other: Any) -> Cell:
        return _build_binary_op(other, self, op="or")

    def __xor__(self, other: Any) -> Cell:
        return _build_binary_op(self, other, op="xor")

    def __rxor__(self, other: Any) -> Cell:
        return _build_binary_op(other, self, op="xor")

    def __invert__(self) -> Cell:
        return _build_unary_op(self, op="not")

    def __pow__(self, other: Any) -> Cell:
        return _build_binary_op(self, other, op="pow")

    def __repr__(self) -> str:
        root = self._find()
        if root is not self:
            return f"Cell({self.cell_id} -> {root.cell_id}: {root._value})"
        return f"Cell({self.cell_id}: {self._value})"


class Propagator(ABC):
    """Abstract base class for all propagator operators with unified TMS provenance."""

    def __init__(
        self,
        name: str,
        inputs: Sequence[Cell],
        outputs: Sequence[Cell],
        confidence: float = 1.0,
        is_assumption: bool = False,
    ) -> None:
        self.name = name
        self.inputs = list(inputs)
        self.outputs = list(outputs)
        self.confidence = confidence
        self.is_assumption = is_assumption
        for c in inputs:
            c.add_propagator(self)
            if c.network is not None and self not in c.network.propagators:
                c.network.add_propagator(self)

    def derive_provenance(
        self,
        antecedents: Sequence[Cell] | None = None,
        parameters: Mapping[str, Any] | None = None,
        source: str | None = None,
        confidence_scale: float = 1.0,
        force_assumption: bool = False,
    ) -> tuple[Justification, float, bool, frozenset[str] | None]:
        """Derive TMS justification, weakest-link confidence, defeasibility, and ATMS support set.

        Args:
            antecedents: Input cells contributing to this deduction (defaults to `self.inputs`).
            parameters: Optional rule parameters for the `Justification` record.
            source: Premise source identifier (defaults to `self.name`).
            confidence_scale: Multiplicative scale factor in (0.0, 1.0] (e.g. for ambiguous branches).
            force_assumption: If True, forces the derived premise to be a defeasible assumption.

        Returns:
            Tuple of `(justification, derived_confidence, derived_is_assumption, derived_support)`.
        """
        ant_cells = tuple(antecedents if antecedents is not None else self.inputs)
        min_input_conf = 1.0
        any_input_assumption = False
        upstream_support: set[str] = set()

        for c in ant_cells:
            root = c._find()
            if root.tms is not None:
                active = [p for p in root.tms.premises.values() if p.is_active]
                if active:
                    min_input_conf = min(
                        min_input_conf,
                        min(p.confidence for p in active),
                    )
                    for p in active:
                        if p.is_assumption or p.support:
                            any_input_assumption = True
                        upstream_support.update(p.support)

        src = source or self.name
        if self.is_assumption or force_assumption:
            upstream_support.add(src)

        derived_conf = round(self.confidence * confidence_scale * min_input_conf, 4)
        derived_is_assump = self.is_assumption or force_assumption or any_input_assumption
        derived_support = frozenset(upstream_support) if upstream_support else None
        just = Justification(
            rule_name=self.__class__.__name__,
            antecedents=tuple(c.cell_id for c in ant_cells),
            parameters=parameters or {},
        )
        return just, derived_conf, derived_is_assump, derived_support

    def emit(
        self,
        target: Cell,
        value: LatticeValue,
        *,
        source: str | None = None,
        overwrite: bool = False,
        recompute_tms: bool = False,
        antecedents: Sequence[Cell] | None = None,
        parameters: Mapping[str, Any] | None = None,
        confidence_scale: float = 1.0,
        force_assumption: bool = False,
    ) -> bool:
        """Emit a deduced value to a target cell with unified TMS provenance tracking.

        Args:
            target: Destination `Cell` receiving the deduced value.
            value: Deduced `LatticeValue` to assert.
            source: Premise source identifier (defaults to `self.name`).
            overwrite: Whether to overwrite `target` instead of merging with its current value.
            recompute_tms: If True, asserts into `target`'s TMS and sets `target` to
                `tms.compute_fused_value()`.
            antecedents: Input cells contributing to this deduction (defaults to `self.inputs`).
            parameters: Optional rule parameters for the `Justification` record.
            confidence_scale: Multiplicative confidence scale factor in (0.0, 1.0].
            force_assumption: If True, forces the emitted premise to be a defeasible assumption.

        Returns:
            True if `target`'s canonical value was updated.
        """
        src = source or self.name
        just, conf, is_assump, support = self.derive_provenance(
            antecedents=antecedents,
            parameters=parameters,
            source=src,
            confidence_scale=confidence_scale,
            force_assumption=force_assumption,
        )
        is_direct_assumption = self.is_assumption or force_assumption

        has_network_tms = (
            target.network is not None and getattr(target.network, "tms", None) is not None
        )
        if recompute_tms or has_network_tms:
            tms = target.get_or_create_tms()
            tms.assert_evidence(
                source_id=src,
                value=value,
                confidence=conf,
                is_assumption=is_assump,
                support=support,
                justification=just,
            )
            if tms.network_tms is not None and is_direct_assumption:
                tms.network_tms.assumptions[src] = tms.premises[src]
            return target.set_value(tms.compute_fused_value(), overwrite=True)

        updated = target.set_value(
            value,
            source=src,
            overwrite=overwrite,
            justification=just,
            confidence=conf,
            is_assumption=is_assump,
            support=support,
        )
        if is_direct_assumption and target._find().tms is not None:
            tms = target._find().tms
            if tms.network_tms is not None and src in tms.premises:
                tms.network_tms.assumptions[src] = tms.premises[src]
        return updated

    @abstractmethod
    def alert(self, network: PropagatorNetwork) -> None:
        """Execute propagation when an input cell updates."""


class ArithmeticPropagator(Propagator):
    """Computes a linear combination or difference: output = sum(w_i * x_i) + offset."""

    def __init__(
        self,
        name: str,
        inputs: Sequence[Cell],
        output: Cell,
        weights: Sequence[float] | None = None,
        offset: float = 0.0,
        confidence: float = 1.0,
        is_assumption: bool = False,
    ) -> None:
        super().__init__(
            name,
            inputs,
            [output],
            confidence=confidence,
            is_assumption=is_assumption,
        )
        self.output = output
        self.weights = list(weights) if weights is not None else [1.0] * len(inputs)
        self.offset = offset

    def alert(self, network: PropagatorNetwork) -> None:
        """Calculate weighted sum across input cells."""
        # Check if all inputs have values
        if any(isinstance(c.value, (Bottom, Contradiction)) for c in self.inputs):
            return

        params = {"weights": self.weights, "offset": self.offset}

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
            self.emit(self.output, new_val, parameters=params)
            return

        # Case 2: Intervals
        all_interval = all(isinstance(c.value, (IntervalValue, GaussianValue)) for c in self.inputs)
        if all_interval:
            min_sum = self.offset
            max_sum = self.offset
            for c, w in zip(self.inputs, self.weights, strict=False):
                c_min, c_max = (
                    (c.value.min_val, c.value.max_val)
                    if isinstance(c.value, IntervalValue)
                    else c.value.confidence_interval(0.95)
                )
                min_sum, max_sum = (
                    (min_sum + w * c_min, max_sum + w * c_max)
                    if w >= 0
                    else (min_sum + w * c_max, max_sum + w * c_min)
                )

            new_val = IntervalValue(min_val=min_sum, max_val=max_sum)
            self.emit(self.output, new_val, parameters=params)


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
    if isinstance(val, bool):
        cid = f"const_{val}"
        if cid in network.cells:
            return network.cells[cid]
        return network.add_cell(cid, FlatValue(val))
    if isinstance(val, (int, float)):
        val_str = str(val).replace(".", "_").replace("-", "neg_")
        cid = f"const_{val_str}"
        if cid in network.cells:
            return network.cells[cid]
        return network.add_cell(cid, IntervalValue(float(val), float(val)))
    if isinstance(val, str):
        cid = f"const_{val}"
        if cid in network.cells:
            return network.cells[cid]
        return network.add_cell(cid, FlatValue(val))
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

    def __init__(
        self,
        name: str,
        a: Cell,
        b: Cell,
        c: Cell,
        confidence: float = 1.0,
        is_assumption: bool = False,
    ) -> None:
        super().__init__(
            name,
            inputs=[a, b, c],
            outputs=[a, b, c],
            confidence=confidence,
            is_assumption=is_assumption,
        )
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
                self.emit(self.c, cand_c, antecedents=(self.a, self.b))
                val_c = self.c.value

        # 2. Backward A: c - b -> a
        if not isinstance(val_c, (Bottom, Contradiction)) and not isinstance(
            val_b, (Bottom, Contradiction)
        ):
            cand_a = _sub_values(val_c, val_b)
            if cand_a is not None and _should_update_target(val_a, cand_a):
                self.emit(self.a, cand_a, antecedents=(self.c, self.b))
                val_a = self.a.value

        # 3. Backward B: c - a -> b
        if not isinstance(val_c, (Bottom, Contradiction)) and not isinstance(
            val_a, (Bottom, Contradiction)
        ):
            cand_b = _sub_values(val_c, val_a)
            if cand_b is not None and _should_update_target(val_b, cand_b):
                self.emit(self.b, cand_b, antecedents=(self.c, self.a))


class MultiplierPropagator(Propagator):
    """Bidirectional multiplier constraint enforcing a * b = c.

    Propagates monotonically in all 3 directions with zero-absorption:
      Forward:    c = a * b
      Backward A: a = c / b (when 0 not in b)
      Backward B: b = c / a (when 0 not in a)
    """

    def __init__(
        self,
        name: str,
        a: Cell,
        b: Cell,
        c: Cell,
        confidence: float = 1.0,
        is_assumption: bool = False,
    ) -> None:
        super().__init__(
            name,
            inputs=[a, b, c],
            outputs=[a, b, c],
            confidence=confidence,
            is_assumption=is_assumption,
        )
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
                self.emit(self.c, cand_c, antecedents=(self.a, self.b))
                val_c = self.c.value

        # 2. Backward A: c / b -> a
        if not isinstance(val_c, (Bottom, Contradiction)) and not isinstance(
            val_b, (Bottom, Contradiction)
        ):
            cand_a = _div_values(val_c, val_b)
            if cand_a is not None and _should_update_target(val_a, cand_a):
                self.emit(self.a, cand_a, antecedents=(self.c, self.b))
                val_a = self.a.value

        # 3. Backward B: c / a -> b
        if not isinstance(val_c, (Bottom, Contradiction)) and not isinstance(
            val_a, (Bottom, Contradiction)
        ):
            cand_b = _div_values(val_c, val_a)
            if cand_b is not None and _should_update_target(val_b, cand_b):
                self.emit(self.b, cand_b, antecedents=(self.c, self.a))


_BINARY_OPS: dict[str, tuple[str, type[Propagator], bool]] = {
    "add": ("+", AdderPropagator, False),
    "sub": ("-", AdderPropagator, True),
    "mul": ("*", MultiplierPropagator, False),
    "div": ("/", MultiplierPropagator, True),
}

_UNARY_OPS: dict[str, tuple[str, type[Propagator]]] = {}


def register_binary_op(
    op: str, symbol: str, prop_cls: type[Propagator], inverted: bool = False
) -> None:
    """Register a custom binary operator for Cell dunder method dispatch.

    Allows extending `Cell` arithmetic and relational expressions (e.g. `+`, `-`, `*`, `/`)
    with custom multi-directional or directed propagator classes.

    Args:
        op: Operator key name (e.g. 'add', 'sub', 'mul', 'div', 'pow').
        symbol: String representation for synthesized cell names (e.g. '+', '-', '**').
        prop_cls: Propagator class to instantiate connecting operands and result.
        inverted: If True, args are passed as `(out, right, left)` to invert
            the relation (e.g. subtraction using `AdderPropagator`). If False,
            args are passed as `(left, right, out)`.
    """
    _BINARY_OPS[op] = (symbol, prop_cls, inverted)


def register_unary_op(op: str, symbol: str, prop_cls: type[Propagator]) -> None:
    """Register a custom unary operator for Cell dunder method dispatch.

    Args:
        op: Operator key name (e.g. 'neg', 'abs', 'invert').
        symbol: String representation for synthesized cell names (e.g. '-', '~').
        prop_cls: Propagator class to instantiate connecting operand and result.
    """
    _UNARY_OPS[op] = (symbol, prop_cls)


def build_unary_op(operand: Cell, op: str) -> Cell:
    """Build a unary operator cell using declarative dispatch.

    Synthesizes an intermediate output cell and wires a corresponding unary
    propagator connecting operand to output.

    Args:
        operand: The input Cell.
        op: Operator key registered in `_UNARY_OPS`.

    Returns:
        The newly synthesized result Cell.

    Raises:
        ValueError: If `op` is not registered.
    """
    spec = _UNARY_OPS.get(op)
    if spec is None:
        supported = ", ".join(repr(k) for k in _UNARY_OPS)
        raise ValueError(f"Unsupported unary operator {op!r}. Supported: {supported}")

    symbol, prop_cls = spec
    net = operand.network if operand.network is not None else PropagatorNetwork()
    out = net.add_cell(f"({symbol}{operand.cell_id})")
    p = prop_cls(f"{op}_{operand.cell_id}", operand, out)
    net.add_propagator(p)
    return out


_build_unary_op = build_unary_op


def build_binary_op(left: Any, right: Any, op: str) -> Cell:
    """Build a binary arithmetic operator cell using declarative dispatch.

    Expression Functionalization:
    Transforms infix Python operator expressions (such as `a + b`, `a * b`, `a - b`)
    into a reactive subnetwork of multi-directional propagators.
    Coerces raw scalar values into constant cells, synthesizes an anonymous
    intermediate result cell, and attaches the appropriate constraint propagator.

    Directionality & Inverted Dispatch:
    - Additive operations (`+`) wire `(left, right, out)` into `AdderPropagator(a, b, c)`.
    - Subtractive operations (`-`) invert dispatch, wiring `(out, right, left)` so that
      `out + right = left` without duplicating arithmetic constraint logic.
    - Multiplicative operations (`*`, `/`) behave analogously via `MultiplierPropagator`.

    Args:
        left: Left operand (Cell or constant scalar).
        right: Right operand (Cell or constant scalar).
        op: Operator key ('add', 'sub', 'mul', 'div', or registered custom key).

    Returns:
        The newly synthesized result Cell in the shared network.

    Raises:
        ValueError: If `op` is not registered in `_BINARY_OPS`.
    """
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


_build_binary_op = build_binary_op


def tree_reduce(
    op: str,
    cells: Sequence[Cell | Any],
    network: PropagatorNetwork | None = None,
) -> Cell:
    """Aggregate a sequence of cells using a balanced binary reduction tree.

    Constructs a balanced binary tree of multi-directional propagators with
    $O(\\log N)$ propagation depth, preventing the degenerate $O(N)$ depth chains
    caused by standard linear reductions (e.g. `functools.reduce`). This minimizes
    worklist churn, shortens causal dependency paths, and accelerates backward
    deduction during constraint solving.

    Args:
        op: Binary operator key registered in `_BINARY_OPS` (e.g. 'add', 'mul').
        cells: Sequence of Cells or coercible scalar values to aggregate.
        network: Optional target network. If omitted, inferred from operand cells.

    Returns:
        The root Cell representing the reduced expression.

    Raises:
        ValueError: If `cells` is empty or `op` is not registered.
    """
    if not cells:
        raise ValueError("Cannot reduce an empty sequence of cells.")

    seq = list(cells)
    if len(seq) == 1:
        item = seq[0]
        if isinstance(item, Cell):
            return item
        net = network or PropagatorNetwork()
        return _coerce_to_cell(item, net, "operand")

    if len(seq) == 2:
        return build_binary_op(seq[0], seq[1], op)

    mid = len(seq) // 2
    left_root = tree_reduce(op, seq[:mid], network=network)
    right_root = tree_reduce(op, seq[mid:], network=network)
    return build_binary_op(left_root, right_root, op)


def tree_sum(
    cells: Sequence[Cell | Any],
    network: PropagatorNetwork | None = None,
) -> Cell:
    """Sum a sequence of cells using a balanced binary reduction tree ($O(\\log N)$ depth).

    Equivalent to `tree_reduce('add', cells, network=network)`. For an empty sequence,
    returns a cell initialized with zero.

    Args:
        cells: Sequence of Cells or numbers to sum.
        network: Optional PropagatorNetwork.

    Returns:
        The root Cell holding the balanced sum.
    """
    if not cells:
        net = network or PropagatorNetwork()
        return net.add_cell("zero", FlatValue(0))
    return tree_reduce("add", cells, network=network)


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
        confidence: float = 1.0,
        is_assumption: bool = False,
    ) -> None:
        super().__init__(
            name,
            inputs=[control_cell, input_cell],
            outputs=[output_cell],
            confidence=confidence,
            is_assumption=is_assumption,
        )
        self.control_cell = control_cell
        self.input_cell = input_cell
        self.output_cell = output_cell
        self.on_value = on_value

    def alert(self, network: PropagatorNetwork) -> None:
        ctrl = self.control_cell.value
        if isinstance(ctrl, (Bottom, Contradiction)):
            return

        is_active = (
            ctrl.val == self.on_value
            if isinstance(ctrl, FlatValue)
            else (ctrl.is_determined and ctrl.value == self.on_value)
            if isinstance(ctrl, DiscreteDomain)
            else (
                math.isclose(ctrl.min_val, float(self.on_value), abs_tol=1e-9)
                and math.isclose(ctrl.max_val, float(self.on_value), abs_tol=1e-9)
            )
            if isinstance(ctrl, IntervalValue)
            else (ctrl == self.on_value)
        )

        if is_active and not isinstance(self.input_cell.value, (Bottom, Contradiction)):
            self.emit(self.output_cell, self.input_cell.value)


class MobileLinkPropagator(Propagator):
    """π-calculus link-mobility propagator routing a payload cell across dynamic channel targets.

    Implements Milner's π-calculus link mobility (`c?(y). y!<v>`) over partial-information
    lattices with Truth Maintenance System (TMS) handoff:
    - Observes `channel_cell` (holding active target channel name(s) as `FlatValue`,
      `DiscreteDomain`, `OrderedInterval`, `SetLattice`, or `BeliefMassValue`) and
      `payload_cell` (holding the `LatticeValue` carried by the mobile entity).
    - Asserts `payload_cell.value` into each resolved target cell's TMS via `self.emit()`.
    - When `channel_cell` moves to a new target (or becomes `Bottom`), automatically
      retracts the premise from vacated target cells so they relax back to their
      remaining active premises.
    - Supports uncertainty-aware mobility (`propagate_ambiguous=True`), projecting
      defeasible `Assumption` premises with scaled confidence across candidate targets
      when location/channel state is ambiguous.
    - Supports dynamic channel creation (`spawn_missing=True`), corresponding to the
      π-calculus restriction operator `(ν y)` by allocating missing target cells in the
      network on demand.
    """

    def __init__(
        self,
        name: str,
        channel_cell: Cell,
        payload_cell: Cell,
        targets: Mapping[str, Cell] | Sequence[Cell] | None = None,
        source_id: str | None = None,
        confidence: float = 1.0,
        is_assumption: bool = False,
        propagate_ambiguous: bool = False,
        min_plausibility: float = 0.25,
        spawn_missing: bool = False,
    ) -> None:
        """Initialize the π-calculus mobile link propagator.

        Args:
            name: Identifier for this propagator.
            channel_cell: Cell carrying the active target channel identifier(s).
            payload_cell: Cell carrying the mobile payload `LatticeValue` to assert.
            targets: Optional mapping from channel name to target `Cell`, or sequence of `Cell`s.
                If omitted, channel names are resolved against `network.cells`.
            source_id: Base source identifier recorded in target TMS premises (defaults to `name`).
            confidence: Base confidence in [0.0, 1.0] inherited from `Propagator`.
            is_assumption: Whether determined bindings are recorded as defeasible assumptions.
            propagate_ambiguous: If True, projects speculative `Assumption` premises across
                multiple candidate targets when `channel_cell` is undetermined/ambiguous.
            min_plausibility: Minimum Dempster-Shafer plausibility threshold in (0.0, 1.0]
                for routing across `BeliefMassValue` candidates when `propagate_ambiguous=True`.
            spawn_missing: If True, dynamically allocates a new `Cell` in the network when
                `channel_cell` names a target channel that does not yet exist (`(ν y)`).
        """
        target_map = (
            dict(targets)
            if isinstance(targets, Mapping)
            else {c.cell_id: c for c in targets}
            if isinstance(targets, Sequence)
            else {}
        )

        super().__init__(
            name,
            inputs=[channel_cell, payload_cell],
            outputs=list(target_map.values()),
            confidence=confidence,
            is_assumption=is_assumption,
        )
        self.channel_cell = channel_cell
        self.payload_cell = payload_cell
        self.target_map: dict[str, Cell] = target_map
        self.source_id = source_id or name
        self.propagate_ambiguous = propagate_ambiguous
        self.min_plausibility = min_plausibility
        self.spawn_missing = spawn_missing
        self._active_bindings: dict[str, str] = {}

    def _extract_bindings(self, channel_val: LatticeValue) -> Mapping[str, tuple[float, bool]]:
        """Extract mapping of target_key -> (confidence_scale, force_assumption) from channel value."""
        if isinstance(channel_val, (Bottom, Contradiction)):
            return {}
        if isinstance(channel_val, FlatValue):
            raw = channel_val.val
            items = raw if isinstance(raw, (set, frozenset, list, tuple)) else (raw,)
            return {str(item): (1.0, False) for item in items if item is not None}
        if isinstance(channel_val, SetLattice):
            return {str(item): (1.0, False) for item in channel_val.elements}
        if isinstance(channel_val, (DiscreteDomain, OrderedInterval)):
            if channel_val.is_determined:
                return {str(channel_val.value): (1.0, False)}
            if not self.propagate_ambiguous:
                return {}
            cands = tuple(channel_val.candidates)
            scale = 1.0 / len(cands)
            return {str(c): (scale, True) for c in cands}
        if isinstance(channel_val, BeliefMassValue):
            if not self.propagate_ambiguous:
                determined = [str(k) for k in channel_val.frame if channel_val.belief(k) >= 0.5]
                if len(determined) != 1:
                    return {}
                key = determined[0]
                bel = channel_val.belief(key)
                return {key: (bel, bel < 1.0)}
            return {
                str(k): (channel_val.plausibility(k), True)
                for k in sorted(channel_val.frame, key=str)
                if channel_val.plausibility(k) >= self.min_plausibility
            }
        return {}

    def _resolve_target(self, target_key: str, network: PropagatorNetwork) -> Cell | None:
        """Resolve a target cell by key, optionally spawning a fresh cell if spawn_missing=True."""
        cell = self.target_map.get(target_key) or network.cells.get(target_key)
        if cell is None and self.spawn_missing:
            cell = network.add_cell(target_key)
            self.target_map[target_key] = cell
        if cell is not None and cell not in self.outputs:
            self.outputs.append(cell)
        return cell

    def alert(self, network: PropagatorNetwork) -> None:
        """Route payload across active channel links and retract from vacated links."""
        payload = self.payload_cell.value
        bindings = (
            {}
            if isinstance(payload, (Bottom, Contradiction))
            else self._extract_bindings(self.channel_cell.value)
        )

        # 1. Retract from vacated targets
        for old_key in self._active_bindings.keys() - bindings.keys():
            old_premise_id = self._active_bindings.pop(old_key)
            old_cell = self._resolve_target(old_key, network)
            if old_cell is not None:
                old_cell.retract_source(old_premise_id, reason="link_moved")

        # 2. Assert or update active targets via unified self.emit()
        is_multi = len(bindings) > 1
        for target_key, (conf_scale, force_assump) in bindings.items():
            target_cell = self._resolve_target(target_key, network)
            if target_cell is None:
                continue

            premise_id = (
                f"{self.source_id}@{target_key}"
                if (is_multi or force_assump or self.is_assumption)
                else self.source_id
            )
            prev_premise_id = self._active_bindings.get(target_key)
            if prev_premise_id is not None and prev_premise_id != premise_id:
                target_cell.retract_source(prev_premise_id, reason="link_refined")

            self._active_bindings[target_key] = premise_id
            self.emit(
                target_cell,
                payload,
                source=premise_id,
                recompute_tms=True,
                parameters={"channel": target_key},
                confidence_scale=conf_scale,
                force_assumption=force_assump,
            )


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
        confidence: float = 1.0,
        is_assumption: bool = False,
    ) -> None:
        super().__init__(
            name,
            inputs=[condition_cell, true_cell, false_cell],
            outputs=[output_cell],
            confidence=confidence,
            is_assumption=is_assumption,
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
            self.emit(
                self.output_cell,
                t_val,
                antecedents=(self.true_cell, self.false_cell),
            )
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

        selected_cell, selected_val = (
            (self.true_cell, t_val)
            if cond_bool is True
            else (self.false_cell, f_val)
            if cond_bool is False
            else (None, None)
        )
        if selected_cell is not None and not isinstance(selected_val, (Bottom, Contradiction)):
            self.emit(
                self.output_cell,
                selected_val,
                antecedents=(self.condition_cell, selected_cell),
            )


class FunctionalPropagator(Propagator):
    """A generic propagator constructed by lifting an arbitrary pure function over cells.

    Directionality Clarification:
        `FunctionalPropagator` is strictly **unidirectional** ($I \to O$).
        Because arbitrary Python callables cannot be symbolically inverted at runtime,
        information flows only forward from `inputs` to `output`.
        If backward deduction or multidirectional constraint solving is needed,
        use compound propagators (such as `AdderPropagator`, `MultiplierPropagator`,
        or expressions built with `build_binary_op`), or use `FunctionalRelation`
        with registered `.invert(...)` decorators.

    Args:
        name: Unique identifier for the propagator.
        fn: Pure function transforming input `LatticeValue` instances into an output `LatticeValue`.
        inputs: Sequence of input cells observed by this propagator.
        output: Target cell into which function results are asserted.
        overwrite: Whether repeated emissions overwrite previous assertions from this propagator.
        confidence: TMS premise confidence factor in [0, 1].
        is_assumption: Whether emitted deductions are defeasible hypotheses.
    """

    def __init__(
        self,
        name: str,
        fn: Callable[..., LatticeValue],
        inputs: Sequence[Cell],
        output: Cell,
        overwrite: bool = True,
        confidence: float = 1.0,
        is_assumption: bool = False,
    ) -> None:
        super().__init__(
            name,
            inputs=inputs,
            outputs=[output],
            confidence=confidence,
            is_assumption=is_assumption,
        )
        self.fn = fn
        self.output = output
        self.overwrite = overwrite

    def alert(self, network: PropagatorNetwork) -> None:
        if any(isinstance(c.value, (Bottom, Contradiction)) for c in self.inputs):
            return
        try:
            res = self.fn(*(c.value for c in self.inputs))
            if isinstance(res, LatticeValue) and not isinstance(res, Bottom):
                self.emit(self.output, res, overwrite=self.overwrite)
        except (TypeError, ValueError, ArithmeticError):
            pass


def lift_propagator(
    name: str,
    fn: Callable[..., LatticeValue],
    inputs: Sequence[Cell],
    output: Cell,
    overwrite: bool = True,
    confidence: float = 1.0,
    is_assumption: bool = False,
) -> FunctionalPropagator:
    """Lift an arbitrary Python function over lattice values into a reactive propagator.

    Directionality Note:
        Primitive function lifting is strictly **unidirectional** ($I \to O$).
        Information will only propagate forward from `inputs` to `output`.
        For multi-directional relations, combine with `FunctionalRelation` or
        use compound constraint propagators (`AdderPropagator`, `build_binary_op`).

    Args:
        name: Identifier for the created propagator.
        fn: Callable taking input `LatticeValue`s and returning an output `LatticeValue`.
        inputs: Sequence of upstream Cells.
        output: Downstream target Cell.
        overwrite: Whether to overwrite earlier assertions from this propagator.
        confidence: Confidence level of asserted deductions.
        is_assumption: Whether asserted premises are defeasible assumptions.

    Returns:
        The instantiated `FunctionalPropagator`.
    """
    return FunctionalPropagator(
        name,
        fn,
        inputs,
        output,
        overwrite=overwrite,
        confidence=confidence,
        is_assumption=is_assumption,
    )


class FunctionalRelation:
    """Multi-directional or unidirectional functional constraint relation.

        Directionality & Inverse Wiring:
            Unlike simple `lift_propagator`, `FunctionalRelation` enables full
            **multi-directional deduction** across cell groups by allowing developers
            to register reverse deduction paths via the `.invert(...)` decorator:

            ```python
            rel = FunctionalRelation(c_to_f, ["celsius"], ["fahrenheit"])


            @rel.invert(["fahrenheit"], ["celsius"])
            def f_to_c(f):
                return (f - 32.0) * 5.0 / 9.0
    ```

            When attached to a network (`rel.attach(net)`), it instantiates directed
            `FunctionalPropagator` instances for each configured direction, achieving
            bidirectional or multi-directional constraint propagation.
    """

    def __init__(
        self,
        forward_fn: Callable[..., Any],
        inputs: Sequence[str | Cell],
        outputs: Sequence[str | Cell],
        name: str | None = None,
        confidence: float = 1.0,
    ) -> None:
        self.forward_fn = forward_fn
        self.inputs = list(inputs)
        self.outputs = list(outputs)
        self.name = name or forward_fn.__name__
        self.confidence = confidence
        self.inversions: list[tuple[Callable[..., Any], list[str | Cell], list[str | Cell]]] = []
        self._attached_networks: list[PropagatorNetwork] = []

    def invert(
        self,
        inputs: Sequence[str | Cell],
        outputs: Sequence[str | Cell],
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Register an inverted causal direction for this relation."""

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.inversions.append((fn, list(inputs), list(outputs)))
            for net in self._attached_networks:
                idx = len(self.inversions) - 1
                self._attach_direction(
                    net, f"{self.name}_inv_{idx}", fn, list(inputs), list(outputs)
                )
            return fn

        return decorator

    def attach(self, network: PropagatorNetwork) -> None:
        """Attach this relation and all registered inversions to a network."""
        if network not in self._attached_networks:
            self._attached_networks.append(network)
        self._attach_direction(
            network, f"{self.name}_fwd", self.forward_fn, self.inputs, self.outputs
        )
        for idx, (inv_fn, inv_inputs, inv_outputs) in enumerate(self.inversions):
            self._attach_direction(
                network, f"{self.name}_inv_{idx}", inv_fn, inv_inputs, inv_outputs
            )

    def _attach_direction(
        self,
        network: PropagatorNetwork,
        prop_name: str,
        fn: Callable[..., Any],
        in_specs: list[str | Cell],
        out_specs: list[str | Cell],
    ) -> None:
        in_cells = [network.add_cell(spec) if isinstance(spec, str) else spec for spec in in_specs]
        out_cells = [
            network.add_cell(spec) if isinstance(spec, str) else spec for spec in out_specs
        ]
        if not out_cells:
            return
        out_cell = out_cells[0]

        def lifted_fn(*args: Any) -> LatticeValue:
            raw_args = [a.val if isinstance(a, Cell) else getattr(a, "val", a) for a in args]
            res = fn(*raw_args)
            return res if isinstance(res, LatticeValue) else coerce_to_lattice_value(res)

        p = lift_propagator(
            prop_name,
            lifted_fn,
            in_cells,
            out_cell,
            confidence=self.confidence,
        )
        network.add_propagator(p)


class DelayedPropagator(Propagator):
    """Dynamic delayed construction propagator with Truth Maintenance System retraction.

    Observes a sequence of trigger cells. Defers instantiation of a subnetwork
    until trigger cells are refined past `Bottom` (⊥) and satisfy an optional
    condition. When triggers revert to `Bottom` or the condition is no longer met,
    cleanly unhooks and deactivates all spawned child propagators, retracting
    downstream deductions without leaving dead topology in the graph.

    Theoretical Foundation:
        - Sussman, G. J., & Radul, A. (2009). "The Art of the Propagator", Section 4: Dynamic Construction.
          https://dspace.mit.edu/handle/1721.1/44215
        - Hanson, C., & Sussman, G. J. (2021). "Software Design for Flexibility", Chapter 7.
          https://mitpress.mit.edu/9780262045490/software-design-for-flexibility/

    Args:
        name: Unique identifier for this delayed propagator.
        trigger_cells: Sequence of cells whose information refinement activates this constructor.
        builder: Callable `(network, *trigger_cells) -> Sequence[Propagator] | None` invoked to
            instantiate the subnetwork when trigger conditions are met.
        condition: Optional predicate `(*trigger_values) -> bool`. If omitted, any non-`Bottom`
            trigger state activates the builder.
        retract_on_unmet: If True (default), deactivates and unhooks all spawned propagators
            when trigger cells revert to `Bottom` or the condition evaluates to False.
        confidence: TMS premise confidence factor in [0, 1].
        is_assumption: Whether emitted deductions are defeasible hypotheses.
    """

    def __init__(
        self,
        name: str,
        trigger_cells: Sequence[Cell],
        builder: Callable[..., Sequence[Propagator] | None],
        condition: Callable[..., bool] | None = None,
        retract_on_unmet: bool = True,
        confidence: float = 1.0,
        is_assumption: bool = False,
    ) -> None:
        super().__init__(
            name,
            inputs=list(trigger_cells),
            outputs=[],
            confidence=confidence,
            is_assumption=is_assumption,
        )
        self.trigger_cells = list(trigger_cells)
        self.builder = builder
        self.condition = condition
        self.retract_on_unmet = retract_on_unmet
        self.spawned_propagators: list[Propagator] = []
        self._activated: bool = False

    def alert(self, network: PropagatorNetwork) -> None:
        # Check if triggers are defined (not Bottom or Contradiction)
        if any(isinstance(c.value, (Bottom, Contradiction)) for c in self.trigger_cells):
            if self._activated and self.retract_on_unmet:
                self.deactivate(network)
            return

        # Check condition predicate if specified
        if self.condition is not None:
            try:
                cond_met = bool(self.condition(*(c.value for c in self.trigger_cells)))
            except (TypeError, ValueError, ArithmeticError, AttributeError):
                cond_met = False
            if not cond_met:
                if self._activated and self.retract_on_unmet:
                    self.deactivate(network)
                return

        # Trigger condition is met -> unroll subnetwork if not already active
        if not self._activated:
            self._activated = True
            existing_props = set(network.propagators)
            res = self.builder(network, *self.trigger_cells)
            new_props: list[Propagator] = []
            if isinstance(res, Sequence):
                for p in res:
                    if isinstance(p, Propagator):
                        new_props.append(p)
                        network.add_propagator(p)
            for p in network.propagators:
                if p not in existing_props and p not in new_props:
                    new_props.append(p)
            self.spawned_propagators = new_props

    def deactivate(self, network: PropagatorNetwork) -> None:
        """Deactivate spawned subnetworks and unhook all created propagators."""
        if not self._activated:
            return
        self._activated = False
        for p in self.spawned_propagators:
            network.remove_propagator(p)
        self.spawned_propagators.clear()


def delay_propagator(
    name: str,
    trigger_cells: Sequence[Cell],
    builder: Callable[..., Sequence[Propagator] | None] | None = None,
    condition: Callable[..., bool] | None = None,
    retract_on_unmet: bool = True,
) -> DelayedPropagator | Callable[[Callable[..., Sequence[Propagator] | None]], DelayedPropagator]:
    """Create or decorate a delayed dynamic construction propagator.

        Allows constructing subnetworks on demand once trigger cells provide sufficient information.

        Usage as a standard function:
            ```python
            delayed = delay_propagator("sqrt_stage", [x, g], build_sqrt_stage, condition=is_not_done)
    ```

        Usage as a decorator:
            ```python
            @delay_propagator("sqrt_stage", [x, g], condition=is_not_done)
            def build_sqrt_stage(net, x, g):
                ...
    ```

        Args:
            name: Name of the delayed propagator.
            trigger_cells: Cells to monitor.
            builder: Optional subnetwork builder callable `(net, *cells) -> Sequence[Propagator] | None`.
            condition: Optional predicate function `(*values) -> bool`.
            retract_on_unmet: Whether to retract and remove spawned propagators when condition fails.

        Returns:
            The instantiated `DelayedPropagator`, or a decorator returning it.
    """
    if builder is not None:
        p = DelayedPropagator(
            name,
            trigger_cells,
            builder,
            condition=condition,
            retract_on_unmet=retract_on_unmet,
        )
        if trigger_cells and trigger_cells[0].network is not None:
            trigger_cells[0].network.add_propagator(p)
        return p

    def decorator(fn: Callable[..., Sequence[Propagator] | None]) -> DelayedPropagator:
        p = DelayedPropagator(
            name,
            trigger_cells,
            fn,
            condition=condition,
            retract_on_unmet=retract_on_unmet,
        )
        if trigger_cells and trigger_cells[0].network is not None:
            trigger_cells[0].network.add_propagator(p)
        return p

    return decorator


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
        confidence: float = 1.0,
        is_assumption: bool = False,
    ) -> None:
        outputs = [output_rate_cell]
        if output_eta_cell:
            outputs.append(output_eta_cell)
        super().__init__(
            name,
            [input_cell],
            outputs,
            confidence=confidence,
            is_assumption=is_assumption,
        )

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
                self.emit(
                    self.output_rate,
                    GaussianValue(mean=rate, variance=max(abs(rate) * 0.1, 0.01)),
                    overwrite=True,
                )

                if self.output_eta is not None:
                    dist_to_thresh = current_val - self.threshold
                    # Approaching threshold if rate and dist_to_thresh have opposite signs
                    if dist_to_thresh > 0 and rate < -1e-4:
                        eta_sec = abs(dist_to_thresh / rate)
                        # Bounds [eta * 0.85, eta * 1.2]
                        self.emit(
                            self.output_eta,
                            IntervalValue(min_val=eta_sec * 0.85, max_val=eta_sec * 1.2),
                            overwrite=True,
                        )
                    elif dist_to_thresh <= 0:
                        self.emit(
                            self.output_eta,
                            IntervalValue(min_val=0.0, max_val=0.0),
                            overwrite=True,
                        )

        self._prev_val = current_val
        self._prev_time = current_time

    def alert(self, network: PropagatorNetwork) -> None:
        """Triggered when input cell updates."""
        val = self.input_cell.value
        scalar = (
            val.mean
            if isinstance(val, GaussianValue)
            else val.center
            if isinstance(val, IntervalValue)
            else None
        )
        if scalar is None:
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
        confidence: float = 1.0,
        is_assumption: bool = False,
    ) -> None:
        super().__init__(
            name,
            [target_cell, state_cell],
            [output_cell],
            confidence=confidence,
            is_assumption=is_assumption,
        )
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
        params = {"tau": self.tau, "dt": dt, "alpha": round(alpha, 4)}

        if isinstance(t_val, GaussianValue) and isinstance(s_val, GaussianValue):
            next_mu = s_val.mean + alpha * (t_val.mean - s_val.mean)
            next_var = s_val.variance * (1 - alpha) ** 2 + t_val.variance * (alpha**2)
            self.emit(
                self.output_cell,
                GaussianValue(mean=next_mu, variance=max(next_var, 1e-4)),
                overwrite=True,
                parameters=params,
            )
        elif isinstance(t_val, IntervalValue) and isinstance(s_val, IntervalValue):
            next_min = s_val.min_val + alpha * (t_val.min_val - s_val.min_val)
            next_max = s_val.max_val + alpha * (t_val.max_val - s_val.max_val)
            self.emit(
                self.output_cell,
                IntervalValue(min_val=next_min, max_val=next_max),
                overwrite=True,
                parameters=params,
            )

    def alert(self, network: PropagatorNetwork) -> None:
        """Alerted when input changes; steps with dt=1.0 or user-driven simulation."""
        self.step(dt=1.0)


@dataclass(frozen=True)
class TrajectorySegment:
    """A distinct temporal segment in a piecewise trajectory envelope.

    Defines the target interval bounds and transition dynamics over a temporal duration.

    Attributes:
        duration: Duration of this segment in seconds (or time units). Must be ≥ 0.
        bounds: Target bounds (IntervalValue or scalar) reached at the end of this segment.
        transition: Transition profile ("linear", "smooth" / "cosine", "sigmoid" / "logistic",
            "tanh", "exponential" / "exp", "step", "hold").
        name: Optional descriptive label for this segment (e.g. "ramp_up", "soak", "decay").
        custom_eval: Optional callable f(u) -> float evaluating custom normalized progress for u ∈ [0, 1].
    """

    duration: float
    bounds: IntervalValue
    transition: str = "linear"
    name: str = ""
    custom_eval: Callable[[float], float] | None = None

    def __post_init__(self) -> None:
        if self.duration < 0:
            raise ValueError(f"duration must be non-negative, got {self.duration}")
        if not isinstance(self.bounds, IntervalValue):
            if isinstance(self.bounds, (int, float)):
                object.__setattr__(
                    self, "bounds", IntervalValue(float(self.bounds), float(self.bounds))
                )
            else:
                raise TypeError(f"bounds must be IntervalValue or float, got {type(self.bounds)}")


class TrajectoryEnvelopePropagator(Propagator):
    """Piecewise trajectory envelope propagator for dynamic profiles and temporal bounds.

    Maps elapsed time Δt from a time cell through a sequence of trajectory segments
    to continuously evaluate an output interval envelope [y_min(t), y_max(t)].
    Optionally modulated by an enable cell (for activation gating) and an output
    phase cell (identifying the active segment name).

    Useful for:
    - Signal Temporal Logic (STL) specification envelopes: [y_lo(t), y_hi(t)]
    - Industrial thermal / process control profiles (ramp-soak schedules)
    - Motion control trajectory bounds and velocity profiles
    - Circadian lighting and temperature curves
    - Multi-stage synthesizer envelope generators (ADSR / breakpoint envelopes)
    """

    def __init__(
        self,
        name: str,
        time_cell: Cell,
        output_cell: Cell,
        segments: Sequence[TrajectorySegment],
        enable_cell: Cell | None = None,
        phase_cell: Cell | None = None,
        initial_bounds: IntervalValue | float | None = None,
        clamp_bounds: IntervalValue | None = None,
        loop: bool = False,
        confidence: float = 1.0,
        is_assumption: bool = False,
    ) -> None:
        """Initialize the trajectory envelope propagator.

        Args:
            name: Identifier for this propagator.
            time_cell: Reactive Cell carrying elapsed time Δt (FlatValue or IntervalValue).
            output_cell: Output Cell receiving the evaluated IntervalValue envelope.
            segments: Ordered sequence of TrajectorySegment instances defining the profile.
            enable_cell: Optional Cell gating activation (DiscreteDomain or FlatValue).
            phase_cell: Optional Cell receiving the active segment name as a DiscreteDomain.
            initial_bounds: Starting bounds at t=0. Defaults to segments[0].bounds if None.
            clamp_bounds: Optional envelope boundary to clamp all evaluated intervals.
            loop: If True, wraps time modulo total duration. If False, holds final segment bounds.
            confidence: Base confidence in [0.0, 1.0] inherited from `Propagator`.
            is_assumption: Whether emitted bounds are recorded as defeasible assumptions.
        """
        if not segments:
            raise ValueError("TrajectoryEnvelopePropagator requires at least one TrajectorySegment")

        inputs = [time_cell]
        if enable_cell is not None:
            inputs.append(enable_cell)

        outputs = [output_cell]
        if phase_cell is not None:
            outputs.append(phase_cell)

        super().__init__(
            name,
            inputs,
            outputs,
            confidence=confidence,
            is_assumption=is_assumption,
        )
        self.time_cell = time_cell
        self.output_cell = output_cell
        self.segments = list(segments)
        self.enable_cell = enable_cell
        self.phase_cell = phase_cell
        self.loop = loop
        self.clamp_bounds = clamp_bounds

        if not (initial_bounds is None or isinstance(initial_bounds, (int, float, IntervalValue))):
            raise TypeError(
                f"initial_bounds must be IntervalValue or float, got {type(initial_bounds)}"
            )
        self.initial_bounds = (
            segments[0].bounds
            if initial_bounds is None
            else IntervalValue(float(initial_bounds), float(initial_bounds))
            if isinstance(initial_bounds, (int, float))
            else initial_bounds
        )

        self.total_duration = sum(max(0.0, s.duration) for s in self.segments)

    def is_active(self) -> bool:
        """Check whether the propagator is currently active."""
        if self.enable_cell is None:
            return True
        val = self.enable_cell.value
        if isinstance(val, (Bottom, Contradiction)):
            return False
        if isinstance(val, DiscreteDomain):
            return val.value not in (False, "off", 0, "inactive", None, "false")
        if isinstance(val, FlatValue):
            return bool(val.val)
        return True

    def set_time(self, t: float) -> None:
        """Set the time cell to a scalar timestamp."""
        self.time_cell.set_value(FlatValue(float(t)), source=self.name, overwrite=True)

    def step(self, dt: float) -> None:
        """Advance time cell by dt seconds."""
        val = self.time_cell.value
        cur_t = (
            float(val.val)
            if isinstance(val, FlatValue) and isinstance(val.val, (int, float))
            else float(val.center)
            if isinstance(val, IntervalValue)
            else 0.0
        )
        self.set_time(cur_t + max(0.0, dt))

    def _locate_segment(self, t: float) -> tuple[TrajectorySegment, IntervalValue, float]:
        """Locate active segment, previous boundary bounds, and segment start timestamp."""
        effective_t = (
            (t % self.total_duration) if (self.loop and self.total_duration > 0) else max(0.0, t)
        )

        accum = 0.0
        active_seg = self.segments[-1]
        phase_start = 0.0
        prev_bounds = self.segments[-2].bounds if len(self.segments) > 1 else self.initial_bounds

        for i, seg in enumerate(self.segments):
            dur = max(0.0, seg.duration)
            end_t = accum + dur
            if effective_t < end_t or i == len(self.segments) - 1:
                active_seg = seg
                phase_start = accum
                prev_bounds = self.initial_bounds if i == 0 else self.segments[i - 1].bounds
                break
            accum = end_t

        return active_seg, prev_bounds, phase_start

    def _interpolate_progress(self, u: float, seg: TrajectorySegment) -> float:
        """Compute transition progress factor in [0.0, 1.0]."""
        if seg.custom_eval is not None:
            try:
                res = float(seg.custom_eval(u))
                return min(1.0, max(0.0, res))
            except (ValueError, TypeError, ArithmeticError):
                pass

        match seg.transition.lower():
            case "linear":
                return u
            case "smooth" | "cosine":
                return (1.0 - math.cos(math.pi * u)) / 2.0
            case "sigmoid" | "logistic":
                k = 10.0
                s0 = 1.0 / (1.0 + math.exp(0.5 * k))
                s1 = 1.0 / (1.0 + math.exp(-0.5 * k))
                su = 1.0 / (1.0 + math.exp(-k * (u - 0.5)))
                return (su - s0) / (s1 - s0)
            case "tanh":
                k = 3.0
                t0 = math.tanh(-0.5 * k)
                t1 = math.tanh(0.5 * k)
                tu = math.tanh(k * (u - 0.5))
                return (tu - t0) / (t1 - t0)
            case "exponential" | "exp":
                k = 4.0
                denom = 1.0 - math.exp(-k)
                return (1.0 - math.exp(-k * u)) / denom if denom != 0.0 else u
            case "step":
                return 1.0
            case "hold":
                return 0.0 if u < 1.0 else 1.0
            case _:
                return u

    def evaluate_at(self, t: float) -> IntervalValue:
        """Evaluate the trajectory envelope interval bounds at timestamp t."""
        if not self.segments:
            return self.initial_bounds

        effective_t = (t % self.total_duration) if (self.loop and self.total_duration > 0) else t

        if effective_t <= 0.0:
            res = self.initial_bounds
        elif not self.loop and effective_t >= self.total_duration:
            res = self.segments[-1].bounds
        else:
            seg, prev_bounds, phase_start = self._locate_segment(effective_t)
            dur = max(seg.duration, 1e-9)
            u = min(1.0, max(0.0, (effective_t - phase_start) / dur))
            p = self._interpolate_progress(u, seg)
            cur_min = prev_bounds.min_val + p * (seg.bounds.min_val - prev_bounds.min_val)
            cur_max = prev_bounds.max_val + p * (seg.bounds.max_val - prev_bounds.max_val)
            res = IntervalValue(min_val=cur_min, max_val=cur_max)

        if self.clamp_bounds is not None:
            clamped = res.clamp(self.clamp_bounds)
            if isinstance(clamped, IntervalValue):
                res = clamped
        return res

    def segment_at(self, t: float) -> TrajectorySegment:
        """Retrieve the active segment at timestamp t."""
        effective_t = (
            (t % self.total_duration) if (self.loop and self.total_duration > 0) else max(0.0, t)
        )
        seg, _, _ = self._locate_segment(effective_t)
        return seg

    def alert(self, network: PropagatorNetwork) -> None:
        """Propagate updated envelope bounds when time or enable cells change."""
        if not self.is_active():
            if self.output_cell.value != BOTTOM:
                self.output_cell.set_value(BOTTOM, source=self.name, overwrite=True)
            if self.phase_cell is not None and self.phase_cell.value != BOTTOM:
                self.phase_cell.set_value(BOTTOM, source=self.name, overwrite=True)
            return

        t_val = self.time_cell.value
        if isinstance(t_val, (Bottom, Contradiction)):
            return

        if isinstance(t_val, FlatValue) and isinstance(t_val.val, (int, float)):
            t = float(t_val.val)
            bounds = self.evaluate_at(t)
            seg = self.segment_at(t)
        elif isinstance(t_val, GaussianValue):
            t = float(t_val.mean)
            bounds = self.evaluate_at(t)
            seg = self.segment_at(t)
        elif isinstance(t_val, IntervalValue):
            b1 = self.evaluate_at(t_val.min_val)
            b2 = self.evaluate_at(t_val.max_val)
            bounds = IntervalValue(min(b1.min_val, b2.min_val), max(b1.max_val, b2.max_val))
            seg = self.segment_at(t_val.max_val)
        else:
            return

        params = {"segment": seg.name or "active"}
        self.emit(self.output_cell, bounds, overwrite=True, parameters=params)
        if self.phase_cell is not None and seg.name:
            self.emit(
                self.phase_cell,
                DiscreteDomain.single(seg.name),
                overwrite=True,
                parameters=params,
            )


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
        confidence: float = 1.0,
        is_assumption: bool = False,
    ) -> None:
        super().__init__(
            name,
            [measurement_cell],
            [output_state_cell, output_rate_cell],
            confidence=confidence,
            is_assumption=is_assumption,
        )
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
        self.emit(
            self.output_state_cell,
            GaussianValue(mean=self.x, variance=self.p00),
            overwrite=True,
        )
        self.emit(
            self.output_rate_cell,
            GaussianValue(mean=self.v, variance=self.p11),
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
        inputs: Sequence[Cell],
        output: Cell,
        conflict_cell: Cell | None = None,
        conflict_threshold: float = 0.95,
        confidence: float = 1.0,
        is_assumption: bool = False,
    ) -> None:
        out_cells = [output] if conflict_cell is None else [output, conflict_cell]
        super().__init__(
            name,
            inputs=inputs,
            outputs=out_cells,
            confidence=confidence,
            is_assumption=is_assumption,
        )
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
                self.emit(self.output_cell, val)
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
            self.emit(
                self.conflict_cell,
                FlatValue(round(max_conflict, 4)),
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

        self.emit(self.output_cell, current, overwrite=True)


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
        confidence: float = 1.0,
        is_assumption: bool = False,
    ) -> None:
        super().__init__(
            name,
            [signal_cell],
            [output_cell],
            confidence=confidence,
            is_assumption=is_assumption,
        )
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

        self.emit(
            self.output_cell,
            GaussianValue(mean=clamped, variance=0.04),
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
        confidence: float = 1.0,
        is_assumption: bool = False,
    ) -> None:
        super().__init__(
            name,
            [input_cell],
            [output_bool_cell],
            confidence=confidence,
            is_assumption=is_assumption,
        )
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
        # 1.0 = True, 0.0 = False in numeric interval
        self.emit(
            self.output_bool,
            IntervalValue(
                min_val=1.0 if is_triggered else 0.0, max_val=1.0 if is_triggered else 0.0
            ),
            overwrite=True,
            parameters={"threshold": self.threshold, "below": self.below},
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

    def __init__(
        self,
        name: str,
        cells: Sequence[Cell],
        confidence: float = 1.0,
        is_assumption: bool = False,
    ) -> None:
        cells_list = list(cells)
        super().__init__(
            name,
            cells_list,
            cells_list,
            confidence=confidence,
            is_assumption=is_assumption,
        )
        self.cells = cells_list

    def _collect_determined(self) -> Mapping[Any, Cell] | None:
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

            for v, source_cell in determined.items():
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


class AllDistinctPropagator(Propagator):
    """Enforces Generalized Arc Consistency (GAC) over DiscreteDomain cells via maximum bipartite matching.

    Implements Régin's filtering algorithm for difference constraints (Régin 1994,
    equivalent to Prolog CLP(Z) `all_distinct/1`):
    1. Maximum Bipartite Matching: Matches variables (cells) to candidate values.
       If any cell cannot be matched, detects a Hall Marriage Theorem violation
       and immediately signals Contradiction (⊤).
    2. Strongly Connected Components (SCC) & Alternating Paths: Finds all edges
       participating in at least one maximum matching via Tarjan's SCC and BFS
       from unmatched values.
    3. Global Pruning (Naked Tuples): Automatically eliminates naked pairs, triples,
       and k-tuples from non-participating peer cells prior to search branching,
       substantially shrinking search tree depth compared to pairwise `AllDifferentPropagator`.

    Theoretical Foundation:
        - Régin, J.-C. (1994). "A filtering algorithm for constraints of difference in CSPs",
          AAAI-94, pp. 362-367. https://cdn.aaai.org/AAAI/1994/AAAI94-055.pdf
        - Triska, M. (2012). "The Boolean Constraint Solver of SWI-Prolog / CLP(FD) & CLP(Z)".
    """

    def __init__(
        self,
        name: str,
        cells: Sequence[Cell],
        confidence: float = 1.0,
        is_assumption: bool = False,
    ) -> None:
        cells_list = list(cells)
        super().__init__(
            name,
            cells_list,
            cells_list,
            confidence=confidence,
            is_assumption=is_assumption,
        )
        self.cells = cells_list

    def alert(self, network: PropagatorNetwork) -> None:
        """Filter domains using Régin's GAC bipartite matching algorithm."""
        domains: dict[Cell, frozenset[Any]] = {}
        for c in self.cells:
            val = c.value
            if isinstance(val, Contradiction):
                return
            if isinstance(val, DiscreteDomain):
                if not val.candidates:
                    c.set_value(
                        Contradiction(reason=f"Exhausted domain in {self.name}"),
                        source=self.name,
                    )
                    return
                domains[c] = val.candidates
            elif isinstance(val, FlatValue):
                domains[c] = frozenset([val.val])
            elif isinstance(val, Bottom):
                return

        # Check duplicate determined values early
        determined: dict[Any, Cell] = {}
        for c, cands in domains.items():
            if len(cands) == 1:
                v = next(iter(cands))
                if v in determined:
                    c.set_value(
                        Contradiction(
                            reason=f"Duplicate value {v} in {self.name} between {determined[v].cell_id} and {c.cell_id}",
                            conflicting_values=(determined[v].value, c.value),
                        ),
                        source=self.name,
                    )
                    return
                determined[v] = c

        # Maximum Bipartite Matching (Augmenting Paths)
        cell_nodes = list(domains.keys())
        match_left: dict[Cell, Any] = {}
        match_right: dict[Any, Cell] = {}

        def dfs(curr: Cell, visited: set[Any]) -> bool:
            for v in domains[curr]:
                if v not in visited:
                    visited.add(v)
                    if v not in match_right or dfs(match_right[v], visited):
                        match_left[curr] = v
                        match_right[v] = curr
                        return True
            return False

        for u in cell_nodes:
            visited: set[Any] = set()
            if not dfs(u, visited):
                # Hall's condition violated: cannot match all variables
                u.set_value(
                    Contradiction(
                        reason=f"AllDistinct Hall condition violation in {self.name}: {len(cell_nodes)} cells cannot be assigned to distinct candidates",
                    ),
                    source=self.name,
                )
                return

        # Build directed graph DG for alternating cycles and paths
        all_values: set[Any] = set()
        for d in domains.values():
            all_values.update(d)

        adj: dict[Any, list[Any]] = {c: [] for c in cell_nodes}
        for v in all_values:
            adj[v] = []

        for c in cell_nodes:
            mv = match_left[c]
            adj[c].append(mv)
            for v in domains[c]:
                if v != mv:
                    adj[v].append(c)

        # Reachability from unmatched / free values (alternating paths)
        free_values = [v for v in all_values if v not in match_right]
        reachable_from_free: set[Any] = set(free_values)
        queue = list(free_values)
        while queue:
            curr = queue.pop(0)
            for neighbor in adj.get(curr, []):
                if neighbor not in reachable_from_free:
                    reachable_from_free.add(neighbor)
                    queue.append(neighbor)

        # Tarjan's Strongly Connected Components (alternating cycles)
        idx = 0
        indices: dict[Any, int] = {}
        lowlink: dict[Any, int] = {}
        on_stack: set[Any] = set()
        stack: list[Any] = []
        scc: dict[Any, int] = {}
        scc_count = 0

        def strongconnect(node: Any) -> None:
            nonlocal idx, scc_count
            indices[node] = idx
            lowlink[node] = idx
            idx += 1
            stack.append(node)
            on_stack.add(node)

            for w in adj.get(node, []):
                if w not in indices:
                    strongconnect(w)
                    lowlink[node] = min(lowlink[node], lowlink[w])
                elif w in on_stack:
                    lowlink[node] = min(lowlink[node], indices[w])

            if lowlink[node] == indices[node]:
                while True:
                    w = stack.pop()
                    on_stack.remove(w)
                    scc[w] = scc_count
                    if w == node:
                        break
                scc_count += 1

        for n in list(adj.keys()):
            if n not in indices:
                strongconnect(n)

        # Prune unsupported domain values
        for c in cell_nodes:
            curr_cands = domains[c]
            if len(curr_cands) <= 1:
                continue
            mv = match_left[c]
            valid_cands = set()
            for v in curr_cands:
                if (
                    v == mv
                    or (c in reachable_from_free and v in reachable_from_free)
                    or scc.get(c) == scc.get(v)
                ):
                    valid_cands.add(v)

            if len(valid_cands) < len(curr_cands):
                if not valid_cands:
                    c.set_value(
                        Contradiction(
                            reason=f"Exhausted domain during AllDistinct filtering in {self.name}"
                        ),
                        source=self.name,
                    )
                    return
                c.set_value(
                    DiscreteDomain(candidates=frozenset(valid_cands)),
                    source=self.name,
                )


class AllDistinctPropagator(Propagator):
    """Enforces Generalized Arc Consistency (GAC) over DiscreteDomain cells via maximum bipartite matching.

    Implements Régin's filtering algorithm for difference constraints (Régin 1994,
    equivalent to Prolog CLP(Z) `all_distinct/1`):
    1. Maximum Bipartite Matching: Matches variables (cells) to candidate values.
       If any cell cannot be matched, detects a Hall Marriage Theorem violation
       and immediately signals Contradiction (⊤).
    2. Strongly Connected Components (SCC) & Alternating Paths: Finds all edges
       participating in at least one maximum matching via Tarjan's SCC and BFS
       from unmatched values.
    3. Global Pruning (Naked Tuples): Automatically eliminates naked pairs, triples,
       and k-tuples from non-participating peer cells prior to search branching,
       substantially shrinking search tree depth compared to pairwise `AllDifferentPropagator`.

    Theoretical Foundation:
        - Régin, J.-C. (1994). "A filtering algorithm for constraints of difference in CSPs",
          AAAI-94, pp. 362-367. https://cdn.aaai.org/AAAI/1994/AAAI94-055.pdf
        - Triska, M. (2012). "The Boolean Constraint Solver of SWI-Prolog / CLP(FD) & CLP(Z)".
    """

    def __init__(
        self,
        name: str,
        cells: Sequence[Cell],
        confidence: float = 1.0,
        is_assumption: bool = False,
    ) -> None:
        cells_list = list(cells)
        super().__init__(
            name,
            cells_list,
            cells_list,
            confidence=confidence,
            is_assumption=is_assumption,
        )
        self.cells = cells_list

    def alert(self, network: PropagatorNetwork) -> None:
        """Filter domains using Régin's GAC bipartite matching algorithm."""
        domains: dict[Cell, frozenset[Any]] = {}
        for c in self.cells:
            val = c.value
            if isinstance(val, Contradiction):
                return
            if isinstance(val, DiscreteDomain):
                if not val.candidates:
                    c.set_value(
                        Contradiction(reason=f"Exhausted domain in {self.name}"),
                        source=self.name,
                    )
                    return
                domains[c] = val.candidates
            elif isinstance(val, FlatValue):
                domains[c] = frozenset([val.val])
            elif isinstance(val, Bottom):
                return

        # Check duplicate determined values early
        determined: dict[Any, Cell] = {}
        for c, cands in domains.items():
            if len(cands) == 1:
                v = next(iter(cands))
                if v in determined:
                    c.set_value(
                        Contradiction(
                            reason=f"Duplicate value {v} in {self.name} between {determined[v].cell_id} and {c.cell_id}",
                            conflicting_values=(determined[v].value, c.value),
                        ),
                        source=self.name,
                    )
                    return
                determined[v] = c

        # Maximum Bipartite Matching (Augmenting Paths)
        cell_nodes = list(domains.keys())
        match_left: dict[Cell, Any] = {}
        match_right: dict[Any, Cell] = {}

        def dfs(curr: Cell, visited: set[Any]) -> bool:
            for v in domains[curr]:
                if v not in visited:
                    visited.add(v)
                    if v not in match_right or dfs(match_right[v], visited):
                        match_left[curr] = v
                        match_right[v] = curr
                        return True
            return False

        for u in cell_nodes:
            visited: set[Any] = set()
            if not dfs(u, visited):
                # Hall's condition violated: cannot match all variables
                u.set_value(
                    Contradiction(
                        reason=f"AllDistinct Hall condition violation in {self.name}: {len(cell_nodes)} cells cannot be assigned to distinct candidates",
                    ),
                    source=self.name,
                )
                return

        # Build directed graph DG for alternating cycles and paths
        all_values: set[Any] = set()
        for d in domains.values():
            all_values.update(d)

        adj: dict[Any, list[Any]] = {c: [] for c in cell_nodes}
        for v in all_values:
            adj[v] = []

        for c in cell_nodes:
            mv = match_left[c]
            adj[c].append(mv)
            for v in domains[c]:
                if v != mv:
                    adj[v].append(c)

        # Reachability from unmatched / free values (alternating paths)
        free_values = [v for v in all_values if v not in match_right]
        reachable_from_free: set[Any] = set(free_values)
        queue = list(free_values)
        while queue:
            curr = queue.pop(0)
            for neighbor in adj.get(curr, []):
                if neighbor not in reachable_from_free:
                    reachable_from_free.add(neighbor)
                    queue.append(neighbor)

        # Tarjan's Strongly Connected Components (alternating cycles)
        idx = 0
        indices: dict[Any, int] = {}
        lowlink: dict[Any, int] = {}
        on_stack: set[Any] = set()
        stack: list[Any] = []
        scc: dict[Any, int] = {}
        scc_count = 0

        def strongconnect(node: Any) -> None:
            nonlocal idx, scc_count
            indices[node] = idx
            lowlink[node] = idx
            idx += 1
            stack.append(node)
            on_stack.add(node)

            for w in adj.get(node, []):
                if w not in indices:
                    strongconnect(w)
                    lowlink[node] = min(lowlink[node], lowlink[w])
                elif w in on_stack:
                    lowlink[node] = min(lowlink[node], indices[w])

            if lowlink[node] == indices[node]:
                while True:
                    w = stack.pop()
                    on_stack.remove(w)
                    scc[w] = scc_count
                    if w == node:
                        break
                scc_count += 1

        for n in list(adj.keys()):
            if n not in indices:
                strongconnect(n)

        # Prune unsupported domain values
        for c in cell_nodes:
            curr_cands = domains[c]
            if len(curr_cands) <= 1:
                continue
            mv = match_left[c]
            valid_cands = set()
            for v in curr_cands:
                if (
                    v == mv
                    or (c in reachable_from_free and v in reachable_from_free)
                    or scc.get(c) == scc.get(v)
                ):
                    valid_cands.add(v)

            if len(valid_cands) < len(curr_cands):
                if not valid_cands:
                    c.set_value(
                        Contradiction(reason=f"Exhausted domain during AllDistinct filtering in {self.name}"),
                        source=self.name,
                    )
                    return
                c.set_value(
                    DiscreteDomain(candidates=frozenset(valid_cands)),
                    source=self.name,
                )


class PropagatorNetwork:
    """Orchestrates cells and propagators, driving the network to fixed-point quiescence."""

    def __init__(self, name: str = "Network") -> None:
        self.name = name
        self.cells: dict[str, Cell] = {}
        self.propagators: list[Propagator] = []
        self._queue: deque[Propagator] = deque()
        self._sources_log: dict[str, list[str]] = {}
        self.tms: Any = None

    @property
    def network(self) -> PropagatorNetwork:
        """Self-reference to network for uniform duck-typing with Cell.network."""
        return self

    def __getattr__(self, name: str) -> Cell:
        """Retrieve or dynamically create a cell from the network by attribute name."""
        if (
            name.startswith("_")
            or name in {"name", "cells", "propagators", "tms"}
            or hasattr(type(self), name)
        ):
            raise AttributeError(name)
        cells = self.__dict__.get("cells")
        if cells is not None:
            if name in cells:
                return cells[name]
            return self.add_cell(name)
        raise AttributeError(f"Network {self.name!r} has no cell or attribute {name!r}")

    def __setattr__(self, name: str, value: Any) -> None:
        """Assign a cell or value to the network as a named cell."""
        if (
            name.startswith("_")
            or name in {"name", "cells", "propagators", "tms"}
            or hasattr(type(self), name)
        ):
            super().__setattr__(name, value)
            return

        if isinstance(value, Cell):
            if name in self.cells:
                self.cells[name].unify(value)
            else:
                c = self.add_cell(name)
                c.unify(value)
            return

        cell = self.add_cell(name)
        cell.set_value(value, overwrite=True)

    def __getitem__(self, key: str) -> Cell:
        """Access a cell by dictionary key."""
        if key in self.cells:
            return self.cells[key]
        raise KeyError(f"Cell {key!r} not found in network {self.name!r}")

    def __setitem__(self, key: str, value: Any) -> None:
        """Assign a cell or value by dictionary key."""
        setattr(self, key, value)

    def __delitem__(self, key: str) -> None:
        """Remove a cell from the network dictionary."""
        if key in self.cells:
            del self.cells[key]
        else:
            raise KeyError(f"Cell {key!r} not found in network {self.name!r}")

    def __contains__(self, key: str) -> bool:
        """Check if a cell exists in the network."""
        return key in self.cells

    def __iter__(self) -> Iterator[Cell]:
        """Iterate over all cells in the network."""
        return iter(self.cells.values())

    def __len__(self) -> int:
        """Return the count of cells registered in the network."""
        return len(self.cells)

    def add_cell(
        self,
        cell_id: str,
        initial_value: Any = BOTTOM,
        unit: str = "",
        display_name: str | None = None,
    ) -> Cell:
        """Create or register a cell in this network."""
        if cell_id in self.cells:
            return self.cells[cell_id]
        coerced = (
            initial_value
            if isinstance(initial_value, LatticeValue)
            else coerce_to_lattice_value(initial_value)
        )
        cell = Cell(
            cell_id=cell_id,
            value=coerced,
            network=self,
            unit=unit,
            display_name=display_name,
        )
        self.cells[cell_id] = cell
        if getattr(self, "tms", None) is not None:
            self.tms.get_or_create_cell_tms(cell_id)
        return cell

    def add_propagator(self, propagator: Propagator) -> None:
        """Register a propagator in this network."""
        if propagator not in self.propagators:
            self.propagators.append(propagator)
        for c in propagator.inputs + propagator.outputs:
            if c.network is None:
                c.network = self
            if c.cell_id not in self.cells:
                self.cells[c.cell_id] = c
        # Trigger initial run
        if propagator not in self._queue:
            self._queue.append(propagator)

    def remove_propagator(self, propagator: Propagator) -> None:
        """Unregister and remove a propagator from this network and its connected cells.

        Unhooks the propagator from input and output cell listener lists, removes it
        from the active worklist queue, and retracts any premises asserted by this
        propagator on its output cells.

        Args:
            propagator: The Propagator instance to remove.
        """
        if propagator in self.propagators:
            self.propagators.remove(propagator)
        while propagator in self._queue:
            self._queue.remove(propagator)

        for c in propagator.inputs + propagator.outputs:
            c.remove_propagator(propagator)

        for out_cell in propagator.outputs:
            out_cell.retract_source(propagator.name)

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
        translator: Translator | None = None,
    ) -> str:
        """Explain the state and causal provenance of a network cell."""
        if cell_id not in self.cells:
            raise KeyError(f"Cell '{cell_id}' not found in network.")
        return self.cells[cell_id].explain(unit=unit, depth=depth, translator=translator)

    def explain_node(
        self,
        cell_id: str,
        unit: str | None = None,
        depth: int | None = None,
    ) -> ExplanationNode:
        """Generate a structured explanation node for a network cell."""
        if cell_id not in self.cells:
            raise KeyError(f"Cell '{cell_id}' not found in network.")
        return self.cells[cell_id].explain_node(unit=unit, depth=depth)

    def to_graph(
        self,
        include_isolated: bool = True,
        group_aliases: bool = True,
    ) -> NetworkGraph:
        """Convert this network into an intermediate NetworkGraph representation.

        Args:
            include_isolated: Whether to include cells not attached to any propagators.
            group_aliases: Whether to group unified cells into alias clusters.

        Returns:
            NetworkGraph instance.
        """
        from .graph import NetworkGraph

        return NetworkGraph.from_network(
            self,
            include_isolated=include_isolated,
            group_aliases=group_aliases,
        )

    def walk_downstream(
        self,
        start: Cell | Sequence[Cell] | None = None,
        max_depth: int | None = None,
    ) -> Iterator[Cell | Propagator]:
        """Traverse downstream from starting cells through observed propagators and consequences.

        Args:
            start: Starting cell(s). If None, all network cells are candidates.
            max_depth: Maximum traversal depth.

        Returns:
            Iterator over cells and propagators in breadth-first causal order.
        """
        from .graph import walk_downstream

        return walk_downstream(self, start=start, max_depth=max_depth)

    def walk_upstream(
        self,
        target: Cell | Sequence[Cell] | None = None,
        max_depth: int | None = None,
    ) -> Iterator[Cell | Propagator]:
        """Traverse upstream from target cells back to governing propagators and antecedent cells.

        Args:
            target: Target cell(s). If None, all network cells are candidates.
            max_depth: Maximum traversal depth.

        Returns:
            Iterator over cells and propagators in upstream causal order.
        """
        from .graph import walk_upstream

        return walk_upstream(self, target=target, max_depth=max_depth)

    def detect_cycles(self) -> list[list[str]]:
        """Detect feedback loops and cyclic dependencies in the network.

        Returns:
            List of detected elementary cycles.
        """
        from .graph import detect_cycles

        return detect_cycles(self)

    def generate_mermaid(
        self,
        orientation: str = "LR",
        include_values: bool = True,
        group_aliases: bool = True,
        style_states: bool = True,
    ) -> str:
        """Generate a Mermaid diagram representing the network structure and state.

        Args:
            orientation: Flow direction ('LR', 'TD', 'RL', 'BT').
            include_values: Whether to include formatted lattice values in cell labels.
            group_aliases: Whether to render subgraphs for alias clusters.
            style_states: Whether to attach semantic CSS classes.

        Returns:
            Formatted Mermaid markdown block.
        """
        return self.to_graph(group_aliases=group_aliases).to_mermaid(
            orientation=orientation,
            include_values=include_values,
            group_aliases=group_aliases,
            style_states=style_states,
        )

    def generate_dot(
        self,
        rankdir: str = "LR",
        include_values: bool = True,
        group_aliases: bool = True,
    ) -> str:
        """Generate a Graphviz DOT representation of the network.

        Args:
            rankdir: Rank direction ('LR', 'TB', 'RL', 'BT').
            include_values: Whether to include formatted lattice values in cell labels.
            group_aliases: Whether to render subgraphs for alias clusters.

        Returns:
            DOT specification string.
        """
        return self.to_graph(group_aliases=group_aliases).to_dot(
            rankdir=rankdir,
            include_values=include_values,
            group_aliases=group_aliases,
        )

    @contextmanager
    def assume(
        self,
        assumption_id: str,
        cell: str | Cell | None = None,
        value: Any = None,
        confidence: float = 1.0,
    ) -> Iterator[str]:
        """Scoped defeasible assumption context manager.

        If cell and value are provided, asserts the assumption into that cell.
        Upon exiting the context, the assumption (and any premises supported by it)
        is automatically retracted from the network, and the network re-propagates.

        Args:
            assumption_id: Unique identifier for the assumption premise.
            cell: Optional cell name or Cell instance to assert the assumption into.
            value: Optional value for the cell (coerced if primitive).
            confidence: Subjective confidence measure in (0.0, 1.0].

        Yields:
            The assumption identifier.
        """
        tms = getattr(self, "tms", None)
        if tms is None:
            from .tms import NetworkTMS

            tms = NetworkTMS(self)
            self.tms = tms

        if cell is not None and value is not None:
            cid = cell.cell_id if isinstance(cell, Cell) else cell
            coerced_val = (
                value if isinstance(value, LatticeValue) else coerce_to_lattice_value(value)
            )
            tms.assume(
                cell_id=cid,
                assumption_id=assumption_id,
                value=coerced_val,
                confidence=confidence,
            )
        else:
            from .tms import Assumption

            tms.assumptions[assumption_id] = Assumption(
                source_id=assumption_id,
                value=BOTTOM,
                confidence=confidence,
            )

        try:
            yield assumption_id
        finally:
            tms.retract(assumption_id, reason="Exited hypothetical scope")
            self.run()

    def relation(
        self,
        inputs: Sequence[str | Cell],
        outputs: Sequence[str | Cell],
        name: str | None = None,
        confidence: float = 1.0,
    ) -> Callable[[Callable[..., Any]], FunctionalRelation]:
        """Decorator to define and attach a functional relation constraint."""

        def decorator(fn: Callable[..., Any]) -> FunctionalRelation:
            rel = FunctionalRelation(
                fn, inputs=inputs, outputs=outputs, name=name, confidence=confidence
            )
            rel.attach(self)
            return rel

        return decorator


class ChoiceEngine:
    """Interleaves monotonic lattice propagation with speculative branching and backtracking.

    When constraint propagation reaches quiescence and discrete domain cells remain
    undetermined (multiple candidates), ChoiceEngine uses the MRV (Minimum Remaining Values)
    heuristic to select a choice point, branches on candidates, runs propagation to a fixed
    point, and backtracks upon encountering a Contradiction.
    """

    def __init__(
        self,
        network: PropagatorNetwork,
        variables: Sequence[Cell] | None = None,
        max_depth: int = 100,
    ) -> None:
        self.network = network
        self.variables = list(variables) if variables is not None else None
        self.max_depth = max_depth

    def is_solved(self) -> bool:
        """Check if all cells in the network are non-bottom, determined, and contradiction-free."""
        cells = self.variables if self.variables is not None else self.network.cells.values()
        for cell in cells:
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
        cells = self.variables if self.variables is not None else self.network.cells.values()
        for cell in cells:
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
            self.network._queue.clear()
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
        self.network._queue.clear()
        for cid, val in saved_state.items():
            self.network.cells[cid].value = val
        return False


class CellDescriptor:
    """Descriptor for declaring reactive cells on a PropagatorModel class."""

    def __init__(
        self,
        default: Any = BOTTOM,
        unit: str = "",
        display_name: str | None = None,
    ) -> None:
        self.default = default
        self.unit = unit
        self.display_name = display_name
        self.name: str = ""

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name

    def __get__(self, instance: Any, owner: type) -> Cell | CellDescriptor:
        if instance is None:
            return self
        if self.name not in instance.cells:
            init_val = (
                self.default
                if isinstance(self.default, LatticeValue)
                else coerce_to_lattice_value(self.default)
            )
            cell = instance.add_cell(
                self.name,
                initial_value=init_val,
                unit=self.unit,
                display_name=self.display_name or self.name,
            )
            return cell
        return instance.cells[self.name]

    def __set__(self, instance: Any, value: Any) -> None:
        if isinstance(value, Cell):
            if self.name in instance.cells:
                instance.cells[self.name].unify(value)
            else:
                cell = instance.add_cell(
                    self.name,
                    unit=self.unit,
                    display_name=self.display_name or self.name,
                )
                cell.unify(value)
        else:
            cell = self.__get__(instance, type(instance))
            cell.set_value(value, overwrite=True)


class PropagatorModel(PropagatorNetwork):
    """Declarative component base class for class-based propagator networks."""

    def __init__(self, name: str | None = None) -> None:
        super().__init__(name=name or self.__class__.__name__)
        for cls in reversed(self.__class__.__mro__):
            for attr, val in cls.__dict__.items():
                if isinstance(val, CellDescriptor):
                    getattr(self, attr)
        self.setup()

    def setup(self) -> None:
        """Lifecycle hook for wiring internal constraints and sub-models."""
