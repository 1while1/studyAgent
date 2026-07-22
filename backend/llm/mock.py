"""MockLLM：免 API key 的确定性假模型，供开发与测试。

行为规则（检查 system prompt 中的「当前阶段」标记）：
- quiz_r2 阶段且用户刚提交答案 → 输出点评 + 【评分：4.5】
- quiz_r1 / quiz_r2 阶段 → 输出一道 Mock 检验题
- 用户文本含「演示读代码」→ 输出带 [READ:...] 标记的讲解（供 tool-use 走查）；
  随后的「【系统注入】」续写调用 → 返回不含标记的收尾讲解
- 其余 → 输出 Mock 讲解段落
也可传入 script 列表按顺序消费，完全脚本化（测试用）。
"""

from __future__ import annotations

from typing import Iterator

from .base import LLMClient, Message


class MockLLM(LLMClient):
    def __init__(self, script: list[str] | None = None):
        self._script = list(script) if script else None

    def _canned(self, messages: list[Message]) -> str:
        system = messages[0]["content"] if messages else ""
        last_user = messages[-1]["content"] if messages else ""
        if "当前阶段：quiz_r2" in system:
            if "第二轮检验题" in last_user or "请出题" in last_user:
                return "【Mock 第二轮检验题】请说明 OkHttp 流式响应为什么不能调用两次 string()？"
            return ("【Mock 点评】回答触及了响应体一次性消费的核心，但源码定位不够精确。\n"
                    "综合两轮表现给出终期评分：【评分：4.5】")
        if "当前阶段：quiz_r1" in system:
            if "第一轮检验题" in last_user or "请出题" in last_user:
                return "【Mock 第一轮检验题】请解释 SSE 协议的 data: 字段格式与事件流结束标志。"
            return "【Mock 点评】第一轮回答正确，概念清晰。下面进入第二轮深度追问。"
        if "复盘拷问进行中" in system or "进入今日复盘模式" in system:
            return "【Mock 拷问题】Q1: 首包探测失败后是重试还是切换？\n【评分：4.0】"
        if "【系统注入】" in last_user:
            return ("【Mock 续写】以上是真实文件内容，可以看到结构与前述分析一致，"
                    "讲解完毕。")
        if "演示读代码" in last_user:
            return ("【Mock 讲解】我们先看一下这个文件的真实开头：\n"
                    "[READ:ragent原项目/frontend/index.html:L1-L5]\n"
                    "（此行不应出现在最终文本）")
        return ("【Mock 讲解】这里是当前阶段的导学内容：核心概念讲解 + 面试考点提示。"
                "（MockLLM 占位回复，配置真实 LLM 后由模型生成）")

    def chat_stream(self, messages: list[Message],
                    max_tokens: int | None = None) -> Iterator[str]:
        if self._script is not None:
            text = self._script.pop(0) if self._script else "【Mock】（脚本已耗尽）"
        else:
            text = self._canned(messages)
        # 按小块吐出，模拟流式
        step = 16
        for i in range(0, len(text), step):
            yield text[i:i + step]
