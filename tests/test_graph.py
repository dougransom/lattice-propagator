"""Unit tests for propagator network graph visitation, traversal, and diagram exports."""

import json

from lattice_propagator import (
    AdderPropagator,
    ArithmeticPropagator,
    Cell,
    Contradiction,
    GaussianValue,
    GraphCluster,
    GraphEdge,
    GraphNode,
    IntervalValue,
    MultiplierPropagator,
    NetworkGraph,
    NetworkVisitor,
    PropagatorNetwork,
    classify_lattice_state,
    detect_cycles,
    walk_downstream,
    walk_upstream,
)


def test_classify_lattice_state() -> None:
    """Verify semantic state classification for lattice values."""
    from lattice_propagator import BOTTOM, DiscreteDomain, FlatValue, SetLattice

    assert classify_lattice_state(BOTTOM) == "bottom"
    assert classify_lattice_state(Contradiction("conflict")) == "contradiction"
    assert classify_lattice_state(IntervalValue(10.0, 20.0)) == "interval"
    assert classify_lattice_state(GaussianValue(mean=21.0, variance=0.5)) == "gaussian"
    assert classify_lattice_state(DiscreteDomain([1, 2, 3])) == "discrete"
    assert classify_lattice_state(SetLattice({"a", "b"})) == "set"
    assert classify_lattice_state(FlatValue("hello")) == "value"


def test_network_graph_from_network() -> None:
    """Verify construction of NetworkGraph intermediate representation."""
    net = PropagatorNetwork("SimpleArithmetic")
    c_a = net.add_cell("A", IntervalValue(10.0, 15.0), unit="°C")
    c_b = net.add_cell("B", IntervalValue(5.0, 10.0), unit="°C")
    c_sum = net.add_cell("Sum", unit="°C")
    net.add_cell("Isolated")

    adder = ArithmeticPropagator("Adder_1", inputs=[c_a, c_b], output=c_sum)
    net.add_propagator(adder)
    net.run()

    graph = net.to_graph(include_isolated=True)
    assert isinstance(graph, NetworkGraph)
    assert "C_A" in graph.nodes
    assert "C_B" in graph.nodes
    assert "C_Sum" in graph.nodes
    assert "C_Isolated" in graph.nodes
    assert "P_Adder_1" in graph.nodes

    # Check node attributes
    node_a = graph.nodes["C_A"]
    assert isinstance(node_a, GraphNode)
    assert node_a.kind == "cell"
    assert node_a.state == "interval"
    assert node_a.metadata["unit"] == "°C"

    node_adder = graph.nodes["P_Adder_1"]
    assert node_adder.kind == "propagator"
    assert node_adder.state == "propagator"

    # Check edges
    assert len(graph.edges) == 3
    for edge in graph.edges:
        assert isinstance(edge, GraphEdge)
    edge_pairs = [(e.source_id, e.target_id, e.kind) for e in graph.edges]
    assert ("C_A", "P_Adder_1", "input") in edge_pairs
    assert ("C_B", "P_Adder_1", "input") in edge_pairs
    assert ("P_Adder_1", "C_Sum", "output") in edge_pairs
    assert isinstance(node_a.cell, Cell)

    # Verify without isolated cells
    graph_connected = net.to_graph(include_isolated=False)
    assert "C_Isolated" not in graph_connected.nodes


def test_alias_clustering_in_graph() -> None:
    """Verify that unified cells form alias cluster subgraphs."""
    net = PropagatorNetwork("AliasNet")
    c1 = net.add_cell("sensor_ambient", IntervalValue(20.0, 24.0))
    c2 = net.add_cell("room_temp")
    out = net.add_cell("heater_cmd")

    # Unify c1 and c2 into an equivalence class
    c1.unify(c2)

    prop = ArithmeticPropagator("HeaterControl", inputs=[c2], output=out, weights=[1.5])
    net.add_propagator(prop)

    graph = net.to_graph(group_aliases=True)
    assert len(graph.clusters) == 1
    cluster = next(iter(graph.clusters.values()))
    assert isinstance(cluster, GraphCluster)
    assert "C_sensor_ambient" in cluster.node_ids
    assert "C_room_temp" in cluster.node_ids


def test_walk_downstream_and_upstream() -> None:
    """Verify forward and backward causal slice traversals."""
    net = PropagatorNetwork("Pipeline")
    c_in = net.add_cell("In", IntervalValue(2.0, 4.0))
    c_mid = net.add_cell("Mid")
    c_out = net.add_cell("Out")

    p1 = ArithmeticPropagator("Stage1", inputs=[c_in], output=c_mid, weights=[2.0])
    p2 = ArithmeticPropagator("Stage2", inputs=[c_mid], output=c_out, offset=1.0)
    net.add_propagator(p1)
    net.add_propagator(p2)
    net.run()

    # Walk downstream from In
    downstream_elements = list(c_in.walk_downstream())
    assert c_in in downstream_elements
    assert p1 in downstream_elements
    assert c_mid in downstream_elements
    assert p2 in downstream_elements
    assert c_out in downstream_elements

    # Walk downstream with max_depth=1
    shallow_downstream = list(net.walk_downstream(start=c_in, max_depth=1))
    assert c_in in shallow_downstream
    assert p1 in shallow_downstream
    assert c_out not in shallow_downstream

    # Walk upstream from Out
    upstream_elements = list(walk_upstream(net, target=c_out))
    assert c_out in upstream_elements
    assert p2 in upstream_elements
    assert c_mid in upstream_elements
    assert p1 in upstream_elements
    assert c_in in upstream_elements


def test_visitor_pruning() -> None:
    """Verify custom NetworkVisitor can prune graph traversal."""
    net = PropagatorNetwork("Branching")
    c_root = net.add_cell("Root")
    c_a = net.add_cell("BranchA")
    c_b = net.add_cell("BranchB")

    p_a = ArithmeticPropagator("PropA", inputs=[c_root], output=c_a)
    p_b = ArithmeticPropagator("PropB", inputs=[c_root], output=c_b)
    net.add_propagator(p_a)
    net.add_propagator(p_b)

    class PrunePropAVisitor(NetworkVisitor):
        def visit_propagator(self, propagator, depth):
            # Prune branch A
            return propagator.name != "PropA"

    visited = list(walk_downstream(net, start=c_root, visitor=PrunePropAVisitor()))
    assert c_root in visited
    assert p_a in visited
    assert c_a not in visited  # Pruned beyond PropA
    assert p_b in visited
    assert c_b in visited


def test_detect_cycles() -> None:
    """Verify detection of feedback loops vs acyclic DAGs."""
    # 1. Acyclic network
    dag_net = PropagatorNetwork("DAG")
    a = dag_net.add_cell("A")
    b = dag_net.add_cell("B")
    c = dag_net.add_cell("C")
    p1 = ArithmeticPropagator("P1", inputs=[a], output=b)
    p2 = ArithmeticPropagator("P2", inputs=[b], output=c)
    dag_net.add_propagator(p1)
    dag_net.add_propagator(p2)

    assert detect_cycles(dag_net) == []

    # 2. Reciprocal cyclic network (feedback loop)
    loop_net = PropagatorNetwork("FeedbackLoop")
    x = loop_net.add_cell("X")
    y = loop_net.add_cell("Y")
    p_fwd = ArithmeticPropagator("PFwd", inputs=[x], output=y)
    p_rev = ArithmeticPropagator("PRev", inputs=[y], output=x)
    loop_net.add_propagator(p_fwd)
    loop_net.add_propagator(p_rev)

    cycles = loop_net.detect_cycles()
    assert len(cycles) > 0
    cycle_nodes = set(cycles[0])
    assert "C_X" in cycle_nodes
    assert "C_Y" in cycle_nodes
    assert "P_PFwd" in cycle_nodes
    assert "P_PRev" in cycle_nodes


def test_mermaid_export_rich() -> None:
    """Verify rich Mermaid flowchart export with styling and clusters."""
    net = PropagatorNetwork("VisualNet")
    c1 = net.add_cell("temp1", IntervalValue(20.0, 22.0), unit="°C")
    c2 = net.add_cell("temp2")
    c1.unify(c2)

    out = net.add_cell("power")
    adder = AdderPropagator("Add", c1, c2, out)
    net.add_propagator(adder)

    mermaid = net.generate_mermaid()
    assert "```mermaid" in mermaid
    assert "graph LR" in mermaid
    assert "classDef interval" in mermaid
    assert "classDef bottom" in mermaid
    assert "subgraph cluster_alias" in mermaid
    assert "P_Add" in mermaid
    assert "C_temp1" in mermaid
    assert "-->" in mermaid


def test_dot_export() -> None:
    """Verify Graphviz DOT export with shapes and subgraphs."""
    net = PropagatorNetwork("DotNet")
    a = net.add_cell("A", GaussianValue(mean=10.0, variance=0.4))
    b = net.add_cell("B", unit="V")
    mult = MultiplierPropagator("Mult", a, a, b)
    net.add_propagator(mult)

    dot = net.generate_dot()
    assert 'digraph "DotNet"' in dot
    assert 'rankdir="LR";' in dot
    assert "C_A [" in dot
    assert "P_Mult [" in dot
    assert "shape=component" in dot
    assert "C_A -> P_Mult;" in dot
    assert "P_Mult -> C_B;" in dot


def test_to_dict_export() -> None:
    """Verify JSON-serializable dictionary export for Cytoscape or D3."""
    net = PropagatorNetwork("JsonNet")
    a = net.add_cell("In1", IntervalValue(1.0, 2.0))
    b = net.add_cell("In2")
    out = net.add_cell("Out")
    adder = ArithmeticPropagator("Adder", inputs=[a, b], output=out)
    net.add_propagator(adder)

    graph_dict = net.to_graph().to_dict()
    # Ensure serializable to valid JSON
    serialized = json.dumps(graph_dict)
    assert serialized is not None

    assert graph_dict["network_name"] == "JsonNet"
    assert len(graph_dict["nodes"]) == 4  # 3 cells + 1 prop
    assert len(graph_dict["edges"]) == 3  # 2 inputs + 1 output
