"""错误模式分类（M1.1 教学大脑）

基于教育学错误分类法（参考 M1_Research_Report.md §1.4）
两级结构：5 固定大类 + LLM 自由子类
"""
from __future__ import annotations

import json
from enum import Enum


class ErrorPatternMajor(str, Enum):
    """错误模式大类（5 固定枚举）"""
    CONCEPT_CONFUSION = "CONCEPT_CONFUSION"    # 概念混淆
    DETAIL_ERROR = "DETAIL_ERROR"              # 记错细节
    LOGIC_BREAK = "LOGIC_BREAK"                # 逻辑链断裂
    CANNOT_APPLY = "CANNOT_APPLY"              # 不会应用
    FORGOTTEN = "FORGOTTEN"                    # 忘记

    @classmethod
    def values(cls) -> list[str]:
        return [e.value for e in cls]


# LLM 自由子类：error_pattern_minor 为 str | None，不做枚举约束


def extract_error_pattern(llm_output: str) -> tuple[str | None, str | None]:
    """从 LLM 评分输出中提取错误分类（支持嵌套 JSON）

    期望 LLM 输出包含 JSON：
    {"error_major": "CONCEPT_CONFUSION", "error_minor": "将BFS当成DFS"}

    使用 json.JSONDecoder 逐位置尝试，支持嵌套/混合文本中的 JSON 提取。

    Returns:
        (major, minor) 元组，解析失败返回 (None, None)
    """
    decoder = json.JSONDecoder()
    idx = 0
    while idx < len(llm_output):
        try:
            pos = llm_output.index('{', idx)
            obj, end = decoder.raw_decode(llm_output, pos)
            if "error_major" in obj:
                major = obj.get("error_major")
                minor = obj.get("error_minor")
                # major 为 null / None → 回答正确，无错误
                if major is None:
                    return None, None
                if major in ErrorPatternMajor.values():
                    return major, minor if minor else None
                return None, None
            idx = end
        except (ValueError, json.JSONDecodeError):
            idx += 1
    return None, None


def extract_error_patterns(llm_output: str) -> list[str]:
    """从 LLM 输出中提取所有错误模式 major 列表（M1.2 教学行动策略输入）。

    使用 json.JSONDecoder 逐位置扫描，支持：
    - 单个 JSON 对象: {"error_major": "CONCEPT_CONFUSION", ...}
    - JSON 数组:   [{"error_major": "...", ...}, ...]
    - 嵌套/混合文本中的 JSON

    Returns:
        合法 major 值列表（去重保序），无匹配返回 []
    """
    results: list[str] = []
    seen: set[str] = set()
    decoder = json.JSONDecoder()
    idx = 0

    while idx < len(llm_output):
        try:
            # 尝试数组
            if llm_output[idx] == '[':
                arr, end = decoder.raw_decode(llm_output, idx)
                if isinstance(arr, list):
                    for item in arr:
                        if isinstance(item, dict):
                            major = item.get("error_major")
                            if (major and major in ErrorPatternMajor.values()
                                    and major not in seen):
                                seen.add(major)
                                results.append(major)
                idx = end
                continue
            # 尝试对象
            if llm_output[idx] == '{':
                obj, end = decoder.raw_decode(llm_output, idx)
                if "error_major" in obj:
                    major = obj.get("error_major")
                    if (major and major in ErrorPatternMajor.values()
                            and major not in seen):
                        seen.add(major)
                        results.append(major)
                idx = end
                continue
        except (ValueError, json.JSONDecodeError):
            pass
        idx += 1

    return results
