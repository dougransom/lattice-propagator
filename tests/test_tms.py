"""Unit tests for the Truth Maintenance System (TMS) and provenance tracking."""

import math

from lattice_propagator.lattice import GaussianValue
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
