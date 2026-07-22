"""文档初始化：骨架模板渲染 + LLM 生成 + 验证管线。

职责边界：只负责「生成并校验一个工作区的初始文档」，不碰 settings 注册与工作区编排。
新增初始化文档类型 = 在 SKELETON_DOCS 注册（模板文件 → 目标文件名）。
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

from ..domain.workspace import Workspace
from .config_service import PROMPTS_DIR, TEMPLATES_DIR
from .study_plan import StudyPlanError, parse_day_text

# 骨架模板 → 目标文件（固定内容，不经 LLM）
SKELETON_DOCS = {
    "StudyState.json.tpl": "StudyState.json",
    "ReplicaPlan.md.tpl": "ReplicaPlan.md",
    "DocIndex.md.tpl": "DocIndex.md",
    "InterviewQA.md.tpl": "InterviewQA.md",
}

# 工作区初始目录结构
INIT_DIRS = ["StudyMemory", "StudyReview", "hooks/backup"]

MAX_RETRIES = 1  # LLM 生成校验失败后的带错重试次数
DEFAULT_INIT_MAX_TOKENS = 8192  # 多数 OpenAI 兼容上游的单次输出硬顶（DeepSeek=8192）


class InitError(Exception):
    pass


class DocInitializer:
    def __init__(self, llm, max_tokens: int = DEFAULT_INIT_MAX_TOKENS):
        self._llm = llm
        self._max_tokens = max_tokens

    # ---- 骨架模板 ----

    def _render_skeletons(self, ws: Workspace) -> dict[Path, str]:
        placeholders = {
            "title": ws.title,
            "goal": ws.goal,
            "total_days": str(ws.total_days),
            "replica_name": ws.replica_name,
            "date": datetime.date.today().isoformat(),
        }
        files: dict[Path, str] = {}
        for tpl_name, target_name in SKELETON_DOCS.items():
            text = (TEMPLATES_DIR / tpl_name).read_text(encoding="utf-8")
            for key, value in placeholders.items():
                text = text.replace(f"<{key}>", value)
            files[ws.docx_dir / target_name] = text
        # StudyState 必须是合法 JSON
        state_path = ws.docx_dir / "StudyState.json"
        try:
            json.loads(files[state_path])
        except (json.JSONDecodeError, KeyError) as e:
            raise InitError(f"StudyState 骨架渲染结果非法: {e}") from e
        return files

    # ---- LLM 生成 + 验证 ----

    def _generate(self, prompt_file: str, ws: Workspace,
                  scan_profile: str, validate, label: str) -> str:
        prompt = (PROMPTS_DIR / prompt_file).read_text(encoding="utf-8")
        prompt = (prompt
                  .replace("<title>", ws.title)
                  .replace("<goal>", ws.goal)
                  .replace("<total_days>", str(ws.total_days))
                  .replace("<replica_name>", ws.replica_name)
                  .replace("<scan_profile>", scan_profile))
        errors = ""
        for attempt in range(1 + MAX_RETRIES):
            p = prompt if not errors else (
                f"{prompt}\n\n【上次输出未通过程序校验】\n{errors}\n"
                f"请修正后重新完整输出（仍禁止任何前言后语）。")
            text = self._llm.chat([{"role": "user", "content": p}],
                                  max_tokens=self._max_tokens)
            # 容错：剥掉可能的 markdown 围栏包裹
            text = text.strip()
            if text.startswith("```") and text.endswith("```"):
                text = "\n".join(text.splitlines()[1:-1]).strip()
            ok, errors = validate(text)
            if ok:
                return text
        raise InitError(f"{label} 生成后未通过校验（重试 {MAX_RETRIES} 次仍失败）: {errors}")

    @staticmethod
    def _validate_project_md(text: str) -> tuple[bool, str]:
        if len(text) < 400:
            return False, f"内容过短（{len(text)} 字符）"
        if "模块结构" not in text:
            return False, "缺少「模块结构」小节"
        return True, ""

    @staticmethod
    def _make_study_md_validator(ws: Workspace):
        def validate(text: str) -> tuple[bool, str]:
            if "当前天数：Day 1" not in text:
                return False, "缺少头部「当前天数：Day 1」"
            if "整体完成度" not in text:
                return False, "缺少头部「整体完成度」"
            bad = []
            for day in range(1, ws.total_days + 1):
                try:
                    parsed = parse_day_text(text, day, ws.replica_name)
                    if not parsed["units"]:
                        bad.append(f"Day {day}: 单元数为 0")
                except StudyPlanError:
                    bad.append(f"Day {day}: 小节缺失或无法解析")
            return (not bad), "；".join(bad[:5])
        return validate

    # ---- 对外入口 ----

    def initialize(self, ws: Workspace, scan_profile: str) -> dict:
        """生成工作区全部初始文档并落盘。返回 {files: [文件名...]}。"""
        for d in INIT_DIRS:
            (ws.docx_dir / d).mkdir(parents=True, exist_ok=True)

        files = self._render_skeletons(ws)
        files[ws.docx_dir / "Project.md"] = self._generate(
            "init_project_md.md", ws, scan_profile,
            self._validate_project_md, "Project.md")
        files[ws.docx_dir / "Study.md"] = self._generate(
            "init_study_md.md", ws, scan_profile,
            self._make_study_md_validator(ws), "Study.md")

        for path, content in files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        return {"files": sorted(p.name for p in files)}

    def refresh_project_md(self, ws: Workspace, scan_profile: str) -> str:
        """手动刷新：仅重新生成 Project.md，返回新内容。"""
        text = self._generate("init_project_md.md", ws, scan_profile,
                              self._validate_project_md, "Project.md")
        path = ws.docx_dir / "Project.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return text
