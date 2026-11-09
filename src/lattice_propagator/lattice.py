"""Information Lattices and Monotonic Merge Operations for the Propagator Engine.

Theoretical Foundation:
Information within propagator cells is structured as join-semilattices, ensuring that
merging (⊔) partial information is associative, commutative, and idempotent.
- Radul, A., & Sussman, G. J. (2009). "The Art of the Propagator", Section 2: Partial Information.
  https://dspace.mit.edu/handle/1721.1/44215
- Radul, A. (2009). "Propagation Networks: A Flexible and Expressive Substrate for Computation", MIT PhD.
  https://dspace.mit.edu/handle/1721.1/54635

Implements mathematical partial orders:
- Bottom (⊥): Complete ignorance / unconstrained / offline.
- Top (⊤): Contradiction / mutual exclusion.
- GaussianValue: N(μ, σ²) continuous statistical distribution.
- IntervalValue: [min, max] bounding intervals.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class LatticeValue:
    """Base class for all elements of an information lattice."""

    def merge(self, other: LatticeValue) -> LatticeValue:
        """Monotonically merge this value with another lattice value."""
        return merge_lattice(self, other)


@dataclass(frozen=True)
class Bottom(LatticeValue):
    """Bottom element (⊥): represents complete ignorance or absence of data."""

    def __repr__(self) -> str:
        return "⊥(Bottom)"


@dataclass(frozen=True)
class Contradiction(LatticeValue):
    """Top element (⊤): represents a mutual contradiction between premises."""

    reason: str = "Conflicting premises"
    conflicting_values: tuple[Any, ...] = field(default_factory=tuple)

    def __repr__(self) -> str:
        return f"⊤(Contradiction: {self.reason})"


@dataclass(frozen=True)
class GaussianValue(LatticeValue):
    """Gaussian distribution N(mean, variance).

    Used for continuous sensor measurements with estimated noise/variance.
    """

    mean: float
    variance: float

    def __post_init__(self) -> None:
        if self.variance <= 0.0:
            raise ValueError(f"Variance must be strictly positive, got {self.variance}")

    @property
    def standard_deviation(self) -> float:
        """Return the standard deviation (σ)."""
        return math.sqrt(self.variance)

    @property
    def precision(self) -> float:
        """Return precision (1 / σ²)."""
        return 1.0 / self.variance

    def confidence_interval(self, confidence: float = 0.95) -> tuple[float, float]:
        """Return confidence interval [mean - z*σ, mean + z*σ]. Default is 95% (z=1.96)."""
        # Common z-multipliers
        z = 1.95996 if math.isclose(confidence, 0.95, rel_tol=1e-3) else 2.57583
        margin = z * self.standard_deviation
        return (self.mean - margin, self.mean + margin)

    def __repr__(self) -> str:
        return f"Gaussian(μ={self.mean:.3f}, σ²={self.variance:.4f})"


@dataclass(frozen=True)
class IntervalValue(LatticeValue):
    """Interval bounding [min_val, max_val].

    Used for physical bounds, tolerance bands, comfort ranges, and actuation limits.
    Supports interval arithmetic (+, -, *, clamp).
    """

    min_val: float
    max_val: float

    def __post_init__(self) -> None:
        if self.min_val > self.max_val:
            raise ValueError(f"min_val ({self.min_val}) cannot exceed max_val ({self.max_val})")

    @property
    def center(self) -> float:
        """Return the midpoint of the interval."""
        return (self.min_val + self.max_val) / 2.0

    @property
    def width(self) -> float:
        """Return the width of the interval."""
        return self.max_val - self.min_val

    def contains(self, x: float) -> bool:
        """Check if x lies within this interval."""
        return self.min_val <= x <= self.max_val

    def clamp(self, bounds: IntervalValue) -> IntervalValue | Contradiction:
        """Clamp / intersect this interval with an allowed bounding interval."""
        result = merge_lattice(self, bounds)
        if isinstance(result, (IntervalValue, Contradiction)):
            return result
        return Contradiction(
            reason=f"Failed to clamp {self} to {bounds}",
            conflicting_values=(self, bounds),
        )

    def __add__(self, other: Any) -> IntervalValue:
        if isinstance(other, IntervalValue):
            return IntervalValue(self.min_val + other.min_val, self.max_val + other.max_val)
        if isinstance(other, (int, float)):
            return IntervalValue(self.min_val + other, self.max_val + other)
        return NotImplemented

    def __radd__(self, other: Any) -> IntervalValue:
        return self.__add__(other)

    def __sub__(self, other: Any) -> IntervalValue:
        if isinstance(other, IntervalValue):
            return IntervalValue(self.min_val - other.max_val, self.max_val - other.min_val)
        if isinstance(other, (int, float)):
            return IntervalValue(self.min_val - other, self.max_val - other)
        return NotImplemented

    def __rsub__(self, other: Any) -> IntervalValue:
        if isinstance(other, (int, float)):
            return IntervalValue(other - self.max_val, other - self.min_val)
        return NotImplemented

    def __mul__(self, other: Any) -> IntervalValue:
        if isinstance(other, IntervalValue):
            products = (
                self.min_val * other.min_val,
                self.min_val * other.max_val,
                self.max_val * other.min_val,
                self.max_val * other.max_val,
            )
            return IntervalValue(min(products), max(products))
        if isinstance(other, (int, float)):
            p1 = self.min_val * other
            p2 = self.max_val * other
            return IntervalValue(min(p1, p2), max(p1, p2))
        return NotImplemented

    def __rmul__(self, other: Any) -> IntervalValue:
        return self.__mul__(other)

    def __truediv__(self, other: Any) -> IntervalValue:
        if isinstance(other, IntervalValue):
            if other.contains(0.0):
                raise ZeroDivisionError(
                    f"Cannot divide interval by interval containing zero: {other}"
                )
            recip = IntervalValue(1.0 / other.max_val, 1.0 / other.min_val)
            return self * recip
        if isinstance(other, (int, float)):
            if other == 0:
                raise ZeroDivisionError("Cannot divide interval by zero")
            if other > 0:
                return IntervalValue(self.min_val / other, self.max_val / other)
            return IntervalValue(self.max_val / other, self.min_val / other)
        return NotImplemented

    def __rtruediv__(self, other: Any) -> IntervalValue:
        if isinstance(other, (int, float)):
            if self.contains(0.0):
                raise ZeroDivisionError(f"Cannot divide by interval containing zero: {self}")
            recip = IntervalValue(1.0 / self.max_val, 1.0 / self.min_val)
            return IntervalValue(float(other), float(other)) * recip
        return NotImplemented

    def __repr__(self) -> str:
        return f"[{self.min_val:.3f}, {self.max_val:.3f}]"


@dataclass(frozen=True)
class CircularInterval(LatticeValue):
    """Circular / modular interval [start, end] (mod modulus).

    Represents a directed arc on the circle S^1 / (modulus * Z), sweeping
    forward (clockwise / increasing) from start to end.
    Common moduli:
      - 24.0: Time-of-day (hours)
      - 360.0: Angles (degrees)
      - 2 * pi: Angles (radians)
    """

    start: float
    end: float
    modulus: float = 360.0

    def __post_init__(self) -> None:
        if self.modulus <= 0.0:
            raise ValueError(f"Modulus must be strictly positive, got {self.modulus}")
        # Normalize start and end to [0, modulus)
        s_norm = self.start % self.modulus
        e_norm = self.end % self.modulus
        if math.isclose(s_norm, self.modulus, abs_tol=1e-9):
            s_norm = 0.0
        if math.isclose(e_norm, self.modulus, abs_tol=1e-9):
            e_norm = 0.0
        object.__setattr__(self, "start", s_norm)
        object.__setattr__(self, "end", e_norm)

    @property
    def length(self) -> float:
        """Return the angular / arc length in [0, modulus]."""
        return (self.end - self.start) % self.modulus

    @property
    def center(self) -> float:
        """Return the midpoint of the arc along the forward direction."""
        return (self.start + self.length / 2.0) % self.modulus

    @property
    def wraps_zero(self) -> bool:
        """Return True if the arc crosses 0 / modulus."""
        return self.start > self.end

    def contains(self, x: float) -> bool:
        """Check if angle/time x lies within this circular interval."""
        x_norm = x % self.modulus
        if math.isclose(self.length, 0.0, abs_tol=1e-9):
            return math.isclose(x_norm, self.start, abs_tol=1e-9)

        if not self.wraps_zero:
            return (self.start - 1e-9) <= x_norm <= (self.end + 1e-9)
        return x_norm >= (self.start - 1e-9) or x_norm <= (self.end + 1e-9)

    def __repr__(self) -> str:
        return f"[{self.start:.1f}, {self.end:.1f}] (mod {self.modulus:.1f})"


@dataclass(frozen=True)
class OrderedInterval(LatticeValue):
    """Interval [min_val, max_val] over an ordered discrete set (Poset/Chain).

    Useful for:
    - Activity / occupancy chains: (Away < Arriving < Home < Occupied < Asleep)
    - Priority / Authority levels: (Default < Automation < Manual < Safety)
    - Security states: (Disarmed < ArmHome < ArmNight < ArmAway)
    - Discrete device modes (e.g. fan speeds: low < medium < high < turbo)
    """

    min_val: Any
    max_val: Any
    domain: tuple[Any, ...] | None = None

    def __post_init__(self) -> None:
        if self.domain is not None:
            if not isinstance(self.domain, tuple):
                object.__setattr__(self, "domain", tuple(self.domain))
            if self.min_val not in self.domain:
                raise ValueError(f"min_val {self.min_val} not in domain {self.domain}")
            if self.max_val not in self.domain:
                raise ValueError(f"max_val {self.max_val} not in domain {self.domain}")
            if self.domain.index(self.min_val) > self.domain.index(self.max_val):
                raise ValueError(
                    f"min_val ({self.min_val}) cannot succeed max_val ({self.max_val}) in domain"
                )
        else:
            try:
                if self.min_val > self.max_val:
                    raise ValueError(
                        f"min_val ({self.min_val}) cannot exceed max_val ({self.max_val})"
                    )
            except TypeError as err:
                raise ValueError(
                    f"min_val ({self.min_val}) and max_val ({self.max_val}) must be comparable or provide domain"
                ) from err

    @classmethod
    def exact(cls, val: Any, domain: tuple[Any, ...] | None = None) -> OrderedInterval:
        """Create a singleton interval [val, val]."""
        return cls(min_val=val, max_val=val, domain=domain)

    @classmethod
    def at_least(cls, val: Any, domain: tuple[Any, ...]) -> OrderedInterval:
        """Create an interval [val, max_domain]."""
        return cls(min_val=val, max_val=domain[-1], domain=domain)

    @classmethod
    def at_most(cls, val: Any, domain: tuple[Any, ...]) -> OrderedInterval:
        """Create an interval [min_domain, val]."""
        return cls(min_val=domain[0], max_val=val, domain=domain)

    @property
    def is_determined(self) -> bool:
        """Return True if interval collapsed to a single unique state."""
        return self.min_val == self.max_val

    @property
    def value(self) -> Any:
        """Return the unique value if determined, else None."""
        return self.min_val if self.is_determined else None

    @property
    def candidates(self) -> tuple[Any, ...]:
        """Return the tuple of candidates spanned by this interval."""
        if self.domain is not None:
            i1 = self.domain.index(self.min_val)
            i2 = self.domain.index(self.max_val)
            return self.domain[i1 : i2 + 1]
        return (self.min_val,) if self.is_determined else (self.min_val, self.max_val)

    def contains(self, item: Any) -> bool:
        """Check if item is within the bounds of this interval."""
        if self.domain is not None:
            if item not in self.domain:
                return False
            idx = self.domain.index(item)
            return self.domain.index(self.min_val) <= idx <= self.domain.index(self.max_val)
        try:
            return self.min_val <= item <= self.max_val
        except TypeError:
            return False

    def __repr__(self) -> str:
        if self.is_determined:
            return f"Ordered({self.min_val})"
        return f"Ordered[{self.min_val} .. {self.max_val}]"


@dataclass(frozen=True)
class DiscreteDomain(LatticeValue):
    """Discrete finite set of possible candidate values.

    Used for finite-domain constraints, discrete states, and combinatorial problems (e.g., Sudoku).
    """

    candidates: frozenset[Any]

    def __post_init__(self) -> None:
        if not isinstance(self.candidates, frozenset):
            object.__setattr__(self, "candidates", frozenset(self.candidates))
        if not self.candidates:
            raise ValueError("DiscreteDomain candidates cannot be initialized empty")

    @classmethod
    def single(cls, val: Any) -> DiscreteDomain:
        """Create a determined domain containing a single value."""
        return cls(candidates=frozenset([val]))

    @classmethod
    def range(cls, start: int, stop: int) -> DiscreteDomain:
        """Create an integer domain spanning [start, stop)."""
        return cls(candidates=frozenset(range(start, stop)))

    @property
    def is_determined(self) -> bool:
        """Return True if the domain has collapsed to a single unique candidate."""
        return len(self.candidates) == 1

    @property
    def value(self) -> Any:
        """Return the unique value if determined, else None."""
        return next(iter(self.candidates)) if self.is_determined else None

    def contains(self, item: Any) -> bool:
        """Check if an item is a valid candidate in this domain."""
        return item in self.candidates

    def __repr__(self) -> str:
        if self.is_determined:
            return f"Discrete({self.value})"
        try:
            sorted_cands = sorted(self.candidates)
        except TypeError:
            sorted_cands = sorted(self.candidates, key=lambda x: str(x))
        return f"Discrete{{{', '.join(map(str, sorted_cands))}}}"


@dataclass(frozen=True)
class FlatValue(LatticeValue):
    """A flat lattice value wrapping any scalar/immutable value (bool, str, int, float, enum).

    Lattice ordering:
      Bottom <= FlatValue(v) <= Contradiction
      FlatValue(v1) ⊔ FlatValue(v2) = FlatValue(v1) if v1 == v2 else Contradiction
    """

    val: Any

    def __repr__(self) -> str:
        return f"Flat({self.val!r})"


@dataclass(frozen=True)
class SetLattice(LatticeValue):
    """Monotonically accumulating set lattice under set union.

    Lattice ordering:
      Bottom <= SetLattice(elements)
      SetLattice(s1) ⊔ SetLattice(s2) = SetLattice(s1 ∪ s2)
    """

    elements: frozenset[Any] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if not isinstance(self.elements, frozenset):
            object.__setattr__(self, "elements", frozenset(self.elements))

    @classmethod
    def from_iterable(cls, items: Iterable[Any]) -> SetLattice:
        """Create a SetLattice from an iterable of elements."""
        return cls(elements=frozenset(items))

    def __contains__(self, item: Any) -> bool:
        return item in self.elements

    def __len__(self) -> int:
        return len(self.elements)

    def __repr__(self) -> str:
        try:
            items = sorted(str(x) for x in self.elements)
        except TypeError:
            items = [str(x) for x in self.elements]
        return f"SetLattice{{{', '.join(items)}}}"


@dataclass(frozen=True)
class MapLattice(LatticeValue):
    """Monotonically merging key-value mapping lattice.

    Union of keys; overlapping keys are merged recursively via merge_lattice.
    If any key merge results in a Contradiction, the entire map becomes a Contradiction.
    """

    mapping: Mapping[Any, LatticeValue] = field(default_factory=dict)

    def __repr__(self) -> str:
        return f"MapLattice{{{', '.join(f'{k}: {v}' for k, v in self.mapping.items())}}}"


@dataclass(frozen=True)
class BeliefMassValue(LatticeValue):
    """Dempster-Shafer belief mass assignment over subsets of a frame of discernment.

    Represents evidential states m: 2^Θ → [0, 1] where ∑ m(A) = 1.0.
    Focal elements are subsets with strictly positive mass. Complete ignorance
    (vacuous belief) is represented by assigning mass 1.0 to the entire frame Θ.
    """

    masses: Mapping[frozenset[str], float] = field(default_factory=dict)
    frame: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        computed_frame = set(self.frame)
        cleaned: dict[frozenset[str], float] = {}
        for s, m in self.masses.items():
            if m > 1e-9:
                fs = frozenset([s] if isinstance(s, str) else s)
                cleaned[fs] = float(m)
                computed_frame.update(fs)
        object.__setattr__(self, "masses", cleaned)
        object.__setattr__(self, "frame", frozenset(computed_frame))

    @classmethod
    def ignorance(cls, frame: Iterable[str]) -> BeliefMassValue:
        """Create a vacuous belief function representing total ignorance on frame Θ."""
        f_set = frozenset(frame)
        return cls(masses={f_set: 1.0}, frame=f_set)

    @classmethod
    def certain(cls, hypothesis: str, frame: Iterable[str] | None = None) -> BeliefMassValue:
        """Create a dogmatic belief function placing 100% certainty on a hypothesis."""
        h_set = frozenset([hypothesis])
        f_set = frozenset(frame) if frame is not None else h_set
        return cls(masses={h_set: 1.0}, frame=f_set | h_set)

    @classmethod
    def simple(
        cls,
        hypothesis: str | Iterable[str],
        confidence: float,
        frame: Iterable[str],
    ) -> BeliefMassValue:
        """Create a simple support function m(H) = confidence, m(Θ) = 1 − confidence."""
        conf = max(0.0, min(1.0, float(confidence)))
        f_set = frozenset(frame)
        h_set = frozenset([hypothesis] if isinstance(hypothesis, str) else hypothesis) & f_set
        if not h_set:
            h_set = f_set
        if conf >= 1.0 - 1e-9:
            return cls(masses={h_set: 1.0}, frame=f_set)
        if conf <= 1e-9 or h_set == f_set:
            return cls(masses={f_set: 1.0}, frame=f_set)
        return cls(masses={h_set: conf, f_set: 1.0 - conf}, frame=f_set)

    def belief(self, hypothesis: str | Iterable[str]) -> float:
        """Return Bel(A): lower probability / total belief committed to hypothesis A."""
        target = frozenset([hypothesis] if isinstance(hypothesis, str) else hypothesis)
        return sum(m for s, m in self.masses.items() if s.issubset(target))

    def plausibility(self, hypothesis: str | Iterable[str]) -> float:
        """Return Pl(A): upper probability / maximum plausibility compatible with A."""
        target = frozenset([hypothesis] if isinstance(hypothesis, str) else hypothesis)
        return sum(m for s, m in self.masses.items() if bool(s & target))

    def doubt(self, hypothesis: str | Iterable[str]) -> float:
        """Return Dou(A) = 1 − Pl(A) = Bel(¬A)."""
        return max(0.0, 1.0 - self.plausibility(hypothesis))

    def evidential_interval(self, hypothesis: str | Iterable[str]) -> tuple[float, float]:
        """Return [Bel(A), Pl(A)] evidential interval bounding true probability."""
        return (self.belief(hypothesis), self.plausibility(hypothesis))

    def pignistic_probability(self, hypothesis: str) -> float:
        """Compute the BetP(x) pignistic probability distribution for decision making."""
        prob = 0.0
        for s, m in self.masses.items():
            if hypothesis in s and len(s) > 0:
                prob += m / len(s)
        return prob

    def conflict_with(self, other: BeliefMassValue) -> float:
        """Compute the orthogonal conflict metric K ∈ [0, 1] with another mass assignment."""
        conflict = 0.0
        for s1, m1 in self.masses.items():
            for s2, m2 in other.masses.items():
                if not (s1 & s2):
                    conflict += m1 * m2
        return min(conflict, 1.0)

    def combine(self, other: BeliefMassValue) -> LatticeValue:
        """Combine two mass assignments via Dempster's rule of combination (orthogonal sum)."""
        if self == other:
            return self

        raw: dict[frozenset[str], float] = {}
        conflict = 0.0

        for s1, m1 in self.masses.items():
            for s2, m2 in other.masses.items():
                inter = s1 & s2
                prod = m1 * m2
                if not inter:
                    conflict += prod
                else:
                    raw[inter] = raw.get(inter, 0.0) + prod

        if conflict >= 1.0 - 1e-9:
            return Contradiction(
                reason=f"Total conflict in Dempster-Shafer evidence combination (K={conflict:.4f})",
                conflicting_values=(self, other),
            )

        scale = 1.0 / (1.0 - conflict)
        new_masses = {s: m * scale for s, m in raw.items()}
        return BeliefMassValue(masses=new_masses, frame=self.frame | other.frame)

    def __repr__(self) -> str:
        items = (
            f"{{{', '.join(sorted(s))}}}: {m:.3f}"
            for s, m in sorted(self.masses.items(), key=lambda x: -x[1])
        )
        return f"BeliefMass({', '.join(items)})"


BOTTOM = Bottom()


def _merge_circular_intervals(a: CircularInterval, b: CircularInterval) -> LatticeValue:
    """Compute the monotonic intersection of two circular intervals on S^1 / (modulus * Z)."""
    if not math.isclose(a.modulus, b.modulus, rel_tol=1e-5):
        return Contradiction(
            reason=f"Incompatible circular moduli: {a.modulus} vs {b.modulus}",
            conflicting_values=(a, b),
        )

    # If both lengths are effectively zero (single points)
    if math.isclose(a.length, 0.0, abs_tol=1e-9) and math.isclose(b.length, 0.0, abs_tol=1e-9):
        if math.isclose(a.start, b.start, abs_tol=1e-9):
            return a
        return Contradiction(
            reason=f"Disjoint circular point values: {a} vs {b}",
            conflicting_values=(a, b),
        )

    # Check complete containment on S^1
    delta_b_from_a = (b.start - a.start) % a.modulus
    b_in_a = (delta_b_from_a + b.length) <= (a.length + 1e-9)

    delta_a_from_b = (a.start - b.start) % a.modulus
    a_in_b = (delta_a_from_b + a.length) <= (b.length + 1e-9)

    if b_in_a and a_in_b:
        return a
    if b_in_a:
        return b
    if a_in_b:
        return a

    # Boundary overlap candidates
    cand1_start = b.start if a.contains(b.start) else None
    cand1_end = a.end if b.contains(a.end) else None

    cand2_start = a.start if b.contains(a.start) else None
    cand2_end = b.end if a.contains(b.end) else None

    match1 = cand1_start is not None and cand1_end is not None
    match2 = cand2_start is not None and cand2_end is not None

    if match1 and match2:
        return Contradiction(
            reason=f"Non-convex disjoint circular intersection between {a} and {b}",
            conflicting_values=(a, b),
        )
    if match1:
        return CircularInterval(start=cand1_start, end=cand1_end, modulus=a.modulus)  # type: ignore[arg-type]
    if match2:
        return CircularInterval(start=cand2_start, end=cand2_end, modulus=a.modulus)  # type: ignore[arg-type]

    return Contradiction(
        reason=f"Empty circular interval intersection between {a} and {b}",
        conflicting_values=(a, b),
    )


def _merge_ordered_intervals(a: OrderedInterval, b: OrderedInterval) -> LatticeValue:
    """Compute the monotonic intersection of two ordered intervals on a discrete poset/chain."""
    if a.domain is not None and b.domain is not None:
        if a.domain != b.domain:
            return Contradiction(
                reason=f"Incompatible ordered domains: {a.domain} vs {b.domain}",
                conflicting_values=(a, b),
            )
        dom = a.domain
        new_min_idx = max(dom.index(a.min_val), dom.index(b.min_val))
        new_max_idx = min(dom.index(a.max_val), dom.index(b.max_val))
        if new_min_idx > new_max_idx:
            return Contradiction(
                reason=f"Empty poset interval intersection between {a} and {b}",
                conflicting_values=(a, b),
            )
        return OrderedInterval(
            min_val=dom[new_min_idx],
            max_val=dom[new_max_idx],
            domain=dom,
        )
    if a.domain is None and b.domain is None:
        try:
            new_min = max(a.min_val, b.min_val)
            new_max = min(a.max_val, b.max_val)
            if new_min > new_max:
                return Contradiction(
                    reason=f"Empty poset interval intersection between {a} and {b}",
                    conflicting_values=(a, b),
                )
            return OrderedInterval(min_val=new_min, max_val=new_max)
        except TypeError:
            return Contradiction(
                reason=f"Incomparable ordered interval values: {a} vs {b}",
                conflicting_values=(a, b),
            )

    return Contradiction(
        reason=f"Mismatched domain configurations for OrderedInterval: {a} vs {b}",
        conflicting_values=(a, b),
    )


def _merge_gaussians(a: GaussianValue, b: GaussianValue) -> GaussianValue:
    """Compute precision-weighted Kalman update of two Gaussian distributions."""
    tau_a = a.precision
    tau_b = b.precision
    tau_merged = tau_a + tau_b
    merged_mean = (tau_a * a.mean + tau_b * b.mean) / tau_merged
    merged_variance = 1.0 / tau_merged
    return GaussianValue(mean=merged_mean, variance=merged_variance)


def _merge_intervals(a: IntervalValue, b: IntervalValue) -> LatticeValue:
    """Compute monotonic set intersection of two bounded numeric intervals."""
    new_min = max(a.min_val, b.min_val)
    new_max = min(a.max_val, b.max_val)
    if new_min > new_max:
        return Contradiction(
            reason=f"Empty interval intersection between {a} and {b}",
            conflicting_values=(a, b),
        )
    return IntervalValue(min_val=new_min, max_val=new_max)


def _merge_discrete_domains(a: DiscreteDomain, b: DiscreteDomain) -> LatticeValue:
    """Compute candidate set intersection of two finite discrete domains."""
    new_candidates = a.candidates & b.candidates
    if not new_candidates:
        return Contradiction(
            reason=f"Empty discrete domain intersection between {a} and {b}",
            conflicting_values=(a, b),
        )
    return DiscreteDomain(candidates=new_candidates)


def _merge_flat_values(a: FlatValue, b: FlatValue) -> LatticeValue:
    """Compute monotonic join of two flat scalar values."""
    if a.val == b.val:
        return a
    return Contradiction(
        reason=f"Conflicting flat values: {a.val!r} vs {b.val!r}",
        conflicting_values=(a, b),
    )


def _merge_set_lattices(a: SetLattice, b: SetLattice) -> LatticeValue:
    """Compute set union of two accumulating set lattices."""
    return SetLattice(elements=a.elements | b.elements)


def _merge_map_lattices(a: MapLattice, b: MapLattice) -> LatticeValue:
    """Compute recursive key-wise monotonic join of two mapping lattices."""
    merged_dict: dict[Any, LatticeValue] = dict(a.mapping)
    for k, v_b in b.mapping.items():
        if k in merged_dict:
            res = merge_lattice(merged_dict[k], v_b)
            if isinstance(res, Contradiction):
                return Contradiction(
                    reason=f"Key conflict on {k!r}: {res.reason}",
                    conflicting_values=(merged_dict[k], v_b),
                )
            merged_dict[k] = res
        else:
            merged_dict[k] = v_b
    return MapLattice(mapping=merged_dict)


def _merge_belief_masses(a: BeliefMassValue, b: BeliefMassValue) -> LatticeValue:
    """Compute monotonic orthogonal join of two Dempster-Shafer belief mass functions."""
    return a.combine(b)


MERGE_DISPATCH: dict[type, Callable[[Any, Any], LatticeValue]] = {
    GaussianValue: _merge_gaussians,
    IntervalValue: _merge_intervals,
    CircularInterval: _merge_circular_intervals,
    OrderedInterval: _merge_ordered_intervals,
    DiscreteDomain: _merge_discrete_domains,
    FlatValue: _merge_flat_values,
    SetLattice: _merge_set_lattices,
    MapLattice: _merge_map_lattices,
    BeliefMassValue: _merge_belief_masses,
}


def register_merge_handler(val_type: type, handler: Callable[[Any, Any], LatticeValue]) -> None:
    """Register a custom monotonic merge handler for a LatticeValue subtype."""
    MERGE_DISPATCH[val_type] = handler


def merge_lattice(a: LatticeValue, b: LatticeValue) -> LatticeValue:
    """Compute the monotonic join / least upper bound (a ⊔ b) on the information lattice."""
    # Contradiction dominates
    if isinstance(a, Contradiction):
        return a
    if isinstance(b, Contradiction):
        return b

    # Bottom is identity
    if isinstance(a, Bottom):
        return b
    if isinstance(b, Bottom):
        return a

    # Homogeneous type dispatch
    handler = MERGE_DISPATCH.get(type(a))
    if handler is not None and type(a) is type(b):
        return handler(a, b)

    return Contradiction(
        reason=f"Incompatible lattice value types: {type(a).__name__} vs {type(b).__name__}",
        conflicting_values=(a, b),
    )


def coerce_to_lattice_value(val: Any) -> LatticeValue:
    """Coerce raw Python primitives into appropriate LatticeValue subtypes.

    Args:
        val: A LatticeValue instance or raw Python primitive (int, float, bool, str, tuple, set, dict, None).

    Returns:
        Corresponding LatticeValue.
    """
    if isinstance(val, LatticeValue):
        return val
    if val is None:
        return BOTTOM
    if isinstance(val, bool):
        return FlatValue(val)
    if isinstance(val, (int, float, str)):
        return FlatValue(val)
    if (
        isinstance(val, (tuple, list))
        and len(val) == 2
        and isinstance(val[0], (int, float))
        and isinstance(val[1], (int, float))
    ):
        return IntervalValue(float(val[0]), float(val[1]))
    if isinstance(val, (set, frozenset)):
        return SetLattice(val)
    if isinstance(val, dict):
        return MapLattice(val)
    return FlatValue(val)
