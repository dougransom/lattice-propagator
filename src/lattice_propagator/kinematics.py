"""Kinematic Arrival Anticipator and Multi-Hypothesis Geofencing Engine.

Pure Python implementation of:
- Haversine great-circle distance calculation
- Radial velocity estimation towards a target point (e.g. Home)
- Transit mode hypothesis classification (Walking, Cycling, Driving, Stationary)
- Bounded interval ETA computation to target perimeters
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import NamedTuple

from .lattice import IntervalValue


class TransitMode(StrEnum):
    """Categorical transit mode hypotheses."""

    STATIONARY = "stationary"
    WALKING = "walking"
    CYCLING = "cycling"
    DRIVING = "driving"
    DEPARTING = "departing"
    UNKNOWN = "unknown"


# Typical operational velocity intervals in meters/second
TRANSIT_MODE_BOUNDS: dict[TransitMode, IntervalValue] = {
    TransitMode.STATIONARY: IntervalValue(0.0, 0.8),  # < 2.9 km/h
    TransitMode.WALKING: IntervalValue(0.8, 2.2),  # 2.9 - 7.9 km/h
    TransitMode.CYCLING: IntervalValue(2.2, 7.5),  # 7.9 - 27.0 km/h
    TransitMode.DRIVING: IntervalValue(7.5, 36.0),  # 27.0 - 130.0 km/h
}

EARTH_RADIUS_METERS = 6_371_000.0


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great-circle distance between two GPS coordinates in meters."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return EARTH_RADIUS_METERS * c


class GPSFix(NamedTuple):
    """Timestamped geographic location fix."""

    latitude: float
    longitude: float
    timestamp: float  # Epoch seconds
    accuracy: float = 10.0  # Accuracy radius in meters


@dataclass(frozen=True)
class ArrivalEstimate:
    """Computed arrival estimate and kinematic state."""

    distance_meters: float
    velocity_mps: float  # Positive = moving towards destination
    velocity_kmh: float
    transit_mode: TransitMode
    approaching: bool
    eta_seconds_interval: IntervalValue | None  # [min_eta, max_eta] or None if not approaching
    eta_minutes: float | None  # Midpoint ETA in minutes
    explanation: str


_HINT_MAP: dict[str, tuple[TransitMode, float, float]] = {
    "driving": (TransitMode.DRIVING, 2.0, float("inf")),
    "automotive": (TransitMode.DRIVING, 2.0, float("inf")),
    "car": (TransitMode.DRIVING, 2.0, float("inf")),
    "walking": (TransitMode.WALKING, 0.0, 3.0),
    "on_foot": (TransitMode.WALKING, 0.0, 3.0),
    "cycling": (TransitMode.CYCLING, 0.0, 10.0),
    "biking": (TransitMode.CYCLING, 0.0, 10.0),
}


def classify_transit_mode(
    velocity_mps: float,
    hint_mode: str | None = None,
) -> TransitMode:
    """Infer or validate transit mode hypothesis based on velocity and optional hints."""
    if velocity_mps < -0.8:
        return TransitMode.DEPARTING

    speed = abs(velocity_mps)
    if speed <= 0.8:
        return TransitMode.STATIONARY

    if hint_mode and (hint_cfg := _HINT_MAP.get(hint_mode.lower())):
        mode, min_s, max_s = hint_cfg
        if min_s <= speed <= max_s:
            return mode

    if speed < 2.2:
        return TransitMode.WALKING
    return TransitMode.CYCLING if speed < 7.5 else TransitMode.DRIVING


def compute_arrival_estimate(
    current_fix: GPSFix,
    previous_fix: GPSFix | None,
    dest_lat: float,
    dest_lon: float,
    target_threshold_meters: float = 500.0,
    hint_mode: str | None = None,
) -> ArrivalEstimate:
    """Compute radial velocity, transit mode, and bounded ETA to a target threshold."""
    current_dist = haversine_distance(
        current_fix.latitude, current_fix.longitude, dest_lat, dest_lon
    )

    if previous_fix is None:
        return ArrivalEstimate(
            distance_meters=current_dist,
            velocity_mps=0.0,
            velocity_kmh=0.0,
            transit_mode=TransitMode.UNKNOWN,
            approaching=False,
            eta_seconds_interval=None,
            eta_minutes=None,
            explanation=f"Initial GPS fix established. Distance to destination: {current_dist:.0f}m. Awaiting secondary fix for velocity.",
        )

    delta_t = current_fix.timestamp - previous_fix.timestamp
    if delta_t <= 0.0:
        delta_t = 1.0  # Safeguard against zero/negative time drift

    prev_dist = haversine_distance(
        previous_fix.latitude, previous_fix.longitude, dest_lat, dest_lon
    )

    # Positive radial velocity = moving closer
    radial_velocity_mps = (prev_dist - current_dist) / delta_t
    radial_velocity_kmh = radial_velocity_mps * 3.6

    mode = classify_transit_mode(radial_velocity_mps, hint_mode=hint_mode)
    approaching = radial_velocity_mps > 0.8

    if not approaching:
        mode_desc = "Stationary" if mode == TransitMode.STATIONARY else "Departing"
        return ArrivalEstimate(
            distance_meters=current_dist,
            velocity_mps=radial_velocity_mps,
            velocity_kmh=radial_velocity_kmh,
            transit_mode=mode,
            approaching=False,
            eta_seconds_interval=None,
            eta_minutes=None,
            explanation=f"{mode_desc} at {current_dist / 1000.0:.2f}km from destination (speed {abs(radial_velocity_kmh):.1f}km/h).",
        )

    # User is approaching: compute ETA interval to perimeter
    # Distance remaining to threshold
    dist_to_threshold = max(0.0, current_dist - target_threshold_meters)

    if dist_to_threshold == 0.0:
        return ArrivalEstimate(
            distance_meters=current_dist,
            velocity_mps=radial_velocity_mps,
            velocity_kmh=radial_velocity_kmh,
            transit_mode=mode,
            approaching=True,
            eta_seconds_interval=IntervalValue(0.0, 0.0),
            eta_minutes=0.0,
            explanation=f"Inside the {target_threshold_meters:.0f}m target perimeter (current: {current_dist:.0f}m).",
        )

    # Use mode bounds combined with observed velocity for robust interval ETA
    mode_bounds = TRANSIT_MODE_BOUNDS.get(mode, IntervalValue(0.8, 30.0))
    v_min = max(0.5, min(radial_velocity_mps * 0.85, mode_bounds.min_val))
    v_max = max(v_min + 0.1, max(radial_velocity_mps * 1.15, mode_bounds.max_val))

    min_eta_sec = dist_to_threshold / v_max
    max_eta_sec = dist_to_threshold / v_min
    eta_interval = IntervalValue(min_eta_sec, max_eta_sec)
    eta_minutes = (dist_to_threshold / radial_velocity_mps) / 60.0

    min_eta_min = min_eta_sec / 60.0
    max_eta_min = max_eta_sec / 60.0

    explanation = (
        f"Approaching at {radial_velocity_kmh:.1f} km/h ({mode.value} mode). "
        f"Estimated arrival at {target_threshold_meters:.0f}m perimeter in "
        f"{min_eta_min:.1f} - {max_eta_min:.1f} min (midpoint {eta_minutes:.1f} min)."
    )

    return ArrivalEstimate(
        distance_meters=current_dist,
        velocity_mps=radial_velocity_mps,
        velocity_kmh=radial_velocity_kmh,
        transit_mode=mode,
        approaching=True,
        eta_seconds_interval=eta_interval,
        eta_minutes=round(eta_minutes, 1),
        explanation=explanation,
    )
