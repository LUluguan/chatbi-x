import pytest

from app.eval.stats import mcnemar_exact_bilateral, wilson_interval


class TestMcNemar:
    def test_known_pair_2_12_matches_reference(self):
        # v4 实测：仅 agent 对 12、仅基线对 2 → 双侧精确 p ≈ 0.0129
        p = mcnemar_exact_bilateral(2, 12)
        assert p == pytest.approx(0.0129, abs=1e-4)

    def test_symmetric_counts_p_one(self):
        assert mcnemar_exact_bilateral(6, 6) == 1.0

    def test_no_discordant_pairs_p_one(self):
        assert mcnemar_exact_bilateral(0, 0) == 1.0

    def test_strong_asymmetry_is_significant(self):
        assert mcnemar_exact_bilateral(0, 10) < 0.005

    def test_symmetric_in_argument_order(self):
        assert mcnemar_exact_bilateral(2, 12) == mcnemar_exact_bilateral(12, 2)


class TestWilson:
    def test_known_intervals_match_reference(self):
        # v4 边际准确率的 95% Wilson 区间（评审对照值）
        lo, hi = wilson_interval(63, 100)
        assert lo == pytest.approx(0.532, abs=1e-3)
        assert hi == pytest.approx(0.718, abs=1e-3)
        lo, hi = wilson_interval(53, 100)
        assert lo == pytest.approx(0.433, abs=1e-3)
        assert hi == pytest.approx(0.625, abs=1e-3)

    def test_interval_contains_point_estimate(self):
        lo, hi = wilson_interval(7, 10)
        assert lo <= 0.7 <= hi

    def test_zero_and_full(self):
        lo, hi = wilson_interval(0, 5)
        assert lo == 0.0 and hi < 0.6
        lo, hi = wilson_interval(5, 5)
        assert lo > 0.4 and hi == 1.0
