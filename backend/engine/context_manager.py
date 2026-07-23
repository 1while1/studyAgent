"""上下文控制（M5b，AgentDesign §8.5）：会话级三层 + 预算钳制 + 压缩机械校验。

三层：
- 钉住层：system prompt（学习者模型摘要经 prompt_builder 可选参数注入，
  确定性渲染 top-K 薄弱 + 当前单元，不走 LLM，永不压缩）
- 窗口层：最近 N 轮，按生效 token 预算伸缩（est_tokens × 渠道校准比率），
  条数硬兜底 [context].max_messages（取代旧 chat_history_max_turns 用途）
- 归档层：压缩摘要（[context].archive_max_chars 上限 + 前部逐出；
  盘上 StudyMemory 才是真归档，摘要是有损缓存）

触发：回合边界（maybe_compress，不在流式中途）；未归档历史估算 > 生效预算×
trigger_ratio 时窗口收缩，被裁部分经 cheap LLM 压缩归档；结构化模板 +
机械校验（concept id 集合、未决问题计数），不齐带原因重试一次，再不齐
原样保留降级不丢数据（§8.4）。cheap 失败 → strong 重试一次（fallback 链）。

预算钳制（用户反馈硬规）：生效预算 = min([context].budget_tokens 用户预算,
[model_context] 模型上限 − 当前渠道 max_tokens 输出预留)，下限 1024；
未知模型落 default（保守）。不同模型上下文长度差异由上限表驱动。
"""

from __future__ import annotations

import re

from ..domain.models import SessionContext
from ..services.config_service import PROMPTS_DIR, ConfigService

_ID_RE = re.compile(r"Day\d+-[A-Za-z0-9]+")
_Q_RE = re.compile(r"【未决问题】[（(]\s*共\s*(\d+)\s*条\s*[)）]")
_EVICT_MARK = "…（更早内容已逐出）"
_MSG_OVERHEAD = 4  # 每条消息的协议开销估算（role 等）


def effective_budget(config: ConfigService) -> int:
    """生效上下文预算：min(用户预算, 模型上限 − 输出预留)，下限 1024。"""
    budget = int(config.data.get("context", {}).get("budget_tokens", 256000))
    llm_cfg = config.llm_config
    provider = llm_cfg.get("provider", "")
    section = llm_cfg.get(provider, {}) if provider else {}
    model = section.get("model", "")
    limits = config.data.get("model_context", {})
    limit = int(limits.get(model, limits.get("default", 32768)))
    reserve = int(section.get("max_tokens", 4096))
    return max(1024, min(budget, limit - reserve))


def validate_compression(ids: set[str], expected_q: int,
                         output: str) -> str | None:
    """机械校验压缩输出（纯函数）。返回 None=通过，否则失败原因（供重试）。"""
    missing = [i for i in sorted(ids) if i not in output]
    if missing:
        return f"概念 id 遗漏：{', '.join(missing)}"
    declared = _declared_q(output)
    if declared != expected_q:
        return (f"未决问题计数不符：期望 {expected_q} 条，"
                f"输出声明 {declared} 条")
    return None


def _concept_ids(text: str) -> set[str]:
    return set(_ID_RE.findall(text or ""))


def _declared_q(summary: str) -> int:
    m = _Q_RE.search(summary or "")
    return int(m.group(1)) if m else 0


def _evict(summary: str, max_chars: int) -> str:
    if len(summary) <= max_chars:
        return summary
    return _EVICT_MARK + "\n" + summary[-max_chars:]


class ContextManager:
    """会话级上下文三层装配与压缩。deps 取 config/state_store/llm/llm_cheap。"""

    def __init__(self, deps):
        self._deps = deps
        self._config = deps.config

    def _ctx(self) -> dict:
        return self._config.data.get("context", {})

    # ---- 钉住层：学习者模型摘要（确定性渲染，不走 LLM） ----

    def learner_summary(self, session: SessionContext) -> str:
        try:
            try:
                day = int(self._deps.state_store.load().get("current_day", 1))
            except Exception:
                day = 1
            from ..services.learner_service import LearnerService
            concepts = LearnerService(self._config).get_model(day)["concepts"]
            if not concepts:
                return ""
            top_k = int(self._ctx().get("pin_top_k", 5))
            picked = sorted(concepts,
                            key=lambda c: c.get("mastery", 0))[:top_k]
            current_cid = ""
            if session.current_unit_id:
                from ..domain.learner import concept_id
                current_cid = concept_id(day, session.current_unit_id)
                if all(c["id"] != current_cid for c in picked):
                    cur = next((c for c in concepts
                                if c["id"] == current_cid), None)
                    if cur:
                        picked.append(cur)
            if not picked:
                return ""
            lines = []
            for c in picked:
                m = float(c.get("mastery", 0))
                band = "薄弱" if m < 0.4 else ("爬升中" if m < 0.7 else "达标")
                mark = "（当前单元）" if c["id"] == current_cid else ""
                lines.append(
                    f"- {c['id']} {c.get('title', '')}：掌握度 {m:.2f}"
                    f"（{band}）{mark}")
            return "\n".join(lines)
        except Exception:
            return ""  # 摘要是增强不是闸门：任何异常静默降级

    # ---- 窗口层装配 ----

    def assemble(self, session: SessionContext, system: str
                 ) -> tuple[list[dict], dict]:
        history = session.chat_history
        upto = session.archive_upto
        if upto < 0 or upto > len(history):
            upto = 0  # 防御：越界（旧会话/手动改库）时从全量重算
        candidates = history[upto:]
        budget = effective_budget(self._config)
        trigger = float(self._ctx().get("trigger_ratio", 0.8))
        if self._est_messages(candidates) <= budget * trigger:
            window = list(candidates)
        else:
            max_msgs = int(self._ctx().get("max_messages", 200))
            window = []
            total = 0
            for msg in reversed(candidates):
                if len(window) >= max_msgs:
                    break
                t = self._est_text(msg.get("content", ""))
                if window and total + t > budget:
                    break
                window.append(msg)  # 最新一条即使自身超预算也保留
                total += t
            window.reverse()
        compress_upto = len(history) - len(window)
        plan = {"needs_compression": compress_upto > upto,
                "compress_from": upto, "compress_upto": compress_upto}
        messages = [{"role": "system", "content": system}]
        if session.archive_summary:
            # 独立 system 消息（OpenAI/DeepSeek 兼容）；若渠道异常，
            # 降级点：并入 pinned system 文本尾部
            messages.append({
                "role": "system",
                "content": "【历史压缩摘要（有损缓存，仅供参考，"
                           "详情以 StudyMemory 为准）】\n"
                           + session.archive_summary})
        messages += window
        return messages, plan

    # ---- 归档层：回合边界压缩 ----

    def maybe_compress(self, session: SessionContext, plan: dict) -> None:
        if not plan or not plan.get("needs_compression"):
            return
        try:
            self._compress(session, plan)
        except Exception:
            pass  # 压缩是增强不是闸门：任何异常静默降级（§8.4）

    def _compress(self, session: SessionContext, plan: dict) -> None:
        frm, upto = plan["compress_from"], plan["compress_upto"]
        turns = session.chat_history[frm:upto]
        if not turns:
            return
        old_summary = session.archive_summary or ""
        source = old_summary + "\n" + "\n\n".join(
            f"{'用户' if m.get('role') == 'user' else 'AI'}："
            f"{m.get('content', '')}" for m in turns)
        ids = sorted(_concept_ids(source))
        expected_q = _declared_q(old_summary) + sum(
            1 for m in turns
            if m.get("role") == "user"
            and ("？" in m.get("content", "") or "?" in m.get("content", "")))
        max_chars = int(self._ctx().get("archive_max_chars", 4000))
        prompt = self._render_prompt(old_summary, turns, ids,
                                     expected_q, max_chars)
        out = self._call_llm(prompt)
        if out is None:
            return
        reason = validate_compression(set(ids), expected_q, out)
        if reason:
            retry = (prompt + f"\n\n上次输出未通过校验：{reason}。"
                              "请严格按输出契约重新输出，只输出摘要。")
            out2 = self._call_llm(retry)
            if out2 is None:
                return
            if validate_compression(set(ids), expected_q, out2):
                return  # 再不齐：原样保留降级，不丢数据
            out = out2
        session.archive_summary = _evict(out.strip(), max_chars)
        session.archive_upto = upto

    def _call_llm(self, prompt: str) -> str | None:
        """cheap 档调用；失败 → strong 重试一次（fallback 链）；都失败 None。"""
        from ..services.observer import task_scope
        messages = [{"role": "user", "content": prompt}]
        cheap = getattr(self._deps, "llm_cheap", None) or self._deps.llm
        with task_scope("compress"):
            try:
                return cheap.chat(messages, max_tokens=2000)
            except Exception:
                pass
            if cheap is not self._deps.llm:
                try:
                    return self._deps.llm.chat(messages, max_tokens=2000)
                except Exception:
                    pass
        return None

    def _render_prompt(self, old_summary: str, turns: list[dict],
                       ids: list[str], expected_q: int,
                       max_chars: int) -> str:
        tpl = (PROMPTS_DIR / "context_compress.md").read_text(encoding="utf-8")
        convo = "\n\n".join(
            f"{'用户' if m.get('role') == 'user' else 'AI'}："
            f"{m.get('content', '')}" for m in turns)
        return (tpl.replace("<旧摘要>", old_summary or "（无）")
                   .replace("<待压缩对话>", convo)
                   .replace("<概念id列表>", "、".join(ids) or "（无）")
                   .replace("<未决问题数>", str(expected_q))
                   .replace("<字数上限>", str(max_chars)))

    # ---- 估算（est_tokens × 渠道校准比率） ----

    def _calib_key(self) -> str:
        cfg = self._config.llm_config
        provider = cfg.get("provider", "")
        model = cfg.get(provider, {}).get("model", "") if provider else ""
        return f"{provider}/{model}" if provider and model else ""

    def _est_text(self, text: str) -> int:
        from ..services.observer import est_tokens, get_observer
        key = self._calib_key()
        ratio = get_observer(self._config).ratio(key) if key else 1.0
        return int(est_tokens(text) * ratio)

    def _est_messages(self, messages: list[dict]) -> int:
        return sum(self._est_text(m.get("content", "")) + _MSG_OVERHEAD
                   for m in messages)
