# Example: Digital Circuit Fault Diagnosis

A quintessential application of Truth Maintenance Systems (Johan de Kleer, 1986; Gerald Jay Sussman, 1980) is **model-based diagnosis**:
- A physical system (such as a 1-bit full adder) is modeled as a network of constraint propagators representing logic gates.
- Each gate's correct operation is conditioned on a defeasible hypothesis: `Assumption("gate_XOR1_ok")`.
- When observed test probe outputs contradict the expected deduction, a `Contradiction` is flagged.
- The [`NetworkTMS`](file:///home/doug/code/lattice-propagator/docs/api/tms.md) isolates the conflicting causal ancestry, extracts the minimal set of suspect components (a **nogood**), and retracts the faulty assumption.

---

## 1. Schematic Diagram (Human View)

![Full Adder Fault Schematic](../assets/circuit_fault.svg)

```mermaid
graph LR
    A["Input A (1)"] --> XOR1["XOR1 (S₁ = A ⊕ B)"]
    B["Input B (0)"] --> XOR1
    XOR1 -->|"S₁ (1)"| XOR2["XOR2 [FAULTY]"]
    Cin["Input C_in (1)"] --> XOR2
    XOR2 -->|"Expected: 0<br/>Probe: 1"| Sum["Sum [CONTRADICTION ⊤]"]
```

---

## 2. Executable Propagator Implementation

```python
from lattice_propagator import (
    Cell,
    Contradiction,
    FlatValue,
    Propagator,
    PropagatorNetwork,
)
from lattice_propagator.tms import NetworkTMS


class LogicGatePropagator(Propagator):
    """Boolean logic gate with Truth Maintenance System assumption tracking."""

    def __init__(
        self,
        name: str,
        gate_type: str,
        in1: Cell,
        in2: Cell,
        out: Cell,
        health_assumption: str,
    ) -> None:
        super().__init__(
            name,
            [in1, in2],
            [out],
            confidence=0.90,
            is_assumption=True,
        )
        self.gate_type = gate_type
        self.in1 = in1
        self.in2 = in2
        self.out = out
        self.health_assumption = health_assumption

    def alert(self, network: PropagatorNetwork) -> None:
        v1, v2 = self.in1.value, self.in2.value
        if isinstance(v1, FlatValue) and isinstance(v2, FlatValue):
            b1, b2 = bool(v1.val), bool(v2.val)
            if self.gate_type == "XOR":
                res = b1 ^ b2
            elif self.gate_type == "AND":
                res = b1 and b2
            elif self.gate_type == "OR":
                res = b1 or b2
            else:
                return

            self.emit(self.out, FlatValue(res), source=self.health_assumption)


# 1. Instantiate the Full Adder Network
net = PropagatorNetwork("FullAdderDiagnosis")
tms = NetworkTMS(net)

# Inputs
A = net.add_cell("A", FlatValue(True))
B = net.add_cell("B", FlatValue(False))
Cin = net.add_cell("Cin", FlatValue(True))

# Internal wires & Outputs registered with NetworkTMS
S1 = net.add_cell("S1")
C1 = net.add_cell("C1")
C2 = net.add_cell("C2")
Sum = net.add_cell("Sum")
Cout = net.add_cell("Cout")
for wire in ("S1", "C1", "C2", "Sum", "Cout"):
    tms.get_or_create_cell_tms(wire)

# Connect logic gates
net.add_propagator(LogicGatePropagator("XOR1", "XOR", A, B, S1, "gate_xor1_ok"))
net.add_propagator(LogicGatePropagator("XOR2", "XOR", S1, Cin, Sum, "gate_xor2_ok"))
net.add_propagator(LogicGatePropagator("AND1", "AND", A, B, C1, "gate_and1_ok"))
net.add_propagator(LogicGatePropagator("AND2", "AND", S1, Cin, C2, "gate_and2_ok"))
net.add_propagator(LogicGatePropagator("OR1", "OR", C1, C2, Cout, "gate_or1_ok"))

net.run()

print(f"Normal deduction: Sum = {Sum.value}, Cout = {Cout.value}")
assert Sum.value == FlatValue(False)
assert Cout.value == FlatValue(True)

# 2. Inject Physical Fault: Multimeter probe reads True on Sum pin
# Register ground truth observation (confidence=1.0, non-defeasible)
Sum.set_value(FlatValue(True), source="multimeter_probe", is_assumption=False)
net.run()

# 3. Contradiction Detection & Nogood Extraction
assert isinstance(Sum.value, Contradiction)
print(f"Contradiction: {Sum.value.reason}")

# DDB isolates the suspect assumption set (including transitive support from S1 -> XOR1) and retracts the weakest culprit
culprit = tms.resolve_contradiction(Sum.tms.active_sources)
print(f"Diagnostic conclusion: Isolated faulty component -> {culprit}")
print(f"Recorded Nogood set: {tms.nogoods}")
assert culprit in ("gate_xor1_ok", "gate_xor2_ok")

# 4. Programmatic Network Visualization & Causal Slicing
# Generate Mermaid flowchart highlighting the contradiction state
mermaid_diagram = net.generate_mermaid()

# Generate Graphviz DOT specification
dot_diagram = net.generate_dot()

# Extract upstream causal cone of influence leading into the contradiction at Sum
from lattice_propagator import NetworkGraph

causal_cone = NetworkGraph.from_slice(net, [Sum], direction="upstream")
causal_mermaid = causal_cone.to_mermaid()

# Persist diagram assets for external tools, CLI viewers, or CI/CD documentation
from pathlib import Path

assets_dir = Path("docs/assets")
if assets_dir.is_dir():
    (assets_dir / "circuit_fault_network.mmd").write_text(mermaid_diagram, encoding="utf-8")
    (assets_dir / "circuit_fault_network.dot").write_text(dot_diagram, encoding="utf-8")
```

---

## 3. Programmatic Network Visualization

Rather than drawing diagrams by hand, [`PropagatorNetwork`](../api/primitives.md) and [`NetworkGraph`](../api/graph.md) automatically generate live diagrams reflecting the exact network topology and lattice states.

### Full Circuit Network Topology (with Contradiction Highlight)

The diagram generated by `net.generate_mermaid()` highlights the contradictory state on `Sum` in bold red while displaying all logic gates, inputs, and intermediate wire values:

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
  C_A["A<br/>True"]:::value
  C_B["B<br/>False"]:::value
  C_C1["C1<br/>False"]:::value
  C_C2["C2<br/>True"]:::value
  C_Cin["Cin<br/>True"]:::value
  C_Cout["Cout<br/>True"]:::value
  C_S1["S1<br/>True"]:::value
  C_Sum["Sum<br/>⊤ (Conflicting flat values: False vs True)"]:::contradiction
  P_AND1["AND1"]:::propagator
  P_AND2["AND2"]:::propagator
  P_OR1["OR1"]:::propagator
  P_XOR1["XOR1"]:::propagator
  P_XOR2["XOR2"]:::propagator
  C_A --> P_XOR1
  C_B --> P_XOR1
  P_XOR1 --> C_S1
  C_S1 --> P_XOR2
  C_Cin --> P_XOR2
  P_XOR2 --> C_Sum
  C_A --> P_AND1
  C_B --> P_AND1
  P_AND1 --> C_C1
  C_S1 --> P_AND2
  C_Cin --> P_AND2
  P_AND2 --> C_C2
  C_C1 --> P_OR1
  C_C2 --> P_OR1
  P_OR1 --> C_Cout
```

### Upstream Causal Slice (Cone of Influence for `Sum`)

By slicing upstream from the failing cell (`NetworkGraph.from_slice(net, [Sum], direction="upstream")`), the engine isolates only the gates and wires implicated in the contradiction, excluding irrelevant components like `AND1`, `AND2`, `OR1`, `C1`, `C2`, and `Cout`:

```mermaid
graph LR
  classDef bottom fill:#f8f9fa,stroke:#adb5bd,stroke-dasharray: 4 4,color:#6c757d;
  classDef contradiction fill:#fff5f5,stroke:#e53e3e,stroke-width:2px,color:#9b2c2c;
  classDef cell fill:#edf2f7,stroke:#4a5568,stroke-width:1.5px;
  classDef value fill:#edf2f7,stroke:#4a5568,stroke-width:1.5px;
  classDef propagator fill:#f7fafc,stroke:#2d3748,stroke-width:1.5px;
  C_A["A<br/>True"]:::value
  C_B["B<br/>False"]:::value
  C_Cin["Cin<br/>True"]:::value
  C_S1["S1<br/>True"]:::value
  C_Sum["Sum<br/>⊤ (Conflicting flat values: False vs True)"]:::contradiction
  P_XOR1["XOR1"]:::propagator
  P_XOR2["XOR2"]:::propagator
  C_A --> P_XOR1
  C_B --> P_XOR1
  P_XOR1 --> C_S1
  C_S1 --> P_XOR2
  C_Cin --> P_XOR2
  P_XOR2 --> C_Sum
```

### Downloadable Diagram Assets

The generated diagram specifications can be exported to static assets or rendered in external tools:
- [Mermaid Diagram Source (`circuit_fault_network.mmd`)](../assets/circuit_fault_network.mmd)
- [Graphviz DOT Specification (`circuit_fault_network.dot`)](../assets/circuit_fault_network.dot)
