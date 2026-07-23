"""AI 读文件 tool-use 闭环：截获导师输出中的读取标记并注入真实内容。

协议（两种标记，同一注入管线、同一限流）：
- `[READ:路径:L起-止]` 读项目代码（行号可省）
- `[READ_DOC:资料id#章节]` 读学习资料（章节可省=先看章节目录）

均要求独立一行、禁止反引号包裹——但解析对反引号/行内出现均容错。
本模块以「增量扫描」截获标记（不下发给前端），只读获取真实内容后以
user 消息注入上下文并续写讲解。

安全与边界：
- 代码读取走 CodeBrowser.resolve + read_file（只读 + 穿越防护 + 1MB 上限）
- 资料读取走 MaterialsService.read_section（注册表内条目，缓存文本）
- 单回复两种标记合计上限 ai_read_max_per_reply（默认 3），超限静默丢弃
- 单次注入行数上限 ai_read_max_lines（默认 200），超出截断并标注
- 注入内容只用于续写调用，不进 chat_history；标记不进最终文本
- materials 为 None 时 READ_DOC 标记按普通文本透传（向后兼容）

M5a：标记分发改经 tool_registry（read_code/read_doc 工具），event 与注入
文本保持逐字一致；注册表对 marker/native 两种传输暴露同一份工具 schema。
"""

from __future__ import annotations

import re
from typing import Iterator

from ..llm.base import LLMClient, Message
from ..services.code_browser import CodeBrowser
from ..services.config_service import ConfigService
from ..services.materials_service import MaterialsService
from .tool_registry import ToolContext, ToolRegistry, build_default_registry

# 代码标记（可带反引号包裹）：`[READ:路径:L10-L40]` / [READ:路径] 等
MARK_RE = re.compile(
    r"`?\[READ:([^:\]`\n]+?)(?::L?(\d+)(?:-L?(\d+))?)?\]`?")
# 资料标记（可带反引号包裹）：[READ_DOC:资料id#章节] / [READ_DOC:资料id]
DOC_MARK_RE = re.compile(
    r"`?\[READ_DOC:([^#`\]\n]+?)(?:#([^`\]\n]+?))?\]`?")
# 两种标记的起点前缀（用于跨 delta 残片 hold-back；前缀互不互含）
_MARK_PREFIXES = ("`[READ:", "[READ:", "`[READ_DOC:", "[READ_DOC:")
# 等待 "]" 闭合的缓冲上限：超过即按普通文本下发（防模型忘闭合卡死输出）
_MARKER_BUF_CAP = 2000


class ToolUseLoop:
    """包装 llm.chat_stream，产出 SSE 事件 dict（delta / tool_read）。"""

    def __init__(self, config: ConfigService, llm: LLMClient,
                 browser: CodeBrowser, materials: MaterialsService | None = None,
                 registry: ToolRegistry | None = None,
                 tool_context: ToolContext | None = None):
        self._config = config
        self._llm = llm
        self._browser = browser
        self._materials = materials
        self._ctx = tool_context or ToolContext(
            config=config, browser=browser, materials=materials)
        self._registry = registry or build_default_registry()
        self.text: str = ""  # 最终文本（不含标记行），供落 chat_history

    def run(self, messages: list[Message]) -> Iterator[dict]:
        max_reads = int(self._config.get("ai_read_max_per_reply", 3))
        reads = 0
        convo = list(messages)
        while True:
            pending_read = None  # 本轮回合截获的标记
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
            if pending_read["kind"] == "doc":
                result = self._registry.invoke(
                    "read_doc", {"doc_id": pending_read["doc"],
                                 "section": pending_read["section"]}, self._ctx)
                tool_name = "read_doc"
                detail = pending_read["doc"]
            else:
                result = self._registry.invoke(
                    "read_code", {"path": pending_read["path"],
                                  "start": pending_read["start"],
                                  "end": pending_read["end"]}, self._ctx)
                tool_name = "read_code"
                detail = pending_read["path"]
            if result.event is None or result.injection is None:
                return  # 注册表缺少读工具（防御性，正常不可达）：放弃本次读取
            event, injection = result.event, result.injection
            from ..services.observer import get_observer
            get_observer(self._config).log_tool(tool_name, event["ok"], detail)
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

    @staticmethod
    def _find_marker(buf: str) -> tuple[int, str]:
        """最早出现的标记起点（[READ: 与 [READ_DOC: 前缀互不互含）。"""
        best_i, best_p = -1, ""
        for p in ("[READ:", "[READ_DOC:"):
            i = buf.find(p)
            if i != -1 and (best_i == -1 or i < best_i):
                best_i, best_p = i, p
        return best_i, best_p

    def _drain(self, buf: str, final: bool,
               allow_read: bool) -> Iterator[dict]:
        """从缓冲中榨取可下发内容。

        产出 {"type":"delta","content":...,"_rest":剩余缓冲}；
        截获标记时产出 {"type":"_marker", ...}（调用方应中断本轮流）。
        """
        while buf:
            i, prefix = self._find_marker(buf)
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
            j = buf.find("]", i + len(prefix))
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
            is_doc = prefix == "[READ_DOC:"
            m = (DOC_MARK_RE if is_doc else MARK_RE).fullmatch(token)
            if not m:  # 非法标记按原文下发
                yield {"type": "delta", "content": token, "_rest": rest}
                return
            if is_doc and self._materials is None:
                # 无资料库服务：标记按普通文本透传（向后兼容）
                yield {"type": "delta", "content": token, "_rest": rest}
                return
            if allow_read:
                if is_doc:
                    yield {"type": "_marker", "kind": "doc", "doc": m.group(1),
                           "section": m.group(2)}
                else:
                    yield {"type": "_marker", "kind": "code", "path": m.group(1),
                           "start": m.group(2), "end": m.group(3)}
                return
            buf = rest  # 超限静默丢弃，继续扫描后续内容
