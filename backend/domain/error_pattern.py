"""错误模式分类（M1.1 教学大脑）

基于教育学错误分类法（参考 M1_Research_Report.md §1.4）
两级结构：5 固定大类 + LLM 自由子类
"""
from __future__ import annotations

import json
import re
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
    """从 LLM 评分输出中提取错误分类

    期望 LLM 输出包含 JSON：
    {"error_major": "CONCEPT_CONFUSION", "error_minor": "将BFS当成DFS"}

    Returns:
        (major, minor) 元组，解析失败返回 (None, None)
    """
    # 尝试从输出中提取 JSON
    json_match = re.search(r'\{[^}]*"error_major"[^}]*\}', llm_output)
    if not json_match:
        return None, None

    try:
        data = json.loads(json_match.group())
        major = data.get("error_major")
        minor = data.get("error_minor")

        # major 为 null / None → 回答正确，无错误
        if major is None:
            return None, None

        # 验证 major 是否为合法枚举值
        if major in ErrorPatternMajor.values():
            return major, minor if minor else None
        return None, None
    except (json.JSONDecodeError, KeyError, TypeError):
        return None, None


def extract_error_patterns(llm_output: str) -> list[str]:
    """从 LLM 输出中提取所有错误模式 major 列表（M1.2 教学行动策略输入）。

    支持单个 JSON 对象或 JSON 数组：
    - 单对象: {"error_major": "CONCEPT_CONFUSION", ...}
    - 数组:   [{"error_major": "...", ...}, ...]

    Returns:
        合法 major 值列表（去重保序），无匹配返回 []
    """
    results: list[str] = []
    seen: set[str] = set()

    # 尝试提取 JSON 数组
    arr_match = re.search(r'\[\s*\{[^]]*\}\s*(?:,\s*\{[^]]*\}\s*)*\]', llm_output)
    if arr_match:
        try:
            arr = json.loads(arr_match.group())
            if isinstance(arr, list):
                for item in arr:
                    major = item.get("error_major") if isinstance(item, dict) else None
                    if major and major in ErrorPatternMajor.values() and major not in seen:
                        seen.add(major)
                        results.append(major)
                if results:
                    return results
        except (json.JSONDecodeError, TypeError):
            pass

    # 回退：提取单个 JSON 对象
    major, _ = extract_error_pattern(llm_output)
    if major and major not in seen:
        results.append(major)

    return results
