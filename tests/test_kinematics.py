import math

from lattice_propagator.kinematics import (
    GPSFix,
    TransitMode,
    classify_transit_mode,
    compute_arrival_estimate,
    haversine_distance,
)


def test_haversine_distance_zero():
    """Verify distance between identical coordinates is 0."""
    dist = haversine_distance(37.7749, -122.4194, 37.7749, -122.4194)
    assert math.isclose(dist, 0.0, abs_tol=1e-5)


def test_haversine_distance_known():
    """Verify distance between two known geographic coordinates (SF to LA ~559 km)."""
    # San Francisco: 37.7749, -122.4194
    # Los Angeles: 34.0522, -118.2437
    dist_meters = haversine_distance(37.7749, -122.4194, 34.0522, -118.2437)
    dist_km = dist_meters / 1000.0
    assert 550 < dist_km < 570


def test_classify_transit_mode():
    """Verify classification across transit mode speeds and hints."""
    # Stationary
    assert classify_transit_mode(0.0) == TransitMode.STATIONARY
    assert classify_transit_mode(0.5) == TransitMode.STATIONARY

    # Departing
    assert classify_transit_mode(-1.5) == TransitMode.DEPARTING

    # Walking (~1.4 m/s = 5 km/h)
    assert classify_transit_mode(1.4) == TransitMode.WALKING

    # Cycling (~5.0 m/s = 18 km/h)
    assert classify_transit_mode(5.0) == TransitMode.CYCLING

    # Driving (~16.7 m/s = 60 km/h)
    assert classify_transit_mode(16.7) == TransitMode.DRIVING

    # Hints override/steer
    assert classify_transit_mode(2.5, hint_mode="driving") == TransitMode.DRIVING
    assert classify_transit_mode(1.8, hint_mode="walking") == TransitMode.WALKING
    assert classify_transit_mode(4.0, hint_mode="cycling") == TransitMode.CYCLING


def test_compute_arrival_estimate_initial_fix():
    """Verify first fix yields initial state without crashing."""
    dest_lat, dest_lon = 37.7749, -122.4194
    fix = GPSFix(latitude=37.7849, longitude=-122.4194, timestamp=1000.0)

    estimate = compute_arrival_estimate(
        current_fix=fix,
        previous_fix=None,
        dest_lat=dest_lat,
        dest_lon=dest_lon,
        target_threshold_meters=500.0,
    )

    assert estimate.approaching is False
    assert estimate.eta_minutes is None
    assert estimate.transit_mode == TransitMode.UNKNOWN
    assert estimate.distance_meters > 500.0
    assert "Initial GPS fix" in estimate.explanation


def test_compute_arrival_estimate_approaching_driving():
    """Verify approaching destination at 50 km/h yields accurate ETA and confidence interval."""
    # Home at (0, 0)
    dest_lat, dest_lon = 0.0, 0.0

    # Fix 1: 5000 meters north at t=0
    # ~1 deg lat = 111,139 meters => 5000m ~= 0.045 deg lat
    lat_5000m = 5000.0 / 111139.0
    fix1 = GPSFix(latitude=lat_5000m, longitude=0.0, timestamp=0.0)

    # Fix 2: 60 seconds later, moved 833 meters closer (13.88 m/s = 50 km/h)
    lat_4167m = (5000.0 - 833.0) / 111139.0
    fix2 = GPSFix(latitude=lat_4167m, longitude=0.0, timestamp=60.0)

    estimate = compute_arrival_estimate(
        current_fix=fix2,
        previous_fix=fix1,
        dest_lat=dest_lat,
        dest_lon=dest_lon,
        target_threshold_meters=500.0,
    )

    assert estimate.approaching is True
    assert estimate.transit_mode == TransitMode.DRIVING
    assert 13.0 < estimate.velocity_mps < 15.0
    assert 48.0 < estimate.velocity_kmh < 52.0

    # Distance to 500m threshold is ~3667 meters
    # Time at ~13.88 m/s is ~264 seconds (~4.4 minutes)
    assert estimate.eta_minutes is not None
    assert 4.0 < estimate.eta_minutes < 5.0
    assert estimate.eta_seconds_interval is not None
    assert estimate.eta_seconds_interval.min_val <= estimate.eta_seconds_interval.max_val
    assert "Approaching at" in estimate.explanation


def test_compute_arrival_estimate_inside_perimeter():
    """Verify entity inside the perimeter returns 0 ETA."""
    dest_lat, dest_lon = 0.0, 0.0
    # 200m from destination
    lat_200m = 200.0 / 111139.0
    lat_300m = 300.0 / 111139.0
    fix1 = GPSFix(latitude=lat_300m, longitude=0.0, timestamp=0.0)
    fix2 = GPSFix(latitude=lat_200m, longitude=0.0, timestamp=10.0)

    estimate = compute_arrival_estimate(
        current_fix=fix2,
        previous_fix=fix1,
        dest_lat=dest_lat,
        dest_lon=dest_lon,
        target_threshold_meters=500.0,
    )

    assert estimate.approaching is True
    assert estimate.eta_minutes == 0.0
    assert "Inside the 500m target perimeter" in estimate.explanation


def test_compute_arrival_estimate_departing():
    """Verify moving away sets approaching=False and mode=departing."""
    dest_lat, dest_lon = 0.0, 0.0
    lat_1000m = 1000.0 / 111139.0
    lat_1500m = 1500.0 / 111139.0
    fix1 = GPSFix(latitude=lat_1000m, longitude=0.0, timestamp=0.0)
    fix2 = GPSFix(latitude=lat_1500m, longitude=0.0, timestamp=30.0)

    estimate = compute_arrival_estimate(
        current_fix=fix2,
        previous_fix=fix1,
        dest_lat=dest_lat,
        dest_lon=dest_lon,
        target_threshold_meters=500.0,
    )

    assert estimate.approaching is False
    assert estimate.transit_mode == TransitMode.DEPARTING
    assert estimate.eta_minutes is None
    assert "Departing" in estimate.explanation


def test_compute_arrival_estimate_zero_delta_t():
    """Verify handling when delta_t is 0 or negative."""
    dest_lat, dest_lon = 0.0, 0.0
    fix1 = GPSFix(latitude=0.01, longitude=0.0, timestamp=100.0)
    fix2 = GPSFix(latitude=0.01, longitude=0.0, timestamp=100.0)

    estimate = compute_arrival_estimate(
        current_fix=fix2,
        previous_fix=fix1,
        dest_lat=dest_lat,
        dest_lon=dest_lon,
    )
    assert estimate.transit_mode == TransitMode.STATIONARY
