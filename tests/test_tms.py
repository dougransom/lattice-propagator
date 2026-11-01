"""Unit tests for the Truth Maintenance System (TMS) and provenance tracking."""

import math

from lattice_propagator.lattice import GaussianValue, IntervalValue
from lattice_propagator.tms import TruthMaintenanceSystem


def test_tms_basic_fusion() -> None:
    """Test asserting evidence from two sensors and computing fused result."""
    tms = TruthMaintenanceSystem(cell_id="living_room_temp")
    tms.assert_evidence("sensor.thermostat", GaussianValue(mean=21.0, variance=0.1))
    tms.assert_evidence("sensor.radiator", GaussianValue(mean=22.0, variance=0.5))

    fused = tms.compute_fused_value()
    assert isinstance(fused, GaussianValue)
    # Merged variance should be lower than either individual sensor
    assert fused.variance < 0.1
    assert 21.0 < fused.mean < 22.0
    assert not tms.is_degraded
    assert tms.data_quality == 1.0
    assert "sensor.thermostat" in tms.active_sources
    assert "sensor.radiator" in tms.active_sources


def test_tms_retraction_and_degradation() -> None:
    """Test retraction of a premise when a sensor drops offline."""
    tms = TruthMaintenanceSystem(cell_id="office_temp")
    tms.assert_evidence("sensor.zigbee", GaussianValue(mean=20.5, variance=0.08))
    tms.assert_evidence("sensor.ble", GaussianValue(mean=21.0, variance=0.25))

    # Initial fusion
    fused_initial = tms.compute_fused_value()
    assert isinstance(fused_initial, GaussianValue)

    # Zigbee battery dies / goes unavailable
    tms.retract_evidence("sensor.zigbee", reason="unavailable")

    assert tms.is_degraded
    assert tms.missing_sources == ["sensor.zigbee"]
    assert tms.active_sources == ["sensor.ble"]
    assert math.isclose(tms.data_quality, 0.5)

    # Fused value should now strictly equal BLE reading alone with wider variance
    fused_degraded = tms.compute_fused_value()
    assert isinstance(fused_degraded, GaussianValue)
    assert math.isclose(fused_degraded.mean, 21.0)
    assert math.isclose(fused_degraded.variance, 0.25)
    assert fused_degraded.variance > fused_initial.variance


def test_tms_all_retracted_prior_fallback() -> None:
    """Test fallback to default prior when all sources are retracted."""
    prior = GaussianValue(mean=20.0, variance=4.0)
    tms = TruthMaintenanceSystem(cell_id="temp", default_prior=prior)

    tms.assert_evidence("sensor.s1", GaussianValue(mean=22.0, variance=0.1))
    tms.retract_evidence("sensor.s1")

    assert tms.compute_fused_value() == prior
    assert not tms.is_degraded  # Zero active sources, completely uncorroborated
    assert tms.data_quality == 0.0


def test_tms_explanation() -> None:
    """Test human-readable explanation generation."""
    tms = TruthMaintenanceSystem(cell_id="temp")
    tms.assert_evidence("sensor.living_room_temp", GaussianValue(mean=21.2, variance=0.1))
    tms.assert_evidence("sensor.radiator_temp", GaussianValue(mean=21.8, variance=0.4))

    explanation = tms.explain(unit="°C")
    assert "Combining living_room_temp (21.2°C), radiator_temp (21.8°C)" in explanation

    # Retract one
    tms.retract_evidence("sensor.radiator_temp")
    degraded_explanation = tms.explain(unit="°C")
    assert "Degraded state; radiator_temp is offline" in degraded_explanation


def test_tms_mermaid_generation() -> None:
    """Test Mermaid diagram generation."""
    tms = TruthMaintenanceSystem(cell_id="climate")
    tms.assert_evidence("sensor.thermostat", GaussianValue(mean=21.0, variance=0.1))
    tms.assert_evidence("sensor.window", GaussianValue(mean=19.0, variance=0.5))
    tms.retract_evidence("sensor.window", reason="offline")

    mermaid = tms.generate_mermaid()
    assert "```mermaid" in mermaid
    assert "graph LR" in mermaid
    assert "sensor_thermostat" in mermaid
    assert "OFFLINE" in mermaid


def test_tms_unitless_default() -> None:
    """Verify that omitting units defaults to dimensionless pure numbers without assuming °C."""
    tms = TruthMaintenanceSystem(cell_id="speed_ratio")
    tms.assert_evidence("sensor.ratio_a", GaussianValue(mean=1.5, variance=0.01))
    tms.assert_evidence("sensor.ratio_b", GaussianValue(mean=1.7, variance=0.01))

    explanation = tms.explain()
    assert "°C" not in explanation
    assert "Combining ratio_a (1.5), ratio_b (1.7) into 1.6" in explanation


def test_tms_custom_engineering_units() -> None:
    """Verify domain-agnostic custom engineering units (e.g. m/s, W, $/kWh)."""
    tms = TruthMaintenanceSystem(cell_id="velocity", unit=" m/s")
    tms.assert_evidence("sensor.gps_vel", IntervalValue(12.0, 15.0))
    tms.assert_evidence("sensor.imu_vel", IntervalValue(13.0, 16.0))

    explanation = tms.explain()
    assert (
        "Intersecting gps_vel [12.0, 15.0] m/s, imu_vel [13.0, 16.0] m/s into [13.0, 15.0] m/s."
        == explanation
    )


def test_tms_interval_explanation() -> None:
    """Test explanation of interval bounding intersections."""
    tms = TruthMaintenanceSystem(cell_id="comfort_band", unit="°C")
    tms.assert_evidence("policy.user_comfort", IntervalValue(19.0, 23.0))
    tms.assert_evidence("rule.solar_upper_bound", IntervalValue(20.5, 25.0))

    explanation = tms.explain()
    assert "Intersecting" in explanation
    assert "policy.user_comfort [19.0, 23.0]°C" in explanation
    assert "rule.solar_upper_bound [20.5, 25.0]°C" in explanation
    assert "[20.5, 23.0]°C" in explanation


def test_tms_discrete_domain_explanation() -> None:
    """Test explanation of DiscreteDomain possibility reductions."""
    from lattice_propagator.lattice import DiscreteDomain

    tms = TruthMaintenanceSystem(cell_id="hvac_candidates")
    tms.assert_evidence("season_rule", DiscreteDomain({"heat", "fan_only"}))
    tms.assert_evidence("occupancy_rule", DiscreteDomain({"heat", "cool"}))

    explanation = tms.explain()
    assert "Constrained candidate states from" in explanation
    assert "{heat}" in explanation


def test_tms_contradiction_actionable_diagnostic() -> None:
    """Test that contradictions produce actionable diagnostics with DDB retraction advice."""
    from lattice_propagator.lattice import FlatValue

    tms = TruthMaintenanceSystem(cell_id="heater_power")
    # Ground truth (non-defeasible)
    tms.assert_evidence("physical_switch", FlatValue("off"), is_assumption=False)
    # Defeasible assumption
    tms.assert_evidence(
        "occupancy_automation",
        FlatValue("on"),
        is_assumption=True,
        confidence=0.65,
    )

    explanation = tms.explain()
    assert "Contradiction detected on heater_power" in explanation
    assert "physical_switch=off (ground, conf=1.00)" in explanation
    assert "occupancy_automation=on (assumption, conf=0.65)" in explanation
    assert (
        "Recommendation: Retract assumption 'occupancy_automation' (confidence=0.65)."
        in explanation
    )


def test_multihop_causal_explanation() -> None:
    """Test multi-hop causal provenance traversal across propagators."""
    from lattice_propagator.primitives import (
        ArithmeticPropagator,
        PropagatorNetwork,
        ThresholdPropagator,
    )

    net = PropagatorNetwork("ClimateCascade")
    t1 = net.add_cell("living_room_temp", unit="°C")
    t2 = net.add_cell("hallway_temp", unit="°C")
    avg_temp = net.add_cell("avg_temp", unit="°C")
    heater_alert = net.add_cell("heater_alert")

    # avg_temp = 0.5 * t1 + 0.5 * t2
    net.add_propagator(
        ArithmeticPropagator(
            "AverageTemp",
            inputs=[t1, t2],
            output=avg_temp,
            weights=[0.5, 0.5],
        )
    )

    # heater_alert = True if avg_temp < 19.0
    net.add_propagator(
        ThresholdPropagator(
            "HeaterTrigger",
            input_cell=avg_temp,
            output_bool_cell=heater_alert,
            threshold=19.0,
            below=True,
        )
    )

    # Set sensors (cold readings)
    t1.set_value(GaussianValue(mean=18.0, variance=0.1), source="sensor.t1")
    t2.set_value(GaussianValue(mean=18.4, variance=0.1), source="sensor.t2")

    # Propagate
    net.run()

    # Local explanation (depth=1) for heater_alert
    local_explain = heater_alert.explain(depth=1)
    assert "Deduced by ThresholdPropagator from avg_temp" in local_explain

    # Multi-hop causal tree (depth=None)
    causal_explain = net.explain("heater_alert", depth=None)
    assert "Deduced by ThresholdPropagator from avg_temp" in causal_explain
    assert "└── [ThresholdPropagator]" in causal_explain
    assert (
        "Deduced by ArithmeticPropagator from living_room_temp, hallway_temp: 18.2°C"
        in causal_explain
    )
    assert "└── [ArithmeticPropagator]" in causal_explain
    assert "Combining t1 (18.0°C) into 18.0°C" in causal_explain
    assert "Combining t2 (18.4°C) into 18.4°C" in causal_explain


def test_tms_explanation_node_structure_and_serialization() -> None:
    """Test that explain_node produces structured, serializable ExplanationNode trees."""
    tms = TruthMaintenanceSystem(cell_id="living_room_temp", unit="°C")
    tms.assert_evidence("sensor.thermostat", GaussianValue(mean=21.0, variance=0.1))
    tms.assert_evidence("sensor.radiator", GaussianValue(mean=22.0, variance=0.2))

    node = tms.explain_node()
    assert node.key == "tms.gaussian_fusion"
    assert node.cell_id == "living_room_temp"
    assert not node.is_degraded
    assert not node.is_contradiction
    assert "thermostat" in node.parameters["sources"]
    assert "radiator" in node.parameters["sources"]

    data = node.to_dict()
    assert data["key"] == "tms.gaussian_fusion"
    assert data["cell_id"] == "living_room_temp"
    assert data["is_degraded"] is False
    assert "parameters" in data
    assert "sources" in data["parameters"]


def test_tms_translator_injection_and_template_overrides() -> None:
    """Test custom Translator callable and make_template_translator for i18n support."""
    from lattice_propagator import make_template_translator

    # Custom French templates for Home Assistant localization demonstration
    fr_templates = {
        "tms.gaussian_fusion": "{prefix}Combinaison de {sources} pour obtenir {mean:.1f}{unit} (±{spread:.2f}{unit}).{degraded_note}",
        "tms.degraded_note": " Remarque: état dégradé; {missing} est hors ligne.",
    }
    fr_translator = make_template_translator(fr_templates)

    tms = TruthMaintenanceSystem(cell_id="salon_temp", unit="°C", translator=fr_translator)
    tms.assert_evidence("sensor.thermostat", GaussianValue(mean=21.0, variance=0.1))
    tms.assert_evidence("sensor.zigbee", GaussianValue(mean=22.0, variance=0.2))

    # Verify translated output
    fr_explain = tms.explain()
    assert "Combinaison de" in fr_explain
    assert "pour obtenir" in fr_explain

    # Simulate sensor offline (degraded state)
    tms.retract_evidence("sensor.zigbee", reason="offline")
    degraded_explain = tms.explain()
    assert "Remarque: état dégradé; zigbee est hors ligne." in degraded_explain

    # Verify per-call override
    en_explain = tms.explain(translator=lambda k, default, p: default.format(**p))
    assert "Combining" in en_explain
    assert "Note: Degraded state; zigbee is offline." in en_explain


def test_tms_contradiction_translation() -> None:
    """Test localization of contradiction diagnostics and actionable recommendations."""
    from lattice_propagator import FlatValue, make_template_translator

    custom_templates = {
        "tms.contradiction": "CONFLIT DÉTECTÉ sur {cell_name}. Prémisses: {premises}. {recommendation}",
        "tms.recommend_retract": "Conseil: Rétracter l'hypothèse '{source_id}' (confiance={confidence:.2f}).",
    }
    translator = make_template_translator(custom_templates)

    tms = TruthMaintenanceSystem(cell_id="safety_switch", translator=translator)
    tms.assert_evidence("ground_sensor", FlatValue("off"), is_assumption=False)
    tms.assert_evidence("user_rule", FlatValue("on"), is_assumption=True, confidence=0.7)

    diag = tms.explain()
    assert "CONFLIT DÉTECTÉ sur safety_switch" in diag
    assert "Conseil: Rétracter l'hypothèse 'user_rule' (confiance=0.70)." in diag


def test_cell_and_network_explain_node_and_translator() -> None:
    """Test explain_node and translator pass-through on Cell and PropagatorNetwork."""
    from lattice_propagator import PropagatorNetwork, make_template_translator

    net = PropagatorNetwork("TestNet")
    c = net.add_cell("temp", unit="°C")
    c.set_value(GaussianValue(mean=20.0, variance=0.1), source="sensor.t1")

    node = net.explain_node("temp")
    assert node.key == "tms.gaussian_fusion"
    assert node.cell_id == "temp"

    cell_node = c.explain_node()
    assert cell_node.cell_id == "temp"

    de_translator = make_template_translator(
        {
            "tms.gaussian_fusion": "Kombiniere {sources} zu {mean:.1f}{unit} (±{spread:.2f}{unit}).{degraded_note}"
        }
    )
    de_explain = net.explain("temp", translator=de_translator)
    assert de_explain.startswith("Kombiniere t1 (20.0°C) zu 20.0°C")
