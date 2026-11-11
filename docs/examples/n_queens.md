# Example: $N$-Queens Constraint Satisfaction

The $N$-Queens problem requires placing $N$ non-attacking queens on an $N \times N$ chessboard such that no two queens share the same row, column, or diagonal.

Using the lattice propagator framework:
- Each queen on file $i \in \{0, \dots, N-1\}$ is modeled as a [`Cell`](file:///home/doug/code/lattice-propagator/docs/api/primitives.md) holding a [`DiscreteDomain`](file:///home/doug/code/lattice-propagator/docs/api/lattice.md) of allowable ranks $\{0, \dots, N-1\}$.
- Row uniqueness is maintained globally via [`AllDistinctPropagator`](file:///home/doug/code/lattice-propagator/docs/api/primitives.md) (Régin's Generalized Arc Consistency via bipartite matching).
- Diagonal non-attack conditions are maintained via pairwise diagonal distance propagators.
- Search is coordinated by [`ChoiceEngine`](file:///home/doug/code/lattice-propagator/docs/api/primitives.md) with First-Fail / MRV (Minimum Remaining Values) branching.

---

## 1. Visual Solution (Human View)

![8-Queens Solution Board](../assets/n_queens.svg)

---

## 2. Executable Propagator Implementation

```python
from lattice_propagator import (
    AllDifferentPropagator,
    AllDistinctPropagator,
    Cell,
    ChoiceEngine,
    Contradiction,
    DiscreteDomain,
    Propagator,
    PropagatorNetwork,
)


class DiagonalConstraintPropagator(Propagator):
    """Enforces that two queens on distinct files i and j cannot share a diagonal (|ri - rj| != |i - j|)."""

    def __init__(self, name: str, qi: Cell, qj: Cell, file_distance: int) -> None:
        super().__init__(name, [qi, qj], [qi, qj])
        self.qi = qi
        self.qj = qj
        self.file_distance = file_distance

    def alert(self, network: PropagatorNetwork) -> None:
        vi, vj = self.qi.value, self.qj.value
        if not (isinstance(vi, DiscreteDomain) and isinstance(vj, DiscreteDomain)):
            return

        valid_i = set()
        valid_j = set()
        for ri in vi.candidates:
            for rj in vj.candidates:
                if abs(ri - rj) != self.file_distance:
                    valid_i.add(ri)
                    valid_j.add(rj)

        if not valid_i or not valid_j:
            self.qi.set_value(
                Contradiction(f"Diagonal attack between {self.qi.cell_id} and {self.qj.cell_id}"),
                source=self.name,
            )
            return

        if valid_i != vi.candidates:
            self.qi.set_value(DiscreteDomain(valid_i), source=self.name)
        if valid_j != vj.candidates:
            self.qj.set_value(DiscreteDomain(valid_j), source=self.name)


def solve_n_queens(n: int = 8) -> list[int]:
    net = PropagatorNetwork(f"{n}Queens")
    queens = [net.add_cell(f"Q_{i}", DiscreteDomain.range(0, n)) for i in range(n)]

    # 1. Global Row Uniqueness (Generalized Arc Consistency via bipartite matching)
    net.add_propagator(AllDistinctPropagator("AllDistinctRows", queens))

    # 2. Pairwise Diagonal Constraints
    for i in range(n):
        for j in range(i + 1, n):
            dist = j - i
            net.add_propagator(
                DiagonalConstraintPropagator(f"Diag_{i}_{j}", queens[i], queens[j], dist)
            )

    # 3. Interleaved propagation & MRV search
    engine = ChoiceEngine(net, variables=queens)
    solved = engine.solve()
    assert solved, "No solution found!"

    # Export and persist network diagrams
    from pathlib import Path

    assets_dir = Path("docs/assets")
    if assets_dir.is_dir():
        (assets_dir / "n_queens_network.mmd").write_text(net.generate_mermaid(), encoding="utf-8")
        (assets_dir / "n_queens_network.dot").write_text(net.generate_dot(), encoding="utf-8")

    return [queens[i].value.value for i in range(n)]


solution = solve_n_queens(8)
print(f"Solved 8-Queens rank placement: {solution}")

# Text / Unicode Board Output for LLMs & terminals:
print("--- Text / Unicode Chessboard ---")
for r in range(7, -1, -1):
    row_str = f"{r + 1} "
    for f in range(8):
        row_str += "♛ " if solution[f] == r else "· "
    print(row_str)
print("  a b c d e f g h")
```

---

## 3. Constraint Network Visualization (4-Queens Topology)

The $N$-Queens constraint network models files as discrete domain cells interconnected by a global row uniqueness constraint (`AllDifferentPropagator`) and pairwise diagonal non-attack propagators:

```mermaid
graph LR
  classDef bottom fill:#f8f9fa,stroke:#adb5bd,stroke-dasharray: 4 4,color:#6c757d;
  classDef contradiction fill:#fff5f5,stroke:#e53e3e,stroke-width:2px,color:#9b2c2c;
  classDef interval fill:#ebf8ff,stroke:#3182ce,stroke-width:1.5px;
  classDef gaussian fill:#f0fff4,stroke:#38a169,stroke-width:1.5px;
  classDef discrete fill:#faf5ff,stroke:#805ad5,stroke-width:1.5px;
  classDef cell fill:#edf2f7,stroke:#4a5568,stroke-width:1.5px;
  classDef value fill:#edf2f7,stroke:#4a5568,stroke-width:1.5px;
  classDef set fill:#faf5ff,stroke:#805ad5,stroke-width:1.5px;
  classDef belief fill:#f0fff4,stroke:#38a169,stroke-width:1.5px;
  classDef propagator fill:#f7fafc,stroke:#2d3748,stroke-width:1.5px;
  C_Q_0["Q_0<br/>{1}"]:::discrete
  C_Q_1["Q_1<br/>{3}"]:::discrete
  C_Q_2["Q_2<br/>{0}"]:::discrete
  C_Q_3["Q_3<br/>{2}"]:::discrete
  P_AllDiffRows["AllDiffRows"]:::propagator
  P_Diag_0_1["Diag_0_1"]:::propagator
  P_Diag_0_2["Diag_0_2"]:::propagator
  P_Diag_0_3["Diag_0_3"]:::propagator
  P_Diag_1_2["Diag_1_2"]:::propagator
  P_Diag_1_3["Diag_1_3"]:::propagator
  P_Diag_2_3["Diag_2_3"]:::propagator
  C_Q_0 --> P_AllDiffRows
  C_Q_1 --> P_AllDiffRows
  C_Q_2 --> P_AllDiffRows
  C_Q_3 --> P_AllDiffRows
  P_AllDiffRows --> C_Q_0
  P_AllDiffRows --> C_Q_1
  P_AllDiffRows --> C_Q_2
  P_AllDiffRows --> C_Q_3
  C_Q_0 --> P_Diag_0_1
  C_Q_1 --> P_Diag_0_1
  P_Diag_0_1 --> C_Q_0
  P_Diag_0_1 --> C_Q_1
  C_Q_0 --> P_Diag_0_2
  C_Q_2 --> P_Diag_0_2
  P_Diag_0_2 --> C_Q_0
  P_Diag_0_2 --> C_Q_2
  C_Q_0 --> P_Diag_0_3
  C_Q_3 --> P_Diag_0_3
  P_Diag_0_3 --> C_Q_0
  P_Diag_0_3 --> C_Q_3
  C_Q_1 --> P_Diag_1_2
  C_Q_2 --> P_Diag_1_2
  P_Diag_1_2 --> C_Q_1
  P_Diag_1_2 --> C_Q_2
  C_Q_1 --> P_Diag_1_3
  C_Q_3 --> P_Diag_1_3
  P_Diag_1_3 --> C_Q_1
  P_Diag_1_3 --> C_Q_3
  C_Q_2 --> P_Diag_2_3
  C_Q_3 --> P_Diag_2_3
  P_Diag_2_3 --> C_Q_2
  P_Diag_2_3 --> C_Q_3
```

### Downloadable 8-Queens Network Assets
- [Mermaid Diagram Source (`n_queens_network.mmd`)](../assets/n_queens_network.mmd)
- [Graphviz DOT Specification (`n_queens_network.dot`)](../assets/n_queens_network.dot)
