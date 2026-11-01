"""Truth Maintenance System (TMS) and Provenance Tracking for the Propagator Engine.

Based on dependency-directed provenance and belief revision literature:
- Doyle, J. (1979). "A Truth Maintenance System", Artificial Intelligence 12(3), 231-272.
- de Kleer, J. (1986). "An Assumption-based TMS", Artificial Intelligence 28(2), 127-162.
- Hanson, C., & Sussman, G. J. (2021). "Software Design for Flexibility", Chapter 6:
  Layered Data and Truth Maintenance Systems. MIT Press.
  https://draugus.github.io/pdf/Software%20Design%20for%20Flexibility%20-%20Chris%20Hanson.pdf
- Radul, A., & Sussman, G. J. (2009). "The Art of the Propagator", Section 5: Dependencies.

Tracks which entities asserted which values, timestamps, variances, and active statuses.
Provides human-readable plain-English explanations and Mermaid diagram generation.
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

if __package__ is None or __package__ == "":
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from lattice_propagator.lattice import (
        BOTTOM,
        Bottom,
        Contradiction,
        DiscreteDomain,
        FlatValue,
        GaussianValue,
        IntervalValue,
        LatticeValue,
        MapLattice,
        SetLattice,
        merge_lattice,
    )
else:
    from .lattice import (
        BOTTOM,
        Bottom,
        Contradiction,
        DiscreteDomain,
        FlatValue,
        GaussianValue,
        IntervalValue,
        LatticeValue,
        MapLattice,
        SetLattice,
        merge_lattice,
    )


@dataclass(frozen=True)
class Justification:
    """Provenance rationale for how a premise was derived."""

    rule_name: str
    antecedents: tuple[str, ...] = field(default_factory=tuple)
    parameters: dict[str, Any] = field(default_factory=dict)


def _clean_source_id(source_id: str) -> str:
    """Strip common entity/sensor prefixes for clean human-readable reporting."""
    if source_id.startswith("sensor."):
        return source_id[7:]
    if source_id.startswith("cell."):
        return source_id[5:]
    return source_id


def format_lattice_value(val: LatticeValue, unit: str = "", precision: int = 1) -> str:
    """Format a lattice value into a human-readable string with units and precision."""
    if isinstance(val, GaussianValue):
        margin = 1.96 * val.standard_deviation
        return f"{val.mean:.{precision}f}{unit} (±{margin:.2f}{unit})"
    if isinstance(val, IntervalValue):
        return f"[{val.min_val:.{precision}f}, {val.max_val:.{precision}f}]{unit}"
    if isinstance(val, DiscreteDomain):
        items = ", ".join(str(x) for x in sorted(val.candidates, key=str))
        return f"{{{items}}}"
    if isinstance(val, FlatValue):
        return f"{val.val}{unit}"
    if isinstance(val, Contradiction):
        return f"Contradiction({val.reason})"
    if isinstance(val, SetLattice):
        items = ", ".join(str(x) for x in sorted(val.elements, key=str))
        return f"{{{items}}}"
    if isinstance(val, MapLattice):
        entries = ", ".join(
            f"{k}: {format_lattice_value(v, precision=precision)}" for k, v in val.mapping.items()
        )
        return f"{{{entries}}}"
    if isinstance(val, Bottom):
        return "⊥(Bottom)"
    return str(val)


@dataclass
class Premise:
    """An individual premise asserted by a sensor, propagator, or hypothesis."""

    source_id: str
    value: LatticeValue
    timestamp: float = field(default_factory=time.time)
    is_active: bool = True
    status_reason: str = "active"
    confidence: float = 1.0
    is_assumption: bool = False
    support: frozenset[str] = field(default_factory=frozenset)
    justification: Justification | None = None

    def __post_init__(self) -> None:
        if not self.support:
            self.support = frozenset([self.source_id])


@dataclass
class Assumption(Premise):
    """A defeasible premise (hypothesis) that can be retracted during backtracking."""

    def __init__(
        self,
        source_id: str,
        value: LatticeValue,
        confidence: float = 1.0,
        timestamp: float | None = None,
        is_active: bool = True,
        status_reason: str = "active",
        support: frozenset[str] | None = None,
        justification: Justification | None = None,
    ) -> None:
        ts = timestamp if timestamp is not None else time.time()
        sup = support if support is not None else frozenset([source_id])
        super().__init__(
            source_id=source_id,
            value=value,
            timestamp=ts,
            is_active=is_active,
            status_reason=status_reason,
            confidence=confidence,
            is_assumption=True,
            support=sup,
            justification=justification,
        )


class TruthMaintenanceSystem:
    """Tracks justifications and premises for a network cell."""

    def __init__(
        self,
        cell_id: str,
        default_prior: LatticeValue = BOTTOM,
        unit: str = "",
        display_name: str | None = None,
        network: Any = None,
        network_tms: Any = None,
    ) -> None:
        """Initialize the Truth Maintenance System."""
        self.cell_id = cell_id
        self.default_prior = default_prior
        self.unit = unit
        self.display_name = display_name
        self.network = network
        self.network_tms = network_tms
        self.premises: dict[str, Premise] = {}
        self.nogoods: list[frozenset[str]] = []

    def assert_evidence(
        self,
        source_id: str,
        value: LatticeValue,
        timestamp: float | None = None,
        is_assumption: bool = False,
        confidence: float = 1.0,
        support: frozenset[str] | None = None,
        justification: Justification | None = None,
    ) -> None:
        """Assert or update evidence from a specific source."""
        ts = timestamp if timestamp is not None else time.time()
        sup = support if support is not None else frozenset([source_id])
        self.premises[source_id] = Premise(
            source_id=source_id,
            value=value,
            timestamp=ts,
            is_active=True,
            status_reason="active",
            confidence=confidence,
            is_assumption=is_assumption,
            support=sup,
            justification=justification,
        )

    def retract_evidence(self, source_id: str, reason: str = "unavailable") -> None:
        """Retract evidence from a specific source (e.g., sensor went offline or backtracked)."""
        if source_id in self.premises:
            self.premises[source_id].is_active = False
            self.premises[source_id].status_reason = reason

    def record_nogood(self, conflict_sources: Iterable[str]) -> frozenset[str]:
        """Record an incompatible combination of premises as a nogood set."""
        ng = frozenset(conflict_sources)
        if ng and ng not in self.nogoods:
            self.nogoods.append(ng)
        return ng

    def compute_fused_value(self) -> LatticeValue:
        """Compute the fused lattice value across all currently active premises."""
        active_premises = [p for p in self.premises.values() if p.is_active]
        if not active_premises:
            return self.default_prior

        result: LatticeValue = BOTTOM
        for p in active_premises:
            result = merge_lattice(result, p.value)
        return result

    @property
    def active_sources(self) -> list[str]:
        """Return list of entity IDs currently providing active evidence."""
        return [p.source_id for p in self.premises.values() if p.is_active]

    @property
    def missing_sources(self) -> list[str]:
        """Return list of entity IDs currently retracted, offline, or stale."""
        return [p.source_id for p in self.premises.values() if not p.is_active]

    @property
    def is_degraded(self) -> bool:
        """Return True if at least one expected premise is inactive/missing."""
        return len(self.missing_sources) > 0 and len(self.active_sources) > 0

    @property
    def data_quality(self) -> float:
        """Return ratio of active sources to total configured sources."""
        total = len(self.premises)
        if total == 0:
            return 1.0
        return len(self.active_sources) / total

    def diagnose_contradiction(self, active_premises: list[Premise]) -> str:
        """Produce an actionable diagnostic and DDB retraction recommendation for a contradiction."""
        parts = []
        for p in active_premises:
            kind = "assumption" if p.is_assumption else "ground"
            parts.append(
                f"{_clean_source_id(p.source_id)}={format_lattice_value(p.value, unit=self.unit)} ({kind}, conf={p.confidence:.2f})"
            )
        premises_str = ", ".join(parts)

        assumptions = [p for p in active_premises if p.is_assumption]
        if assumptions:
            assumptions.sort(key=lambda p: (p.confidence, -p.timestamp))
            weakest = assumptions[0]
            rec = f"Recommendation: Retract assumption '{weakest.source_id}' (confidence={weakest.confidence:.2f})."
        else:
            rec = "No defeasible assumptions present; contradiction is between ground facts."

        cell_name = self.display_name or _clean_source_id(self.cell_id)
        return f"Contradiction detected on {cell_name}. Conflicting premises: {premises_str}. {rec}"

    def _resolve_upstream_tms(self, antecedent_id: str) -> TruthMaintenanceSystem | None:
        """Resolve the TMS for an upstream cell if available."""
        if self.network_tms and antecedent_id in self.network_tms.cell_tms:
            return self.network_tms.cell_tms[antecedent_id]
        if self.network and antecedent_id in self.network.cells:
            cell = self.network.cells[antecedent_id]
            if hasattr(cell, "tms") and cell.tms:
                return cell.tms
            if hasattr(cell, "get_or_create_tms"):
                return cell.get_or_create_tms()
        return None

    def explain(
        self,
        unit: str | None = None,
        depth: int | None = 1,
        indent: int = 0,
        visited: set[str] | None = None,
    ) -> str:
        """Generate a human-readable, plain-English explanation.

        Args:
            unit: Optional unit string override (e.g. '°C', 'm/s').
            depth: Traversal depth for causal antecedents (1 for cell-local, None or >1 for recursive).
            indent: Indentation level for recursive causal trees.
            visited: Set of visited cell IDs to avoid cyclic recursion.
        """
        eff_unit = unit if unit is not None else self.unit
        prefix = "  " * indent
        active = [p for p in self.premises.values() if p.is_active]
        missing = [p for p in self.premises.values() if not p.is_active]

        if not active:
            cell_name = self.display_name or _clean_source_id(self.cell_id)
            return f"{prefix}No active sensors reporting for {cell_name}. Reverted to prior ({self.default_prior})."

        fused = self.compute_fused_value()

        # Handle Contradiction
        if isinstance(fused, Contradiction):
            diag = self.diagnose_contradiction(active)
            return f"{prefix}{diag}"

        gaussian_premises = [
            (p.source_id, p.value) for p in active if isinstance(p.value, GaussianValue)
        ]

        # 1. Single active premise with justification (propagator deduction)
        if len(active) == 1 and active[0].justification is not None:
            j = active[0].justification
            local_explanation = (
                f"{prefix}Deduced by {j.rule_name} from {', '.join(_clean_source_id(a) for a in j.antecedents)}: "
                f"{format_lattice_value(fused, unit=eff_unit)}."
            )

        # 2. Gaussian fusion explanation
        elif gaussian_premises and isinstance(fused, GaussianValue):
            parts = []
            for src, val in gaussian_premises:
                parts.append(f"{_clean_source_id(src)} ({val.mean:.1f}{eff_unit})")
            src_list = ", ".join(parts)
            explanation = f"{prefix}Combining {src_list} into {fused.mean:.1f}{eff_unit} (±{1.96 * fused.standard_deviation:.2f}{eff_unit})."
            if missing:
                missing_str = ", ".join(_clean_source_id(s) for s in self.missing_sources)
                explanation += f" Note: Degraded state; {missing_str} is offline."
            local_explanation = explanation

        # 3. Interval fusion explanation
        elif all(isinstance(p.value, IntervalValue) for p in active) and isinstance(
            fused, IntervalValue
        ):
            parts = [
                f"{_clean_source_id(p.source_id)} [{p.value.min_val:.1f}, {p.value.max_val:.1f}]{eff_unit}"
                for p in active
            ]
            src_list = ", ".join(parts)
            explanation = f"{prefix}Intersecting {src_list} into [{fused.min_val:.1f}, {fused.max_val:.1f}]{eff_unit}."
            if missing:
                missing_str = ", ".join(_clean_source_id(s) for s in self.missing_sources)
                explanation += f" Note: Degraded state; {missing_str} is offline."
            local_explanation = explanation

        # 4. DiscreteDomain fusion explanation
        elif all(isinstance(p.value, DiscreteDomain) for p in active) and isinstance(
            fused, DiscreteDomain
        ):
            parts = [
                f"{_clean_source_id(p.source_id)} {format_lattice_value(p.value)}" for p in active
            ]
            src_list = ", ".join(parts)
            explanation = f"{prefix}Constrained candidate states from {src_list} down to {format_lattice_value(fused)}."
            if missing:
                missing_str = ", ".join(_clean_source_id(s) for s in self.missing_sources)
                explanation += f" Note: Degraded state; {missing_str} is offline."
            local_explanation = explanation

        # 5. Generic lattice fusion fallback
        else:
            parts = [
                f"{_clean_source_id(p.source_id)} ({format_lattice_value(p.value, unit=eff_unit)})"
                for p in active
            ]
            local_explanation = f"{prefix}Fused {len(active)} active sources: {', '.join(parts)} into {format_lattice_value(fused, unit=eff_unit)}."
            if missing:
                missing_str = ", ".join(_clean_source_id(s) for s in self.missing_sources)
                local_explanation += f" Note: Degraded state; {missing_str} is offline."

        # Upstream recursive traversal if depth is None or depth > 1
        if depth is None or depth > 1:
            next_depth = None if depth is None else depth - 1
            seen = set(visited) if visited is not None else {self.cell_id}
            sub_lines = [local_explanation]

            for p in active:
                if p.justification and p.justification.antecedents:
                    rule_label = f"└── [{p.justification.rule_name}]"
                    params_str = (
                        f" {p.justification.parameters}" if p.justification.parameters else ""
                    )
                    sub_lines.append(f"{prefix}  {rule_label}{params_str}")

                    for ant in p.justification.antecedents:
                        if ant in seen:
                            sub_lines.append(
                                f"{prefix}    └── {_clean_source_id(ant)} (cycle/memoized)"
                            )
                            continue
                        seen.add(ant)

                        ant_tms = self._resolve_upstream_tms(ant)
                        if ant_tms:
                            ant_explain = ant_tms.explain(
                                unit=None,
                                depth=next_depth,
                                indent=indent + 2,
                                visited=seen,
                            )
                            sub_lines.append(ant_explain)
                        else:
                            sub_lines.append(f"{prefix}    └── {_clean_source_id(ant)}")

            return "\n".join(sub_lines)

        return local_explanation

    def generate_mermaid(self) -> str:
        """Generate a Mermaid flowchart representing the current cell and premises."""
        fused = self.compute_fused_value()
        fused_str = str(fused)

        lines = [
            "```mermaid",
            "graph LR",
            f'  Cell["cell.{self.cell_id}<br/>{fused_str}"]',
        ]

        for p in self.premises.values():
            safe_id = p.source_id.replace(".", "_")
            if p.is_active:
                lines.append(f'  {safe_id}["{p.source_id}<br/>{p.value}"] --> Cell')
            else:
                lines.append(
                    f'  {safe_id}["{p.source_id}<br/>({p.status_reason.upper()})"]:::offline -.-> Cell'
                )

        lines.append("  classDef offline stroke:#f00,stroke-dasharray: 5 5,color:#888;")
        lines.append("```")
        return "\n".join(lines)


class NetworkTMS:
    """Optional, opt-in Network-level Truth Maintenance System with Dependency-Directed Backtracking (DDB).

    This subsystem is strictly opt-in for speculative reasoning and belief revision.
    By default, `PropagatorNetwork` operates strictly monotonically and treats all
    `Contradiction`s as hard invariants without any automatic retraction.

    When explicitly instantiated and enabled, `NetworkTMS` coordinates cell-level TMS
    instances, records global nogood sets, manages defeasible hypotheses/assumptions,
    and allows user-directed resolution of network contradictions by retracting
    weakest assumptions.
    """

    def __init__(self, network: Any = None) -> None:
        self.network = network
        self.cell_tms: dict[str, TruthMaintenanceSystem] = {}
        self.nogoods: list[frozenset[str]] = []
        self.assumptions: dict[str, Premise] = {}

    def get_or_create_cell_tms(
        self,
        cell_id: str,
        default_prior: LatticeValue = BOTTOM,
        unit: str = "",
        display_name: str | None = None,
    ) -> TruthMaintenanceSystem:
        """Get or initialize the TMS for a specific cell."""
        if cell_id not in self.cell_tms:
            prior = default_prior
            cell_unit = unit
            cell_disp = display_name
            if self.network and cell_id in self.network.cells:
                cell = self.network.cells[cell_id]
                prior = cell.value
                if not cell_unit and hasattr(cell, "unit") and cell.unit:
                    cell_unit = cell.unit
                if not cell_disp and hasattr(cell, "display_name") and cell.display_name:
                    cell_disp = cell.display_name
            self.cell_tms[cell_id] = TruthMaintenanceSystem(
                cell_id=cell_id,
                default_prior=prior,
                unit=cell_unit,
                display_name=cell_disp,
                network=self.network,
                network_tms=self,
            )
            if self.network and cell_id in self.network.cells:
                self.network.cells[cell_id].tms = self.cell_tms[cell_id]
        return self.cell_tms[cell_id]

    def assume(
        self,
        cell_id: str,
        assumption_id: str,
        value: LatticeValue,
        confidence: float = 1.0,
    ) -> bool:
        """Assert a defeasible assumption into a cell."""
        ctms = self.get_or_create_cell_tms(cell_id)
        ctms.assert_evidence(
            source_id=assumption_id,
            value=value,
            is_assumption=True,
            confidence=confidence,
        )
        premise = ctms.premises[assumption_id]
        self.assumptions[assumption_id] = premise

        # Propagate into the cell if network is bound
        if self.network and cell_id in self.network.cells:
            cell = self.network.cells[cell_id]
            cell.set_value(ctms.compute_fused_value(), source=assumption_id, overwrite=True)
        return True

    def retract(self, assumption_id: str, reason: str = "retracted") -> bool:
        """Retract an active assumption across the network."""
        found = False
        if assumption_id in self.assumptions:
            self.assumptions[assumption_id].is_active = False
            self.assumptions[assumption_id].status_reason = reason
            found = True

        for ctms in self.cell_tms.values():
            if assumption_id in ctms.premises:
                ctms.retract_evidence(assumption_id, reason=reason)
                found = True
                if self.network and ctms.cell_id in self.network.cells:
                    cell = self.network.cells[ctms.cell_id]
                    cell.set_value(ctms.compute_fused_value(), source="retract", overwrite=True)
        return found

    def record_nogood(self, conflict_sources: Iterable[str]) -> frozenset[str]:
        """Record an inconsistent set of premises/assumptions as a Nogood."""
        ng = frozenset(conflict_sources)
        if ng and ng not in self.nogoods:
            self.nogoods.append(ng)
        return ng

    def is_nogood(self, sources: Iterable[str]) -> bool:
        """Check if any recorded nogood is a subset of the given source set."""
        source_set = set(sources)
        return any(ng.issubset(source_set) for ng in self.nogoods)

    def resolve_contradiction(self, conflict_sources: Iterable[str]) -> str | None:
        """Dependency-Directed Backtracking (DDB): resolve contradiction by retracting the lowest-confidence assumption."""
        self.record_nogood(conflict_sources)

        # Identify active assumptions involved in the conflict
        culprits: list[Premise] = []
        for src in conflict_sources:
            if src in self.assumptions and self.assumptions[src].is_active:
                culprits.append(self.assumptions[src])

        if not culprits:
            # Contradiction between non-defeasible ground premises! Cannot be resolved.
            return None

        # Sort by confidence ascending (lowest confidence first), then newest timestamp
        culprits.sort(key=lambda p: (p.confidence, -p.timestamp))
        weakest = culprits[0]

        # Retract the weakest assumption
        self.retract(weakest.source_id, reason="nogood_backtracking")
        return weakest.source_id

    def explain(
        self,
        cell_id: str,
        unit: str | None = None,
        depth: int | None = None,
    ) -> str:
        """Explain the state and provenance of a network cell."""
        ctms = self.get_or_create_cell_tms(cell_id)
        return ctms.explain(unit=unit, depth=depth)


if __name__ == "__main__":
    # Demonstration of TMS and explanation engine
    tms = TruthMaintenanceSystem(cell_id="living_room_temp", unit="°C")
    tms.assert_evidence("sensor.thermostat", GaussianValue(mean=21.2, variance=0.1))
    tms.assert_evidence("sensor.radiator", GaussianValue(mean=21.8, variance=0.4))
    print("--- Sensor Fusion Explanation ---")
    print(tms.explain())

    print("\n--- Interval Narrowing Explanation ---")
    interval_tms = TruthMaintenanceSystem(cell_id="target_band", unit="°C")
    interval_tms.assert_evidence("policy.comfort", IntervalValue(19.0, 23.0))
    interval_tms.assert_evidence("rule.solar_gain", IntervalValue(20.5, 25.0))
    print(interval_tms.explain())

    print("\n--- Contradiction Actionable Diagnosis ---")
    conflict_tms = TruthMaintenanceSystem(cell_id="hvac_mode")
    conflict_tms.assert_evidence("user_manual_override", FlatValue("cool"), is_assumption=False)
    conflict_tms.assert_evidence(
        "freeze_protection_rule", FlatValue("heat"), is_assumption=True, confidence=0.7
    )
    print(conflict_tms.explain())
