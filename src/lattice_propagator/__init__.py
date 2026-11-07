"""Lattice Propagator: Monotonic constraint networks over partial-information lattices.

Theoretical Foundations:
The propagator computational paradigm was pioneered by Gerald Jay Sussman and Alexey Radul
at MIT, establishing computation as autonomous, multi-directional constraint networks operating
monotonically over semilattices of partial information with truth maintenance.

Primary Citations & Literature:
1. Radul, A., & Sussman, G. J. (2009). "The Art of the Propagator". MIT-CSAIL-TR-2009-002.
   https://dspace.mit.edu/handle/1721.1/44215
2. Radul, A. (2009). "Propagation Networks: A Flexible and Expressive Substrate for Computation".
   Doctoral Dissertation, MIT. https://dspace.mit.edu/handle/1721.1/54635
3. Hanson, C., & Sussman, G. J. (2021). "Software Design for Flexibility". MIT Press.
   https://draugus.github.io/pdf/Software%20Design%20for%20Flexibility%20-%20Chris%20Hanson.pdf
"""

from __future__ import annotations

from .graph import (
    GraphCluster,
    GraphEdge,
    GraphNode,
    NetworkGraph,
    NetworkVisitor,
    classify_lattice_state,
    detect_cycles,
    walk_downstream,
    walk_upstream,
)
from .lattice import (
    BOTTOM,
    BeliefMassValue,
    Bottom,
    CircularInterval,
    Contradiction,
    DiscreteDomain,
    FlatValue,
    GaussianValue,
    IntervalValue,
    LatticeValue,
    MapLattice,
    OrderedInterval,
    SetLattice,
    merge_lattice,
)
from .primitives import (
    AdderPropagator,
    AllDifferentPropagator,
    ArithmeticPropagator,
    BoundedLinearPropagator,
    Cell,
    ChoiceEngine,
    ConditionalPropagator,
    DempsterShaferPropagator,
    FunctionalPropagator,
    KalmanEstimatorPropagator,
    LagPropagator,
    MobileLinkPropagator,
    MultiplierPropagator,
    Propagator,
    PropagatorNetwork,
    RatePropagator,
    SpatialZone,
    SwitchPropagator,
    ThresholdPropagator,
    TrajectoryEnvelopePropagator,
    TrajectorySegment,
    lift_propagator,
)
from .tms import (
    DEFAULT_EXPLANATION_TEMPLATES,
    Assumption,
    ExplanationNode,
    Justification,
    NetworkTMS,
    Premise,
    Translator,
    TruthMaintenanceSystem,
    format_lattice_value,
    make_template_translator,
)

__version__ = "0.0.1dev1"

__all__ = [
    "BOTTOM",
    "DEFAULT_EXPLANATION_TEMPLATES",
    "AdderPropagator",
    "AllDifferentPropagator",
    "ArithmeticPropagator",
    "Assumption",
    "BeliefMassValue",
    "Bottom",
    "BoundedLinearPropagator",
    "Cell",
    "ChoiceEngine",
    "CircularInterval",
    "ConditionalPropagator",
    "Contradiction",
    "DempsterShaferPropagator",
    "DiscreteDomain",
    "ExplanationNode",
    "FlatValue",
    "FunctionalPropagator",
    "GaussianValue",
    "GraphCluster",
    "GraphEdge",
    "GraphNode",
    "IntervalValue",
    "Justification",
    "KalmanEstimatorPropagator",
    "LagPropagator",
    "LatticeValue",
    "MapLattice",
    "MobileLinkPropagator",
    "MultiplierPropagator",
    "NetworkGraph",
    "NetworkTMS",
    "NetworkVisitor",
    "OrderedInterval",
    "Premise",
    "Propagator",
    "PropagatorNetwork",
    "RatePropagator",
    "SetLattice",
    "SpatialZone",
    "SwitchPropagator",
    "ThresholdPropagator",
    "TrajectoryEnvelopePropagator",
    "TrajectorySegment",
    "Translator",
    "TruthMaintenanceSystem",
    "classify_lattice_state",
    "detect_cycles",
    "format_lattice_value",
    "lift_propagator",
    "make_template_translator",
    "merge_lattice",
    "walk_downstream",
    "walk_upstream",
]
