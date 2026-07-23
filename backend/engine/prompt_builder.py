"""system prompt 组装管线：角色 + 硬约束 + 当前 SOP 卡 + 状态摘要 + 当前阶段指令。"""

from __future__ import annotations

from ..domain.enums import DayPhase
from ..domain.models import SessionContext
from ..services.config_service import ConfigService
from ..services.memory_store import MemoryStore
from ..services.state_store import StateStore
from .stage_machine import StageMachine


def _state_summary(state: dict, current_day: int, memory: MemoryStore) -> str:
    day = state["days"].get(str(current_day), {})
    lines = [f"当前进度：Day {current_day}（完成度 {state.get('overall_completion_percentage', 0)}%）",
             "当日单元："]
    for u in day.get("units", []):
        rating = f"，评分 {u['rating']}" if u.get("rating") else ""
        lines.append(f"- 单元{u['id']}：{u['title']}（{u['status']}{rating}）")
    if memory.exists(current_day):
        counts = memory.sync_counts(memory.read(current_day))
        lines.append(f"[同步] 统计：{counts}")
    return "\n".join(lines)


def _project_structure(cfg: ConfigService) -> str:
    """读取 docx/Project.md（真实项目架构），供模型引用代码时对照，防虚构路径。"""
    try:
        p = cfg.docx_dir / "Project.md"
        if p.exists():
            return p.read_text(encoding="utf-8")
    except Exception:
        pass
    return ""


class PromptBuilder:
    def __init__(self, config: ConfigService, state_store: StateStore,
                 memory: MemoryStore, stages: StageMachine, materials=None):
        self._config = config
        self._state_store = state_store
        self._memory = memory
        self._stages = stages
        self._materials = materials  # MaterialsService | None（None 跳过资料清单）

    def build(self, session: SessionContext, sop_card: str = "",
              extra_instruction: str = "", learner_summary: str = "") -> str:
        cfg = self._config
        roots = "、".join(r["name"] for r in cfg.code_roots) or "（未配置）"
        example_root = cfg.code_roots[0]["name"] if cfg.code_roots else "项目根"
        ws = cfg.workspace
        parts = [
            f"你是「{ws.title}」的 AI 导学助手，负责带用户深度学习。",
            f"学习目标：{ws.goal}" if ws.goal else "",
            "",
            "## 硬约束（违反即违规）",
            f"1. 单次连续代码输出 ≤ {cfg.get('code_line_limit', 20)} 行"
            f"（Day {cfg.get('code_line_exemption_days', [21])} 除外）。",
            "2. 禁止替用户做决定：阶段推进必须由系统状态机执行，你只负责讲解、提问、点评。",
            "3. 评价类输出（单元考核/复盘）必须给出量化评分，格式严格为【评分：X.X】（1.0-5.0），否则系统无法识别。",
            "4. 讲解单次回复正文控制在 1000 字以内；出题后必须停止，等待用户回答。",
            "5. 用户说「继续/嗯/好」不等于推进单元，按当前阶段继续讲解即可。",
            "6. 提及项目代码文件时，必须用反引号包裹完整路径，可附行号范围，"
            f"格式如 `{example_root}/路径/文件名:L4-L11`（行号不确定可省略）。"
            f"当前可用代码根：{roots}。用户可点击该引用跳转查看源码；"
            "引用前必须对照下方「项目真实结构」，禁止编造不存在的类与路径，不确定时只引用到模块/包目录级别。",
            "7. 讲解中需要查看真实内容时，**独立一行**输出读取标记，"
            "**禁止用反引号包裹标记**，**输出标记后立即停止该条回复**，"
            "系统会自动注入真实内容供你继续；禁止自己模拟注入过程、"
            "禁止在未见真实内容时编造代码或教材文字。两种标记："
            "① 读代码：`[READ:路径:L起-L止]`（行号不确定可省略为 `[READ:路径]`），"
            f"路径写法同第 6 条。用户明确要求读取/查看真实代码时必须使用。"
            "② 读教材：`[READ_DOC:资料id#章节名]`（章节不确定可省略为 "
            "`[READ_DOC:资料id]`，系统会先返回章节目录供你选择），"
            "资料 id 必须取自下方「可用学习资料」清单，禁止编造 id。"
            "讲解涉及教材具体内容、用户追问资料原文时必须使用。"
            f"单条回复两种标记合计最多 {cfg.get('ai_read_max_per_reply', 3)} 次；"
            "读取失败时按系统注入的候选修正，仍失败则跳过并如实告知，禁止编造内容。",
            "8. 讲架构、流程、时序、状态流转时，优先用 ```mermaid 代码块画图"
            "（flowchart / sequenceDiagram / stateDiagram），前端会渲染成图，图比长段文字更直观。",
            "",
        ]
        project = _project_structure(cfg)
        if project:
            parts += ["## 项目真实结构（引用代码文件以此为准）", project, ""]
        if self._materials is not None:
            try:
                catalog = self._materials.catalog()
            except Exception:
                catalog = ""
            if catalog:
                parts += ["## 可用学习资料（用 [READ_DOC:资料id#章节] 读取原文）",
                          catalog, ""]
        if sop_card:
            parts += ["## 当前流程的 SOP 卡（必须严格遵守）", sop_card, ""]
        if self._state_store.exists():
            state = self._state_store.load()
            parts += ["## 当前学习状态",
                      _state_summary(state, state["current_day"], self._memory), ""]
        if learner_summary:
            parts += ["## 学习者模型摘要（薄弱优先，供个性化讲解参考）",
                      learner_summary, ""]
        if (session.current_stage and self._stages.exists(session.current_stage)
                and session.day_phase != DayPhase.INTERVIEW.value):
            # 面试期不注入阶段指令（R8：防"最高优先级带读"与面试 rubric 双指令矛盾）
            parts += [
                "## 当前阶段指令（最高优先级）",
                f"当前阶段：{session.current_stage}（{self._stages.sop_step(session.current_stage)}）",
                self._stages.instruction(session.current_stage),
                "",
            ]
        if extra_instruction:
            parts += ["## 本次回复的附加指令", extra_instruction, ""]
        return "\n".join(parts)
