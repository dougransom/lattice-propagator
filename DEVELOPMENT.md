# Development Guide

Quick reference for setting up and working on `lattice-propagator`.

For the complete rendered documentation site, see the [Online Documentation](https://dougransom.github.io/lattice-propagator/) or run `lattice-dev docs-serve`.

---

## 1. Quick Setup

```bash
# Clone the repository
git clone https://github.com/dougransom/lattice-propagator.git
cd lattice-propagator

# Install with all developer & documentation dependencies
uv pip install -e ".[all]"
```

---

## 2. Developer Commands (`lattice-dev`)

All common workflows are accessible via the `lattice-dev` CLI or `./scripts/dev.sh`:

```bash
# Run test suite with coverage
lattice-dev test --cov

# Check code formatting & linting
lattice-dev lint

# Autoformat code
lattice-dev format

# Live documentation server (http://127.0.0.1:8000)
lattice-dev docs-serve

# Build static documentation
lattice-dev docs-build

# Build distribution wheels and sdist
lattice-dev build

# Run all checks before pushing (lint + test + docs)
lattice-dev check
```

Or using the shell wrapper:
```bash
./scripts/dev.sh check
```
