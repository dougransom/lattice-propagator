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
from collections.abc import Callable, Iterable, Mapping, Sequence
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
        IntegerDomain,
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
        IntegerDomain,
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
    parameters: Mapping[str, Any] = field(default_factory=dict)


Translator = Callable[[str, str, Mapping[str, Any]], str]


def make_template_translator(templates: Mapping[str, str]) -> Translator:
    """Create a translator callable that overrides default templates with custom translations.

    Args:
        templates: Mapping from message keys (e.g. 'tms.gaussian_fusion') to format strings.

    Returns:
        A Translator callable suitable for passing to `explain()` or `ExplanationNode.render()`.
    """

    def _translate(key: str, default_template: str, params: Mapping[str, Any]) -> str:
        template = templates.get(key, default_template)
        return template.format(**params)

    return _translate


DEFAULT_EXPLANATION_TEMPLATES: Mapping[str, str] = {
    "tms.no_active_sensors": "{prefix}No active sensors reporting for {cell_name}. Reverted to prior ({prior}).",
    "tms.contradiction": "{prefix}Contradiction detected on {cell_name}. Conflicting premises: {premises}. {recommendation}",
    "tms.recommend_retract": "Recommendation: Retract assumption '{source_id}' (confidence={confidence:.2f}).",
    "tms.no_assumptions": "No defeasible assumptions present; contradiction is between ground facts.",
    "tms.propagator_deduction": "{prefix}Deduced by {rule_name} from {antecedents}: {fused}.",
    "tms.gaussian_fusion": "{prefix}Combining {sources} into {mean:.1f}{unit} (±{spread:.2f}{unit}).{degraded_note}",
    "tms.interval_fusion": "{prefix}Intersecting {sources} into [{min_val:.1f}, {max_val:.1f}]{unit}.{degraded_note}",
    "tms.discrete_fusion": "{prefix}Constrained candidate states from {sources} down to {fused}.{degraded_note}",
    "tms.generic_fusion": "{prefix}Fused {count} active sources: {sources} into {fused}.{degraded_note}",
    "tms.degraded_note": " Note: Degraded state; {missing} is offline.",
    "tms.rule_branch": "{prefix}└── [{rule_name}]{params}",
    "tms.cycle_memoized": "{prefix}└── {antecedent} (cycle/memoized)",
    "tms.antecedent_leaf": "{prefix}└── {antecedent}",
}


@dataclass
class ExplanationNode:
    """Structured, localizable representation of an explanation step and its causal tree.

    Decouples causal provenance analysis from formatted string representation to enable
    internationalization (i18n), semantic inspection, and serializable payloads
    for external systems (e.g. Home Assistant entities, WebSocket APIs, or frontends).

    Attributes:
        key: Semantic translation key (e.g. 'tms.gaussian_fusion', 'tms.contradiction').
        parameters: Interpolation parameters for message formatting.
        default_template: Default English format template with named placeholders.
        cell_id: Identifier of the cell explained by this node.
        display_name: Optional human-readable display name for the cell.
        fused_value: Current fused lattice value of the cell, if computed.
        is_contradiction: True if this explanation represents a contradiction state.
        is_degraded: True if the cell's active inputs are degraded or offline.
        rule_name: Propagator or inference rule name if deduced.
        rule_parameters: Parameters passed to the rule or justification.
        indent_offset: Relative indentation offset for rendering tree hierarchy.
        children: Subordinate causal antecedent explanation nodes.
    """

    key: str
    parameters: Mapping[str, Any]
    default_template: str
    cell_id: str
    display_name: str | None = None
    fused_value: LatticeValue | None = None
    is_contradiction: bool = False
    is_degraded: bool = False
    rule_name: str | None = None
    rule_parameters: Mapping[str, Any] | None = None
    indent_offset: int = 0
    children: Sequence[ExplanationNode] = field(default_factory=list)

    def render(self, indent: int = 0, translator: Translator | None = None) -> str:
        """Render this explanation node and its children to an indented text string.

        Args:
            indent: Indentation level (each level corresponds to two spaces).
            translator: Optional translation callable `(key, default_template, params) -> str`.
                If None, the default English template is formatted.

        Returns:
            Human-readable, formatted explanation string.
        """
        prefix = "  " * indent
        params = dict(self.parameters)
        params["prefix"] = prefix

        if self.is_degraded and "degraded_missing" in params:
            missing_text = params["degraded_missing"]
            deg_default = DEFAULT_EXPLANATION_TEMPLATES["tms.degraded_note"]
            params["degraded_note"] = (
                translator("tms.degraded_note", deg_default, {"missing": missing_text})
                if translator is not None
                else deg_default.format(missing=missing_text)
            )

        if self.is_contradiction and "rec_key" in params:
            rec_key = params["rec_key"]
            rec_params = params.get("rec_params", {})
            rec_default = DEFAULT_EXPLANATION_TEMPLATES.get(rec_key, "")
            if rec_default:
                params["recommendation"] = (
                    translator(rec_key, rec_default, rec_params)
                    if translator is not None
                    else rec_default.format(**rec_params)
                )

        local_line = (
            translator(self.key, self.default_template, params)
            if translator is not None
            else self.default_template.format(**params)
        )

        lines = [local_line]
        for child in self.children:
            lines.append(child.render(indent=indent + child.indent_offset, translator=translator))

        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Convert the explanation node into a JSON-serializable dictionary."""
        clean_params = {
            k: v if (isinstance(v, (str, int, float, bool, list, dict)) or v is None) else str(v)
            for k, v in self.parameters.items()
            if k != "prefix"
        }

        result: dict[str, Any] = {
            "key": self.key,
            "cell_id": self.cell_id,
            "parameters": clean_params,
            "is_contradiction": self.is_contradiction,
            "is_degraded": self.is_degraded,
        }
        if self.display_name:
            result["display_name"] = self.display_name
        if self.fused_value is not None:
            result["fused_value"] = str(self.fused_value)
        if self.rule_name:
            result["rule_name"] = self.rule_name
        if self.rule_parameters:
            result["rule_parameters"] = self.rule_parameters
        if self.children:
            result["children"] = [child.to_dict() for child in self.children]
        return result

    def __str__(self) -> str:
        return self.render()


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
    if isinstance(val, IntegerDomain):
        return val.format_display(unit=unit, precision=precision)
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
        translator: Translator | None = None,
    ) -> None:
        """Initialize the Truth Maintenance System."""
        self.cell_id = cell_id
        self.default_prior = default_prior
        self.unit = unit
        self.display_name = display_name
        self.network = network
        self.network_tms = network_tms
        self.translator = translator
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
    def active_sources(self) -> Sequence[str]:
        """Return sequence of entity IDs currently providing active evidence."""
        return [p.source_id for p in self.premises.values() if p.is_active]

    @property
    def missing_sources(self) -> Sequence[str]:
        """Return sequence of entity IDs currently retracted, offline, or stale."""
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

    def diagnose_contradiction(
        self,
        active_premises: Sequence[Premise],
        translator: Translator | None = None,
    ) -> str:
        """Produce an actionable diagnostic and DDB retraction recommendation for a contradiction."""
        premises_str = ", ".join(
            f"{_clean_source_id(p.source_id)}={format_lattice_value(p.value, unit=self.unit)} ({'assumption' if p.is_assumption else 'ground'}, conf={p.confidence:.2f})"
            for p in active_premises
        )

        weakest = min(
            (p for p in active_premises if p.is_assumption),
            key=lambda p: (p.confidence, -p.timestamp),
            default=None,
        )
        rec_key, rec_params, rec = (
            (
                "tms.recommend_retract",
                {"source_id": weakest.source_id, "confidence": weakest.confidence},
                f"Recommendation: Retract assumption '{weakest.source_id}' (confidence={weakest.confidence:.2f}).",
            )
            if weakest is not None
            else (
                "tms.no_assumptions",
                {},
                "No defeasible assumptions present; contradiction is between ground facts.",
            )
        )

        eff_tr = translator if translator is not None else self.translator
        cell_name = self.display_name or _clean_source_id(self.cell_id)

        if eff_tr is not None:
            rec_default = DEFAULT_EXPLANATION_TEMPLATES[rec_key]
            rec = eff_tr(rec_key, rec_default, rec_params)
            diag_default = DEFAULT_EXPLANATION_TEMPLATES["tms.contradiction"]
            return eff_tr(
                "tms.contradiction",
                diag_default,
                {
                    "prefix": "",
                    "cell_name": cell_name,
                    "premises": premises_str,
                    "recommendation": rec,
                },
            )

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

    def explain_node(
        self,
        unit: str | None = None,
        depth: int | None = 1,
        visited: set[str] | None = None,
    ) -> ExplanationNode:
        """Generate a structured, localizable explanation node and causal tree.

        Args:
            unit: Optional unit string override (e.g. '°C', 'm/s').
            depth: Traversal depth for causal antecedents (1 for cell-local, None or >1 for recursive).
            visited: Set of visited cell IDs to avoid cyclic recursion.

        Returns:
            An ExplanationNode representing this cell's provenance, local explanation,
            and upstream causal children.
        """
        eff_unit = unit if unit is not None else self.unit
        active = [p for p in self.premises.values() if p.is_active]
        missing = [p for p in self.premises.values() if not p.is_active]
        cell_name = self.display_name or _clean_source_id(self.cell_id)

        # 0. No active premises
        if not active:
            return ExplanationNode(
                key="tms.no_active_sensors",
                parameters={"cell_name": cell_name, "prior": str(self.default_prior)},
                default_template=DEFAULT_EXPLANATION_TEMPLATES["tms.no_active_sensors"],
                cell_id=self.cell_id,
                display_name=self.display_name,
                is_degraded=False,
            )

        fused = self.compute_fused_value()

        # Handle Contradiction
        if isinstance(fused, Contradiction):
            premises_str = ", ".join(
                f"{_clean_source_id(p.source_id)}={format_lattice_value(p.value, unit=self.unit)} ({'assumption' if p.is_assumption else 'ground'}, conf={p.confidence:.2f})"
                for p in active
            )

            weakest = min(
                (p for p in active if p.is_assumption),
                key=lambda p: (p.confidence, -p.timestamp),
                default=None,
            )
            rec_key, rec_params, rec = (
                (
                    "tms.recommend_retract",
                    {"source_id": weakest.source_id, "confidence": weakest.confidence},
                    f"Recommendation: Retract assumption '{weakest.source_id}' (confidence={weakest.confidence:.2f}).",
                )
                if weakest is not None
                else (
                    "tms.no_assumptions",
                    {},
                    "No defeasible assumptions present; contradiction is between ground facts.",
                )
            )

            return ExplanationNode(
                key="tms.contradiction",
                parameters={
                    "cell_name": cell_name,
                    "premises": premises_str,
                    "recommendation": rec,
                    "rec_key": rec_key,
                    "rec_params": rec_params,
                },
                default_template=DEFAULT_EXPLANATION_TEMPLATES["tms.contradiction"],
                cell_id=self.cell_id,
                display_name=self.display_name,
                fused_value=fused,
                is_contradiction=True,
            )

        gaussian_premises = [
            (p.source_id, p.value) for p in active if isinstance(p.value, GaussianValue)
        ]

        degraded_note = ""
        degraded_missing = ""
        if missing:
            degraded_missing = ", ".join(_clean_source_id(s) for s in self.missing_sources)
            degraded_note = f" Note: Degraded state; {degraded_missing} is offline."

        # 1. Single active premise with justification (propagator deduction)
        if len(active) == 1 and active[0].justification is not None:
            j = active[0].justification
            antecedents_str = ", ".join(_clean_source_id(a) for a in j.antecedents)
            node = ExplanationNode(
                key="tms.propagator_deduction",
                parameters={
                    "rule_name": j.rule_name,
                    "antecedents": antecedents_str,
                    "fused": format_lattice_value(fused, unit=eff_unit),
                },
                default_template=DEFAULT_EXPLANATION_TEMPLATES["tms.propagator_deduction"],
                cell_id=self.cell_id,
                display_name=self.display_name,
                fused_value=fused,
                rule_name=j.rule_name,
                rule_parameters=j.parameters,
            )

        # 2. Gaussian fusion explanation
        elif gaussian_premises and isinstance(fused, GaussianValue):
            src_list = ", ".join(
                f"{_clean_source_id(src)} ({val.mean:.1f}{eff_unit})"
                for src, val in gaussian_premises
            )
            node = ExplanationNode(
                key="tms.gaussian_fusion",
                parameters={
                    "sources": src_list,
                    "mean": fused.mean,
                    "unit": eff_unit,
                    "spread": 1.96 * fused.standard_deviation,
                    "degraded_note": degraded_note,
                    "degraded_missing": degraded_missing,
                },
                default_template=DEFAULT_EXPLANATION_TEMPLATES["tms.gaussian_fusion"],
                cell_id=self.cell_id,
                display_name=self.display_name,
                fused_value=fused,
                is_degraded=bool(missing),
            )

        # 3. Interval fusion explanation
        elif all(isinstance(p.value, IntervalValue) for p in active) and isinstance(
            fused, IntervalValue
        ):
            src_list = ", ".join(
                f"{_clean_source_id(p.source_id)} [{p.value.min_val:.1f}, {p.value.max_val:.1f}]{eff_unit}"
                for p in active
            )
            node = ExplanationNode(
                key="tms.interval_fusion",
                parameters={
                    "sources": src_list,
                    "min_val": fused.min_val,
                    "max_val": fused.max_val,
                    "unit": eff_unit,
                    "degraded_note": degraded_note,
                    "degraded_missing": degraded_missing,
                },
                default_template=DEFAULT_EXPLANATION_TEMPLATES["tms.interval_fusion"],
                cell_id=self.cell_id,
                display_name=self.display_name,
                fused_value=fused,
                is_degraded=bool(missing),
            )

        # 4. DiscreteDomain fusion explanation
        elif all(isinstance(p.value, DiscreteDomain) for p in active) and isinstance(
            fused, DiscreteDomain
        ):
            src_list = ", ".join(
                f"{_clean_source_id(p.source_id)} {format_lattice_value(p.value)}" for p in active
            )
            node = ExplanationNode(
                key="tms.discrete_fusion",
                parameters={
                    "sources": src_list,
                    "fused": format_lattice_value(fused),
                    "degraded_note": degraded_note,
                    "degraded_missing": degraded_missing,
                },
                default_template=DEFAULT_EXPLANATION_TEMPLATES["tms.discrete_fusion"],
                cell_id=self.cell_id,
                display_name=self.display_name,
                fused_value=fused,
                is_degraded=bool(missing),
            )

        # 5. Generic lattice fusion fallback
        else:
            node = ExplanationNode(
                key="tms.generic_fusion",
                parameters={
                    "count": len(active),
                    "sources": ", ".join(
                        f"{_clean_source_id(p.source_id)} ({format_lattice_value(p.value, unit=eff_unit)})"
                        for p in active
                    ),
                    "fused": format_lattice_value(fused, unit=eff_unit),
                    "degraded_note": degraded_note,
                    "degraded_missing": degraded_missing,
                },
                default_template=DEFAULT_EXPLANATION_TEMPLATES["tms.generic_fusion"],
                cell_id=self.cell_id,
                display_name=self.display_name,
                fused_value=fused,
                is_degraded=bool(missing),
            )

        # Upstream recursive traversal if depth is None or depth > 1
        if depth is None or depth > 1:
            next_depth = None if depth is None else depth - 1
            seen = set(visited) if visited is not None else {self.cell_id}

            for p in active:
                if p.justification and p.justification.antecedents:
                    rule_name = p.justification.rule_name
                    params_str = (
                        f" {p.justification.parameters}" if p.justification.parameters else ""
                    )
                    rule_node = ExplanationNode(
                        key="tms.rule_branch",
                        parameters={
                            "rule_name": rule_name,
                            "params": params_str,
                            "rule_parameters": p.justification.parameters or {},
                        },
                        default_template=DEFAULT_EXPLANATION_TEMPLATES["tms.rule_branch"],
                        cell_id=self.cell_id,
                        rule_name=rule_name,
                        rule_parameters=p.justification.parameters,
                        indent_offset=1,
                    )
                    node.children.append(rule_node)

                    for ant in p.justification.antecedents:
                        if ant in seen:
                            rule_node.children.append(
                                ExplanationNode(
                                    key="tms.cycle_memoized",
                                    parameters={"antecedent": _clean_source_id(ant)},
                                    default_template=DEFAULT_EXPLANATION_TEMPLATES[
                                        "tms.cycle_memoized"
                                    ],
                                    cell_id=ant,
                                    indent_offset=1,
                                )
                            )
                            continue
                        seen.add(ant)

                        ant_tms = self._resolve_upstream_tms(ant)
                        if ant_tms:
                            ant_node = ant_tms.explain_node(
                                unit=None,
                                depth=next_depth,
                                visited=seen,
                            )
                            ant_node.indent_offset = 1
                            rule_node.children.append(ant_node)
                        else:
                            rule_node.children.append(
                                ExplanationNode(
                                    key="tms.antecedent_leaf",
                                    parameters={"antecedent": _clean_source_id(ant)},
                                    default_template=DEFAULT_EXPLANATION_TEMPLATES[
                                        "tms.antecedent_leaf"
                                    ],
                                    cell_id=ant,
                                    indent_offset=1,
                                )
                            )

        return node

    def explain(
        self,
        unit: str | None = None,
        depth: int | None = 1,
        indent: int = 0,
        visited: set[str] | None = None,
        translator: Translator | None = None,
    ) -> str:
        """Generate a human-readable explanation.

        Args:
            unit: Optional unit string override (e.g. '°C', 'm/s').
            depth: Traversal depth for causal antecedents (1 for cell-local, None or >1 for recursive).
            indent: Indentation level for recursive causal trees.
            visited: Set of visited cell IDs to avoid cyclic recursion.
            translator: Optional translator callable `(key, default_template, params) -> str`.
                Defaults to `self.translator` or standard English template interpolation.
        """
        eff_tr = translator if translator is not None else self.translator
        node = self.explain_node(unit=unit, depth=depth, visited=visited)
        return node.render(indent=indent, translator=eff_tr)

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
            edge = (
                f'  {safe_id}["{p.source_id}<br/>{p.value}"] --> Cell'
                if p.is_active
                else f'  {safe_id}["{p.source_id}<br/>({p.status_reason.upper()})"]:::offline -.-> Cell'
            )
            lines.append(edge)

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
        if network is not None:
            network.tms = self
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
            cell.set_value(ctms.compute_fused_value(), overwrite=True)
        return True

    def retract(self, assumption_id: str, reason: str = "retracted") -> bool:
        """Retract an active assumption and any derived premises supported by it across the network."""
        found = False
        if assumption_id in self.assumptions:
            self.assumptions[assumption_id].is_active = False
            self.assumptions[assumption_id].status_reason = reason
            found = True

        for ctms in self.cell_tms.values():
            retracted_in_cell = False
            for src_id, prem in ctms.premises.items():
                if src_id == assumption_id or (prem.is_active and assumption_id in prem.support):
                    ctms.retract_evidence(src_id, reason=reason)
                    retracted_in_cell = True
                    found = True
            if retracted_in_cell and self.network and ctms.cell_id in self.network.cells:
                cell = self.network.cells[ctms.cell_id]
                cell.set_value(ctms.compute_fused_value(), overwrite=True)
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

        # Identify active assumptions involved directly or via transitive support in the conflict
        seen_ids: set[str] = set()
        culprits: list[Premise] = []
        for src in conflict_sources:
            if src in self.assumptions and self.assumptions[src].is_active and src not in seen_ids:
                seen_ids.add(src)
                culprits.append(self.assumptions[src])
            for ctms in self.cell_tms.values():
                prem = ctms.premises.get(src)
                if prem is not None and prem.is_active:
                    for sup_id in prem.support:
                        if (
                            sup_id in self.assumptions
                            and self.assumptions[sup_id].is_active
                            and sup_id not in seen_ids
                        ):
                            seen_ids.add(sup_id)
                            culprits.append(self.assumptions[sup_id])

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
        translator: Translator | None = None,
    ) -> str:
        """Explain the state and provenance of a network cell."""
        ctms = self.get_or_create_cell_tms(cell_id)
        return ctms.explain(unit=unit, depth=depth, translator=translator)

    def explain_node(
        self,
        cell_id: str,
        unit: str | None = None,
        depth: int | None = None,
    ) -> ExplanationNode:
        """Generate a structured explanation node for a network cell."""
        ctms = self.get_or_create_cell_tms(cell_id)
        return ctms.explain_node(unit=unit, depth=depth)


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
