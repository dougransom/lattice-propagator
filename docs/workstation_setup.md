# Workstation & Agent Setup

This guide helps developers and coding-agent users configure their workstations to build with `lattice-propagator`—both inside this repository and across downstream projects.

---

## 1. Python Environment Setup (Consumer Projects)

`lattice-propagator` targets **Python 3.11+** with **zero mandatory runtime dependencies** (`dependencies = []` in `pyproject.toml`) and ships a PEP 561 [`py.typed`](https://github.com/dougransom/lattice-propagator/blob/main/src/lattice_propagator/py.typed) marker for static type checking (`pyright` / `mypy`).

=== "Using uv (Recommended)"

    ```bash
    uv add lattice-propagator
    ```

=== "Using pip"

    ```bash
    pip install lattice-propagator
    ```

=== "Local Editable Checkout"

    ```bash
    uv pip install -e /path/to/lattice-propagator
    ```

---

## 2. Visual Debugging Tools (`dot` & Mermaid)

Networks expose `net.generate_mermaid()` and `net.generate_dot()` for inspecting constraint topologies, fixed points, and contradictions. Installing Graphviz and a Mermaid preview makes debugging effortless for both humans and agents:

- **Graphviz CLI:** Install `graphviz` (`sudo apt install graphviz` / `brew install graphviz`) to render `.dot` exports (`dot -Tsvg network.dot -o network.svg`).
- **IDE Markdown / Mermaid Preview:** Enable built-in or extension Mermaid rendering so generated `.mmd` diagrams display inline.

---

## 3. Coding-Agent Plugin & Skill Setup

The repository ships a distributable agent bundle at [`plugins/lattice-propagator/`](https://github.com/dougransom/lattice-propagator/tree/main/plugins/lattice-propagator) containing:
- **`rules/AGENTS.md`**: A compact problem-recognition rule that prompts agents to recognize constraint-propagation, sensor-fusion, CLP(Z), and TMS problems instead of writing ad-hoc imperative `if/else` arbitration.
- **`skills/lattice-propagator/SKILL.md`**: A progressive-disclosure usage guide with lattice selection tables, `ChoiceEngine` vs. `NetworkTMS` workflows, Prolog CLP(Z) mappings, and starter recipes.

### Installing Globally in Antigravity

Copy or symlink the plugin into your global Antigravity config so it activates across **all** projects on your workstation:

```bash
mkdir -p ~/.gemini/config/plugins
ln -s /path/to/lattice-propagator/plugins/lattice-propagator \
  ~/.gemini/config/plugins/lattice-propagator
```

*(Alternatively, register its path in `~/.gemini/config/plugins.json`, or use `agy plugin` management commands.)*

### Using the Skill with Other Coding Agents

`SKILL.md` follows the open Agent Skills convention (`skills/<name>/SKILL.md`), so you can link just the skill directory into other agent tools or any target repository's `.agents/` folder:

```bash
# Project-local (any tool supporting .agents/skills/)
mkdir -p .agents/skills
ln -s /path/to/lattice-propagator/plugins/lattice-propagator/skills/lattice-propagator \
  .agents/skills/lattice-propagator

# Or global skill folder (e.g., Claude Code / Codex)
mkdir -p ~/.claude/skills
ln -s /path/to/lattice-propagator/plugins/lattice-propagator/skills/lattice-propagator \
  ~/.claude/skills/lattice-propagator
```

---

## 4. Essential Links for Agents & Developers

Bookmark or reference these entry points in project `AGENTS.md` / prompts:

- **API Reference Overview:** [`api/index.md`](api/index.md) ([Hosted](https://dougransom.github.io/lattice-propagator/api/))
- **Design Guidelines (When to Use What):** [`concepts/design_guidelines.md`](concepts/design_guidelines.md) ([Hosted](https://dougransom.github.io/lattice-propagator/concepts/design_guidelines/))
- **Getting Started:** [`getting_started.md`](getting_started.md) ([Hosted](https://dougransom.github.io/lattice-propagator/getting_started/))
- **Truth Maintenance (`NetworkTMS`):** [`concepts/tms.md`](concepts/tms.md) ([Hosted](https://dougransom.github.io/lattice-propagator/concepts/tms/))
- **Machine-Readable LLM Index (`llms.txt`):** [`llms.txt`](llms.txt) ([Hosted](https://dougransom.github.io/lattice-propagator/llms.txt))

!!! tip "Prompting Tip for Higher-Quality Agent Solutions"
    When asking an agent to solve a constraint or fusion problem with `lattice-propagator`, ask for **bidirectional and contradiction tests** alongside the forward case (e.g., *"Verify forward deduction, backward deduction, and that conflicting bounds produce `Contradiction`"*). That immediately catches one-way imperative workarounds.

