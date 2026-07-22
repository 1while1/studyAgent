"""模板锚点解析与渲染测试（stdlib unittest，免第三方依赖）。"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.config_service import get_config, reset_config
from backend.services.template_service import TemplateService

# 8 张 SOP 卡中锚定的全部模板（30 个）
EXPECTED_TEMPLATES = {
    # SOP_下一内容
    "mastery_check", "next_preview", "consolidate_hint", "reject_advance",
    # SOP_开始今日学习
    "fail_fast_exists", "step1_history", "step2_repo_check", "step3_plan",
    "step4_guide", "paper_block", "unit_open",
    # SOP_恢复学习
    "resume_summary",
    # SOP_同步
    "sync_mastered", "sync_stuck", "sync_question",
    "interview_qa_entry", "sync_code_done", "sync_summary",
    # SOP_开始写代码
    "code_start", "code_review", "code_done",
    # SOP_开始今日复盘
    "review_step1", "review_step2", "review_qa_format", "review_step4",
    # SOP_结束今日学习
    "end_step1_sync", "end_step3_qa", "study_review_doc", "end_step6",
    # SOP_跳转天数
    "jump_confirm",
}


class TestTemplateService(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        reset_config()
        cls.service = TemplateService(get_config())

    def test_all_expected_templates_parsed(self):
        parsed = set(self.service.names())
        missing = EXPECTED_TEMPLATES - parsed
        self.assertFalse(missing, f"缺失模板: {missing}")

    def test_mastery_check_char_level(self):
        """mastery_check 必须与 SOP 卡原文逐字符一致（规则 10 的代码断言）。"""
        expected = (
            "---【掌握情况检查】---\n"
            "当前学习单元：<填入>\n"
            "- 已讲解知识点：<填入>\n"
            "- 用户提问/卡点：<填入>\n"
            "- 掌握度评估：[已掌握 / 基本掌握 / 需巩固]\n"
            "- 编码进度：[已完成 / 进行中 / 未开始 / 不适用]\n"
            "\n"
            "请确认：\n"
            "1. 继续下一内容（说 [下一内容]）\n"
            "2. 再巩固一下当前内容\n"
            "3. 我有新问题要问\n"
            "4. 开始写代码（说 [开始写代码]）\n"
            "---"
        )
        self.assertEqual(self.service.get("mastery_check"), expected)

    def test_fence_stripped(self):
        for name in self.service.names():
            body = self.service.get(name)
            self.assertFalse(body.startswith("```"), f"{name} 围栏未剥离")
            self.assertFalse(body.endswith("```"), f"{name} 围栏未剥离")

    def test_render_replaces_only_given_placeholders(self):
        out = self.service.render("sync_mastered", XXX="熔断器三态")
        self.assertEqual(out, "已记录：「熔断器三态」标记为已掌握。")
        # 未提供的占位符原样保留
        out2 = self.service.render("next_preview", 单元名="RAG 基础")
        self.assertIn("「RAG 基础」", out2)
        self.assertIn("<下一单元名>", out2)

    def test_unknown_template_raises(self):
        with self.assertRaises(Exception):
            self.service.get("no_such_template")


if __name__ == "__main__":
    unittest.main()
