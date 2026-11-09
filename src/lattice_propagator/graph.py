"""Graph visitation, causal traversal, and multi-format diagram generation.

Provides a unified graph abstraction for propagator networks:
- Semantic classification of cell lattice states (⊥, ⊤, intervals, Gaussian distributions).
- Bidirectional traversal algorithms (upstream causal slice, downstream impact walk).
- Cycle and feedback loop detection.
- Disjoint Set Union (Union-Find) alias clustering.
- Multi-format diagram exports (Mermaid with state styling, Graphviz DOT, Cytoscape/D3 JSON).

Theoretical Foundations:
- Radul, A., & Sussman, G. J. (2009). "The Art of the Propagator", MIT-CSAIL-TR-2009-002.
- Hanson, C., & Sussman, G. J. (2021). "Software Design for Flexibility", MIT Press, Chapter 7.
"""

from __future__ import annotations

import html
import re
from abc import ABC
from collections import deque
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .lattice import (
    BeliefMassValue,
    Bottom,
    Contradiction,
    DiscreteDomain,
    FlatValue,
    GaussianValue,
    IntervalValue,
    LatticeValue,
    MapLattice,
    SetLattice,
)
from .tms import format_lattice_value

if TYPE_CHECKING:
    from .primitives import Cell, Propagator, PropagatorNetwork


def sanitize_identifier(raw_id: str, prefix: str = "") -> str:
    """Sanitize arbitrary strings into valid Mermaid and DOT node identifiers.

    Args:
        raw_id: Raw string identifier (e.g. cell_id or propagator name).
        prefix: Optional prefix ('C_' for cells, 'P_' for propagators).

    Returns:
        Safe alphanumeric identifier.
    """
    cleaned = re.sub(r"[^a-zA-Z0-9_]", "_", raw_id)
    safe = cleaned if cleaned and cleaned[0].isalpha() else f"node_{cleaned}"
    return f"{prefix}{safe}" if prefix else safe


def classify_lattice_state(val: LatticeValue) -> str:
    """Classify a lattice value into a semantic display category.

    Args:
        val: The lattice value to classify.

    Returns:
        One of 'bottom', 'contradiction', 'interval', 'gaussian',
        'discrete', 'set', 'map', 'belief', or 'value'.
    """
    if isinstance(val, Bottom):
        return "bottom"
    if isinstance(val, Contradiction):
        return "contradiction"
    if isinstance(val, IntervalValue):
        return "interval"
    if isinstance(val, GaussianValue):
        return "gaussian"
    if isinstance(val, DiscreteDomain):
        return "discrete"
    if isinstance(val, (SetLattice, MapLattice)):
        return "set"
    if isinstance(val, BeliefMassValue):
        return "belief"
    return "value"


def format_node_label(
    cell_id: str,
    val: LatticeValue,
    unit: str = "",
    include_value: bool = True,
    escape_html: bool = False,
) -> str:
    """Format a cell label with its current lattice value and rich typography.

    Args:
        cell_id: Identifier of the cell.
        val: Lattice value held by the cell.
        unit: Optional physical unit (e.g., '°C', 'V', 'kΩ').
        include_value: Whether to append the formatted value string.
        escape_html: Whether to HTML-escape the resulting text.

    Returns:
        Formatted label text.
    """
    if not include_value:
        return html.escape(cell_id) if escape_html else cell_id

    if isinstance(val, Bottom):
        val_str = "⊥"
    elif isinstance(val, Contradiction):
        val_str = f"⊤ ({val.reason})"
    elif isinstance(val, GaussianValue):
        margin = 1.96 * val.standard_deviation
        val_str = f"{val.mean:.2f} ± {margin:.2f}{unit} (σ²={val.variance:.3f})"
    elif isinstance(val, IntervalValue):
        val_str = f"[{val.min_val:.2f}, {val.max_val:.2f}]{unit}"
    elif isinstance(val, FlatValue):
        val_str = f"{val.val}{unit}"
    else:
        val_str = format_lattice_value(val, unit=unit)

    raw_label = f"{cell_id}\\n{val_str}"
    return html.escape(raw_label) if escape_html else raw_label


@dataclass
class GraphNode:
    """Represents a vertex in the propagator network graph (Cell or Propagator).

    Attributes:
        node_id: Unique identifier for rendering (e.g. 'C_temp', 'P_Adder').
        kind: 'cell' or 'propagator'.
        label: Primary display label.
        state: Semantic state ('bottom', 'contradiction', 'interval', etc.).
        cell: Associated Cell instance if kind == 'cell'.
        propagator: Associated Propagator instance if kind == 'propagator'.
        cluster_id: Canonical alias cluster identifier if unified.
        metadata: Arbitrary user-defined or topological annotations.
    """

    node_id: str
    kind: str
    label: str
    state: str = "value"
    cell: Cell | None = None
    propagator: Propagator | None = None
    cluster_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphEdge:
    """Represents a directed or undirected edge between graph nodes.

    Attributes:
        source_id: Origin node ID.
        target_id: Destination node ID.
        kind: Edge relation ('input', 'output', 'alias', 'causal').
        label: Optional edge annotation.
        active: True if the relationship is active; False if offline/retracted.
        metadata: Arbitrary user-defined or topological annotations.
    """

    source_id: str
    target_id: str
    kind: str
    label: str = ""
    active: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphCluster:
    """Represents a subgraph cluster (e.g., Union-Find alias equivalence class).

    Attributes:
        cluster_id: Unique identifier for the cluster subgraph.
        label: Descriptive label for the cluster.
        node_ids: Member node IDs contained within this cluster.
    """

    cluster_id: str
    label: str
    node_ids: list[str] = field(default_factory=list)


class NetworkVisitor(ABC):
    """Abstract base visitor for inspecting and traversing propagator networks."""

    def visit_cell(self, cell: Cell, depth: int) -> bool | None:
        """Called upon visiting a Cell.

        Args:
            cell: The cell being visited.
            depth: Current search depth from the root.

        Returns:
            Return False to prune traversal beyond this cell, or None/True to continue.
        """
        return True

    def visit_propagator(self, propagator: Propagator, depth: int) -> bool | None:
        """Called upon visiting a Propagator.

        Args:
            propagator: The propagator being visited.
            depth: Current search depth from the root.

        Returns:
            Return False to prune traversal beyond this propagator, or None/True to continue.
        """
        return True

    def visit_edge(
        self,
        source: Cell | Propagator,
        target: Cell | Propagator,
        kind: str,
        depth: int,
    ) -> None:
        """Called when an edge between cells and propagators is traversed.

        Args:
            source: Source cell or propagator.
            target: Destination cell or propagator.
            kind: Edge type ('input', 'output').
            depth: Traversal depth of this step.
        """


def walk_downstream(
    network_or_cell: PropagatorNetwork | Cell,
    start: Cell | Sequence[Cell] | None = None,
    visitor: NetworkVisitor | None = None,
    max_depth: int | None = None,
) -> Iterator[Cell | Propagator]:
    """Traverse downstream from starting cells through observed propagators and consequences.

    Follows: Cell → observing Propagators → output Cells → ...

    Args:
        network_or_cell: PropagatorNetwork instance or single starting Cell.
        start: Starting cell(s). If network_or_cell is a Cell and start is None,
            the cell itself is used as the starting point.
        visitor: Optional NetworkVisitor for filtering or side effects.
        max_depth: Maximum traversal depth (None for unbounded).

    Yields:
        Cells and Propagators in breadth-first causal order.
    """
    start_cells = (
        [network_or_cell]
        if start is None and hasattr(network_or_cell, "cell_id")
        else [start]
        if isinstance(start, object) and hasattr(start, "cell_id")
        else list(start)
        if start is not None
        else []
    )

    visited: set[int] = set()
    queue: deque[tuple[Cell | Propagator, int]] = deque((c, 0) for c in start_cells)

    while queue:
        item, depth = queue.popleft()
        item_id = id(item)
        if item_id in visited:
            continue
        visited.add(item_id)

        # Visit and conditionally prune
        if hasattr(item, "cell_id"):
            cell: Cell = item  # type: ignore[assignment]
            continue_walk = True if visitor is None else visitor.visit_cell(cell, depth)
            yield cell
            if continue_walk is False or (max_depth is not None and depth >= max_depth):
                continue

            # Queue downstream observing propagators
            root = cell._find()
            for p in root.propagators:
                if id(p) not in visited:
                    if visitor is not None:
                        visitor.visit_edge(cell, p, "input", depth)
                    queue.append((p, depth + 1))
        else:
            prop: Propagator = item  # type: ignore[assignment]
            continue_walk = True if visitor is None else visitor.visit_propagator(prop, depth)
            yield prop
            if continue_walk is False or (max_depth is not None and depth >= max_depth):
                continue

            # Queue downstream output cells
            for out_cell in prop.outputs:
                if id(out_cell) not in visited:
                    if visitor is not None:
                        visitor.visit_edge(prop, out_cell, "output", depth)
                    queue.append((out_cell, depth + 1))


def walk_upstream(
    network_or_cell: PropagatorNetwork | Cell,
    target: Cell | Sequence[Cell] | None = None,
    visitor: NetworkVisitor | None = None,
    max_depth: int | None = None,
) -> Iterator[Cell | Propagator]:
    """Traverse upstream from target cells back to governing propagators and antecedent cells.

    Follows: Cell → feeding Propagators → input Cells → ...

    Args:
        network_or_cell: PropagatorNetwork instance or single target Cell.
        target: Target cell(s). If network_or_cell is a Cell and target is None,
            the cell itself is used as the target.
        visitor: Optional NetworkVisitor for filtering or side effects.
        max_depth: Maximum traversal depth (None for unbounded).

    Yields:
        Cells and Propagators in upstream causal cone order.
    """
    target_cells = (
        [network_or_cell]
        if target is None and hasattr(network_or_cell, "cell_id")
        else [target]
        if isinstance(target, object) and hasattr(target, "cell_id")
        else list(target)
        if target is not None
        else []
    )

    # Build backward map from output cell roots to propagators
    net = (
        network_or_cell
        if hasattr(network_or_cell, "propagators") and hasattr(network_or_cell, "cells")
        else network_or_cell.network
        if hasattr(network_or_cell, "network") and network_or_cell.network is not None
        else None
    )

    prop_sources: dict[int, list[Propagator]] = {}
    if net is not None and hasattr(net, "propagators"):
        for p in net.propagators:
            for out_c in p.outputs:
                prop_sources.setdefault(id(out_c._find()), []).append(p)

    visited: set[int] = set()
    queue: deque[tuple[Cell | Propagator, int]] = deque((c, 0) for c in target_cells)

    while queue:
        item, depth = queue.popleft()
        item_id = id(item)
        if item_id in visited:
            continue
        visited.add(item_id)

        if hasattr(item, "cell_id"):
            cell: Cell = item  # type: ignore[assignment]
            continue_walk = True if visitor is None else visitor.visit_cell(cell, depth)
            yield cell
            if continue_walk is False or (max_depth is not None and depth >= max_depth):
                continue

            root_id = id(cell._find())
            for p in prop_sources.get(root_id, []):
                if id(p) not in visited:
                    if visitor is not None:
                        visitor.visit_edge(p, cell, "output", depth)
                    queue.append((p, depth + 1))
        else:
            prop: Propagator = item  # type: ignore[assignment]
            continue_walk = True if visitor is None else visitor.visit_propagator(prop, depth)
            yield prop
            if continue_walk is False or (max_depth is not None and depth >= max_depth):
                continue

            for in_cell in prop.inputs:
                if id(in_cell) not in visited:
                    if visitor is not None:
                        visitor.visit_edge(in_cell, prop, "input", depth)
                    queue.append((in_cell, depth + 1))


def detect_cycles(network: PropagatorNetwork) -> list[list[str]]:
    """Detect feedback loops and cyclic dependencies in the propagator network.

    Analyzes the bipartite directed graph:
    Cell → Propagator (inputs) and Propagator → Cell (outputs).

    Args:
        network: PropagatorNetwork to analyze.

    Returns:
        List of detected elementary cycles, each expressed as a sequence of node IDs.
    """
    # Build adjacency list using canonical IDs
    adj: dict[str, list[str]] = {}

    for c in network.cells.values():
        c_id = sanitize_identifier(c.cell_id, "C_")
        adj.setdefault(c_id, [])
        for p in c._find().propagators:
            p_id = sanitize_identifier(p.name, "P_")
            if p_id not in adj[c_id]:
                adj[c_id].append(p_id)

    for p in network.propagators:
        p_id = sanitize_identifier(p.name, "P_")
        adj.setdefault(p_id, [])
        for out_c in p.outputs:
            c_id = sanitize_identifier(out_c.cell_id, "C_")
            if c_id not in adj[p_id]:
                adj[p_id].append(c_id)

    visited: set[str] = set()
    rec_stack: list[str] = []
    cycles: list[list[str]] = []

    def dfs(curr: str) -> None:
        visited.add(curr)
        rec_stack.append(curr)

        for nxt in adj.get(curr, []):
            if nxt not in visited:
                dfs(nxt)
            elif nxt in rec_stack:
                cycle_start = rec_stack.index(nxt)
                cycle = rec_stack[cycle_start:] + [nxt]
                cycles.append(cycle)

        rec_stack.pop()

    for node in sorted(adj.keys()):
        if node not in visited:
            dfs(node)

    return cycles


@dataclass
class NetworkGraph:
    """Intermediate bipartite graph representation of a propagator network.

    Decouples graph topology, alias clustering, and lattice states from
    specific presentation formats (Mermaid, Graphviz DOT, Cytoscape JSON).

    Attributes:
        nodes: Mapping from node_id to GraphNode.
        edges: List of GraphEdge instances.
        clusters: Mapping from cluster_id to GraphCluster (e.g. alias groups).
        network_name: Human-readable name of the origin network.
    """

    nodes: dict[str, GraphNode] = field(default_factory=dict)
    edges: list[GraphEdge] = field(default_factory=list)
    clusters: dict[str, GraphCluster] = field(default_factory=dict)
    network_name: str = "Network"

    @classmethod
    def from_network(
        cls,
        network: PropagatorNetwork,
        include_isolated: bool = True,
        group_aliases: bool = True,
    ) -> NetworkGraph:
        """Construct a NetworkGraph from a PropagatorNetwork.

        Args:
            network: The PropagatorNetwork to transform.
            include_isolated: Whether to include cells unconnected to any propagators.
            group_aliases: Whether to group unified cells into alias clusters.

        Returns:
            Fully populated NetworkGraph instance.
        """
        graph = cls(network_name=network.name)

        # 1. Alias grouping via Union-Find canonical root
        alias_groups: dict[str, list[Cell]] = {}
        for c in network.cells.values():
            root_id = c._find().cell_id
            alias_groups.setdefault(root_id, []).append(c)

        for root_id, group in alias_groups.items():
            if group_aliases and len(group) > 1:
                cluster_id = sanitize_identifier(f"cluster_alias_{root_id}")
                graph.clusters[cluster_id] = GraphCluster(
                    cluster_id=cluster_id,
                    label=f"Equivalence Class: {root_id}",
                    node_ids=[sanitize_identifier(c.cell_id, "C_") for c in group],
                )

        # 2. Add Cell Nodes
        connected_cells: set[str] = set()
        for p in network.propagators:
            for in_c in p.inputs:
                connected_cells.add(in_c.cell_id)
            for out_c in p.outputs:
                connected_cells.add(out_c.cell_id)

        for cell in network.cells.values():
            if not include_isolated and cell.cell_id not in connected_cells:
                continue
            c_node_id = sanitize_identifier(cell.cell_id, "C_")
            state = classify_lattice_state(cell.value)
            cluster_id = (
                sanitize_identifier(f"cluster_alias_{cell._find().cell_id}")
                if group_aliases and len(alias_groups.get(cell._find().cell_id, [])) > 1
                else None
            )

            graph.nodes[c_node_id] = GraphNode(
                node_id=c_node_id,
                kind="cell",
                label=cell.display_name or cell.cell_id,
                state=state,
                cell=cell,
                cluster_id=cluster_id,
                metadata={"unit": cell.unit, "raw_id": cell.cell_id},
            )

        # 3. Add Propagator Nodes & Edges
        for p in network.propagators:
            p_node_id = sanitize_identifier(p.name, "P_")
            graph.nodes[p_node_id] = GraphNode(
                node_id=p_node_id,
                kind="propagator",
                label=p.name,
                state="propagator",
                propagator=p,
                metadata={"class": p.__class__.__name__},
            )

            # Input edges: Cell → Propagator
            for in_c in p.inputs:
                in_node_id = sanitize_identifier(in_c.cell_id, "C_")
                if in_node_id in graph.nodes:
                    graph.edges.append(
                        GraphEdge(
                            source_id=in_node_id,
                            target_id=p_node_id,
                            kind="input",
                        )
                    )

            # Output edges: Propagator → Cell
            for out_c in p.outputs:
                out_node_id = sanitize_identifier(out_c.cell_id, "C_")
                if out_node_id in graph.nodes:
                    graph.edges.append(
                        GraphEdge(
                            source_id=p_node_id,
                            target_id=out_node_id,
                            kind="output",
                        )
                    )

        return graph

    @classmethod
    def from_slice(
        cls,
        network: PropagatorNetwork,
        roots: Sequence[Cell],
        direction: str = "downstream",
        max_depth: int | None = None,
    ) -> NetworkGraph:
        """Construct a subgraph slice by walking upstream or downstream from root cells.

        Args:
            network: Origin PropagatorNetwork.
            roots: Root cells to start traversal from.
            direction: 'downstream' for impact cone, 'upstream' for causal cone.
            max_depth: Maximum traversal depth.

        Returns:
            Filtered NetworkGraph containing only visited cells, propagators, and edges.
        """
        full_graph = cls.from_network(network)
        traversal = (
            walk_downstream(network, roots, max_depth=max_depth)
            if direction == "downstream"
            else walk_upstream(network, roots, max_depth=max_depth)
        )
        visited_elements = set(traversal)

        valid_node_ids = {
            node.node_id
            for node in full_graph.nodes.values()
            if (node.cell in visited_elements or node.propagator in visited_elements)
        }

        sliced_nodes = {
            nid: node for nid, node in full_graph.nodes.items() if nid in valid_node_ids
        }
        sliced_edges = [
            e
            for e in full_graph.edges
            if e.source_id in valid_node_ids and e.target_id in valid_node_ids
        ]

        sliced_clusters = {}
        for cid, cluster in full_graph.clusters.items():
            member_nodes = [nid for nid in cluster.node_ids if nid in valid_node_ids]
            if member_nodes:
                sliced_clusters[cid] = GraphCluster(
                    cluster_id=cluster.cluster_id,
                    label=cluster.label,
                    node_ids=member_nodes,
                )

        return cls(
            nodes=sliced_nodes,
            edges=sliced_edges,
            clusters=sliced_clusters,
            network_name=f"{network.name} ({direction} slice)",
        )

    def to_mermaid(
        self,
        orientation: str = "LR",
        include_values: bool = True,
        group_aliases: bool = True,
        style_states: bool = True,
    ) -> str:
        """Generate a rich, styled Mermaid flowchart representing the network.

        Args:
            orientation: Flow direction ('LR', 'TD', 'RL', 'BT').
            include_values: Whether to include formatted lattice values in cell labels.
            group_aliases: Whether to render subgraphs for alias clusters.
            style_states: Whether to attach semantic CSS classes (bottom, contradiction, etc.).

        Returns:
            Formatted Mermaid markdown block.
        """
        lines = ["```mermaid", f"graph {orientation}"]

        # CSS Class Definitions
        if style_states:
            lines.extend(
                [
                    "  classDef bottom fill:#f8f9fa,stroke:#adb5bd,stroke-dasharray: 4 4,color:#6c757d;",
                    "  classDef contradiction fill:#fff5f5,stroke:#e53e3e,stroke-width:2px,color:#9b2c2c;",
                    "  classDef interval fill:#ebf8ff,stroke:#3182ce,stroke-width:1.5px;",
                    "  classDef gaussian fill:#f0fff4,stroke:#38a169,stroke-width:1.5px;",
                    "  classDef discrete fill:#faf5ff,stroke:#805ad5,stroke-width:1.5px;",
                    "  classDef cell fill:#edf2f7,stroke:#4a5568,stroke-width:1.5px;",
                    "  classDef value fill:#edf2f7,stroke:#4a5568,stroke-width:1.5px;",
                    "  classDef set fill:#faf5ff,stroke:#805ad5,stroke-width:1.5px;",
                    "  classDef belief fill:#f0fff4,stroke:#38a169,stroke-width:1.5px;",
                    "  classDef propagator fill:#f7fafc,stroke:#2d3748,stroke-width:1.5px;",
                ]
            )

        def _format_cell_node(node: GraphNode) -> str:
            val_str = ""
            if include_values and node.cell is not None:
                val = node.cell.value
                unit = node.metadata.get("unit", "")
                if isinstance(val, Bottom):
                    val_str = "<br/>⊥"
                elif isinstance(val, Contradiction):
                    val_str = f"<br/>⊤ ({val.reason})"
                elif isinstance(val, GaussianValue):
                    margin = 1.96 * val.standard_deviation
                    val_str = f"<br/>{val.mean:.2f} ± {margin:.2f}{unit}"
                elif isinstance(val, IntervalValue):
                    val_str = f"<br/>[{val.min_val:.2f}, {val.max_val:.2f}]{unit}"
                elif isinstance(val, FlatValue):
                    val_str = f"<br/>{val.val}{unit}"
                else:
                    val_str = f"<br/>{format_lattice_value(val, unit=unit)}"

            safe_label = f"{node.label}{val_str}".replace('"', "'")
            style_suffix = f":::{node.state}" if style_states else ""
            return f'  {node.node_id}["{safe_label}"]{style_suffix}'

        def _format_prop_node(node: GraphNode) -> str:
            safe_label = node.label.replace('"', "'")
            style_suffix = ":::propagator" if style_states else ""
            return f'  {node.node_id}["{safe_label}"]{style_suffix}'

        # Render Clusters & Clustered Cells
        rendered_nodes: set[str] = set()
        if group_aliases and self.clusters:
            for cluster in self.clusters.values():
                lines.append(f'  subgraph {cluster.cluster_id} ["{cluster.label}"]')
                for nid in cluster.node_ids:
                    if nid in self.nodes:
                        lines.append(f"  {_format_cell_node(self.nodes[nid])}")
                        rendered_nodes.add(nid)
                lines.append("  end")

        # Render Remaining Unclustered Nodes
        for nid, node in sorted(self.nodes.items()):
            if nid in rendered_nodes:
                continue
            line = _format_cell_node(node) if node.kind == "cell" else _format_prop_node(node)
            lines.append(line)

        # Render Edges
        for edge in self.edges:
            edge_syntax = "-->" if edge.active else "-.->"
            label_syntax = f"|{edge.label}|" if edge.label else ""
            lines.append(f"  {edge.source_id} {edge_syntax}{label_syntax} {edge.target_id}")

        lines.append("```")
        return "\n".join(lines)

    def to_dot(
        self,
        rankdir: str = "LR",
        include_values: bool = True,
        group_aliases: bool = True,
    ) -> str:
        """Generate a Graphviz DOT representation of the network.

        Args:
            rankdir: Rank direction ('LR', 'TB', 'RL', 'BT').
            include_values: Whether to include formatted lattice values in cell labels.
            group_aliases: Whether to render subgraphs for alias clusters.

        Returns:
            DOT specification string.
        """
        lines = [
            f'digraph "{self.network_name}" {{',
            f'  rankdir="{rankdir}";',
            '  node [fontname="Helvetica", fontsize=10];',
            '  edge [fontname="Helvetica", fontsize=9];',
            "",
        ]

        def _cell_dot_attrs(node: GraphNode) -> str:
            val_str = ""
            if include_values and node.cell is not None:
                val = node.cell.value
                unit = node.metadata.get("unit", "")
                if isinstance(val, Bottom):
                    val_str = r"\n⊥"
                elif isinstance(val, Contradiction):
                    val_str = rf"\n⊤ ({val.reason})"
                elif isinstance(val, GaussianValue):
                    margin = 1.96 * val.standard_deviation
                    val_str = rf"\n{val.mean:.2f} ± {margin:.2f}{unit}"
                elif isinstance(val, IntervalValue):
                    val_str = rf"\n[{val.min_val:.2f}, {val.max_val:.2f}]{unit}"
                elif isinstance(val, FlatValue):
                    val_str = rf"\n{val.val}{unit}"
                else:
                    val_str = rf"\n{format_lattice_value(val, unit=unit)}"

            label = f"{node.label}{val_str}".replace('"', r"\"")

            # Selection of visual styles
            if node.state == "bottom":
                return f'label="{label}", shape=box, style="filled,dashed", fillcolor="#f8f9fa", color="#adb5bd"'
            if node.state == "contradiction":
                return f'label="{label}", shape=box, style="filled,bold", fillcolor="#fff5f5", color="#e53e3e"'
            if node.state == "interval":
                return f'label="{label}", shape=box, style="filled,rounded", fillcolor="#ebf8ff", color="#3182ce"'
            if node.state == "gaussian":
                return f'label="{label}", shape=box, style="filled,rounded", fillcolor="#f0fff4", color="#38a169"'
            return f'label="{label}", shape=box, style="filled,rounded", fillcolor="#edf2f7", color="#4a5568"'

        def _prop_dot_attrs(node: GraphNode) -> str:
            label = node.label.replace('"', r"\"")
            return f'label="{label}", shape=component, style=filled, fillcolor="#f7fafc", color="#2d3748"'

        rendered_nodes: set[str] = set()
        if group_aliases and self.clusters:
            for cluster in self.clusters.values():
                lines.append(f'  subgraph "{cluster.cluster_id}" {{')
                lines.append(f'    label="{cluster.label}";')
                lines.append('    style="dashed";')
                lines.append('    color="#718096";')
                for nid in cluster.node_ids:
                    if nid in self.nodes:
                        attrs = _cell_dot_attrs(self.nodes[nid])
                        lines.append(f"    {nid} [{attrs}];")
                        rendered_nodes.add(nid)
                lines.append("  }")

        for nid, node in sorted(self.nodes.items()):
            if nid in rendered_nodes:
                continue
            attrs = _cell_dot_attrs(node) if node.kind == "cell" else _prop_dot_attrs(node)
            lines.append(f"  {nid} [{attrs}];")

        lines.append("")
        for edge in self.edges:
            style = "" if edge.active else ' [style="dashed", color="#e53e3e"]'
            lines.append(f"  {edge.source_id} -> {edge.target_id}{style};")

        lines.append("}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Export the graph as a JSON-serializable dictionary for Cytoscape or D3.

        Returns:
            Dictionary containing 'nodes', 'edges', and 'clusters'.
        """
        return {
            "network_name": self.network_name,
            "nodes": [
                {
                    "id": node.node_id,
                    "kind": node.kind,
                    "label": node.label,
                    "state": node.state,
                    "cluster": node.cluster_id,
                    "metadata": node.metadata,
                }
                for node in self.nodes.values()
            ],
            "edges": [
                {
                    "source": edge.source_id,
                    "target": edge.target_id,
                    "kind": edge.kind,
                    "label": edge.label,
                    "active": edge.active,
                    "metadata": edge.metadata,
                }
                for edge in self.edges
            ],
            "clusters": [
                {
                    "id": c.cluster_id,
                    "label": c.label,
                    "nodes": list(c.node_ids),
                }
                for c in self.clusters.values()
            ],
        }
