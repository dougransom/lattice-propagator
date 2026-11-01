# Example: Sudoku & Constraint Search

Sudoku is a classic finite-domain constraint satisfaction problem:
- 81 cells, each with domain $\{1, \dots, 9\}$.
- 27 `AllDifferentPropagator` constraints: 9 rows, 9 columns, 9 $3 \times 3$ boxes.

Because `AllDifferentPropagator` continuously performs **pairwise exclusion** and **hidden single elimination**, easy-to-medium puzzles are solved purely monotonically without any backtracking search!

---

## Complete Executable Solver

```python
from lattice_propagator import (
    AllDifferentPropagator,
    Cell,
    DiscreteDomain,
    PropagatorNetwork,
)


def build_sudoku_network() -> tuple[PropagatorNetwork, list[list[Cell]]]:
    net = PropagatorNetwork("SudokuSolver")

    # 81 Cells
    grid = [[net.add_cell(f"R{r + 1}C{c + 1}") for c in range(9)] for r in range(9)]

    # 9 Row Constraints
    for r in range(9):
        net.add_propagator(AllDifferentPropagator(f"Row_{r + 1}", grid[r]))

    # 9 Column Constraints
    for c in range(9):
        net.add_propagator(AllDifferentPropagator(f"Col_{c + 1}", [grid[r][c] for r in range(9)]))

    # 9 3×3 Box Constraints
    for br in range(3):
        for bc in range(3):
            box_cells = [grid[br * 3 + r][bc * 3 + c] for r in range(3) for c in range(3)]
            net.add_propagator(AllDifferentPropagator(f"Box_{br + 1}_{bc + 1}", box_cells))

    return net, grid


# Instantiate the network
net, grid = build_sudoku_network()

puzzle = "003020600900305001001806400008102900700000008006708200002609500800203009005010300"

# Load initial clues into cells
for i, ch in enumerate(puzzle):
    r, c = divmod(i, 9)
    val = int(ch)
    initial_domain = DiscreteDomain.single(val) if val != 0 else DiscreteDomain.range(1, 10)
    grid[r][c].set_value(initial_domain, overwrite=True)

# Propagate constraints monotonically until fixed point:
net.run()

# Print solved board:
for r in range(9):
    print(" ".join(str(grid[r][c].value.value) for c in range(9)))
```
