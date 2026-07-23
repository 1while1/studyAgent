"""planner ACTION 契约与 plan-act-observe（M5c）测试。

断言动作边界契约（§8.2）：ACTION 截获/执行/注入/上限/记账/契约错误处理，
不断言自由文本。含 [导学] 跑通端到端（planner 经工具回答）。
"""

import json
import shutil
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.engine.tool_registry import ToolContext, build_default_registry
from backend.engine.tool_use import ToolUseLoop
from backend.services.code_browser import CodeBrowser
from backend.services.config_service import ConfigService
from backend.services.state_store import StateStore
from tests.scriptable_llm import ScriptableLLM

TODAY = date.today().isoformat()

_SETTINGS = (
    'active_workspace = "t"\n'
    'status_enum = ["not_started", "in_progress", "completed"]\n'
    '{context}'
    '[evidence_delta]\nquiz_right = 0.10\nteach_back_pass = 0.25\n'
    '[[stages]]\nname = "teaching"\nnext = ""\n'
    'sop_step = "步骤一"\ninstruction = "讲"\n'
    '[[code_roots]]\nname = "projA"\npath = "{proj}"\n'
    '[[workspaces]]\nslug = "t"\n'
    'docx_dir = "{docx}"\n'
    'project_dir = "{tmp}"\n'
    'session_path = "{session}"\n'
)

_CTX = '[context]\nplanner_max_actions_per_reply = {max_actions}\n'


class TestPlannerActions(unittest.TestCase):
    max_actions = 4

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="planner_"))
        self.docx = self.tmp / "docx"
        self.docx.mkdir()
        proj = self.tmp / "projA"
        proj.mkdir()
        (proj / "a.txt").write_text("l1\nl2\nl3", encoding="utf-8")
        settings = self.tmp / "settings.toml"
        settings.write_text(_SETTINGS.format(
            context=_CTX.format(max_actions=self.max_actions),
            proj=proj.as_posix(), docx=self.docx.as_posix(),
            tmp=self.tmp.as_posix(),
            session=(self.tmp / "session.json").as_posix()), encoding="utf-8")
        self.config = ConfigService(settings)
        (self.docx / "StudyState.json").write_text(json.dumps({
            "current_day": 2, "overall_completion_percentage": 0,
            "last_active_date": TODAY,
            "days": {"2": {"date": TODAY, "units": [
                {"id": "A", "title": "单元A", "status": "in_progress"}]}}},
            ensure_ascii=False), encoding="utf-8")
        self.state_store = StateStore(self.config)
        self.registry = build_default_registry()
        self.ctx = ToolContext(config=self.config,
                               browser=CodeBrowser(self.config),
                               state_store=self.state_store)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, llm: ScriptableLLM, allow_actions: bool = True):
        loop = ToolUseLoop(self.config, llm, self.ctx.browser,
                           registry=self.registry, tool_context=self.ctx,
                           allow_actions=allow_actions)
        messages = [{"role": "system", "content": "sys"},
                    {"role": "user", "content": "问"}]
        events = list(loop.run(messages))
        return llm, loop, events

    @staticmethod
    def _deltas(events):
        return "".join(e["content"] for e in events if e["type"] == "delta")

    @staticmethod
    def _actions(events):
        return [e for e in events
                if e["type"] == "tool_read" and e.get("kind") == "action"]

    def _write_notes(self):
        (self.docx / "notes.json").write_text(json.dumps({
            "schema_version": 1,
            "notes": [{"id": "n1", "kind": "question", "text": "什么是背压",
                       "status": "open", "concept_id": "Day2-A",
                       "source_ref": "t:1"}]}, ensure_ascii=False),
            encoding="utf-8")

    def test_action_intercepted_executed_injected(self):
        """ACTION 截获不显示 + 工具真实执行 + 结果注入续写。"""
        self._write_notes()
        llm = ScriptableLLM([
            {"match": "^问$", "respond":
                '先查笔记\n[ACTION:{"action":"search_notes",'
                '"args":{"kind":"question"},"reason":"查疑问"}]'},
            {"match": "系统注入", "respond": "查完了：背压是流控机制"},
        ])
        _, loop, events = self._run(llm)
        text = self._deltas(events)
        self.assertNotIn("ACTION", text)          # 标记不下发
        self.assertIn("查完了", text)
        acts = self._actions(events)
        self.assertEqual(len(acts), 1)
        self.assertEqual(acts[0]["tool"], "search_notes")
        self.assertTrue(acts[0]["ok"])
        self.assertEqual(acts[0]["reason"], "查疑问")
        # 第二次调用的注入含真实执行结果（notes 数据）
        injected = llm.calls[1][-1]["content"]
        self.assertIn("执行结果", injected)
        self.assertIn("什么是背压", injected)

    def test_action_contract_violation_teaches_correction(self):
        """契约不符（action 非字符串）→ 错误注入教模型纠正。"""
        llm = ScriptableLLM([
            {"match": "^问$", "respond":
                '[ACTION:{"action":123,"args":{},"reason":"x"}]'},
            {"match": "契约不符", "respond": "已修正，继续"},
        ])
        _, _, events = self._run(llm)
        acts = self._actions(events)
        self.assertEqual(len(acts), 1)
        self.assertFalse(acts[0]["ok"])
        injected = llm.calls[1][-1]["content"]
        self.assertIn("契约不符", injected)

    def test_action_unknown_tool(self):
        llm = ScriptableLLM([
            {"match": "^问$", "respond":
                '[ACTION:{"action":"no_such_tool","args":{},'
                '"reason":"试探"}]'},
            {"match": "未知工具", "respond": "工具不存在，换个思路"},
        ])
        _, _, events = self._run(llm)
        acts = self._actions(events)
        self.assertEqual(len(acts), 1)
        self.assertFalse(acts[0]["ok"])
        self.assertIn("未知工具", llm.calls[1][-1]["content"])

    def test_malformed_passthrough_as_text(self):
        """JSON 无法解析（与非法 READ 标记同策略）→ 按普通文本下发。"""
        llm = ScriptableLLM([
            {"match": "^问$", "respond": "哦[ACTION:{坏 json}]呀"},
        ])
        _, _, events = self._run(llm)
        self.assertIn("[ACTION:{坏 json}]", self._deltas(events))
        self.assertEqual(self._actions(events), [])

    def test_malformed_trailing_text_preserved(self):
        """R4 修复：无法解析的 ACTION 不吞后续文本（final _rest 续排）。"""
        llm = ScriptableLLM([
            {"match": "^问$", "respond": "前[ACTION:[1,2]]之后文字"},
        ])
        _, _, events = self._run(llm)
        text = self._deltas(events)
        self.assertIn("[ACTION:[1,2]]", text)
        self.assertIn("之后文字", text)  # 修复前会被吞掉

    def test_tutor_mode_action_not_executed(self):
        """R2 修复：allow_actions=False（导学模式）→ ACTION 静默丢弃不执行。"""
        self._write_notes()
        llm = ScriptableLLM([
            {"match": "^问$", "respond":
                '[ACTION:{"action":"search_notes","args":{},"reason":"越权"}]'},
        ])
        _, _, events = self._run(llm, allow_actions=False)
        self.assertEqual(self._actions(events), [])
        self.assertNotIn("search_notes", self._deltas(events))
        # 未执行：无 plan 记账
        from backend.services.config_service import runtime_dir
        log_path = runtime_dir(self.config) / "agent.log"
        logged = log_path.read_text(encoding="utf-8") \
            if log_path.exists() else ""
        self.assertNotIn('"kind": "plan"', logged)

    def test_action_read_code_uses_tool_injection(self):
        """R1 修复：ACTION 调 read_code → 注入工具构造的真实代码内容。"""
        llm = ScriptableLLM([
            {"match": "^问$", "respond":
                '[ACTION:{"action":"read_code",'
                '"args":{"path":"projA/a.txt"},"reason":"读文件"}]'},
            {"match": "系统注入", "respond": "看到了真实内容"},
        ])
        _, _, events = self._run(llm)
        acts = self._actions(events)
        self.assertEqual(len(acts), 1)
        self.assertTrue(acts[0]["ok"])
        injected = llm.calls[1][-1]["content"]
        self.assertIn("l1\nl2\nl3", injected)  # 修复前注入为空

    def test_action_large_payload_within_cap(self):
        """R3 修复：>2000 字符的合法 ACTION 也能截获（ACTION 独立 16K cap）。"""
        long_text = "长" * 2500
        llm = ScriptableLLM([
            {"match": "^问$", "respond":
                '[ACTION:{"action":"write_note","args":{"kind":"insight",'
                f'"text":"{long_text}"'.replace("\n", "") + '},"reason":"长文"}]'},
            {"match": "系统注入", "respond": "已写"},
        ])
        _, _, events = self._run(llm)
        acts = self._actions(events)
        self.assertEqual(len(acts), 1)
        self.assertTrue(acts[0]["ok"])
        notes = json.loads(
            (self.docx / "notes.json").read_text(encoding="utf-8"))
        self.assertEqual(len(notes["notes"][0]["text"]), 2500)

    def test_routes_ctx_has_llm(self):
        """R1/R2 修复回归：生产 ToolContext 构造点必须含 llm。"""
        from backend.api import routes
        from tests.test_flows import make_deps
        deps = make_deps(self.config, self.tmp / "session.json")
        ctx = routes._build_tool_context(deps)
        self.assertIs(ctx.llm, deps.llm)
        self.assertIsNotNone(ctx.llm)

    def test_action_json_with_nested_brackets(self):
        """args 内含 ]（数组）也能完整提取（逐 ] 尝试解析）。"""
        llm = ScriptableLLM([
            {"match": "^问$", "respond":
                '[ACTION:{"action":"search_notes","args":'
                '{"kind":"question","limit":2},"reason":"嵌套"}]'},
            {"match": "系统注入", "respond": "完成"},
        ])
        _, _, events = self._run(llm)
        self.assertEqual(len(self._actions(events)), 1)

    def test_plan_logged(self):
        """plan 决策记 agent.log（§10）：action/args/reason/ok。"""
        self._write_notes()
        llm = ScriptableLLM([
            {"match": "^问$", "respond":
                '[ACTION:{"action":"search_notes","args":{"kind":"question"},'
                '"reason":"查疑问"}]'},
            {"match": "系统注入", "respond": "完"},
        ])
        self._run(llm)
        from backend.services.config_service import runtime_dir
        log = (runtime_dir(self.config) / "agent.log").read_text(
            encoding="utf-8")
        plans = [json.loads(l) for l in log.splitlines()
                 if '"kind": "plan"' in l]
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0]["action"], "search_notes")
        self.assertIn("question", plans[0]["args"])
        self.assertEqual(plans[0]["reason"], "查疑问")
        self.assertTrue(plans[0]["ok"])

    def test_guided_learning_e2e(self):
        """[导学] 跑通：planner 经 read_model 工具回答掌握度问题。"""
        (self.docx / "learner_model.json").write_text(json.dumps({
            "schema_version": 1,
            "concepts": {"Day2-A": {
                "title": "单元A", "mastery": 0.1,
                "evidence": [{"type": "quiz_right", "source_ref": "q",
                              "delta": 0.10, "ts": TODAY}],
                "last_review_day": 2, "review_due": [3]}}},
            ensure_ascii=False), encoding="utf-8")
        llm = ScriptableLLM([
            {"match": "掌握得怎么样", "respond":
                '[ACTION:{"action":"read_model","args":{},'
                '"reason":"查学习者模型"}]'},
            {"match": "系统注入", "respond": "你 Day2-A 掌握度 0.10，属薄弱"},
        ])
        loop = ToolUseLoop(self.config, llm, self.ctx.browser,
                           registry=self.registry, tool_context=self.ctx,
                           allow_actions=True)
        events = list(loop.run([
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "我 Day2-A 掌握得怎么样？"}]))
        acts = [e for e in events
                if e["type"] == "tool_read" and e.get("kind") == "action"]
        self.assertEqual(len(acts), 1)
        self.assertEqual(acts[0]["tool"], "read_model")
        # 动作边界断言：注入给模型的含真实模型数据
        self.assertIn("Day2-A", llm.calls[1][-1]["content"])
        self.assertIn("0.10", self._deltas(events))


class TestPlannerActionCap(TestPlannerActions):
    max_actions = 1

    def test_action_cap_enforced(self):
        """planner_max_actions_per_reply=1：第二个 ACTION 静默丢弃。"""
        llm = ScriptableLLM([
            {"match": "^问$", "respond":
                '[ACTION:{"action":"search_notes","args":{},"reason":"一"}]\n'
                '[ACTION:{"action":"read_model","args":{},"reason":"二"}]\n'
                "收尾"},
        ])
        _, _, events = self._run(llm)
        acts = self._actions(events)
        self.assertEqual(len(acts), 1)              # 只执行第一个
        text = self._deltas(events)
        self.assertNotIn("read_model", text)        # 第二个被丢弃不下发


class TestLlmTierTools(unittest.TestCase):
    """quiz_generate / retell_assess（LLM 档工具）。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="llmtool_"))
        self.docx = self.tmp / "docx"
        self.docx.mkdir()
        settings = self.tmp / "settings.toml"
        settings.write_text(
            'active_workspace = "t"\n'
            'status_enum = ["not_started", "in_progress"]\n'
            '[evidence_delta]\nquiz_right = 0.10\n'
            '[[workspaces]]\nslug = "t"\n'
            f'docx_dir = "{self.docx.as_posix()}"\n'
            f'project_dir = "{self.tmp.as_posix()}"\n'
            f'session_path = "{(self.tmp / "s.json").as_posix()}"\n',
            encoding="utf-8")
        self.config = ConfigService(settings)
        (self.docx / "learner_model.json").write_text(json.dumps({
            "schema_version": 1,
            "concepts": {"Day2-A": {
                "title": "单元A", "mastery": 0.1,
                "evidence": [{"type": "quiz_right", "source_ref": "q",
                              "delta": 0.10, "ts": TODAY}],
                "last_review_day": 2, "review_due": [3]}}},
            ensure_ascii=False), encoding="utf-8")
        self.registry = build_default_registry()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _ctx(self, llm=None):
        return ToolContext(config=self.config,
                           state_store=StateStore(self.config), llm=llm)

    def test_quiz_generate(self):
        llm = ScriptableLLM([
            {"match": "出题任务", "respond": "Q：背压缓冲区满时会发生什么？"},
        ])
        result = self.registry.invoke(
            "quiz_generate", {"concept_id": "Day2-A"}, self._ctx(llm))
        self.assertTrue(result.ok, result.error)
        self.assertIn("背压", result.data["question"])
        self.assertEqual(len(llm.calls), 1)
        # prompt 含知识点标题与掌握度（基于证据的个性化）
        prompt = llm.calls[0][-1]["content"]
        self.assertIn("单元A", prompt)
        self.assertIn("0.10", prompt)

    def test_retell_assess(self):
        llm = ScriptableLLM([
            {"match": "口述原文", "respond": "四档点评……【评分：4.0】"},
        ])
        result = self.registry.invoke(
            "retell_assess", {"concept_id": "Day2-A",
                              "transcript": "我讲讲背压机制……"},
            self._ctx(llm))
        self.assertTrue(result.ok, result.error)
        self.assertIn("评分", result.data["assessment"])
        self.assertIn("单元A", llm.calls[0][-1]["content"])

    def test_llm_tool_missing_llm(self):
        result = self.registry.invoke(
            "quiz_generate", {"concept_id": "Day2-A"}, self._ctx(None))
        self.assertFalse(result.ok)
        self.assertIn("LLM", result.error)

    def test_quiz_generate_unknown_concept(self):
        llm = ScriptableLLM([])
        result = self.registry.invoke(
            "quiz_generate", {"concept_id": "Day9-Z"}, self._ctx(llm))
        self.assertFalse(result.ok)
        self.assertIn("不存在", result.error)
        self.assertEqual(len(llm.calls), 0)  # 未浪费 LLM 调用


if __name__ == "__main__":
    unittest.main()
