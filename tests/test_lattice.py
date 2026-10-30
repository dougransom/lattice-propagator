"""Unit tests for the Propagator Engine lattice representations and merge operations."""

import math

import pytest

from lattice_propagator.lattice import (
    BOTTOM,
    CircularInterval,
    Contradiction,
    DiscreteDomain,
    GaussianValue,
    IntervalValue,
    OrderedInterval,
    merge_lattice,
)


def test_bottom_identity() -> None:
    """Test that Bottom acts as identity under lattice merge."""
    g = GaussianValue(mean=21.5, variance=0.2)
    i = IntervalValue(min_val=19.0, max_val=23.0)

    assert merge_lattice(BOTTOM, g) == g
    assert merge_lattice(g, BOTTOM) == g
    assert merge_lattice(BOTTOM, i) == i
    assert merge_lattice(i, BOTTOM) == i
    assert merge_lattice(BOTTOM, BOTTOM) == BOTTOM


def test_gaussian_equal_variance_merge() -> None:
    """Test precision-weighted merging of two Gaussians with identical variance."""
    g1 = GaussianValue(mean=20.0, variance=0.5)
    g2 = GaussianValue(mean=22.0, variance=0.5)

    merged = merge_lattice(g1, g2)
    assert isinstance(merged, GaussianValue)
    assert math.isclose(merged.mean, 21.0)
    # With equal precision tau, merged variance is 1 / (2*tau) = 0.25
    assert math.isclose(merged.variance, 0.25)


def test_gaussian_unequal_variance_merge() -> None:
    """Test that a more precise sensor dominates a noisy sensor in Gaussian merge."""
    precise = GaussianValue(mean=21.0, variance=0.05)  # High accuracy
    noisy = GaussianValue(mean=25.0, variance=1.0)  # Noisy radiator

    merged = merge_lattice(precise, noisy)
    assert isinstance(merged, GaussianValue)

    # Weighted mean should be heavily pulled towards 21.0
    # tau_precise = 20, tau_noisy = 1, tau_total = 21
    # expected_mean = (20*21 + 1*25) / 21 = (420 + 25) / 21 = 445 / 21 = 21.19047
    expected_mean = (20.0 * 21.0 + 1.0 * 25.0) / 21.0
    expected_var = 1.0 / 21.0

    assert math.isclose(merged.mean, expected_mean, rel_tol=1e-5)
    assert math.isclose(merged.variance, expected_var, rel_tol=1e-5)
    assert merged.variance < precise.variance  # Monotonic narrowing


def test_gaussian_confidence_interval() -> None:
    """Test confidence interval computation."""
    g = GaussianValue(mean=20.0, variance=1.0)  # std dev = 1.0
    low, high = g.confidence_interval(0.95)
    assert math.isclose(low, 20.0 - 1.95996, rel_tol=1e-3)
    assert math.isclose(high, 20.0 + 1.95996, rel_tol=1e-3)


def test_interval_overlapping_merge() -> None:
    """Test interval intersection merge for overlapping bounds."""
    i1 = IntervalValue(min_val=18.0, max_val=22.0)
    i2 = IntervalValue(min_val=20.0, max_val=24.0)

    merged = merge_lattice(i1, i2)
    assert isinstance(merged, IntervalValue)
    assert math.isclose(merged.min_val, 20.0)
    assert math.isclose(merged.max_val, 22.0)
    assert math.isclose(merged.center, 21.0)
    assert math.isclose(merged.width, 2.0)


def test_interval_disjoint_contradiction() -> None:
    """Test that disjoint intervals yield a Contradiction."""
    i1 = IntervalValue(min_val=18.0, max_val=19.5)
    i2 = IntervalValue(min_val=20.5, max_val=22.0)

    merged = merge_lattice(i1, i2)
    assert isinstance(merged, Contradiction)
    assert "Empty interval intersection" in merged.reason


def test_incompatible_types_contradiction() -> None:
    """Test merging incompatible value types yields Contradiction."""
    g = GaussianValue(mean=21.0, variance=0.1)
    i = IntervalValue(min_val=19.0, max_val=22.0)

    merged = merge_lattice(g, i)
    assert isinstance(merged, Contradiction)
    assert "Incompatible lattice value types" in merged.reason


def test_invalid_parameters() -> None:
    """Test parameter validation on values."""
    with pytest.raises(ValueError, match="Variance must be strictly positive"):
        GaussianValue(mean=20.0, variance=0.0)

    with pytest.raises(ValueError, match="min_val .* cannot exceed max_val"):
        IntervalValue(min_val=25.0, max_val=20.0)


def test_interval_integer_bounds() -> None:
    """Test that intervals support integer bounds and preserve integer types."""
    i1 = IntervalValue(min_val=1, max_val=6)
    i2 = IntervalValue(min_val=4, max_val=9)

    merged = merge_lattice(i1, i2)
    assert isinstance(merged, IntervalValue)
    assert merged.min_val == 4
    assert merged.max_val == 6
    assert isinstance(merged.min_val, int)
    assert isinstance(merged.max_val, int)
    assert merged.center == 5.0
    assert merged.width == 2
    assert merged.contains(5)
    assert not merged.contains(3)
    assert not merged.contains(7)

    # Disjoint integer intervals
    disjoint = merge_lattice(
        IntervalValue(min_val=1, max_val=3), IntervalValue(min_val=5, max_val=8)
    )
    assert isinstance(disjoint, Contradiction)


def test_interval_with_infinities() -> None:
    """Test intervals with positive and negative infinity (math.inf)."""
    # Unbounded interval [-inf, +inf]
    unbounded = IntervalValue(min_val=-math.inf, max_val=math.inf)
    assert unbounded.contains(0)
    assert unbounded.contains(-(10**18))
    assert unbounded.contains(10**18)
    assert math.isinf(unbounded.width)
    assert math.isnan(unbounded.center)

    # Narrowing semi-infinite intervals with integer bounds
    lower_bound = IntervalValue(min_val=1, max_val=math.inf)
    upper_bound = IntervalValue(min_val=-math.inf, max_val=9)

    merged = merge_lattice(lower_bound, upper_bound)
    assert isinstance(merged, IntervalValue)
    assert merged.min_val == 1
    assert merged.max_val == 9
    assert isinstance(merged.min_val, int)
    assert isinstance(merged.max_val, int)
    assert merged.center == 5.0
    assert merged.width == 8

    # Inverted infinities raise ValueError
    with pytest.raises(ValueError, match="min_val .* cannot exceed max_val"):
        IntervalValue(min_val=math.inf, max_val=-math.inf)


def test_discrete_domain_operations() -> None:
    """Test DiscreteDomain creation, accessors, and representations."""
    d_multi = DiscreteDomain(candidates={1, 2, 3})
    assert not d_multi.is_determined
    assert d_multi.value is None
    assert d_multi.contains(2)
    assert not d_multi.contains(4)
    assert repr(d_multi) == "Discrete{1, 2, 3}"

    d_single = DiscreteDomain.single(7)
    assert d_single.is_determined
    assert d_single.value == 7
    assert repr(d_single) == "Discrete(7)"

    d_range = DiscreteDomain.range(1, 4)
    assert d_range.candidates == frozenset({1, 2, 3})

    with pytest.raises(ValueError, match="cannot be initialized empty"):
        DiscreteDomain(candidates=set())


def test_discrete_domain_merge() -> None:
    """Test monotonic set intersection merge for DiscreteDomain."""
    d1 = DiscreteDomain(candidates={1, 2, 3, 4})
    d2 = DiscreteDomain(candidates={3, 4, 5, 6})

    merged = merge_lattice(d1, d2)
    assert isinstance(merged, DiscreteDomain)
    assert merged.candidates == frozenset({3, 4})

    # Narrowing to determined single
    d3 = DiscreteDomain.single(3)
    narrowed = merge_lattice(merged, d3)
    assert isinstance(narrowed, DiscreteDomain)
    assert narrowed.is_determined
    assert narrowed.value == 3

    # Disjoint intersection produces Contradiction
    disjoint = merge_lattice(DiscreteDomain.single(1), DiscreteDomain.single(2))
    assert isinstance(disjoint, Contradiction)
    assert "Empty discrete domain intersection" in disjoint.reason

    # Bottom identity
    assert merge_lattice(BOTTOM, d1) == d1
    assert merge_lattice(d1, BOTTOM) == d1

    # Contradiction dominance
    assert isinstance(merge_lattice(disjoint, d1), Contradiction)

    # Incompatible types
    incompatible = merge_lattice(d1, IntervalValue(min_val=1.0, max_val=4.0))
    assert isinstance(incompatible, Contradiction)
    assert "Incompatible lattice value types" in incompatible.reason


def test_interval_arithmetic_and_clamp() -> None:
    """Test interval addition, subtraction, multiplication, and capability clamping."""
    i1 = IntervalValue(min_val=10.0, max_val=20.0)
    i2 = IntervalValue(min_val=2.0, max_val=5.0)

    # Addition
    sum_int = i1 + i2
    assert sum_int == IntervalValue(min_val=12.0, max_val=25.0)
    assert i1 + 5.0 == IntervalValue(min_val=15.0, max_val=25.0)
    assert 5.0 + i1 == IntervalValue(min_val=15.0, max_val=25.0)

    # Subtraction: [a, b] - [c, d] = [a - d, b - c]
    diff_int = i1 - i2
    assert diff_int == IntervalValue(min_val=5.0, max_val=18.0)
    assert i1 - 3.0 == IntervalValue(min_val=7.0, max_val=17.0)
    assert 25.0 - i1 == IntervalValue(min_val=5.0, max_val=15.0)

    # Multiplication: products of min/max combinations
    prod_int = i1 * i2
    assert prod_int == IntervalValue(min_val=20.0, max_val=100.0)
    assert i1 * 2.0 == IntervalValue(min_val=20.0, max_val=40.0)
    assert 2.0 * i1 == IntervalValue(min_val=20.0, max_val=40.0)
    # Negative multiplier flips bounds
    neg_prod = i1 * -2.0
    assert neg_prod == IntervalValue(min_val=-40.0, max_val=-20.0)

    # Clamping
    allowed_bounds = IntervalValue(min_val=12.0, max_val=18.0)
    clamped = i1.clamp(allowed_bounds)
    assert clamped == IntervalValue(min_val=12.0, max_val=18.0)

    # Clamping contradiction
    disjoint_bounds = IntervalValue(min_val=25.0, max_val=30.0)
    failed_clamp = i1.clamp(disjoint_bounds)
    assert isinstance(failed_clamp, Contradiction)

    # Type error on unsupported operand
    with pytest.raises(TypeError):
        _ = i1 + "unsupported"  # type: ignore[operator]


def test_circular_interval_basics_and_normalization() -> None:
    """Test CircularInterval initialization, modulo normalization, and containment."""
    # Standard angle arc [10°, 50°] (mod 360)
    c1 = CircularInterval(start=10.0, end=50.0, modulus=360.0)
    assert c1.start == 10.0
    assert c1.end == 50.0
    assert c1.length == 40.0
    assert c1.center == 30.0
    assert not c1.wraps_zero
    assert c1.contains(10.0)
    assert c1.contains(30.0)
    assert c1.contains(50.0)
    assert not c1.contains(5.0)
    assert not c1.contains(55.0)

    # Modulo normalization of out-of-range inputs: 370° -> 10°, -30° -> 330°
    c_norm = CircularInterval(start=370.0, end=-30.0, modulus=360.0)
    assert math.isclose(c_norm.start, 10.0)
    assert math.isclose(c_norm.end, 330.0)

    # Zero-crossing angle arc (e.g. [350°, 20°])
    c_wrap = CircularInterval(start=350.0, end=20.0, modulus=360.0)
    assert c_wrap.wraps_zero
    assert c_wrap.length == 30.0
    assert c_wrap.center == 5.0
    assert c_wrap.contains(350.0)
    assert c_wrap.contains(0.0)
    assert c_wrap.contains(360.0)  # 360 % 360 == 0
    assert c_wrap.contains(20.0)
    assert not c_wrap.contains(340.0)
    assert not c_wrap.contains(25.0)

    # Time-of-day quiet hours arc across midnight (mod 24h)
    night = CircularInterval(start=22.5, end=6.5, modulus=24.0)
    assert night.wraps_zero
    assert night.length == 8.0
    assert math.isclose(night.center, 2.5)  # 02:30 AM
    assert night.contains(23.0)
    assert night.contains(0.0)
    assert night.contains(3.0)
    assert not night.contains(12.0)

    # Point arc (length 0)
    point = CircularInterval(start=15.0, end=15.0, modulus=360.0)
    assert point.length == 0.0
    assert point.center == 15.0
    assert point.contains(15.0)
    assert not point.contains(15.1)

    # Invalid modulus
    with pytest.raises(ValueError, match="Modulus must be strictly positive"):
        CircularInterval(start=0.0, end=10.0, modulus=0.0)

    assert repr(c1) == "[10.0, 50.0] (mod 360.0)"


def test_circular_interval_merge_cases() -> None:
    """Test monotonic join operations for circular intervals on S^1."""
    # 1. Non-wrapping overlap: [10, 50] ⊔ [30, 70] -> [30, 50]
    a = CircularInterval(start=10.0, end=50.0, modulus=360.0)
    b = CircularInterval(start=30.0, end=70.0, modulus=360.0)
    m1 = merge_lattice(a, b)
    assert isinstance(m1, CircularInterval)
    assert m1.start == 30.0
    assert m1.end == 50.0

    # Symmetric merge
    assert merge_lattice(b, a) == m1

    # 2. Wrapping overlap: [350, 20] ⊔ [10, 40] -> [10, 20]
    c_wrap = CircularInterval(start=350.0, end=20.0, modulus=360.0)
    c_sub = CircularInterval(start=10.0, end=40.0, modulus=360.0)
    m2 = merge_lattice(c_wrap, c_sub)
    assert isinstance(m2, CircularInterval)
    assert m2.start == 10.0
    assert m2.end == 20.0

    # 3. Night hours complete containment: [22.0, 7.0] ⊔ [23.5, 6.0] (mod 24) -> [23.5, 6.0]
    night_wide = CircularInterval(start=22.0, end=7.0, modulus=24.0)
    night_tight = CircularInterval(start=23.5, end=6.0, modulus=24.0)
    m3 = merge_lattice(night_wide, night_tight)
    assert m3 == night_tight
    assert merge_lattice(night_tight, night_wide) == night_tight

    # 4. Touching endpoints: [0, 90] ⊔ [90, 180] -> [90, 90]
    arc1 = CircularInterval(start=0.0, end=90.0, modulus=360.0)
    arc2 = CircularInterval(start=90.0, end=180.0, modulus=360.0)
    m4 = merge_lattice(arc1, arc2)
    assert isinstance(m4, CircularInterval)
    assert m4.start == 90.0
    assert m4.end == 90.0
    assert m4.length == 0.0

    # 5. Point values merge
    p1 = CircularInterval(start=45.0, end=45.0, modulus=360.0)
    p2 = CircularInterval(start=45.0, end=45.0, modulus=360.0)
    p3 = CircularInterval(start=60.0, end=60.0, modulus=360.0)
    assert merge_lattice(p1, p2) == p1
    assert isinstance(merge_lattice(p1, p3), Contradiction)

    # 6. Disjoint arcs -> Contradiction
    disjoint1 = CircularInterval(start=0.0, end=90.0, modulus=360.0)
    disjoint2 = CircularInterval(start=180.0, end=270.0, modulus=360.0)
    m_disjoint = merge_lattice(disjoint1, disjoint2)
    assert isinstance(m_disjoint, Contradiction)
    assert "Empty circular interval intersection" in m_disjoint.reason

    # 7. Incompatible moduli -> Contradiction
    incompat = merge_lattice(
        CircularInterval(start=0.0, end=10.0, modulus=360.0),
        CircularInterval(start=0.0, end=10.0, modulus=24.0),
    )
    assert isinstance(incompat, Contradiction)
    assert "Incompatible circular moduli" in incompat.reason

    # 8. Bottom identity and Contradiction dominance
    assert merge_lattice(BOTTOM, a) == a
    assert merge_lattice(a, BOTTOM) == a
    assert isinstance(merge_lattice(m_disjoint, a), Contradiction)


def test_ordered_interval_with_domain() -> None:
    """Test OrderedInterval operations and merging over a discrete chain/poset."""
    activity_domain = ("away", "arriving", "home", "occupied", "asleep")

    # Constructors
    at_least_home = OrderedInterval.at_least("home", domain=activity_domain)
    at_most_occupied = OrderedInterval.at_most("occupied", domain=activity_domain)
    exact_asleep = OrderedInterval.exact("asleep", domain=activity_domain)

    assert at_least_home.min_val == "home"
    assert at_least_home.max_val == "asleep"
    assert not at_least_home.is_determined
    assert at_least_home.candidates == ("home", "occupied", "asleep")
    assert at_least_home.contains("home")
    assert at_least_home.contains("occupied")
    assert not at_least_home.contains("away")
    assert not at_least_home.contains("nonexistent")

    assert exact_asleep.is_determined
    assert exact_asleep.value == "asleep"
    assert exact_asleep.candidates == ("asleep",)
    assert repr(exact_asleep) == "Ordered(asleep)"
    assert repr(at_least_home) == "Ordered[home .. asleep]"

    # Monotonic merge: at_least(home) ⊔ at_most(occupied) -> [home .. occupied]
    m_range = merge_lattice(at_least_home, at_most_occupied)
    assert isinstance(m_range, OrderedInterval)
    assert m_range.min_val == "home"
    assert m_range.max_val == "occupied"
    assert m_range.candidates == ("home", "occupied")

    # Narrowing to exact state
    m_exact = merge_lattice(m_range, OrderedInterval.exact("occupied", domain=activity_domain))
    assert isinstance(m_exact, OrderedInterval)
    assert m_exact.is_determined
    assert m_exact.value == "occupied"

    # Disjoint intersection produces Contradiction
    m_conflict = merge_lattice(
        OrderedInterval.at_most("away", domain=activity_domain),
        OrderedInterval.at_least("home", domain=activity_domain),
    )
    assert isinstance(m_conflict, Contradiction)
    assert "Empty poset interval intersection" in m_conflict.reason

    # Incompatible domains
    other_domain = ("low", "medium", "high")
    m_incompat = merge_lattice(
        at_least_home,
        OrderedInterval.exact("medium", domain=other_domain),
    )
    assert isinstance(m_incompat, Contradiction)
    assert "Incompatible ordered domains" in m_incompat.reason

    # Validation errors
    with pytest.raises(ValueError, match="min_val .* not in domain"):
        OrderedInterval(min_val="unknown", max_val="home", domain=activity_domain)

    with pytest.raises(ValueError, match="cannot succeed max_val"):
        OrderedInterval(min_val="asleep", max_val="away", domain=activity_domain)


def test_ordered_interval_without_domain() -> None:
    """Test OrderedInterval operations using comparable types (integers) without explicit domain."""
    o1 = OrderedInterval(min_val=10, max_val=50)
    o2 = OrderedInterval(min_val=30, max_val=70)

    m = merge_lattice(o1, o2)
    assert isinstance(m, OrderedInterval)
    assert m.min_val == 30
    assert m.max_val == 50
    assert m.contains(40)
    assert not m.contains(20)

    # Disjoint intersection
    disjoint = merge_lattice(OrderedInterval(1, 10), OrderedInterval(20, 30))
    assert isinstance(disjoint, Contradiction)

    # Incomparable values without domain
    with pytest.raises(ValueError, match="must be comparable"):
        OrderedInterval(min_val=1, max_val="string")  # type: ignore[operator]

    # Mismatched domain configs
    mismatch = merge_lattice(o1, OrderedInterval.exact("home", domain=("away", "home")))
    assert isinstance(mismatch, Contradiction)
    assert "Mismatched domain configurations" in mismatch.reason


def test_lattice_representations_and_corner_cases() -> None:
    """Test string representations, non-convex circular intersections, and method delegation."""
    # Method delegation .merge()
    g1 = GaussianValue(mean=20.0, variance=0.5)
    g2 = GaussianValue(mean=22.0, variance=0.5)
    assert g1.merge(g2) == merge_lattice(g1, g2)

    # String representations
    assert repr(BOTTOM) == "⊥(Bottom)"
    c_err = Contradiction(reason="test conflict")
    assert repr(c_err) == "⊤(Contradiction: test conflict)"
    assert repr(g1) == "Gaussian(μ=20.000, σ²=0.5000)"

    # CircularInterval boundary normalization at modulus
    c_zero_bound = CircularInterval(start=360.0, end=720.0, modulus=360.0)
    assert c_zero_bound.start == 0.0
    assert c_zero_bound.end == 0.0

    # Non-convex circular intersection (two arcs overlapping on both sides)
    # Arc 1: [0, 270] (length 270)
    # Arc 2: [180, 90] (wraps through zero, length 270)
    # Overlap 1: [180, 270], Overlap 2: [0, 90] -> Disjoint non-convex
    c_wide1 = CircularInterval(start=0.0, end=270.0, modulus=360.0)
    c_wide2 = CircularInterval(start=180.0, end=90.0, modulus=360.0)
    m_nonconvex = merge_lattice(c_wide1, c_wide2)
    assert isinstance(m_nonconvex, Contradiction)
    assert "Non-convex disjoint circular intersection" in m_nonconvex.reason

    # CircularInterval match2 branch
    # c_b starts inside c_a: [30, 70] and [10, 50]
    c_a = CircularInterval(start=30.0, end=70.0, modulus=360.0)
    c_b = CircularInterval(start=10.0, end=50.0, modulus=360.0)
    assert merge_lattice(c_a, c_b) == CircularInterval(start=30.0, end=50.0, modulus=360.0)

    # OrderedInterval domain provided as list (converted to tuple)
    o_list = OrderedInterval(min_val="a", max_val="b", domain=["a", "b", "c"])  # type: ignore[arg-type]
    assert isinstance(o_list.domain, tuple)

    # OrderedInterval candidates without domain
    o_nodom = OrderedInterval(min_val=5, max_val=10)
    assert o_nodom.candidates == (5, 10)
    o_nodom_single = OrderedInterval(min_val=5, max_val=5)
    assert o_nodom_single.candidates == (5,)
    assert not o_nodom.contains("non-comparable")
