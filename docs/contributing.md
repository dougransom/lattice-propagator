# Contributing Guidelines

Thank you for contributing to **Lattice Propagator**!

We welcome pull requests, issue reports, documentation improvements, and feedback.

---

## Code Standards

1. **Dependency Guideline**: Strong preference for zero runtime dependencies. Any addition of dependencies (runtime or dev) requires explicit human approval.
2. **Purity & Monotonicity**: Information in cells must only refine monotonically according to join-semilattice algebraic laws (associativity, commutativity, idempotence).
3. **Type Annotations**: All public classes, methods, and functions must include strict Python 3.11+ type hints.
4. **Docstrings**: We follow the **Google Python Style Guide** for docstrings to ensure clean rendering in `mkdocstrings`.
5. **Code Style**: Code is automatically formatted and linted via `ruff`.

---

## Development Workflow

1. **Fork and Clone**:
   ```bash
   git clone https://github.com/your-username/lattice-propagator.git
   cd lattice-propagator
   ```

2. **Install Development Tools**:
   ```bash
   uv venv
   uv pip install -e ".[all]"
   ```

3. **Create a Feature Branch**:
   ```bash
   git checkout -b feature/my-new-propagator
   ```

4. **Verify Your Changes**:
   Before opening a pull request, run the full verification suite:
   ```bash
   lattice-dev check
   ```
   This runs:
   - Ruff linting and format verification.
   - The full pytest suite with coverage.
   - Strict documentation build to catch broken links or docstring errors.

5. **Commit and Submit**:
   Use descriptive commit messages and open a pull request against the `main` branch.
