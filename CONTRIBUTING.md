# Contributing to Lattice Propagator

Thank you for contributing to **Lattice Propagator**!

Please see our comprehensive [Contributing Guidelines](docs/contributing.md) and [Development Guide](DEVELOPMENT.md).

### AI-Assisted Development & Agent Customizations
This project has been primarily developed using **Antigravity**, including the authoring of all implementation code, tests, documentation, and the generation of architectural diagrams and images. Repository-specific agent customizations and guidelines are located in `.agents/` (and root `AGENTS.md`).

### Quick Checklist Before Submitting a PR
1. **Dependency Guideline**: Strong preference for zero runtime dependencies. Any addition of dependencies (runtime or dev) requires explicit human approval.
2. Run `lattice-dev check` (or `./scripts/dev.sh check`) to verify linting, tests, and documentation build without errors.
3. Include tests for all new propagators or lattice types under `tests/`.
