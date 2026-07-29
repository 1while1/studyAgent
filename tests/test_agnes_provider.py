"""Agnes 渠道接入回归测试（feat/agnes-provider）。

覆盖：
- factory 注册与构建（ObservedLLM 包装 + section 参数正确 / 缺 key 报错清晰）
- _PROVIDER_META 元信息与 _section_view 解析（配置页渲染的真实数据源）
- save_llm_config 提交 agnes 节区 → TOML 往返一致 + 未提交节区原文保留
- 仓内 settings.toml 完整性（provider 已注册 / agnes 节区 / 点号键防拆表 / 定价）
- observer._record_cost 对 agnes 0 定价的命中路径
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.config_service import ConfigService

_REPO_SETTINGS = Path(__file__).resolve().parents[1] / "config" / "settings.toml"
_KEY = "LLM_API_KEY_AGNES"

_SETTINGS_BODY = (
    'active_workspace = "t"\n'
    'status_enum = ["not_started", "in_progress", "completed"]\n'
    '[[stages]]\nname = "teaching"\nnext = ""\n'
    'sop_step = "步骤一"\ninstruction = "讲"\n'
    '[[workspaces]]\nslug = "t"\ntotal_days = 5\n'
    'docx_dir = "{docx}"\n'
    'project_dir = "{tmp}"\n'
    'session_path = "{sess}"\n'
    '[llm]\nprovider = "{provider}"\nfallback_provider = ""\n'
    'warmup_on_start = false\n'
    '[llm.agnes]\nmodel = "agnes-2.0-flash"\nmax_tokens = 4096\n'
    'temperature = 0.7\nbase_url = "https://apihub.agnes-ai.cn/v1"\n'
    'api_key_env = "LLM_API_KEY_AGNES"\n'
    '[llm.deepseek_official]\nmodel = "m2"\nmax_tokens = 4096\n'
    'temperature = 0.7\nbase_url = "https://b"\napi_key_env = "K2"\n'
    '[commands."跳转天数"]\nhandler = "jump_day"\nsop_card = ""\n'
)

_STUDY_MD = """# 学习计划

当前天数：Day 1
整体完成度：0%

## Day 1 | 2026-07-22（星期三）
**目标**：基础
**导学单元**：
1. [ ] 单元A：基础一（预计 40min）
   - 文档：无
**编码目标**：无
**推荐论文**：无
**面试话术目标**：无
"""


class AgnesBase(unittest.TestCase):
    """tmp 配置夹具 + LLM_API_KEY_AGNES 环境对称保存/恢复。"""

    provider = "agnes"

    def setUp(self):
        self._saved_key = os.environ.get(_KEY)
        self.tmp = Path(tempfile.mkdtemp(prefix="agnes_"))
        self.docx = self.tmp / "docx"
        (self.docx / "StudyMemory").mkdir(parents=True)
        (self.docx / "Study.md").write_text(_STUDY_MD, encoding="utf-8")
        (self.tmp / "settings.toml").write_text(
            _SETTINGS_BODY.format(
                docx=self.docx.as_posix(), tmp=self.tmp.as_posix(),
                sess=(self.tmp / "s.json").as_posix(),
                provider=self.provider),
            encoding="utf-8")
        self.config = ConfigService(self.tmp / "settings.toml")

    def tearDown(self):
        if self._saved_key is None:
            os.environ.pop(_KEY, None)
        else:
            os.environ[_KEY] = self._saved_key


class TestAgnesFactory(AgnesBase):
    def test_registered_in_builders(self):
        from backend.llm.factory import _BUILDERS
        self.assertIn("agnes", _BUILDERS)

    def test_create_llm_builds_openai_compat_with_agnes_section(self):
        os.environ[_KEY] = "sk-test-agnes"
        from backend.llm.factory import create_llm
        from backend.llm.observed import ObservedLLM
        client = create_llm(self.config)
        self.assertIsInstance(client, ObservedLLM)
        inner = client._inner
        self.assertEqual(inner._model, "agnes-2.0-flash")
        self.assertEqual(str(inner._client.base_url).rstrip("/"),
                         "https://apihub.agnes-ai.cn/v1")

    def test_missing_key_raises_clear_error(self):
        os.environ.pop(_KEY, None)
        from backend.llm.factory import create_llm
        with self.assertRaises(RuntimeError) as ctx:
            create_llm(self.config)
        self.assertIn("llm.agnes", str(ctx.exception))


class TestAgnesConfigPage(AgnesBase):
    """配置页真实数据路径：_section_view 解析 + save_llm_config 写盘往返。"""

    def _routes(self):
        from backend.api import routes
        from backend.engine.orchestrator import ChatOrchestrator
        from tests.test_flows import make_deps
        deps = make_deps(self.config, self.tmp / "s.json")
        orch = ChatOrchestrator(self.config, deps.stages, deps.quiz,
                                deps.state_store, deps.memory, deps.templates)
        routes.init(deps, orch)
        return routes

    def test_section_view_resolves_agnes(self):
        os.environ[_KEY] = "sk-test-agnes-123456"
        routes = self._routes()
        view = routes._section_view("agnes")
        self.assertEqual(view["model"], "agnes-2.0-flash")
        self.assertEqual(view["base_url"], "https://apihub.agnes-ai.cn/v1")
        self.assertTrue(view["has_key"])
        self.assertNotIn("sk-test-agnes-123456", view["api_key_masked"])  # 脱敏

    def test_save_llm_config_agnes_roundtrip_preserves_unsubmitted(self):
        import tomllib
        os.environ[_KEY] = "sk-test-agnes"  # 保存后热重建 create_llm 需要 key
        routes = self._routes()
        before = (self.tmp / "settings.toml").read_text(encoding="utf-8")
        ds_before = before[before.index("[llm.deepseek_official]"):]
        ds_before = ds_before[:ds_before.index("[commands.")]
        body = routes.LlmConfigIn(
            provider="agnes", fallback_provider="", warmup_on_start=True,
            sections={"agnes": {
                "model": "agnes-2.0-flash",
                "base_url": "https://apihub.agnes-ai.cn/v1",
                "max_tokens": 8192, "temperature": 0.5}})
        r = routes.save_llm_config(body)
        self.assertTrue(r["ok"], r.get("error"))
        with open(self.tmp / "settings.toml", "rb") as f:
            data = tomllib.load(f)
        self.assertEqual(data["llm"]["provider"], "agnes")
        self.assertEqual(data["llm"]["agnes"]["max_tokens"], 8192)
        self.assertEqual(data["llm"]["agnes"]["temperature"], 0.5)
        after = (self.tmp / "settings.toml").read_text(encoding="utf-8")
        ds_after = after[after.index("[llm.deepseek_official]"):]
        ds_after = ds_after[:ds_after.index("[commands.")]
        self.assertEqual(ds_before, ds_after)  # 未提交节区逐字节保留

    def test_save_without_key_warns_instead_of_500(self):
        # 缺 key 保存：配置落盘 + ok + warning，运行态保留旧客户端（不 500）
        import tomllib
        os.environ.pop(_KEY, None)
        routes = self._routes()
        old_llm = routes._deps.llm
        body = routes.LlmConfigIn(
            provider="agnes", fallback_provider="", warmup_on_start=True,
            sections={"agnes": {
                "model": "agnes-2.0-flash",
                "base_url": "https://apihub.agnes-ai.cn/v1",
                "max_tokens": 4096, "temperature": 0.7}})
        r = routes.save_llm_config(body)
        self.assertTrue(r["ok"], r.get("error"))
        self.assertIn("构建失败", r.get("warning", ""))
        self.assertIs(routes._deps.llm, old_llm)  # 运行态未被破坏
        with open(self.tmp / "settings.toml", "rb") as f:
            self.assertEqual(tomllib.load(f)["llm"]["provider"], "agnes")


class TestAgnesRepoSettings(unittest.TestCase):
    """仓内 settings.toml 完整性（防 TOML 点号键/误切渠道的回归）。"""

    @classmethod
    def setUpClass(cls):
        import tomllib
        with open(_REPO_SETTINGS, "rb") as f:
            cls.data = tomllib.load(f)

    def test_provider_is_registered(self):
        from backend.llm.factory import _BUILDERS
        self.assertIn(self.data["llm"]["provider"], _BUILDERS)

    def test_agnes_section_complete(self):
        sec = self.data["llm"]["agnes"]
        self.assertEqual(sec["model"], "agnes-2.0-flash")
        self.assertEqual(sec["base_url"], "https://apihub.agnes-ai.cn/v1")
        self.assertEqual(sec["api_key_env"], "LLM_API_KEY_AGNES")
        self.assertGreater(sec["max_tokens"], 0)

    def test_model_context_keyed_not_nested(self):
        # "agnes-2.0-flash" 含点号，必须加引号；不加会被 TOML 拆成嵌套表
        self.assertIn("agnes-2.0-flash", self.data["model_context"])
        self.assertEqual(
            self.data["model_context"]["agnes-2.0-flash"], 524288)
        self.assertNotIn("agnes-2", self.data["model_context"])  # 拆表痕迹

    def test_pricing_free_zero(self):
        # 跳线测试：agnes 恢复收费改价时本测试必红——届时必须同步处理
        # observer.totals 跨币种直接加总 + 前端 fmtCost 硬编码 ¥ 的问题
        # （见 docs/DevLog.md 留档），不能只改数字。
        p = self.data["pricing"]["agnes-2.0-flash"]
        self.assertEqual(p["input_per_million"], 0)
        self.assertEqual(p["output_per_million"], 0)
        self.assertEqual(p["currency"], "USD")


class TestAgnesCost(AgnesBase):
    def test_record_cost_zero_for_agnes(self):
        import tomllib
        from backend.services.observer import Observer
        with open(_REPO_SETTINGS, "rb") as f:
            pricing = tomllib.load(f)["pricing"]
        obs = Observer(self.config)
        cost, currency = obs._record_cost(
            {"model": "agnes-2.0-flash", "in_tokens": 10000,
             "out_tokens": 500, "cache_hit": 0,
             "ts": "2026-07-25 10:00:00"}, pricing)  # 10 点属高峰时段
        self.assertEqual(cost, 0.0)   # 0 价 × 峰谷倍率仍为 0，无除零/负值
        self.assertEqual(currency, "USD")


if __name__ == "__main__":
    unittest.main()
