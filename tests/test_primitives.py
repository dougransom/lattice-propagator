"""Unit tests for the Generalized Propagator Network Primitives."""

import math

from lattice_propagator.lattice import (
    Contradiction,
    DiscreteDomain,
    GaussianValue,
    IntervalValue,
)
from lattice_propagator.primitives import (
    AllDifferentPropagator,
    ArithmeticPropagator,
    DynamicScenePropagator,
    ElasticModulatorPropagator,
    KalmanEstimatorPropagator,
    LagPropagator,
    PropagatorNetwork,
    RatePropagator,
    ScenePhase,
    ThresholdPropagator,
)


def test_arithmetic_propagator_gaussian():
    """Verify linear combination of Gaussian random variables (e.g. power balance)."""
    net = PropagatorNetwork("PowerBalance")
    solar = net.add_cell("Solar", GaussianValue(mean=5000.0, variance=100.0))
    load = net.add_cell("Load", GaussianValue(mean=2000.0, variance=50.0))
    net_power = net.add_cell("NetPower")

    # Net = 1.0 * Solar - 1.0 * Load
    p = ArithmeticPropagator(
        "PowerCalc", inputs=[solar, load], output=net_power, weights=[1.0, -1.0]
    )
    net.add_propagator(p)
    net.run()

    res = net_power.value
    assert isinstance(res, GaussianValue)
    # Expected mean: 5000 - 2000 = 3000
    assert math.isclose(res.mean, 3000.0, abs_tol=1e-3)
    # Expected variance: 100 + 50 = 150
    assert math.isclose(res.variance, 150.0, abs_tol=1e-3)


def test_arithmetic_propagator_intervals():
    """Verify interval arithmetic propagation."""
    net = PropagatorNetwork("IntervalSum")
    c1 = net.add_cell("C1", IntervalValue(10.0, 20.0))
    c2 = net.add_cell("C2", IntervalValue(5.0, 15.0))
    c3 = net.add_cell("C3")

    p = ArithmeticPropagator("Sum", inputs=[c1, c2], output=c3, weights=[1.0, 1.0])
    net.add_propagator(p)
    net.run()

    res = c3.value
    assert isinstance(res, IntervalValue)
    assert math.isclose(res.min_val, 15.0, abs_tol=1e-3)
    assert math.isclose(res.max_val, 35.0, abs_tol=1e-3)


def test_rate_propagator_and_eta():
    """Verify rate calculations and time-to-threshold interval estimation."""
    net = PropagatorNetwork("Rate")
    pos = net.add_cell("Distance")
    speed = net.add_cell("Speed")
    eta = net.add_cell("ETA")

    rate_p = RatePropagator(
        "Kinematics", input_cell=pos, output_rate_cell=speed, output_eta_cell=eta, threshold=500.0
    )
    net.add_propagator(rate_p)

    # Observation 1: 5000m at t=0
    rate_p.update_observation(5000.0, 0.0, net)
    net.run()

    # Observation 2: 4000m at t=50s (moving closer at -20 m/s = 72 km/h)
    rate_p.update_observation(4000.0, 50.0, net)
    net.run()

    speed_val = speed.value
    assert isinstance(speed_val, GaussianValue)
    assert math.isclose(speed_val.mean, -20.0, abs_tol=1e-3)

    eta_val = eta.value
    assert isinstance(eta_val, IntervalValue)
    # Distance to threshold (500m) is 4000 - 500 = 3500m
    # Nominal time = 3500 / 20 = 175s
    # Bounds [175 * 0.85, 175 * 1.2] = [148.75, 210.0]
    assert 140.0 < eta_val.min_val < 155.0
    assert 200.0 < eta_val.max_val < 220.0


def test_lag_propagator_thermal_inertia():
    """Verify first-order RC thermal lag modeling (exponential smoothing)."""
    net = PropagatorNetwork("ThermalLag")
    outdoor = net.add_cell("Outdoor", GaussianValue(mean=30.0, variance=0.1))
    indoor = net.add_cell("Indoor", GaussianValue(mean=20.0, variance=0.1))
    projected = net.add_cell("Projected")

    # Building thermal time constant tau = 10.0 hours (or arbitrary time unit)
    lag = LagPropagator(
        "BuildingLag", target_cell=outdoor, state_cell=indoor, output_cell=projected, tau=10.0
    )
    net.add_propagator(lag)

    # Step by dt = 1.0 time unit
    lag.step(dt=1.0)
    res = projected.value
    assert isinstance(res, GaussianValue)
    # alpha = 1 - exp(-1/10) ~= 0.09516
    # next_mu = 20 + 0.09516 * (30 - 20) ~= 20.95
    assert 20.9 < res.mean < 21.1


def test_elastic_modulator_tou_pricing():
    """Verify comfort band target modulation driven by electricity tariff / solar signal."""
    net = PropagatorNetwork("ComfortOptimizer")
    price = net.add_cell("Tariff")
    target = net.add_cell("EffectiveTarget")

    # Comfort interval: [20.0°C, 22.5°C], nominal = 21.0°C, baseline price = $0.20/kWh
    # Sensitivity = 10.0 (°C per $/kWh)
    modulator = ElasticModulatorPropagator(
        name="TOUModulator",
        signal_cell=price,
        output_cell=target,
        acceptable_range=IntervalValue(20.0, 22.5),
        nominal_target=21.0,
        baseline_signal=0.20,
        sensitivity=10.0,
    )
    net.add_propagator(modulator)

    # Scenario A: Peak Price ($0.45/kWh) -> Target relaxes down to min comfort (20.0°C)
    price.set_value(GaussianValue(mean=0.45, variance=0.001))
    net.run()
    res_peak = target.value
    assert isinstance(res_peak, GaussianValue)
    # Adjustment = 10.0 * (0.20 - 0.45) = -2.5 -> 21.0 - 2.5 = 18.5 -> clamped to 20.0°C
    assert math.isclose(res_peak.mean, 20.0, abs_tol=1e-3)

    # Scenario B: Negative / Cheap Price ($0.05/kWh) -> Target tightens up to max comfort (22.5°C, pre-heating)
    price.set_value(GaussianValue(mean=0.05, variance=0.001), overwrite=True)
    net.run()
    res_cheap = target.value
    assert isinstance(res_cheap, GaussianValue)
    # Adjustment = 10.0 * (0.20 - 0.05) = +1.5 -> 21.0 + 1.5 = 22.5 -> clamped to 22.5°C
    assert math.isclose(res_cheap.mean, 22.5, abs_tol=1e-3)


def test_threshold_propagator():
    """Verify threshold comparator triggering."""
    net = PropagatorNetwork("AlertThreshold")
    temp = net.add_cell("Temp", GaussianValue(mean=18.5, variance=0.1))
    freeze_alert = net.add_cell("FreezeAlert")

    p = ThresholdPropagator(
        "FreezeDetector", input_cell=temp, output_bool_cell=freeze_alert, threshold=19.0, below=True
    )
    net.add_propagator(p)
    net.run()

    val = freeze_alert.value
    assert isinstance(val, IntervalValue)
    assert val.min_val == 1.0  # Triggered!


def test_propagator_network_mermaid():
    """Verify Mermaid diagram generation for composed network."""
    net = PropagatorNetwork("SimpleNet")
    c1 = net.add_cell("A", GaussianValue(mean=1.0, variance=0.1))
    c2 = net.add_cell("B")
    p = ArithmeticPropagator("Adder", inputs=[c1], output=c2, offset=5.0)
    net.add_propagator(p)
    net.run()

    mermaid = net.generate_mermaid()
    assert "graph LR" in mermaid
    assert "P_Adder" in mermaid
    assert "C_A" in mermaid


def test_lag_propagator_intervals():
    """Verify lag propagation with interval bounds."""
    net = PropagatorNetwork("IntervalLag")
    t = net.add_cell("Target", IntervalValue(20.0, 25.0))
    s = net.add_cell("State", IntervalValue(10.0, 15.0))
    out = net.add_cell("Out")

    lag = LagPropagator("Lag", target_cell=t, state_cell=s, output_cell=out, tau=5.0)
    net.add_propagator(lag)
    lag.step(dt=2.5)

    res = out.value
    assert isinstance(res, IntervalValue)
    assert 10.0 < res.min_val < 20.0
    assert 15.0 < res.max_val < 25.0


def test_rate_propagator_from_interval_and_threshold_above():
    """Verify rate propagator alert with interval input and threshold above."""
    net = PropagatorNetwork("IntervalRate")
    pos = net.add_cell("Pos", IntervalValue(100.0, 200.0))
    rate = net.add_cell("Rate")
    p = RatePropagator("RateP", input_cell=pos, output_rate_cell=rate)
    net.add_propagator(p)
    net.run()

    # Threshold above
    val = net.add_cell("Val", GaussianValue(mean=25.0, variance=0.1))
    alert = net.add_cell("Alert")
    tp = ThresholdPropagator(
        "HeatAlert", input_cell=val, output_bool_cell=alert, threshold=24.0, below=False
    )
    net.add_propagator(tp)
    net.run()

    res = alert.value
    assert isinstance(res, IntervalValue)
    assert res.min_val == 1.0


def test_all_different_propagator_chain():
    """Verify chain deduction (naked singles) with AllDifferentPropagator."""
    net = PropagatorNetwork("NakedSinglesChain")
    c1 = net.add_cell("C1", DiscreteDomain.single(1))
    c2 = net.add_cell("C2", DiscreteDomain(candidates={1, 2}))
    c3 = net.add_cell("C3", DiscreteDomain(candidates={1, 2, 3}))

    p = AllDifferentPropagator("AllDiff", [c1, c2, c3])
    net.add_propagator(p)
    net.run()

    assert c1.value.value == 1
    assert c2.value.value == 2
    assert c3.value.value == 3


def test_all_different_propagator_hidden_singles():
    """Verify hidden single deduction in a discrete domain unit."""
    net = PropagatorNetwork("HiddenSingles")
    c1 = net.add_cell("C1", DiscreteDomain(candidates={1, 2}))
    c2 = net.add_cell("C2", DiscreteDomain(candidates={1, 3}))
    c3 = net.add_cell("C3", DiscreteDomain(candidates={1, 2, 3, 4}))

    p = AllDifferentPropagator("AllDiff", [c1, c2, c3])
    net.add_propagator(p)
    net.run()

    # 4 only exists in c3, so c3 collapses to 4
    assert c3.value.is_determined
    assert c3.value.value == 4


def test_all_different_propagator_duplicate_contradiction():
    """Verify contradiction detection when two cells share the same determined value."""
    net = PropagatorNetwork("DuplicateConflict")
    c1 = net.add_cell("C1", DiscreteDomain.single(5))
    c2 = net.add_cell("C2", DiscreteDomain.single(5))

    p = AllDifferentPropagator("AllDiff", [c1, c2])
    net.add_propagator(p)
    net.run()

    assert any(isinstance(c.value, Contradiction) for c in [c1, c2])


def test_all_different_propagator_exhaustion_contradiction():
    """Verify contradiction detection when eliminating a value exhausts a cell's candidate set."""
    net = PropagatorNetwork("ExhaustionConflict")
    c1 = net.add_cell("C1", DiscreteDomain.single(1))
    c2 = net.add_cell("C2", DiscreteDomain.single(2))
    # C3 can only be 1 or 2, but both are claimed by peers
    c3 = net.add_cell("C3", DiscreteDomain(candidates={1, 2}))

    p = AllDifferentPropagator("AllDiff", [c1, c2, c3])
    net.add_propagator(p)
    net.run()

    assert isinstance(c3.value, Contradiction)
    assert "exhausted all candidates" in c3.value.reason


def test_kalman_estimator_constant_velocity():
    """Verify linear Kalman estimator tracks position and velocity under constant speed."""
    net = PropagatorNetwork("KalmanTracking")
    meas = net.add_cell("RawDistance")
    est_pos = net.add_cell("EstimatedDistance")
    est_vel = net.add_cell("EstimatedVelocity")

    kf = KalmanEstimatorPropagator(
        "Tracker",
        measurement_cell=meas,
        output_state_cell=est_pos,
        output_rate_cell=est_vel,
        process_noise_q=0.05,
        default_measurement_noise_r=4.0,
    )
    net.add_propagator(kf)

    # True trajectory: x(t) = 1000 - 20 * t (moving towards home at 20 m/s)
    true_v = -20.0
    for t in range(15):
        noisy_z = 1000.0 + true_v * t + (0.5 if t % 2 == 0 else -0.5)
        kf.step(noisy_z, r=4.0, dt=1.0)

    # Check that estimated position and velocity have converged closely
    pos_val = est_pos.value
    vel_val = est_vel.value
    assert isinstance(pos_val, GaussianValue)
    assert isinstance(vel_val, GaussianValue)

    # Expected position at t=14 is 1000 - 280 = 720
    assert abs(pos_val.mean - 720.0) < 5.0
    # Expected velocity is -20.0 m/s
    assert abs(vel_val.mean - true_v) < 2.0
    # Posterior variance should have narrowed from initial 100.0/10.0
    assert pos_val.variance < 4.0
    assert vel_val.variance < 2.0


def test_kalman_estimator_spike_rejection():
    """Verify that an isolated measurement spike is smoothed out by the filter."""
    net = PropagatorNetwork("KalmanSpikeTest")
    meas = net.add_cell("Temp")
    est_temp = net.add_cell("EstTemp")
    est_rate = net.add_cell("EstRate")

    kf = KalmanEstimatorPropagator(
        "TempFilter",
        measurement_cell=meas,
        output_state_cell=est_temp,
        output_rate_cell=est_rate,
        process_noise_q=0.01,
        default_measurement_noise_r=1.0,
    )

    # Steady state around 21.0C
    for _ in range(10):
        kf.step(21.0, r=1.0, dt=1.0)

    assert abs(est_temp.value.mean - 21.0) < 0.1
    assert abs(est_rate.value.mean) < 0.05

    # Sudden one-off sensor glitch spike: 28.0C
    kf.step(28.0, r=1.0, dt=1.0)

    # The filter dampens the 7.0C spike significantly
    assert est_temp.value.mean < 25.0

    # Next reading returns to normal (21.1C)
    kf.step(21.1, r=1.0, dt=1.0)
    assert est_temp.value.mean < 23.5

    # Subsequent readings converge back to baseline
    for _ in range(5):
        kf.step(21.0, r=1.0, dt=1.0)
    assert abs(est_temp.value.mean - 21.0) < 0.2


def test_kalman_estimator_network_reactive_alert():
    """Verify KalmanEstimatorPropagator reacts when cell values update in a PropagatorNetwork."""
    net = PropagatorNetwork("ReactiveKalman")
    meas = net.add_cell("Observation")
    pos = net.add_cell("State")
    rate = net.add_cell("Rate")

    kf = KalmanEstimatorPropagator(
        "KF",
        measurement_cell=meas,
        output_state_cell=pos,
        output_rate_cell=rate,
        process_noise_q=0.1,
    )
    net.add_propagator(kf)

    # Initial measurement via Gaussian
    meas.set_value(GaussianValue(mean=50.0, variance=0.5))
    net.run()

    assert isinstance(pos.value, GaussianValue)
    assert pos.value.mean == 50.0
    assert isinstance(rate.value, GaussianValue)
    assert rate.value.mean == 0.0

    # Observation via IntervalValue
    meas.set_value(IntervalValue(min_val=51.0, max_val=53.0), overwrite=True)
    net.run()

    assert isinstance(pos.value, GaussianValue)
    assert 50.0 < pos.value.mean < 53.0

    # Reset
    kf.reset(x=10.0, v=2.0)
    assert kf.x == 10.0
    assert kf.v == 2.0


def test_dynamic_scene_propagator_lifecycle():
    """Verify DynamicScenePropagator multi-phase temporal progression and deactivation."""
    net = PropagatorNetwork("WakeupScene")
    scene_active = net.add_cell("SceneActive", DiscreteDomain.single(True))
    light_target = net.add_cell("LightTarget")
    scene_phase = net.add_cell("CurrentPhase")

    phases = [
        ScenePhase(
            name="Dawn",
            duration_seconds=60.0,
            bounds=IntervalValue(0.01, 0.10),
            transition="linear",
        ),
        ScenePhase(
            name="Sunrise",
            duration_seconds=120.0,
            bounds=IntervalValue(0.10, 0.70),
            transition="linear",
        ),
        ScenePhase(
            name="Full", duration_seconds=60.0, bounds=IntervalValue(0.70, 1.00), transition="step"
        ),
    ]

    scene_prop = DynamicScenePropagator(
        "WakeupTrajectory",
        active_cell=scene_active,
        output_target_cell=light_target,
        phases=phases,
        output_phase_cell=scene_phase,
    )
    net.add_propagator(scene_prop)
    net.run()

    # t = 0: Initial evaluation at start of Dawn phase
    assert isinstance(light_target.value, IntervalValue)
    assert math.isclose(light_target.value.min_val, 0.01)
    assert math.isclose(light_target.value.max_val, 0.10)
    assert scene_phase.value == DiscreteDomain.single("Dawn")

    # t = 30s: Halfway through Dawn (linear interpolation from [0.01, 0.10] to [0.01, 0.10] is [0.01, 0.10])
    scene_prop.evaluate_at(30.0)
    assert math.isclose(light_target.value.min_val, 0.01)
    assert math.isclose(light_target.value.max_val, 0.10)

    # t = 120s: 60s into Sunrise phase (halfway through Sunrise, interpolated from [0.01, 0.10] to [0.10, 0.70])
    # progress = (120 - 60) / 120 = 0.5
    # min_val = 0.01 + 0.5 * (0.10 - 0.01) = 0.055
    # max_val = 0.10 + 0.5 * (0.70 - 0.10) = 0.40
    scene_prop.evaluate_at(120.0)
    assert scene_phase.value == DiscreteDomain.single("Sunrise")
    assert math.isclose(light_target.value.min_val, 0.055, abs_tol=1e-3)
    assert math.isclose(light_target.value.max_val, 0.40, abs_tol=1e-3)

    # t = 180s: Start of Full phase (step transition)
    scene_prop.evaluate_at(180.0)
    assert scene_phase.value == DiscreteDomain.single("Full")
    assert math.isclose(light_target.value.min_val, 0.70)
    assert math.isclose(light_target.value.max_val, 1.00)

    # Stepping dt forwards
    scene_prop.step(10.0)
    assert scene_phase.value == DiscreteDomain.single("Full")

    # Scene deactivation -> automatic relaxation to BOTTOM
    scene_active.set_value(DiscreteDomain.single(False), overwrite=True)
    net.run()
    from lattice_propagator.lattice import BOTTOM

    assert light_target.value == BOTTOM
    assert scene_phase.value == BOTTOM


def test_dynamic_scene_modifiers_and_clamping():
    """Verify contextual reference cell modulation, reactive modifiers, and envelope clamping."""
    net = PropagatorNetwork("CinemaScene")
    scene_active = net.add_cell("CinemaActive", DiscreteDomain.single("active"))
    tv_paused = net.add_cell("TVPaused", DiscreteDomain.single(False))
    circadian_cct = net.add_cell("CircadianCCT", IntervalValue(2200.0, 2700.0))
    cct_target = net.add_cell("CCTTarget")

    phases = [
        ScenePhase(
            name="CinemaDim",
            duration_seconds=100.0,
            bounds=IntervalValue(2000.0, 3200.0),
            transition="step",
        )
    ]

    scene_prop = DynamicScenePropagator(
        "CinemaLighting",
        active_cell=scene_active,
        output_target_cell=cct_target,
        phases=phases,
        reference_cell=circadian_cct,
        modifier_cell=tv_paused,
        modifier_delta=200.0,  # Boost color temperature slightly when paused
        clamp_bounds=IntervalValue(1800.0, 3000.0),
    )
    net.add_propagator(scene_prop)
    net.run()

    # Base evaluation: [2000, 3200] clamped with circadian [2200, 2700] -> [2200, 2700]
    assert isinstance(cct_target.value, IntervalValue)
    assert math.isclose(cct_target.value.min_val, 2200.0)
    assert math.isclose(cct_target.value.max_val, 2700.0)

    # TV pauses -> modifier applies (+200 K) -> [2400, 2900], within clamp envelope [1800, 3000]
    tv_paused.set_value(DiscreteDomain.single(True), overwrite=True)
    net.run()
    assert math.isclose(cct_target.value.min_val, 2400.0)
    assert math.isclose(cct_target.value.max_val, 2900.0)
