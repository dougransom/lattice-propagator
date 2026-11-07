"""Degenerate computation, multi-pathway redundancy, and fault-tolerant estimation.

Theoretical Foundations:
Degeneracy in the sense of Gerald Jay Sussman (and *Software Design for Flexibility*,
MIT Press, 2021) and biological systems (Edelman & Gally, 2001) refers to structurally
different components performing the same function or calculating the same quantity.

Unlike simple duplication/redundancy, degenerate computation combines heterogeneous
sources of information (e.g. direct sensory measurement, physical dynamic models, and
heuristic schedules) into a single target Cell over join-semilattices, governed by a
Truth Maintenance System (TMS) with automatic degraded-mode fallback and conflict recovery.

Classes:
- `DegenerateBranch`: Representation of an individual computational or sensory pathway.
- `DegeneratePipeline`: Multi-pathway propagator with monotonic consensus and tiered fallback.
- `add_degenerate_pipeline`: Declarative helper function for attaching degenerate pipelines.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from .lattice import (
    Bottom,
    Contradiction,
    GaussianValue,
    IntervalValue,
)
from .primitives import (
    Cell,
    Propagator,
    PropagatorNetwork,
)


@dataclass(frozen=True)
class DegenerateBranch:
    """A distinct computational or sensory pathway contributing to a degenerate cell.

    Attributes:
        name: Human-readable name of this branch (e.g., 'direct_sensor', 'thermal_rc_model').
        cell: Source `Cell` producing this pathway's estimate or measurement.
        priority: Defeasible confidence weighting in (0.0, 1.0]. Higher priority indicates
            higher fidelity or trustworthiness during conflict resolution.
        assumption_id: Unique TMS assumption ID tagging this branch's contribution.
        description: Informative description of the physical or mathematical principle used.
    """

    name: str
    cell: Cell
    priority: float = 1.0
    assumption_id: str = ""
    description: str = ""

    def __post_init__(self) -> None:
        if not self.assumption_id:
            object.__setattr__(self, "assumption_id", f"branch_{self.name}")


class DegeneratePipeline(Propagator):
    """Monotonic multi-pathway degenerate computation propagator.

    Coordinates multiple heterogeneous computational branches feeding into a single
    target `Cell`. Operates in two distinct modes:

    1. `"consensus"` (default): Monotonically fuses all active, consistent branches
       via semilattice join ($\\sqcup$). In the event of physical contradiction
       ($\\top$), the Truth Maintenance System identifies the conflicting assumptions
       and automatically retracts the lowest-priority (least confident) culprit,
       gracefully transitioning the system into a degraded operational state.
    2. `"tiered"`: Priority-driven strict fallback. Actively routes the highest-priority
       healthy branch into the target cell, seamlessly switching to auxiliary or
       heuristic fallback tiers if the primary branch fails or is retracted.

    Attributes:
        target: Target `Cell` receiving the fused or selected estimation.
        branches: Sequence of `DegenerateBranch` computational pathways.
        mode: Coordination mode (`"consensus"` or `"tiered"`).
    """

    def __init__(
        self,
        name: str,
        target: Cell,
        branches: Sequence[DegenerateBranch],
        mode: str = "consensus",
    ) -> None:
        """Initialize the degenerate pipeline propagator.

        Args:
            name: Identifier for this propagator.
            target: Output cell receiving the synthesized value.
            branches: Ordered collection of degenerate computation branches.
            mode: Coordination strategy (`'consensus'` or `'tiered'`).
        """
        self.target = target
        self.branches: list[DegenerateBranch] = list(branches)
        self.mode = mode

        inputs = [b.cell for b in self.branches]
        outputs = [self.target]
        super().__init__(name, inputs, outputs)

    @property
    def primary_branch(self) -> DegenerateBranch | None:
        """The highest-priority branch in the pipeline."""
        if not self.branches:
            return None
        return max(self.branches, key=lambda b: b.priority)

    @property
    def active_branches(self) -> list[DegenerateBranch]:
        """List of branches currently active and providing non-bottom evidence."""
        tms = self.target.get_or_create_tms()
        active: list[DegenerateBranch] = []
        for b in self.branches:
            prem = tms.premises.get(b.assumption_id)
            is_active = prem.is_active if prem is not None else True
            if is_active and not isinstance(b.cell.value, Bottom):
                active.append(b)
        return active

    @property
    def is_degraded(self) -> bool:
        """True if any configured branch is retracted, offline, or contradictory while others remain active."""
        if not self.active_branches:
            return False

        # Any branch that has non-bottom input but is retracted or contradictory
        for b in self.branches:
            if isinstance(b.cell.value, Bottom):
                continue
            if b not in self.active_branches or isinstance(b.cell.value, Contradiction):
                return True

        prim = self.primary_branch
        return bool(prim is not None and prim not in self.active_branches)

    @property
    def status(self) -> str:
        """Current operational status ('consensus', 'degraded', 'contradiction', 'idle')."""
        if isinstance(self.target.value, Contradiction):
            return "contradiction"
        if not self.active_branches:
            return "idle"
        if self.is_degraded:
            return "degraded"
        return "consensus"

    @property
    def consensus_spread(self) -> float | None:
        """Compute numerical spread/discrepancy across active branches (or None if N/A)."""
        active_vals: list[float] = []
        for b in self.active_branches:
            val = b.cell.value
            if isinstance(val, IntervalValue):
                active_vals.extend([val.min_val, val.max_val])
            elif isinstance(val, GaussianValue):
                active_vals.append(val.mean)
            elif hasattr(val, "val") and isinstance(val.val, (int, float)):
                active_vals.append(float(val.val))

        if len(active_vals) < 2:
            return None
        return max(active_vals) - min(active_vals)

    def retract_branch(self, branch_name: str, reason: str = "fault_detected") -> bool:
        """Explicitly retract a branch via TMS, forcing the pipeline to degrade or re-fuse.

        Args:
            branch_name: Name of branch to retract.
            reason: Diagnostic explanation for retraction.

        Returns:
            True if branch was found and retracted.
        """
        for b in self.branches:
            if b.name == branch_name:
                tms = self.target.get_or_create_tms()
                tms.retract_evidence(b.assumption_id, reason=reason)
                # If network TMS exists, update network assumptions
                if tms.network_tms is not None:
                    tms.network_tms.retract(b.assumption_id, reason=reason)
                self.target.set_value(tms.compute_fused_value(), overwrite=True)
                if self.target.network is not None:
                    self.target.network.add_propagator(self)
                return True
        return False

    def restore_branch(self, branch_name: str) -> bool:
        """Restore a previously retracted branch in TMS and re-propagate.

        Args:
            branch_name: Name of branch to restore.

        Returns:
            True if branch was found and restored.
        """
        for b in self.branches:
            if b.name == branch_name:
                tms = self.target.get_or_create_tms()
                prem = tms.premises.get(b.assumption_id)
                if prem is not None:
                    prem.is_active = True
                    prem.status_reason = "restored"
                if tms.network_tms is not None and b.assumption_id in tms.network_tms.assumptions:
                    tms.network_tms.assumptions[b.assumption_id].is_active = True
                    tms.network_tms.assumptions[b.assumption_id].status_reason = "restored"
                self.target.set_value(tms.compute_fused_value(), overwrite=True)
                if self.target.network is not None:
                    self.target.network.add_propagator(self)
                return True
        return False

    def resolve_conflict(self) -> str | None:
        """Attempt to resolve a target contradiction using Dependency-Directed Backtracking.

        Returns:
            Name of retracted assumption if resolved, or None.
        """
        tms = self.target.get_or_create_tms()
        if tms.network_tms is not None and isinstance(self.target.value, Contradiction):
            culprit = tms.network_tms.resolve_contradiction(tms.active_sources)
            if culprit is not None and self.target.network is not None:
                self.target.network.run()
            return culprit
        return None

    def diagnostics(self) -> dict[str, Any]:
        """Produce structured diagnostic metrics for monitoring and health reporting."""
        return {
            "status": self.status,
            "mode": self.mode,
            "is_degraded": self.is_degraded,
            "primary_branch": self.primary_branch.name if self.primary_branch else None,
            "active_branches": [b.name for b in self.active_branches],
            "consensus_spread": self.consensus_spread,
            "target_value": str(self.target.value),
        }

    def alert(self, network: PropagatorNetwork | None = None) -> None:
        """Reactive callback triggered when any input branch cell updates."""
        self.step()

    def step(self) -> None:
        """Execute degenerate computation across pathways."""
        tms = self.target.get_or_create_tms()

        if self.mode == "consensus":
            # In consensus mode, all active, healthy branches assert evidence into target's TMS
            for b in self.branches:
                # If this branch was explicitly retracted, do not re-assert unless restored
                prem = tms.premises.get(b.assumption_id)
                if prem is not None and not prem.is_active:
                    continue

                val = b.cell.value
                if isinstance(val, Bottom):
                    continue

                self.emit(
                    self.target,
                    val,
                    source=b.assumption_id,
                    confidence_scale=b.priority,
                    force_assumption=True,
                    recompute_tms=True,
                    antecedents=[b.cell],
                )
            return

        if self.mode == "tiered":
            # In tiered mode, route the highest-priority healthy, non-bottom branch
            sorted_branches = sorted(self.branches, key=lambda b: b.priority, reverse=True)
            for b in sorted_branches:
                prem = tms.premises.get(b.assumption_id)
                if prem is not None and not prem.is_active:
                    continue

                val = b.cell.value
                if isinstance(val, (Bottom, Contradiction)):
                    continue

                # Emit selected tier
                self.emit(
                    self.target,
                    val,
                    source=b.assumption_id,
                    confidence_scale=b.priority,
                    force_assumption=True,
                    recompute_tms=True,
                    antecedents=[b.cell],
                )
                return


# --- Declarative Helper Builders ---


def add_degenerate_pipeline(
    network: PropagatorNetwork,
    target: Cell,
    branches: Sequence[DegenerateBranch],
    name: str | None = None,
    mode: str = "consensus",
) -> DegeneratePipeline:
    """Attach a degenerate computational pipeline constraint to the network.

    Args:
        network: PropagatorNetwork hosting the computation.
        target: Cell receiving the fused or tiered estimation.
        branches: Sequence of `DegenerateBranch` computational pathways.
        name: Optional unique propagator name (defaults to 'degenerate_{target.cell_id}').
        mode: Coordination strategy ('consensus' or 'tiered').

    Returns:
        The instantiated and attached `DegeneratePipeline`.
    """
    prop_name = name or f"degenerate_{target.cell_id}"
    pipeline = DegeneratePipeline(prop_name, target, branches, mode=mode)
    network.add_propagator(pipeline)
    return pipeline
