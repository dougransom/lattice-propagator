"""Truth Maintenance System (TMS) and Provenance Tracking for the Propagator Engine.

Based on dependency-directed provenance and belief revision literature:
- Doyle, J. (1979). "A Truth Maintenance System", Artificial Intelligence 12(3), 231-272.
- de Kleer, J. (1986). "An Assumption-based TMS", Artificial Intelligence 28(2), 127-162.
- Hanson, C., & Sussman, G. J. (2021). "Software Design for Flexibility", Chapter 6:
  Layered Data and Truth Maintenance Systems. MIT Press.
- Radul, A., & Sussman, G. J. (2009). "The Art of the Propagator", Section 5: Dependencies.

Tracks which entities asserted which values, timestamps, variances, and active statuses.
Provides human-readable plain-English explanations and Mermaid diagram generation.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .lattice import BOTTOM, GaussianValue, LatticeValue, merge_lattice


@dataclass
class Premise:
    """An individual premise asserted by a sensor or propagator."""

    source_id: str
    value: LatticeValue
    timestamp: float = field(default_factory=time.time)
    is_active: bool = True
    status_reason: str = "active"


class TruthMaintenanceSystem:
    """Tracks justifications and premises for a network cell."""

    def __init__(self, cell_id: str, default_prior: LatticeValue = BOTTOM) -> None:
        """Initialize the Truth Maintenance System."""
        self.cell_id = cell_id
        self.default_prior = default_prior
        self.premises: dict[str, Premise] = {}

    def assert_evidence(
        self,
        source_id: str,
        value: LatticeValue,
        timestamp: float | None = None,
    ) -> None:
        """Assert or update evidence from a specific source."""
        ts = timestamp if timestamp is not None else time.time()
        self.premises[source_id] = Premise(
            source_id=source_id,
            value=value,
            timestamp=ts,
            is_active=True,
            status_reason="active",
        )

    def retract_evidence(self, source_id: str, reason: str = "unavailable") -> None:
        """Retract evidence from a specific source (e.g., sensor went offline)."""
        if source_id in self.premises:
            self.premises[source_id].is_active = False
            self.premises[source_id].status_reason = reason

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

    def explain(self, unit: str = "°C") -> str:
        """Generate a human-readable, plain-English explanation."""
        active = [p for p in self.premises.values() if p.is_active]
        missing = [p for p in self.premises.values() if not p.is_active]

        if not active:
            return f"No active sensors reporting. Reverted to prior ({self.default_prior})."

        # Gaussian fusion explanation
        gaussian_premises = [
            (p.source_id, p.value) for p in active if isinstance(p.value, GaussianValue)
        ]

        if gaussian_premises:
            fused = self.compute_fused_value()
            if isinstance(fused, GaussianValue):
                parts = []
                for src, val in gaussian_premises:
                    parts.append(f"{src.replace('sensor.', '')} ({val.mean:.1f}{unit})")
                src_list = ", ".join(parts)
                explanation = f"Combining {src_list} into {fused.mean:.1f}{unit} (±{1.96 * fused.standard_deviation:.2f}{unit})."
                if missing:
                    missing_str = ", ".join(s.replace("sensor.", "") for s in self.missing_sources)
                    explanation += f" Note: Degraded state; {missing_str} is offline."
                return explanation

        return f"Fused {len(active)} active sources."

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
