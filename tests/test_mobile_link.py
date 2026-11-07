"""Tests for π-calculus MobileLinkPropagator and Cell.retract_source."""

from __future__ import annotations

from lattice_propagator import (
    BOTTOM,
    AdderPropagator,
    BeliefMassValue,
    Contradiction,
    DiscreteDomain,
    IntervalValue,
    MobileLinkPropagator,
    NetworkTMS,
    OrderedInterval,
    PropagatorNetwork,
    SetLattice,
)


def test_mobile_link_handoff_and_retraction() -> None:
    """Verify π-calculus channel handoff between rooms and automatic TMS retraction."""
    net = PropagatorNetwork("RoomMobility")

    office = net.add_cell("zone.office", unit="°C")
    kitchen = net.add_cell("zone.kitchen", unit="°C")
    office.set_value(IntervalValue(18.0, 26.0), source="base_policy")
    kitchen.set_value(IntervalValue(18.0, 26.0), source="base_policy")

    doug_pref = net.add_cell("pref.doug", IntervalValue(20.0, 22.0))
    doug_loc = net.add_cell("loc.doug")

    alice_pref = net.add_cell("pref.alice", IntervalValue(21.5, 24.0))
    alice_loc = net.add_cell("loc.alice")

    targets = {"office": office, "kitchen": kitchen}
    net.add_propagator(MobileLinkPropagator("link.doug", doug_loc, doug_pref, targets=targets))
    net.add_propagator(MobileLinkPropagator("link.alice", alice_loc, alice_pref, targets=targets))

    # 1. Doug enters office
    doug_loc.set_value(DiscreteDomain.single("office"), overwrite=True)
    net.run()
    assert office.value == IntervalValue(20.0, 22.0)
    assert kitchen.value == IntervalValue(18.0, 26.0)

    # 2. Alice enters office -> interval intersection [21.5, 22.0]
    alice_loc.set_value(DiscreteDomain.single("office"), overwrite=True)
    net.run()
    assert office.value == IntervalValue(21.5, 22.0)

    # 3. Doug moves to kitchen -> office relaxes to Alice's [21.5, 24.0], kitchen narrows to [20.0, 22.0]
    doug_loc.set_value(DiscreteDomain.single("kitchen"), overwrite=True)
    net.run()
    assert office.value == IntervalValue(21.5, 24.0)
    assert kitchen.value == IntervalValue(20.0, 22.0)

    # 4. Doug leaves building (Bottom) -> kitchen relaxes back to [18.0, 26.0]
    doug_loc.set_value(BOTTOM, overwrite=True)
    net.run()
    assert kitchen.value == IntervalValue(18.0, 26.0)


def test_mobile_link_ambiguous_discrete_and_network_tms_ddb() -> None:
    """Verify ambiguous channel projection as defeasible assumptions and DDB resolution."""
    net = PropagatorNetwork("AmbiguousDDB")
    ntms = NetworkTMS(net)

    office = net.add_cell("zone.office")
    server = net.add_cell("zone.server")
    ntms.get_or_create_cell_tms("zone.office")
    ntms.get_or_create_cell_tms("zone.server")

    office.set_value(IntervalValue(18.0, 26.0), source="rule.office")
    server.set_value(IntervalValue(15.0, 18.5), source="rule.server_cooling")

    pref = net.add_cell("pref.doug", IntervalValue(20.0, 22.0))
    loc = net.add_cell("loc.doug")

    net.add_propagator(
        MobileLinkPropagator(
            "link.doug",
            loc,
            pref,
            targets={"office": office, "server": server},
            confidence=0.8,
            propagate_ambiguous=True,
        )
    )

    loc.set_value(DiscreteDomain({"office", "server"}), overwrite=True)
    net.run()

    assert office.value == IntervalValue(20.0, 22.0)
    assert isinstance(server.value, Contradiction)

    retracted = ntms.resolve_contradiction(server.tms.active_sources)
    assert retracted == "link.doug@server"
    assert server.value == IntervalValue(15.0, 18.5)
    assert office.value == IntervalValue(20.0, 22.0)


def test_mobile_link_set_lattice_belief_mass_and_spawn_missing() -> None:
    """Verify multicast SetLattice routing, BeliefMassValue routing, and (ν y) dynamic cell spawning."""
    net = PropagatorNetwork("DynamicSpawnAndMulticast")

    channel = net.add_cell("channel")
    payload = net.add_cell("payload", IntervalValue(10.0, 20.0))

    prop = MobileLinkPropagator(
        "dynamic_router",
        channel,
        payload,
        propagate_ambiguous=True,
        min_plausibility=0.3,
        spawn_missing=True,
    )
    net.add_propagator(prop)

    # 1. Multicast via SetLattice to dynamically spawned cells
    channel.set_value(SetLattice.from_iterable(["zone.a", "zone.b"]), overwrite=True)
    net.run()
    assert "zone.a" in net.cells
    assert "zone.b" in net.cells
    assert net.cells["zone.a"].value == IntervalValue(10.0, 20.0)
    assert net.cells["zone.b"].value == IntervalValue(10.0, 20.0)

    # 2. Switch to BeliefMassValue over {"zone.a", "zone.c"}
    frame = {"zone.a", "zone.b", "zone.c"}
    channel.set_value(
        BeliefMassValue.simple({"zone.a", "zone.c"}, 0.8, frame),
        overwrite=True,
    )
    net.run()
    assert net.cells["zone.a"].value == IntervalValue(10.0, 20.0)
    assert net.cells["zone.b"].value == BOTTOM
    assert net.cells["zone.c"].value == IntervalValue(10.0, 20.0)

    # 3. OrderedInterval determined channel
    domain = ("zone.a", "zone.b", "zone.c")
    channel.set_value(OrderedInterval.exact("zone.b", domain=domain), overwrite=True)
    net.run()
    assert net.cells["zone.a"].value == BOTTOM
    assert net.cells["zone.b"].value == IntervalValue(10.0, 20.0)
    assert net.cells["zone.c"].value == BOTTOM


def test_base_propagator_emit_inherits_upstream_assumption_and_confidence() -> None:
    """Verify base Propagator.emit propagates upstream assumption support and weakest-link confidence."""
    from lattice_propagator import AdderPropagator

    net = PropagatorNetwork("ProvenanceCascade")
    ntms = NetworkTMS(net)

    a = net.add_cell("a")
    b = net.add_cell("b")
    c = net.add_cell("c")
    ntms.get_or_create_cell_tms("a")
    ntms.get_or_create_cell_tms("b")
    ntms.get_or_create_cell_tms("c")

    # Assert a defeasible assumption on 'a' (confidence=0.6) and ground fact on 'b'
    ntms.assume("a", "hyp_a_high", IntervalValue(20.0, 22.0), confidence=0.6)
    b.set_value(IntervalValue(5.0, 5.0), source="ground_b")

    # Connect AdderPropagator with rule confidence=0.9
    net.add_propagator(AdderPropagator("add_ab", a, b, c, confidence=0.9))
    net.run()

    assert c.value == IntervalValue(25.0, 27.0)
    prem_c = c.tms.premises["add_ab"]
    assert prem_c.is_assumption is True
    assert prem_c.confidence == 0.54  # 0.9 * 0.6
    assert "hyp_a_high" in prem_c.support

    # Introduce conflicting hard safety limit on 'c' -> Contradiction
    c.set_value(IntervalValue(10.0, 20.0), source="safety_cap")
    assert isinstance(c.value, Contradiction)

    # DDB resolves contradiction on 'c' by tracing support back to 'hyp_a_high'
    culprit = ntms.resolve_contradiction(c.tms.active_sources)
    assert culprit == "hyp_a_high"
    assert c.value == IntervalValue(10.0, 20.0)


def test_dynamic_ev_power_routing_hourly_simulation() -> None:
    """Verify π-calculus mobile link in a 5-hour solar EV charging splitter simulation."""
    net = PropagatorNetwork("SolarEVSplitter")

    solar = net.add_cell("solar_production", unit="kW")
    baseload = net.add_cell("home_baseload", unit="kW")
    surplus = net.add_cell("solar_surplus", unit="kW")
    channel = net.add_cell("active_vehicle")

    rivian = net.add_cell("rivian_power", unit="kW")
    tesla = net.add_cell("tesla_power", unit="kW")

    rivian.set_value(IntervalValue(0.0, 11.5), source="hardware_envelope")
    tesla.set_value(IntervalValue(0.0, 7.6), source="hardware_envelope")

    # Battery pack capacities and initial state of charge (SOC)
    cap_rivian = 135.0  # Rivian R1S (135 kWh pack)
    cap_tesla = 75.0  # Tesla Model Y (75 kWh pack)

    e_rivian = IntervalValue(cap_rivian * 0.67, cap_rivian * 0.67)  # Starts at 67.0% (90.45 kWh)
    e_tesla = IntervalValue(cap_tesla * 0.20, cap_tesla * 0.20)  # Starts at 20.0% (15.00 kWh)

    net.add_propagator(AdderPropagator("power_balance", baseload, surplus, solar))
    net.add_propagator(
        MobileLinkPropagator(
            "ev_dispatcher",
            channel_cell=channel,
            payload_cell=surplus,
            targets={"rivian": rivian, "tesla": tesla},
            spawn_missing=True,
        )
    )

    rivian_target_soc = 75.0  # Charge Rivian first until 75.0% target

    # Hourly time series simulation inputs:
    # Column 1 (hour):        Time-of-day step identifier
    # Column 2 (sol_val):     Solar PV generation power envelope [P_min, P_max] in kW
    # Column 3 (base_val):    Home baseload power consumption envelope [B_min, B_max] in kW
    # Column 4 (guest_event): External override when a guest plugs in (None or "guest_ev")
    hourly_inputs = [
        ("11:00", IntervalValue(3.5, 4.0), IntervalValue(0.5, 0.8), None),
        ("12:00", IntervalValue(6.0, 7.5), IntervalValue(1.0, 1.2), None),
        ("13:00", IntervalValue(6.8, 7.2), IntervalValue(0.6, 0.8), None),
        ("14:00", IntervalValue(5.0, 5.5), IntervalValue(0.8, 1.0), None),
        ("15:00", IntervalValue(4.2, 4.8), IntervalValue(0.7, 0.9), None),
        ("16:00", IntervalValue(3.0, 3.6), IntervalValue(0.6, 0.8), "guest_ev"),
    ]

    for _hour, sol_val, base_val, guest_event in hourly_inputs:
        surplus.set_value(BOTTOM, overwrite=True)
        solar.set_value(sol_val, overwrite=True)
        baseload.set_value(base_val, overwrite=True)

        curr_soc_r = e_rivian.min_val / cap_rivian * 100.0
        if guest_event:
            target_car = guest_event
        elif curr_soc_r < rivian_target_soc:
            target_car = "rivian"
        else:
            target_car = "tesla"

        channel.set_value(DiscreteDomain.single(target_car), overwrite=True)
        net.run()

        if target_car == "rivian":
            assert rivian.value == surplus.value
            assert tesla.value == IntervalValue(0.0, 7.6)
            e_rivian = IntervalValue(
                e_rivian.min_val + rivian.value.min_val,
                e_rivian.max_val + rivian.value.max_val,
            )
        elif target_car == "tesla":
            assert rivian.value == IntervalValue(0.0, 11.5)
            assert tesla.value == surplus.value
            e_tesla = IntervalValue(
                e_tesla.min_val + tesla.value.min_val,
                e_tesla.max_val + tesla.value.max_val,
            )
        elif target_car == "guest_ev":
            assert rivian.value == IntervalValue(0.0, 11.5)
            assert tesla.value == IntervalValue(0.0, 7.6)
            assert "guest_ev" in net.cells
            assert net.cells["guest_ev"].value == surplus.value

    # Verify final integrated state of charge intervals
    soc_r_final = IntervalValue(
        e_rivian.min_val / cap_rivian * 100.0,
        e_rivian.max_val / cap_rivian * 100.0,
    )
    soc_t_final = IntervalValue(
        e_tesla.min_val / cap_tesla * 100.0,
        e_tesla.max_val / cap_tesla * 100.0,
    )
    assert 76.5 <= soc_r_final.min_val <= 77.5
    assert 79.0 <= soc_r_final.max_val <= 79.5
    assert 29.5 <= soc_t_final.min_val <= 30.0
    assert 31.5 <= soc_t_final.max_val <= 32.0
