"""LogAnalyzer 测试"""
import unittest
import json
import tempfile
from pathlib import Path
from backend.services.log_analyzer import LogAnalyzer, LogStats


class TestLogAnalyzer(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._log_path = Path(self._tmp) / "agent.log"
    
    def test_analyze_empty(self):
        analyzer = LogAnalyzer(self._log_path)
        stats = analyzer.analyze()
        self.assertEqual(stats.total_entries, 0)
    
    def test_analyze_json_entries(self):
        entries = [
            json.dumps({"event": "chat", "tokens": {"input": 100, "output": 50}, "level": "info"}),
            json.dumps({"event": "tool", "tokens": {"input": 200}, "level": "info"}),
            json.dumps({"event": "error", "level": "error"}),
        ]
        self._log_path.write_text("\n".join(entries), encoding="utf-8")
        analyzer = LogAnalyzer(self._log_path)
        stats = analyzer.analyze()
        self.assertEqual(stats.total_entries, 3)
        self.assertEqual(stats.error_count, 1)
        self.assertEqual(stats.token_usage["input"], 300)
    
    def test_query(self):
        entries = [json.dumps({"event": "chat", "message": "hello"}), json.dumps({"event": "tool"})]
        self._log_path.write_text("\n".join(entries), encoding="utf-8")
        analyzer = LogAnalyzer(self._log_path)
        results = analyzer.query("hello")
        self.assertEqual(len(results), 1)
    
    def test_last_n(self):
        entries = [json.dumps({"event": f"e{i}"}) for i in range(10)]
        self._log_path.write_text("\n".join(entries), encoding="utf-8")
        analyzer = LogAnalyzer(self._log_path)
        stats = analyzer.analyze(last_n=3)
        self.assertEqual(stats.total_entries, 3)
    
    def test_token_summary(self):
        entries = [json.dumps({"tokens": {"input": 100}})]
        self._log_path.write_text("\n".join(entries), encoding="utf-8")
        analyzer = LogAnalyzer(self._log_path)
        summary = analyzer.get_token_summary()
        self.assertEqual(summary["total_tokens"], 100)
    
    def test_error_summary(self):
        entries = [json.dumps({"level": "error", "msg": "fail"})]
        self._log_path.write_text("\n".join(entries), encoding="utf-8")
        analyzer = LogAnalyzer(self._log_path)
        errors = analyzer.get_error_summary()
        self.assertEqual(len(errors), 1)


class TestLogStats(unittest.TestCase):
    def test_default(self):
        stats = LogStats()
        self.assertEqual(stats.total_entries, 0)
        self.assertEqual(stats.error_count, 0)


if __name__ == "__main__":
    unittest.main()
