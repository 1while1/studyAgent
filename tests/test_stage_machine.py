"""阶段机测试：配置驱动的流转、终态、quiz 阶段识别。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.engine.stage_machine import StageMachine, StageError
from backend.services.config_service import get_config, reset_config


class TestStageMachine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reset_config()
        cls.sm = StageMachine(get_config())

    def test_full_chain(self):
        expected = ["teaching", "coding", "source_review", "paper",
                    "quiz_r1", "quiz_r2", "scored", "completed"]
        cur = self.sm.first
        chain = [cur]
        while self.sm.next_of(cur):
            cur = self.sm.advance(cur)
            chain.append(cur)
        self.assertEqual(chain, expected)

    def test_terminal(self):
        self.assertEqual(self.sm.terminal, "completed")
        with self.assertRaises(StageError):
            self.sm.advance("completed")

    def test_quiz_detection(self):
        self.assertEqual(self.sm.quiz_stages(), ["quiz_r1", "quiz_r2"])
        self.assertFalse(self.sm.is_quiz("teaching"))

    def test_unknown_stage(self):
        with self.assertRaises(StageError):
            self.sm.info("no_such_stage")

    def test_instructions_loaded(self):
        for name in self.sm.names():
            self.assertTrue(self.sm.instruction(name), f"{name} 缺 instruction")
            self.assertTrue(self.sm.sop_step(name), f"{name} 缺 sop_step")


if __name__ == "__main__":
    unittest.main()
