"""AI 读文件 tool-use 闭环：截获导师输出中的 [READ:路径:Lx-y] 标记并注入真实代码。

协议：导师在讲解中输出 `[READ:路径:L起-止]`（行号可省，要求独立一行、
禁止反引号包裹——但解析对反引号/行内出现均容错），本模块以「增量扫描」
方式截获该标记（不下发给前端），经 code_browser 只读读取真实文件内容后，
以 user 消息注入上下文并续写讲解。

安全与边界：
- 读取走 CodeBrowser.resolve + read_file（只读 + 穿越防护 + 1MB 上限）
- 单次回复 READ 上限 ai_read_max_per_reply（默认 3），超限标记静默丢弃
- 单次注入行数上限 ai_read_max_lines（默认 200），超出截断并标注
- 注入的文件内容只用于续写调用，不进 chat_history；标记不进最终文本
"""

from __future__ import annotations

import re
from typing import Iterator

from ..llm.base import LLMClient, Message
from ..services.code_browser import CodeBrowser
from ..services.config_service import ConfigService

# 完整标记（可带反引号包裹）：`[READ:路径:L10-L40]` / [READ:路径] 等
MARK_RE = re.compile(
    r"`?\[READ:([^:\]`\n]+?)(?::L?(\d+)(?:-L?(\d+))?)?\]`?")
# 标记可能出现的起点前缀（用于跨 delta 残片hold-back）
_MARK_PREFIXES = ("`[READ:", "[READ:")
# 等待 "]" 闭合的缓冲上限：超过即按普通文本下发（防模型忘闭合卡死输出）
_MARKER_BUF_CAP = 2000


class ToolUseLoop:
    """包装 llm.chat_stream，产出 SSE 事件 dict（delta / tool_read）。"""

    def __init__(self, config: ConfigService, llm: LLMClient,
                 browser: CodeBrowser):
        self._config = config
        self._llm = llm
        self._browser = browser
        self.text: str = ""  # 最终文本（不含标记行），供落 chat_history

    def run(self, messages: list[Message]) -> Iterator[dict]:
        max_reads = int(self._config.get("ai_read_max_per_reply", 3))
        reads = 0
        convo = list(messages)
        while True:
            pending_read = None  # 本轮回合截获的标记 (path, start, end)
            for ev in self._stream_round(convo,
                                         allow_read=reads < max_reads):
                if ev["type"] == "delta":
                    self.text += ev["content"]
                    yield ev
                elif ev["type"] == "_marker":
                    pending_read = ev
                    break
            if pending_read is None:
                return  # 流正常结束
            reads += 1
            event, injection = self._do_read(pending_read)
            yield event
            convo = convo + [
                {"role": "assistant", "content": self.text},
                {"role": "user", "content": injection},
            ]

    # ---- 单轮流式输出，增量扫描截获标记 ----

    def _stream_round(self, messages: list[Message],
                      allow_read: bool) -> Iterator[dict]:
        buf = ""
        for delta in self._llm.chat_stream(messages):
            buf += delta
            for ev in self._drain(buf, final=False, allow_read=allow_read):
                if ev["type"] == "_marker":
                    yield ev
                    return
                buf = ev.pop("_rest")
                if ev["content"]:
                    yield ev
        for ev in self._drain(buf, final=True, allow_read=allow_read):
            if ev["type"] == "_marker":
                yield ev
                return
            if ev["content"]:
                yield ev

    def _drain(self, buf: str, final: bool,
               allow_read: bool) -> Iterator[dict]:
        """从缓冲中榨取可下发内容。

        产出 {"type":"delta","content":...,"_rest":剩余缓冲}；
        截获标记时产出 {"type":"_marker", ...}（调用方应中断本轮流）。
        """
        while buf:
            i = buf.find("[READ:")
            if i == -1:
                if final:
                    yield {"type": "delta", "content": buf, "_rest": ""}
                    return
                # 尾部可能是不完整标记前缀（含可选反引号），hold 住等后续
                hold = 0
                for p in _MARK_PREFIXES:
                    for n in range(1, len(p)):
                        if buf.endswith(p[:n]):
                            hold = max(hold, n)
                if hold:
                    head, buf = buf[:-hold], buf[-hold:]
                    if head:
                        yield {"type": "delta", "content": head, "_rest": buf}
                        return
                yield {"type": "delta", "content": "", "_rest": buf}
                return
            # 标记起点前的文本（连同可能的包裹反引号一起剥离）
            start = i - 1 if i > 0 and buf[i - 1] == "`" else i
            if start > 0:
                yield {"type": "delta", "content": buf[:start], "_rest": buf[start:]}
                return
            j = buf.find("]", i + 6)
            if j == -1:
                if not final and len(buf) < _MARKER_BUF_CAP:
                    yield {"type": "delta", "content": "", "_rest": buf}
                    return  # 等 "]" 到达
                # 流结束/超长仍未闭合：按普通文本下发
                yield {"type": "delta", "content": buf, "_rest": ""}
                return
            token = buf[i:j + 1]
            rest = buf[j + 1:]
            if rest.startswith("`"):
                token += "`"
                rest = rest[1:]
            m = MARK_RE.fullmatch(token)
            if not m:  # 非法标记按原文下发
                yield {"type": "delta", "content": token, "_rest": rest}
                return
            if allow_read:
                yield {"type": "_marker", "path": m.group(1),
                       "start": m.group(2), "end": m.group(3)}
                return
            buf = rest  # 超限静默丢弃，继续扫描后续内容

    # ---- 读取文件并构造注入文本 ----

    def _do_read(self, marker: dict) -> tuple[dict, str]:
        path, start, end = marker["path"], marker["start"], marker["end"]
        lines_label = f"L{start}-L{end or start}" if start else ""
        event = {"type": "tool_read", "path": path, "lines": lines_label,
                 "ok": False, "error": None}
        hit = self._browser.resolve(path)
        if not hit:
            event["error"] = "文件未找到"
            tips = self._browser.suggest(path)
            if tips:
                event["suggestions"] = [f"{t['root']}/{t['path']}" for t in tips]
                cand = "\n".join(f"- `{t['root']}/{t['path']}`" for t in tips)
                return event, (
                    f"【系统注入】读取失败：未找到文件 `{path}`。"
                    f"索引中最接近的候选文件：\n{cand}\n"
                    "若其中有目标文件，请用候选路径重新发起读取；"
                    "若都不相关，说明该文件可能不存在，禁止编造其内容，"
                    "请明确告知用户并换用真实存在的文件讲解。")
            return event, (f"【系统注入】读取失败：未找到文件 `{path}`，"
                           "索引中也没有相似文件，该文件很可能不存在。"
                           "禁止编造其内容，请对照「项目真实结构」换用真实存在的文件，"
                           "或明确告知用户该文件不存在。")
        try:
            data = self._browser.read_file(hit["root"], hit["path"])
        except Exception as e:
            event["error"] = str(e)[:100]
            return event, (f"【系统注入】读取失败：{e}。"
                           "请换用其他引用或跳过该文件继续讲解。")
        if not data["content"].strip():
            event.update({"ok": True, "path": f"{hit['root']}/{hit['path']}",
                          "lines": ""})
            return event, (
                f"【系统注入】`{hit['path']}` 存在但**内容为空**（0 字节占位文件）。"
                "请明确告知用户该文件为空，换用其他真实文件继续，禁止编造其内容。")
        all_lines = data["content"].split("\n")
        total = len(all_lines)
        s = max(1, int(start)) if start else 1
        e = int(end) if end else (s if start else total)
        e = max(s, min(e, total))
        max_lines = int(self._config.get("ai_read_max_lines", 200))
        truncated = ""
        if e - s + 1 > max_lines:
            e = s + max_lines - 1
            truncated = f"（已截断：仅前 {max_lines} 行）"
        snippet = "\n".join(all_lines[s - 1:e])
        real = hit["path"]
        event.update({"ok": True, "path": f"{hit['root']}/{real}",
                      "lines": f"L{s}-L{e}"})
        injection = (
            f"【系统注入】`{real}`:L{s}-L{e} 的真实内容"
            f"（共 {total} 行）{truncated}：\n"
            f"```{data['lang']}\n{snippet}\n```\n"
            "以上是该文件的真实代码。请基于真实内容继续讲解，"
            "与此前已讲内容衔接，禁止重复，禁止再虚构行号或代码。")
        return event, injection
