"""Generalized Propagator Network Primitives and Constraint Engine.

Based on the propagator computational model by Alexey Radul and Gerald Jay Sussman:
- Radul, A., & Sussman, G. J. (2009). "The Art of the Propagator", MIT-CSAIL-TR-2009-002.
  https://dspace.mit.edu/handle/1721.1/44215
- Hanson, C., & Sussman, G. J. (2021). "Software Design for Flexibility", MIT Press, Chapter 7.
- Sussman, G. J., & Steele, G. L. (1980). "CONSTRAINTS", Artificial Intelligence 14(1).

Core building blocks for composing autonomous propagator networks:
- Cell: Reactive container holding lattice values with TMS dependency tracking.
- Propagator: Monotonic constraint operator linking input cells to output cells.
- Primitive Operators:
  * ArithmeticPropagator: Linear combinations, differences, and power balances.
  * RatePropagator: Derivative/velocity and time-to-threshold (ETA) intervals.
  * LagPropagator: First-order dynamic lag (RC thermal inertia / exponential smoothing).
  * ElasticModulatorPropagator: Interval constraint modulation based on cost/solar signals.
  * ThresholdPropagator: Bounded threshold comparisons with hysteresis.
- PropagatorNetwork: Fixed-point relaxation engine with TMS justification tracking.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from .lattice import (
    BOTTOM,
    Bottom,
    Contradiction,
    DiscreteDomain,
    GaussianValue,
    IntervalValue,
    LatticeValue,
    merge_lattice,
)


@dataclass
class Cell:
    """Reactive container holding an information lattice value."""

    cell_id: str
    value: LatticeValue = field(default_factory=lambda: BOTTOM)
    propagators: list[Propagator] = field(default_factory=list)
    network: PropagatorNetwork | None = None

    def add_propagator(self, propagator: Propagator) -> None:
        """Register a propagator that observes this cell."""
        if propagator not in self.propagators:
            self.propagators.append(propagator)

    def set_value(
        self,
        new_value: LatticeValue,
        source: str | None = None,
        overwrite: bool = False,
    ) -> bool:
        """Merge or update a value into this cell.

        Returns True if the cell's value was updated (information gained).
        """
        if overwrite or self.value == BOTTOM:
            if self.value == new_value:
                return False
            self.value = new_value
            if self.network:
                self.network.notify_changed(self, source=source)
            return True

        merged = merge_lattice(self.value, new_value)
        if merged == self.value:
            return False

        self.value = merged
        if self.network:
            self.network.notify_changed(self, source=source)
        return True

    def __repr__(self) -> str:
        return f"Cell({self.cell_id}: {self.value})"


class Propagator(ABC):
    """Abstract base class for all propagator operators."""

    def __init__(
        self,
        name: str,
        inputs: list[Cell],
        outputs: list[Cell],
    ) -> None:
        self.name = name
        self.inputs = inputs
        self.outputs = outputs
        for c in inputs:
            c.add_propagator(self)

    @abstractmethod
    def alert(self, network: PropagatorNetwork) -> None:
        """Execute propagation when an input cell updates."""


class ArithmeticPropagator(Propagator):
    """Computes a linear combination or difference: output = sum(w_i * x_i) + offset."""

    def __init__(
        self,
        name: str,
        inputs: list[Cell],
        output: Cell,
        weights: list[float] | None = None,
        offset: float = 0.0,
    ) -> None:
        super().__init__(name, inputs, [output])
        self.output = output
        self.weights = weights or [1.0] * len(inputs)
        self.offset = offset

    def alert(self, network: PropagatorNetwork) -> None:
        """Calculate weighted sum across input cells."""
        # Check if all inputs have values
        if any(isinstance(c.value, (Bottom, Contradiction)) for c in self.inputs):
            return

        # Case 1: Pure floats or Gaussians
        all_gaussian = all(isinstance(c.value, GaussianValue) for c in self.inputs)
        if all_gaussian:
            # Linear combination of Gaussians:
            # μ = sum(w_i * μ_i) + offset
            # σ² = sum(w_i² * σ_i²)
            mu = self.offset
            var = 0.0
            for c, w in zip(self.inputs, self.weights, strict=False):
                val = c.value
                assert isinstance(val, GaussianValue)
                mu += w * val.mean
                var += (w**2) * val.variance

            new_val = GaussianValue(mean=mu, variance=max(var, 1e-6))
            self.output.set_value(new_val, source=self.name)
            return

        # Case 2: Intervals
        all_interval = all(isinstance(c.value, (IntervalValue, GaussianValue)) for c in self.inputs)
        if all_interval:
            min_sum = self.offset
            max_sum = self.offset
            for c, w in zip(self.inputs, self.weights, strict=False):
                if isinstance(c.value, IntervalValue):
                    c_min, c_max = c.value.min_val, c.value.max_val
                else:
                    assert isinstance(c.value, GaussianValue)
                    c_min, c_max = c.value.confidence_interval(0.95)

                if w >= 0:
                    min_sum += w * c_min
                    max_sum += w * c_max
                else:
                    min_sum += w * c_max
                    max_sum += w * c_min

            new_val = IntervalValue(min_val=min_sum, max_val=max_sum)
            self.output.set_value(new_val, source=self.name)


class RatePropagator(Propagator):
    """Computes rate of change and estimated time to reach a target threshold.

    rate = (x_now - x_prev) / delta_t
    eta = (x_now - threshold) / rate
    """

    def __init__(
        self,
        name: str,
        input_cell: Cell,
        output_rate_cell: Cell,
        output_eta_cell: Cell | None = None,
        threshold: float = 0.0,
    ) -> None:
        outputs = [output_rate_cell]
        if output_eta_cell:
            outputs.append(output_eta_cell)
        super().__init__(name, [input_cell], outputs)

        self.input_cell = input_cell
        self.output_rate = output_rate_cell
        self.output_eta = output_eta_cell
        self.threshold = threshold

        self._prev_val: float | None = None
        self._prev_time: float | None = None

    def update_observation(
        self, current_val: float, current_time: float, network: PropagatorNetwork
    ) -> None:
        """Push a timestamped scalar observation into the rate calculator."""
        if self._prev_val is not None and self._prev_time is not None:
            dt = current_time - self._prev_time
            if dt > 0:
                dx = current_val - self._prev_val
                rate = dx / dt
                self.output_rate.set_value(
                    GaussianValue(mean=rate, variance=max(abs(rate) * 0.1, 0.01)),
                    source=self.name,
                    overwrite=True,
                )

                if self.output_eta is not None:
                    dist_to_thresh = current_val - self.threshold
                    # Approaching threshold if rate and dist_to_thresh have opposite signs
                    if dist_to_thresh > 0 and rate < -1e-4:
                        eta_sec = abs(dist_to_thresh / rate)
                        # Bounds [eta * 0.85, eta * 1.2]
                        self.output_eta.set_value(
                            IntervalValue(min_val=eta_sec * 0.85, max_val=eta_sec * 1.2),
                            source=self.name,
                            overwrite=True,
                        )
                    elif dist_to_thresh <= 0:
                        self.output_eta.set_value(
                            IntervalValue(min_val=0.0, max_val=0.0),
                            source=self.name,
                            overwrite=True,
                        )

        self._prev_val = current_val
        self._prev_time = current_time

    def alert(self, network: PropagatorNetwork) -> None:
        """Triggered when input cell updates."""
        val = self.input_cell.value
        if isinstance(val, GaussianValue):
            scalar = val.mean
        elif isinstance(val, IntervalValue):
            scalar = val.center
        else:
            return

        import time

        self.update_observation(scalar, time.time(), network)


class LagPropagator(Propagator):
    """First-order dynamic lag filter (RC thermal model or exponential decay).

    x(t + dt) = x(t) + (dt / tau) * (target - x(t))
    """

    def __init__(
        self,
        name: str,
        target_cell: Cell,
        state_cell: Cell,
        output_cell: Cell,
        tau: float,  # Time constant (in seconds or hours)
    ) -> None:
        super().__init__(name, [target_cell, state_cell], [output_cell])
        self.target_cell = target_cell
        self.state_cell = state_cell
        self.output_cell = output_cell
        self.tau = max(tau, 1e-3)

    def step(self, dt: float) -> None:
        """Advance time by dt and propagate the dynamic lag."""
        t_val = self.target_cell.value
        s_val = self.state_cell.value

        if isinstance(t_val, (Bottom, Contradiction)) or isinstance(s_val, (Bottom, Contradiction)):
            return

        alpha = 1.0 - math.exp(-dt / self.tau)

        if isinstance(t_val, GaussianValue) and isinstance(s_val, GaussianValue):
            next_mu = s_val.mean + alpha * (t_val.mean - s_val.mean)
            next_var = s_val.variance * (1 - alpha) ** 2 + t_val.variance * (alpha**2)
            self.output_cell.set_value(
                GaussianValue(mean=next_mu, variance=max(next_var, 1e-4)),
                source=self.name,
                overwrite=True,
            )
        elif isinstance(t_val, IntervalValue) and isinstance(s_val, IntervalValue):
            next_min = s_val.min_val + alpha * (t_val.min_val - s_val.min_val)
            next_max = s_val.max_val + alpha * (t_val.max_val - s_val.max_val)
            self.output_cell.set_value(
                IntervalValue(min_val=next_min, max_val=next_max),
                source=self.name,
                overwrite=True,
            )

    def alert(self, network: PropagatorNetwork) -> None:
        """Alerted when input changes; steps with dt=1.0 or user-driven simulation."""
        self.step(dt=1.0)


class KalmanEstimatorPropagator(Propagator):
    """Linear 2-State Kalman Filter Propagator.

    Tracks an internal continuous state vector [x, dx/dt]^T (e.g. [position, velocity]
    or [temperature, rate]) from noisy scalar observations, projecting marginal Gaussians
    onto individual output cells.
    """

    def __init__(
        self,
        name: str,
        measurement_cell: Cell,
        output_state_cell: Cell,
        output_rate_cell: Cell,
        process_noise_q: float = 0.1,
        default_measurement_noise_r: float = 1.0,
        initial_state: tuple[float, float] = (0.0, 0.0),
        initial_cov: tuple[float, float] = (100.0, 10.0),
    ) -> None:
        super().__init__(name, [measurement_cell], [output_state_cell, output_rate_cell])
        self.measurement_cell = measurement_cell
        self.output_state_cell = output_state_cell
        self.output_rate_cell = output_rate_cell
        self.q = max(process_noise_q, 1e-6)
        self.default_r = max(default_measurement_noise_r, 1e-6)

        # State vector [x, v]
        self.x: float = initial_state[0]
        self.v: float = initial_state[1]

        # Covariance matrix [[P00, P01], [P10, P11]] (P01 == P10)
        self.p00: float = initial_cov[0]
        self.p01: float = 0.0
        self.p11: float = initial_cov[1]

        self._last_time: float | None = None
        self._initialized: bool = False

    def reset(
        self,
        x: float = 0.0,
        v: float = 0.0,
        p00: float = 100.0,
        p11: float = 10.0,
    ) -> None:
        """Reset internal filter state."""
        self.x = x
        self.v = v
        self.p00 = p00
        self.p01 = 0.0
        self.p11 = p11
        self._last_time = None
        self._initialized = False

    def step(self, z: float, r: float | None = None, dt: float | None = None) -> None:
        """Perform predict and update step for observation z."""
        if not self._initialized:
            self.x = z
            self.v = 0.0
            self.p00 = r if r is not None else self.default_r
            self.p01 = 0.0
            self.p11 = self.q * 10.0
            self._initialized = True
            self._publish()
            return

        dt_val = max(dt if dt is not None else 1.0, 1e-4)
        meas_r = max(r if r is not None else self.default_r, 1e-6)

        # 1. Predict
        x_pred = self.x + self.v * dt_val
        v_pred = self.v

        dt2 = dt_val * dt_val
        dt3 = dt2 * dt_val
        p00_pred = self.p00 + 2.0 * dt_val * self.p01 + dt2 * self.p11 + self.q * (dt3 / 3.0)
        p01_pred = self.p01 + dt_val * self.p11 + self.q * (dt2 / 2.0)
        p11_pred = self.p11 + self.q * dt_val

        # 2. Update (H = [1, 0])
        y = z - x_pred
        s = p00_pred + meas_r

        k0 = p00_pred / s
        k1 = p01_pred / s

        self.x = x_pred + k0 * y
        self.v = v_pred + k1 * y

        self.p00 = max((1.0 - k0) * p00_pred, 1e-6)
        self.p01 = (1.0 - k0) * p01_pred
        self.p11 = max(p11_pred - k1 * p01_pred, 1e-6)

        self._publish()

    def _publish(self) -> None:
        """Project marginal distributions to output cells."""
        self.output_state_cell.set_value(
            GaussianValue(mean=self.x, variance=self.p00),
            source=self.name,
            overwrite=True,
        )
        self.output_rate_cell.set_value(
            GaussianValue(mean=self.v, variance=self.p11),
            source=self.name,
            overwrite=True,
        )

    def alert(self, network: PropagatorNetwork) -> None:
        """Handle new observation in measurement cell."""
        val = self.measurement_cell.value
        if isinstance(val, (Bottom, Contradiction)):
            return

        import time

        now = time.time()
        dt = (now - self._last_time) if self._last_time is not None else 1.0
        self._last_time = now

        if isinstance(val, GaussianValue):
            z = val.mean
            r = val.variance
        elif isinstance(val, IntervalValue):
            z = val.center
            sigma = max(val.width / 4.0, 1e-3)
            r = sigma * sigma
        else:
            return

        self.step(z, r=r, dt=dt)


class ElasticModulatorPropagator(Propagator):
    """Modulates a target within an acceptable tolerance interval based on a driving signal (e.g. price, solar).

    Target = clamp(Nominal + sensitivity * (Baseline - Signal), [Min, Max])
    """

    def __init__(
        self,
        name: str,
        signal_cell: Cell,
        output_cell: Cell,
        acceptable_range: IntervalValue,
        nominal_target: float,
        baseline_signal: float,
        sensitivity: float,
    ) -> None:
        super().__init__(name, [signal_cell], [output_cell])
        self.signal_cell = signal_cell
        self.output_cell = output_cell
        self.acceptable_range = acceptable_range
        self.nominal_target = nominal_target
        self.baseline_signal = baseline_signal
        self.sensitivity = sensitivity

    def alert(self, network: PropagatorNetwork) -> None:
        """Compute modulated target."""
        val = self.signal_cell.value
        if isinstance(val, (Bottom, Contradiction)):
            return

        sig = val.mean if isinstance(val, GaussianValue) else val.center
        # High signal (e.g. high price) lowers target; cheap signal raises target
        adjustment = self.sensitivity * (self.baseline_signal - sig)
        modulated = self.nominal_target + adjustment

        clamped = max(
            self.acceptable_range.min_val,
            min(self.acceptable_range.max_val, modulated),
        )

        self.output_cell.set_value(
            GaussianValue(mean=clamped, variance=0.04),
            source=self.name,
            overwrite=True,
        )


class ThresholdPropagator(Propagator):
    """Evaluates whether an input cell crosses a critical threshold."""

    def __init__(
        self,
        name: str,
        input_cell: Cell,
        output_bool_cell: Cell,
        threshold: float,
        below: bool = True,
    ) -> None:
        super().__init__(name, [input_cell], [output_bool_cell])
        self.input_cell = input_cell
        self.output_bool = output_bool_cell
        self.threshold = threshold
        self.below = below

    def alert(self, network: PropagatorNetwork) -> None:
        """Evaluate threshold predicate."""
        val = self.input_cell.value
        if isinstance(val, (Bottom, Contradiction)):
            return

        scalar = val.mean if isinstance(val, GaussianValue) else val.center
        is_triggered = (scalar < self.threshold) if self.below else (scalar > self.threshold)
        # 1.0 = True, 0.0 = False in numeric interval
        self.output_bool.set_value(
            IntervalValue(
                min_val=1.0 if is_triggered else 0.0, max_val=1.0 if is_triggered else 0.0
            ),
            source=self.name,
            overwrite=True,
        )


class AllDifferentPropagator(Propagator):
    """Enforces that all cells in a unit/group must take mutually distinct values from a DiscreteDomain.

    Performs:
    1. Forward Elimination (Naked Singles): When a cell resolves to a unique value {v}, eliminates v from
       all peers in the unit.
    2. Hidden Singles Deduction: When a candidate v occurs in exactly one undetermined cell in the unit,
       narrows that cell directly to {v}.
    3. Contradiction Detection: Signals Contradiction on duplicate determined values or exhausted domains.
    """

    def __init__(self, name: str, cells: list[Cell]) -> None:
        super().__init__(name, cells, cells)
        self.cells = cells

    def _collect_determined(self) -> dict[Any, Cell] | None:
        """Collect determined values, returning None and setting contradiction on duplicates."""
        determined: dict[Any, Cell] = {}
        for cell in self.cells:
            if isinstance(cell.value, DiscreteDomain) and cell.value.is_determined:
                v = cell.value.value
                if v in determined:
                    cell.set_value(
                        Contradiction(
                            reason=f"Duplicate value {v} in {self.name} between {determined[v].cell_id} and {cell.cell_id}",
                            conflicting_values=(determined[v].value, cell.value),
                        ),
                        source=self.name,
                    )
                    return None
                determined[v] = cell
        return determined

    def _eliminate_value_from_peers(self, v: Any, source_cell: Cell) -> tuple[bool, bool]:
        """Eliminate value v from all peer cells. Returns (did_change, has_conflict)."""
        changed = False
        for target in self.cells:
            if (
                target is not source_cell
                and isinstance(target.value, DiscreteDomain)
                and target.value.contains(v)
            ):
                remaining = target.value.candidates - {v}
                if not remaining:
                    target.set_value(
                        Contradiction(
                            reason=f"Cell {target.cell_id} exhausted all candidates by eliminating {v} in {self.name}",
                            conflicting_values=(target.value,),
                        ),
                        source=self.name,
                    )
                    return False, True
                if target.set_value(DiscreteDomain(candidates=remaining), source=self.name):
                    changed = True
        return changed, False

    def _forward_eliminate(self) -> bool:
        """Run forward elimination loop until local quiescence. Returns False on contradiction."""
        changed = True
        while changed:
            changed = False
            determined = self._collect_determined()
            if determined is None:
                return False

            for v, source_cell in list(determined.items()):
                did_change, has_conflict = self._eliminate_value_from_peers(v, source_cell)
                if has_conflict:
                    return False
                if did_change:
                    changed = True
        return True

    def _deduce_hidden_singles(self) -> None:
        """Deduce hidden singles where a candidate only appears in a single undetermined cell."""
        current_determined = {
            c.value.value
            for c in self.cells
            if isinstance(c.value, DiscreteDomain) and c.value.is_determined
        }
        candidate_occurrences: dict[Any, list[Cell]] = {}
        for cell in self.cells:
            if isinstance(cell.value, DiscreteDomain) and not cell.value.is_determined:
                for cand in cell.value.candidates:
                    if cand not in current_determined:
                        candidate_occurrences.setdefault(cand, []).append(cell)

        assigned_cell_ids: set[str] = set()
        for cand, containing_cells in candidate_occurrences.items():
            if len(containing_cells) == 1:
                target_cell = containing_cells[0]
                if target_cell.cell_id not in assigned_cell_ids:
                    assigned_cell_ids.add(target_cell.cell_id)
                    target_cell.set_value(
                        DiscreteDomain.single(cand),
                        source=f"{self.name}:hidden_single",
                    )

    def alert(self, network: PropagatorNetwork) -> None:
        """Run all-different constraint propagation across the cell group."""
        if self._forward_eliminate():
            self._deduce_hidden_singles()


@dataclass(frozen=True)
class ScenePhase:
    """A distinct temporal phase in a dynamic scene trajectory envelope."""

    name: str
    duration_seconds: float
    bounds: IntervalValue
    transition: str = "linear"  # "linear" or "step"


class DynamicScenePropagator(Propagator):
    """Dynamic Scene Propagator modeling temporal envelopes and contextual bounds.

    Maps elapsed time since scene activation (delta_t) through a multi-phase
    trajectory envelope (e.g. Wakeup, Cinema, Sunset), optionally modulated
    by contextual reference cells (e.g. circadian CCT or ambient lux) and
    temporary modifiers (e.g. TV paused or motion detected).
    """

    def __init__(
        self,
        name: str,
        active_cell: Cell,
        output_target_cell: Cell,
        phases: list[ScenePhase],
        reference_cell: Cell | None = None,
        modifier_cell: Cell | None = None,
        modifier_delta: float = 0.0,
        clamp_bounds: IntervalValue | None = None,
        output_phase_cell: Cell | None = None,
    ) -> None:
        inputs = [active_cell]
        if reference_cell is not None:
            inputs.append(reference_cell)
        if modifier_cell is not None:
            inputs.append(modifier_cell)

        outputs = [output_target_cell]
        if output_phase_cell is not None:
            outputs.append(output_phase_cell)

        super().__init__(name, inputs, outputs)
        self.active_cell = active_cell
        self.output_target_cell = output_target_cell
        self.phases = phases
        self.reference_cell = reference_cell
        self.modifier_cell = modifier_cell
        self.modifier_delta = modifier_delta
        self.clamp_bounds = clamp_bounds
        self.output_phase_cell = output_phase_cell

        self._start_time: float | None = None
        self._elapsed_time: float = 0.0

    def is_active(self) -> bool:
        """Return True if the active_cell signifies an active scene."""
        val = self.active_cell.value
        if isinstance(val, (Bottom, Contradiction)):
            return False
        if isinstance(val, DiscreteDomain):
            v = val.value
            return v not in (False, "off", 0, "inactive", None)
        return True

    def reset(self) -> None:
        """Reset elapsed time and activation state."""
        self._start_time = None
        self._elapsed_time = 0.0

    def step(self, dt: float) -> None:
        """Advance scene timeline by dt seconds and evaluate current bounds."""
        if not self.is_active():
            if self._start_time is not None or self.output_target_cell.value != BOTTOM:
                self.reset()
                self.output_target_cell.set_value(BOTTOM, source=self.name, overwrite=True)
                if self.output_phase_cell is not None:
                    self.output_phase_cell.set_value(BOTTOM, source=self.name, overwrite=True)
            return

        if self._start_time is None:
            self._start_time = 0.0
            self._elapsed_time = 0.0
        else:
            self._elapsed_time += max(0.0, dt)

        self._evaluate()

    def evaluate_at(self, elapsed_seconds: float) -> None:
        """Evaluate scene bounds at a specific elapsed duration."""
        if not self.is_active():
            self.output_target_cell.set_value(BOTTOM, source=self.name, overwrite=True)
            if self.output_phase_cell is not None:
                self.output_phase_cell.set_value(BOTTOM, source=self.name, overwrite=True)
            return

        self._start_time = 0.0
        self._elapsed_time = max(0.0, elapsed_seconds)
        self._evaluate()

    def _find_current_phase(self, elapsed: float) -> tuple[ScenePhase, IntervalValue, float]:
        """Find the active phase, reference previous bounds, and phase start timestamp."""
        accumulated_t = 0.0
        current_phase = self.phases[-1]
        prev_bounds = self.phases[0].bounds
        phase_start_t = 0.0

        for i, phase in enumerate(self.phases):
            phase_duration = max(0.0, phase.duration_seconds)
            phase_end_t = accumulated_t + phase_duration
            if elapsed < phase_end_t or i == len(self.phases) - 1:
                current_phase = phase
                phase_start_t = accumulated_t
                prev_bounds = self.phases[i - 1].bounds if i > 0 else phase.bounds
                break
            accumulated_t = phase_end_t

        return current_phase, prev_bounds, phase_start_t

    def _interpolate_bounds(
        self,
        phase: ScenePhase,
        prev_bounds: IntervalValue,
        phase_start_t: float,
        elapsed: float,
    ) -> IntervalValue:
        """Interpolate bounds for the current phase or return step bounds."""
        if phase.transition != "linear":
            return phase.bounds
        dur = max(phase.duration_seconds, 1e-6)
        progress = min(1.0, max(0.0, (elapsed - phase_start_t) / dur))
        cur_min = prev_bounds.min_val + progress * (phase.bounds.min_val - prev_bounds.min_val)
        cur_max = prev_bounds.max_val + progress * (phase.bounds.max_val - prev_bounds.max_val)
        return IntervalValue(min_val=cur_min, max_val=cur_max)

    def _is_modifier_active(self) -> bool:
        """Check if secondary modifier cell is currently active."""
        if self.modifier_cell is None or isinstance(
            self.modifier_cell.value, (Bottom, Contradiction)
        ):
            return False
        if isinstance(self.modifier_cell.value, DiscreteDomain):
            return self.modifier_cell.value.value not in (False, "off", 0, None)
        return True

    def _apply_modulations(self, bounds: IntervalValue) -> IntervalValue:
        """Apply reference cell clamping, reactive modifiers, and safety envelope."""
        cur_bounds = bounds
        if self.reference_cell is not None and isinstance(self.reference_cell.value, IntervalValue):
            clamped = cur_bounds.clamp(self.reference_cell.value)
            if isinstance(clamped, IntervalValue):
                cur_bounds = clamped

        if self._is_modifier_active():
            cur_bounds = cur_bounds + self.modifier_delta

        if self.clamp_bounds is not None:
            envelope = cur_bounds.clamp(self.clamp_bounds)
            if isinstance(envelope, IntervalValue):
                cur_bounds = envelope

        return cur_bounds

    def _evaluate(self) -> None:
        """Compute and propagate current interval bounds based on elapsed timeline."""
        if not self.phases:
            return

        phase, prev_bounds, phase_start_t = self._find_current_phase(self._elapsed_time)
        raw_bounds = self._interpolate_bounds(phase, prev_bounds, phase_start_t, self._elapsed_time)
        final_bounds = self._apply_modulations(raw_bounds)

        self.output_target_cell.set_value(final_bounds, source=self.name, overwrite=True)
        if self.output_phase_cell is not None:
            self.output_phase_cell.set_value(
                DiscreteDomain.single(phase.name),
                source=self.name,
                overwrite=True,
            )

    def alert(self, network: PropagatorNetwork) -> None:
        """Triggered when active_cell, reference_cell, or modifier_cell changes."""
        self.step(dt=0.0)


class PropagatorNetwork:
    """Orchestrates cells and propagators, driving the network to fixed-point quiescence."""

    def __init__(self, name: str = "Network") -> None:
        self.name = name
        self.cells: dict[str, Cell] = {}
        self.propagators: list[Propagator] = []
        self._queue: deque[Propagator] = deque()
        self._sources_log: dict[str, list[str]] = {}

    def add_cell(self, cell_id: str, initial_value: LatticeValue = BOTTOM) -> Cell:
        """Create or register a cell in this network."""
        if cell_id in self.cells:
            return self.cells[cell_id]
        cell = Cell(cell_id=cell_id, value=initial_value, network=self)
        self.cells[cell_id] = cell
        return cell

    def add_propagator(self, propagator: Propagator) -> None:
        """Register a propagator in this network."""
        self.propagators.append(propagator)
        # Trigger initial run
        self._queue.append(propagator)

    def notify_changed(self, cell: Cell, source: str | None = None) -> None:
        """Enqueue all propagators watching the changed cell."""
        if source:
            self._sources_log.setdefault(cell.cell_id, []).append(source)
        for p in cell.propagators:
            if p not in self._queue:
                self._queue.append(p)

    def run(self, max_iterations: int = 100) -> int:
        """Run the propagation queue to fixed-point quiescence. Returns iterations taken."""
        iterations = 0
        while self._queue and iterations < max_iterations:
            propagator = self._queue.popleft()
            propagator.alert(self)
            iterations += 1
        return iterations

    def generate_mermaid(self) -> str:
        """Generate a Mermaid diagram representing the network structure and state."""
        lines = ["```mermaid", "graph LR"]
        for p in self.propagators:
            p_node = f'P_{p.name.replace(" ", "_")}["{p.name}"]'
            for in_c in p.inputs:
                c_node = f'C_{in_c.cell_id.replace(" ", "_")}["{in_c.cell_id}<br/>{in_c.value}"]'
                lines.append(f"  {c_node} --> {p_node}")
            for out_c in p.outputs:
                c_node = f'C_{out_c.cell_id.replace(" ", "_")}["{out_c.cell_id}<br/>{out_c.value}"]'
                lines.append(f"  {p_node} --> {c_node}")
        lines.append("```")
        return "\n".join(lines)
