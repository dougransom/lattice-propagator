# `lattice_propagator.clpz`

CLP(Z)-style constraint logic programming over unbounded integer domains ($\mathbb{Z} \cup \{-\infty, +\infty\}$), linear Diophantine equations, reification, and exact bounds propagation.

::: lattice_propagator.clpz
    options:
      show_root_heading: true
      members:
        - IntExpr
        - IntRelationPropagator
        - ReifiedIntRelationPropagator
        - IntLinearPropagator
        - IntAddPropagator
        - IntMulPropagator
        - IntAbsPropagator
        - IntAllDifferentPropagator
        - int_cell
        - int_cells
        - int_expr
        - normalize_int_op
        - add_int_rel
        - add_int_linear
        - add_int_add
        - add_int_mul
        - add_int_abs
        - add_int_reified
        - add_int_all_different
