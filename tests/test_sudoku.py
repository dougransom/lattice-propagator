"""Unit tests demonstrating Sudoku solving and constraint propagation with Propagator Networks.

Sudoku is modeled as 81 Cells in a PropagatorNetwork with 27 AllDifferentPropagators:
- 9 Row constraints
- 9 Column constraints
- 9 Box (3x3) constraints

Candidate elimination and hidden-single deduction solve easy/medium puzzles
purely via monotonic lattice relaxation without any backtracking search.
"""

from collections.abc import Sequence

from lattice_propagator.lattice import Contradiction, DiscreteDomain
from lattice_propagator.primitives import (
    AllDifferentPropagator,
    Cell,
    PropagatorNetwork,
)


def _build_sudoku_network(
    name: str = "Sudoku",
) -> tuple[PropagatorNetwork, Sequence[Sequence[Cell]]]:
    """Helper to scaffold an 81-cell Sudoku PropagatorNetwork with 27 AllDifferent units."""
    net = PropagatorNetwork(name)
    grid = [[net.add_cell(f"R{r + 1}C{c + 1}") for c in range(9)] for r in range(9)]

    # 9 Row constraints
    for r in range(9):
        net.add_propagator(AllDifferentPropagator(f"Row_{r + 1}", grid[r]))

    # 9 Column constraints
    for c in range(9):
        net.add_propagator(AllDifferentPropagator(f"Col_{c + 1}", [grid[r][c] for r in range(9)]))

    # 9 Box (3x3) constraints
    for br in range(3):
        for bc in range(3):
            box_cells = [grid[br * 3 + r][bc * 3 + c] for r in range(3) for c in range(3)]
            net.add_propagator(AllDifferentPropagator(f"Box_{br + 1}_{bc + 1}", box_cells))

    return net, grid


def test_sudoku_full_solve_purely_with_propagators() -> None:
    """Verify that a 9x9 Sudoku puzzle is completely solved by monotonic propagation."""
    net, grid = _build_sudoku_network("SudokuSolver")

    # Classic puzzle solvable via constraint propagation
    puzzle_str = "003020600900305001001806400008102900700000008006708200002609500800203009005010300"

    for i, ch in enumerate(puzzle_str):
        r, c = divmod(i, 9)
        val = int(ch)
        initial_domain = DiscreteDomain.single(val) if val != 0 else DiscreteDomain.range(1, 10)
        grid[r][c].set_value(initial_domain, overwrite=True)

    iterations = net.run(max_iterations=500)

    # Verify that all 81 cells are determined
    solved_cells = [
        grid[r][c].value.value
        for r in range(9)
        for c in range(9)
        if isinstance(grid[r][c].value, DiscreteDomain) and grid[r][c].value.is_determined
    ]
    assert len(solved_cells) == 81
    assert iterations < 200  # Fast relaxation

    # Verify validity of every row, column, and 3x3 block
    digits = set(range(1, 10))
    for r in range(9):
        assert {grid[r][c].value.value for c in range(9)} == digits

    for c in range(9):
        assert {grid[r][c].value.value for r in range(9)} == digits

    for br in range(3):
        for bc in range(3):
            box_values = {
                grid[br * 3 + r][bc * 3 + c].value.value for r in range(3) for c in range(3)
            }
            assert box_values == digits


def test_sudoku_conflict_contradiction() -> None:
    """Verify that introducing conflicting clues in a unit signals a Contradiction."""
    net, grid = _build_sudoku_network("SudokuConflict")

    # Initialize all cells with domain 1..9
    for r in range(9):
        for c in range(9):
            grid[r][c].set_value(DiscreteDomain.range(1, 10), overwrite=True)

    # Introduce duplicate 5 in Row 1 (R1C1 and R1C5)
    grid[0][0].set_value(DiscreteDomain.single(5), overwrite=True)
    grid[0][4].set_value(DiscreteDomain.single(5), overwrite=True)

    net.run(max_iterations=100)

    # The propagator must flag a Contradiction
    contradictions = [c for row in grid for c in row if isinstance(c.value, Contradiction)]
    assert len(contradictions) > 0
    assert any("Duplicate value 5 in Row_1" in c.value.reason for c in contradictions)
