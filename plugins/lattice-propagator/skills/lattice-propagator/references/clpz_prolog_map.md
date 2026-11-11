# Prolog CLP(Z) → `lattice_propagator` Translation Map

| Prolog (`library(clpz)`) | `lattice_propagator` Equivalent | Notes |
| :--- | :--- | :--- |
| `X in inf..sup` | `x = int_cell(net, "x")` | Starts at `(-∞ .. +∞)` |
| `[X, Y] ins 1..9` | `x, y = int_cells(net, ["x", "y"], lo=1, hi=9)` | Bounded `IntegerDomain` |
| `X #= Y`, `X #\= Y`, `X #< Y`, `X #=< Y` | `add_int_rel(net, x, "#=", y)` (supports `#\=`, `#<`, `#=<`, `#>`, `#>=`) | Bidirectional relation |
| `2*X + 3*Y #= 7` | `add_int_linear(net, 2 * int_expr(x) + 3 * int_expr(y), "#=", 7)` | Includes Bézout GCD check |
| `abs(X) #= Y` | `add_int_abs(net, x, y)` | Exact segment mirroring |
| `B #<==> (X #=< Y)` | `add_int_reified(net, bool_cell, x, "#=<", y)` | Links `FlatValue(bool)` to relation |
| `all_different(Vs)` | `add_int_all_different(net, vs)` or `AllDifferentPropagator` | Forward elimination + hidden singles |
| `all_distinct(Vs)` | `AllDistinctPropagator(name, vs)` | Régin GAC via bipartite matching (`DiscreteDomain`) |
| `once(labeling([ff], Vs))` | `ChoiceEngine(net, variables=vs).first_solution()` | MRV + fixed-point propagation per branch |
| `labeling([ff], Vs)` (`;`) | `ChoiceEngine(net, variables=vs).iter_solutions()` | Lazy backtracking generator |
| `findnsols(N, Vs, ...)` | `ChoiceEngine(net, variables=vs).all_solutions(limit=N)` | Bounded solution list |

