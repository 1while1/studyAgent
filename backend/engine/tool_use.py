"""AI 读文件 tool-use 闭环：截获导师输出中的 [READ:路径:Lx-y] 标记并注入真实代码。

协议：导师在讲解中**独立一行**输出 `[READ:路径:L起-止]`（行号可省），
本模块以「行缓冲」方式截获该标记（不下发给前端），经 code_browser 只读读取
真实文件内容后，以 user 消息注入上下文并续写讲解。

安全与边界：
- 读取走 CodeBrowser.resolve + read_file（只读 + 穿越防护 + 1MB 上限）
- 单次回复 READ 上限 ai_read_max_per_reply（默认 3），超限标记静默丢弃
- 单次注入行数上限 ai_read_max_lines（默认 200），超出截断并标注
- 注入的文件内容只用于续写调用，不进 chat_history；标记行不进最终文本
"""

from __future__ import annotations

import re
from typing import Iterator

from ..llm.base import LLMClient, Message
from ..services.code_browser import CodeBrowser
from ..services.config_service import ConfigService

# [READ:路径] / [READ:路径:L10] / [READ:路径:L10-L40]（独立一行）
READ_RE = re.compile(
    r"^\[READ:([^:\]\n]+?)(?::L?(\d+)(?:-L?(\d+))?)?\]\s*$")


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
                elif ev["type"] == "_read_marker":
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

    # ---- 单轮流式输出，行缓冲截获标记 ----

    def _stream_round(self, messages: list[Message],
                      allow_read: bool) -> Iterator[dict]:
        buf = ""
        for delta in self._llm.chat_stream(messages):
            buf += delta
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                m = READ_RE.match(line)
                if m:
                    if not allow_read:
                        continue  # 超限静默丢弃，流照常继续
                    yield {"type": "_read_marker", "path": m.group(1),
                           "start": m.group(2), "end": m.group(3)}
                    return
                yield {"type": "delta", "content": line + "\n"}
        # 流结束：flush 暂存的最后一行（也要过标记匹配）
        if buf:
            m = READ_RE.match(buf)
            if m:
                if not allow_read:
                    return
                yield {"type": "_read_marker", "path": m.group(1),
                       "start": m.group(2), "end": m.group(3)}
                return
            yield {"type": "delta", "content": buf}

    # ---- 读取文件并构造注入文本 ----

    def _do_read(self, marker: dict) -> tuple[dict, str]:
        path, start, end = marker["path"], marker["start"], marker["end"]
        lines_label = f"L{start}-L{end or start}" if start else ""
        event = {"type": "tool_read", "path": path, "lines": lines_label,
                 "ok": False, "error": None}
        hit = self._browser.resolve(path)
        if not hit:
            event["error"] = "文件未找到"
            return event, (f"【系统注入】读取失败：未找到文件 `{path}`。"
                           "请对照「项目真实结构」修正路径后继续讲解，"
                           "禁止编造文件内容。")
        try:
            data = self._browser.read_file(hit["root"], hit["path"])
        except Exception as e:
            event["error"] = str(e)[:100]
            return event, (f"【系统注入】读取失败：{e}。"
                           "请换用其他引用或跳过该文件继续讲解。")
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
