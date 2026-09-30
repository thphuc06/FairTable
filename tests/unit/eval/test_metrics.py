"""P1-20: the metrics against values worked out by hand."""

import pytest

from eval.metrics import TaskCounts, c_out, pass_at_1, pass_hat_k, percentile, rate

# Three tasks with four trials each: always passes, passes half the time, never passes.
COUNTS = [TaskCounts("a", 4, 4), TaskCounts("b", 4, 2), TaskCounts("c", 4, 0)]


def test_pass_at_1_is_the_mean_pass_rate():
    assert pass_at_1(COUNTS) == pytest.approx((1 + 0.5 + 0) / 3)


def test_pass_hat_1_equals_pass_at_1():
    assert pass_hat_k(COUNTS, 1) == pytest.approx(pass_at_1(COUNTS))


def test_pass_hat_2_by_hand():
    # a: C(4,2)/C(4,2) = 1;  b: C(2,2)/C(4,2) = 1/6;  c: 0
    assert pass_hat_k(COUNTS, 2) == pytest.approx((1 + 1 / 6 + 0) / 3)


def test_pass_hat_3_and_4_only_count_the_task_that_never_fails():
    # b has 2 passes, so it can never fill 3 or 4 draws
    assert pass_hat_k(COUNTS, 3) == pytest.approx(1 / 3)
    assert pass_hat_k(COUNTS, 4) == pytest.approx(1 / 3)


def test_pass_hat_k_never_rises_with_k():
    values = [pass_hat_k(COUNTS, k) for k in (1, 2, 3, 4)]
    assert values == sorted(values, reverse=True)


def test_c_out_is_one_for_consistent_tasks_and_zero_for_a_coin_flip():
    # a: (2*1-1)^2 = 1;  b: (2*0.5-1)^2 = 0;  c: (2*0-1)^2 = 1
    assert c_out(COUNTS) == pytest.approx(2 / 3)
    assert c_out([TaskCounts("x", 10, 5)]) == 0
    assert c_out([TaskCounts("x", 10, 10)]) == 1
    assert c_out([TaskCounts("x", 10, 8)]) == pytest.approx(0.36)  # (2*0.8-1)^2


def test_bad_inputs_are_refused_not_averaged_away():
    with pytest.raises(ValueError, match="no tasks"):
        pass_at_1([])
    with pytest.raises(ValueError, match="bad counts"):
        c_out([TaskCounts("x", 3, 4)])
    with pytest.raises(ValueError, match="bad counts"):
        c_out([TaskCounts("x", 0, 0)])
    with pytest.raises(ValueError, match="at least 5 trials"):
        pass_hat_k(COUNTS, 5)
    with pytest.raises(ValueError, match="k must be"):
        pass_hat_k(COUNTS, 0)


def test_percentiles_use_the_nearest_rank():
    assert percentile([5, 1, 3, 2, 4], 50) == 3
    assert percentile([5, 1, 3, 2, 4], 95) == 5
    assert percentile([5, 1, 3, 2, 4], 20) == 1
    assert percentile([10], 95) == 10
    assert percentile([], 50) is None


def test_rate_of_nothing_is_not_zero():
    assert rate(0, 0) is None
    assert rate(1, 4) == 0.25
