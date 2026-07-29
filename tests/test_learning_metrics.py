"""M1.3 学习效果度量测试：三指标 + BKT + FSRS + 落盘格式"""
import unittest
from unittest.mock import MagicMock

from backend.engine.learning_metrics import (
    compute_indicator_a,
    compute_indicator_b,
    compute_indicator_c,
    compute_mastery_score,
    compute_learning_metrics,
    LearningMetrics,
    bkt_update,
    bkt_mastery,
    BKT_DEFAULT_PARAMS,
    fsrs_schedule,
    fsrs_interval_from_evidence,
    FSRS_DEFAULT_PARAMS,
)


# ---------------------------------------------------------------------------
# 指标 A：掌握进度
# ---------------------------------------------------------------------------

class TestIndicatorA(unittest.TestCase):
    def test_empty_evidence(self):
        self.assertEqual(compute_indicator_a([], 10), 0.0)

    def test_zero_days(self):
        self.assertEqual(compute_indicator_a([{"type": "x"}], 0), 0.0)

    def test_negative_days(self):
        self.assertEqual(compute_indicator_a([{"type": "x"}], -1), 0.0)

    def test_exact_expected(self):
        # 5 天 × 2 = 10 条预期，给 10 条 → 1.0
        evs = [{"type": "x"} for _ in range(10)]
        self.assertEqual(compute_indicator_a(evs, 5), 1.0)

    def test_half_expected(self):
        evs = [{"type": "x"} for _ in range(5)]
        self.assertAlmostEqual(compute_indicator_a(evs, 5), 0.5)

    def test_capped_at_one(self):
        evs = [{"type": "x"} for _ in range(100)]
        self.assertEqual(compute_indicator_a(evs, 5), 1.0)


# ---------------------------------------------------------------------------
# 指标 B：知识保持度
# ---------------------------------------------------------------------------

class TestIndicatorB(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(compute_indicator_b([]), 0.0)

    def test_all_zero_scores(self):
        self.assertEqual(
            compute_indicator_b([{"score": 0}, {"score": 0}]), 0.0)

    def test_perfect_scores(self):
        result = compute_indicator_b([{"score": 5.0}, {"score": 5.0}])
        self.assertAlmostEqual(result, 1.0)

    def test_mixed_scores(self):
        # score=3 → 3/5=0.6, score=4 → 4/5=0.8 → avg=0.7
        result = compute_indicator_b([{"score": 3}, {"score": 4}])
        self.assertAlmostEqual(result, 0.7)

    def test_single_score(self):
        result = compute_indicator_b([{"score": 2.5}])
        self.assertAlmostEqual(result, 0.5)


# ---------------------------------------------------------------------------
# 指标 C：迁移应用
# ---------------------------------------------------------------------------

class TestIndicatorC(unittest.TestCase):
    def test_no_code_concept(self):
        self.assertEqual(compute_indicator_c(False, False), 1.0)

    def test_code_pass(self):
        self.assertEqual(compute_indicator_c(True, True), 1.0)

    def test_code_fail(self):
        self.assertAlmostEqual(compute_indicator_c(False, True), 0.3)


# ---------------------------------------------------------------------------
# 组合公式
# ---------------------------------------------------------------------------

class TestMasteryScore(unittest.TestCase):
    def test_default_weights(self):
        # 0.3*1 + 0.3*1 + 0.4*1 = 1.0
        self.assertAlmostEqual(
            compute_mastery_score(1.0, 1.0, 1.0), 1.0)

    def test_zero_all(self):
        self.assertAlmostEqual(compute_mastery_score(0, 0, 0), 0.0)

    def test_custom_weights(self):
        w = (0.5, 0.3, 0.2)
        result = compute_mastery_score(0.8, 0.6, 1.0, w)
        expected = 0.5 * 0.8 + 0.3 * 0.6 + 0.2 * 1.0
        self.assertAlmostEqual(result, expected)

    def test_partial(self):
        # 0.3*0.5 + 0.3*0.7 + 0.4*0.3 = 0.15 + 0.21 + 0.12 = 0.48
        result = compute_mastery_score(0.5, 0.7, 0.3)
        self.assertAlmostEqual(result, 0.48)


# ---------------------------------------------------------------------------
# 一站式 compute_learning_metrics
# ---------------------------------------------------------------------------

class TestComputeLearningMetrics(unittest.TestCase):
    def test_full_run(self):
        evs = [{"type": "quiz_right"} for _ in range(4)]
        quizzes = [{"score": 4.0}]
        m = compute_learning_metrics(
            concept_id="Day1-U1",
            evidence_list=evs,
            total_days=2,
            quiz_results=quizzes,
            code_verify_pass=True,
            has_code_concept=True,
        )
        self.assertIsInstance(m, LearningMetrics)
        self.assertEqual(m.concept_id, "Day1-U1")
        self.assertGreater(m.mastery_score, 0)
        self.assertEqual(m.indicator_c, 1.0)


# ---------------------------------------------------------------------------
# BKT
# ---------------------------------------------------------------------------

class TestBKT(unittest.TestCase):
    def test_initial_prior(self):
        self.assertAlmostEqual(BKT_DEFAULT_PARAMS["p_init"], 0.1)

    def test_correct_increases(self):
        prior = 0.1
        posterior = bkt_update(prior, True)
        self.assertGreater(posterior, prior)

    def test_wrong_decreases(self):
        prior = 0.5
        posterior = bkt_update(prior, False)
        self.assertLess(posterior, prior)

    def test_bounded_zero_one(self):
        # 多次正确后趋近 1
        p = 0.1
        for _ in range(20):
            p = bkt_update(p, True)
        self.assertLessEqual(p, 1.0)
        self.assertGreater(p, 0.9)

    def test_bkt_mastery_empty(self):
        self.assertAlmostEqual(bkt_mastery([]), BKT_DEFAULT_PARAMS["p_init"])

    def test_bkt_mastery_with_evidence(self):
        evs = [
            {"type": "quiz_right", "delta": 0.2},
            {"type": "quiz_wrong", "delta": -0.1},
            {"type": "quiz_right", "delta": 0.2},
        ]
        result = bkt_mastery(evs)
        self.assertGreater(result, 0)
        self.assertLessEqual(result, 1.0)

    def test_bkt_mastery_quiz_score(self):
        evs = [{"type": "quiz_score", "delta": 0.8}]
        result = bkt_mastery(evs)
        self.assertGreater(result, BKT_DEFAULT_PARAMS["p_init"])

    def test_custom_params(self):
        params = {"p_init": 0.5, "p_transit": 0.2,
                  "p_slip": 0.05, "p_guess": 0.1}
        result = bkt_update(0.5, True, params)
        self.assertGreater(result, 0.5)

    def test_zero_p_correct_guard(self):
        # 极端参数：p_slip=1, p_guess=0 → p_correct = prior*0 + (1-prior)*0 = 0
        params = {"p_init": 0.1, "p_transit": 0.1,
                  "p_slip": 1.0, "p_guess": 0.0}
        prior = 0.5
        result = bkt_update(prior, True, params)
        # p_correct = 0.5*0 + 0.5*0 = 0 → 返回 prior
        self.assertEqual(result, prior)


# ---------------------------------------------------------------------------
# FSRS
# ---------------------------------------------------------------------------

class TestFSRS(unittest.TestCase):
    def test_empty_reviews(self):
        result = fsrs_schedule([])
        self.assertEqual(result["interval_days"], 1)
        self.assertEqual(result["stability"], 1.0)
        self.assertEqual(result["difficulty"], 5.0)

    def test_forgot(self):
        reviews = [{"date": "2026-01-01", "rating": 1}]
        result = fsrs_schedule(reviews)
        self.assertEqual(result["interval_days"], 1)

    def test_hard(self):
        reviews = [{"date": "2026-01-01", "rating": 2},
                   {"date": "2026-01-02", "rating": 2}]
        result = fsrs_schedule(reviews)
        self.assertEqual(result["interval_days"], 2)

    def test_good(self):
        reviews = [{"date": "2026-01-01", "rating": 3},
                   {"date": "2026-01-02", "rating": 3}]
        result = fsrs_schedule(reviews)
        self.assertEqual(result["interval_days"], 4)  # 2*2

    def test_easy(self):
        reviews = [{"date": "2026-01-01", "rating": 4},
                   {"date": "2026-01-02", "rating": 4}]
        result = fsrs_schedule(reviews)
        self.assertEqual(result["interval_days"], 6)  # 2*3

    def test_interval_capped_at_365(self):
        reviews = [{"date": "2026-01-01", "rating": 4} for _ in range(200)]
        result = fsrs_schedule(reviews)
        self.assertEqual(result["interval_days"], 365)

    def test_difficulty_decreases_with_rating(self):
        r1 = fsrs_schedule([{"rating": 1}])
        r4 = fsrs_schedule([{"rating": 4}])
        self.assertGreater(r1["difficulty"], r4["difficulty"])

    def test_fsrs_from_evidence(self):
        evs = [
            {"type": "quiz_right", "ts": "2026-01-01"},
            {"type": "quiz_wrong", "ts": "2026-01-02"},
        ]
        result = fsrs_interval_from_evidence(evs)
        self.assertIn("interval_days", result)
        self.assertGreaterEqual(result["interval_days"], 1)

    def test_fsrs_from_evidence_quiz_score(self):
        evs = [
            {"type": "quiz_score", "delta": 0.9, "ts": "2026-01-01"},
            {"type": "quiz_score", "delta": 0.3, "ts": "2026-01-02"},
        ]
        result = fsrs_interval_from_evidence(evs)
        self.assertGreaterEqual(result["interval_days"], 1)


# ---------------------------------------------------------------------------
# 落盘格式（observer.log_learning_metrics）
# ---------------------------------------------------------------------------

class TestObserverMetricsLog(unittest.TestCase):
    def test_log_format(self):
        """验证 log_learning_metrics 写入正确 kind 与字段"""
        from backend.services.observer import Observer
        from backend.services.config_service import ConfigService
        from pathlib import Path
        import tempfile, json

        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "settings.toml"
            cfg_path.write_text('[server]\nport=8000\n', encoding="utf-8")
            config = ConfigService(cfg_path)
            obs = Observer(config)
            # 拦截 _write
            captured = []
            obs._write = lambda r: captured.append(r)
            obs.log_learning_metrics(
                concept_id="Day1-U1",
                indicator_a=0.8,
                indicator_b=0.6,
                indicator_c=1.0,
                mastery_score=0.74,
                bkt_prob=0.65,
                fsrs_interval=3,
            )
            self.assertEqual(len(captured), 1)
            rec = captured[0]
            self.assertEqual(rec["kind"], "metrics")
            self.assertEqual(rec["concept_id"], "Day1-U1")
            self.assertAlmostEqual(rec["mastery_score"], 0.74)
            self.assertAlmostEqual(rec["bkt_prob"], 0.65)
            self.assertEqual(rec["fsrs_interval"], 3)


if __name__ == "__main__":
    unittest.main()
