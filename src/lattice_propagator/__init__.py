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
"""

from __future__ import annotations

from .kinematics import (
    ArrivalEstimate,
    GPSFix,
    TransitMode,
    classify_transit_mode,
    compute_arrival_estimate,
    haversine_distance,
)
from .lattice import (
    BOTTOM,
    Bottom,
    CircularInterval,
    Contradiction,
    DiscreteDomain,
    GaussianValue,
    IntervalValue,
    LatticeValue,
    OrderedInterval,
    merge_lattice,
)
from .primitives import (
    AllDifferentPropagator,
    ArithmeticPropagator,
    Cell,
    DynamicScenePropagator,
    ElasticModulatorPropagator,
    KalmanEstimatorPropagator,
    LagPropagator,
    Propagator,
    PropagatorNetwork,
    RatePropagator,
    ScenePhase,
    ThresholdPropagator,
)
from .tms import Premise, TruthMaintenanceSystem

__version__ = "0.0.1dev1"

__all__ = [
    # Core Lattice Elements
    "BOTTOM",
    "Bottom",
    "Contradiction",
    "LatticeValue",
    "GaussianValue",
    "IntervalValue",
    "OrderedInterval",
    "CircularInterval",
    "DiscreteDomain",
    "merge_lattice",
    # Propagators and Network
    "Cell",
    "Propagator",
    "PropagatorNetwork",
    "ArithmeticPropagator",
    "RatePropagator",
    "LagPropagator",
    "ElasticModulatorPropagator",
    "ThresholdPropagator",
    "DynamicScenePropagator",
    "ScenePhase",
    "KalmanEstimatorPropagator",
    "AllDifferentPropagator",
    # Kinematics
    "GPSFix",
    "TransitMode",
    "ArrivalEstimate",
    "classify_transit_mode",
    "compute_arrival_estimate",
    "haversine_distance",
    # TMS
    "Premise",
    "TruthMaintenanceSystem",
]
