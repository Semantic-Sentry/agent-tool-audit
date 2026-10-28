import math

import pytest

from ata.stats import wilson_interval, aggregate_outcomes, VectorOutcomeCounts


def test_wilson_interval_known_values():
    # k=0, n=30 — известный случай: point=0, но upper > 0 (Wilson не даёт
    # ложной уверенности "0% значит невозможно", в отличие от нормального приближения)
    r = wilson_interval(0, 30)
    assert r.point_estimate == 0.0
    assert r.lower == 0.0
    assert r.upper > 0.0
    assert r.upper < 0.15  # разумная верхняя граница при 0/30

    # k=n=30 — симметричный случай
    r2 = wilson_interval(30, 30)
    assert r2.point_estimate == 1.0
    assert r2.upper == 1.0
    assert r2.lower < 1.0
    assert r2.lower > 0.85

    # k=15, n=30 — p_hat=0.5, интервал симметричен вокруг 0.5
    r3 = wilson_interval(15, 30)
    assert r3.point_estimate == 0.5
    assert abs((r3.lower + r3.upper) / 2 - 0.5) < 0.01


def test_wilson_interval_n_zero():
    r = wilson_interval(0, 0)
    assert r.n == 0
    assert r.point_estimate == 0.0


def test_wilson_interval_rejects_invalid_k():
    with pytest.raises(ValueError):
        wilson_interval(31, 30)
    with pytest.raises(ValueError):
        wilson_interval(-1, 30)


def test_wilson_interval_narrows_with_larger_n():
    # тот же p_hat=0.5, но N=10 против N=100 — интервал должен сужаться
    small_n = wilson_interval(5, 10)
    large_n = wilson_interval(50, 100)
    assert (large_n.upper - large_n.lower) < (small_n.upper - small_n.lower)


def test_vector_outcome_counts_error_excluded_from_denominator():
    counts = VectorOutcomeCounts(
        vector_id="v1", n=30, none=10, attempt=5, unblocked=8, confirmed=4, error=3,
    )
    assert counts.completed_n() == 27  # 30 - 3 error

    confirmed_iv = counts.confirmed_interval()
    assert confirmed_iv.k == 4
    assert confirmed_iv.n == 27  # НЕ 30


def test_vector_outcome_counts_monotonic_metrics():
    counts = VectorOutcomeCounts(
        vector_id="v1", n=20, none=5, attempt=5, unblocked=6, confirmed=4, error=0,
    )
    attempt_iv = counts.attempt_or_worse_interval()
    unblocked_iv = counts.unblocked_or_worse_interval()
    confirmed_iv = counts.confirmed_interval()

    # ATTEMPT-or-worse >= UNBLOCKED-or-worse >= CONFIRMED по определению
    assert attempt_iv.k == 5 + 6 + 4  # 15
    assert unblocked_iv.k == 6 + 4     # 10
    assert confirmed_iv.k == 4
    assert attempt_iv.k >= unblocked_iv.k >= confirmed_iv.k


def test_aggregate_outcomes_basic():
    data = {
        "v1": ["NONE", "ATTEMPT", "CONFIRMED", "CONFIRMED"],
        "v2": ["NONE", "NONE", "ERROR"],
    }
    result = aggregate_outcomes(data)
    by_id = {c.vector_id: c for c in result}

    assert by_id["v1"].n == 4
    assert by_id["v1"].none == 1
    assert by_id["v1"].attempt == 1
    assert by_id["v1"].confirmed == 2

    assert by_id["v2"].n == 3
    assert by_id["v2"].none == 2
    assert by_id["v2"].error == 1
    assert by_id["v2"].completed_n() == 2


def test_aggregate_outcomes_rejects_unknown_value():
    with pytest.raises(ValueError):
        aggregate_outcomes({"v1": ["NONE", "BOGUS"]})
