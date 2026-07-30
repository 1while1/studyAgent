"""日志分析器（M3.5 可观测性增强）

提供 agent.log 的结构化查询和统计能力。
"""
from __future__ import annotations
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class LogStats:
    total_entries: int = 0
    token_usage: dict = field(default_factory=dict)
    error_count: int = 0
    warning_count: int = 0
    event_types: dict = field(default_factory=dict)
    avg_response_time: float = 0.0


class LogAnalyzer:
    def __init__(self, log_path: Path):
        self._log_path = log_path
    
    def analyze(self, last_n: int = 0) -> LogStats:
        stats = LogStats()
        if not self._log_path.exists():
            return stats
        lines = self._log_path.read_text(encoding="utf-8").strip().split("\n")
        if last_n > 0:
            lines = lines[-last_n:]
        token_counter = Counter()
        event_counter = Counter()
        response_times = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            stats.total_entries += 1
            try:
                entry = json.loads(line)
                if "tokens" in entry:
                    for k, v in entry["tokens"].items():
                        token_counter[k] += v
                if "event" in entry:
                    event_counter[entry["event"]] += 1
                if "response_time" in entry:
                    response_times.append(entry["response_time"])
                if entry.get("level") == "error":
                    stats.error_count += 1
                elif entry.get("level") == "warning":
                    stats.warning_count += 1
            except json.JSONDecodeError:
                if "ERROR" in line or "error" in line.lower():
                    stats.error_count += 1
                elif "WARNING" in line or "warning" in line.lower():
                    stats.warning_count += 1
        stats.token_usage = dict(token_counter)
        stats.event_types = dict(event_counter)
        if response_times:
            stats.avg_response_time = sum(response_times) / len(response_times)
        return stats
    
    def query(self, keyword: str, last_n: int = 0) -> list[dict]:
        results = []
        if not self._log_path.exists():
            return results
        lines = self._log_path.read_text(encoding="utf-8").strip().split("\n")
        if last_n > 0:
            lines = lines[-last_n:]
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if keyword.lower() in line.lower():
                try:
                    results.append(json.loads(line))
                except json.JSONDecodeError:
                    results.append({"raw": line})
        return results
    
    def get_token_summary(self) -> dict:
        stats = self.analyze()
        return {"total_tokens": sum(stats.token_usage.values()), "by_type": stats.token_usage}
    
    def get_error_summary(self, last_n: int = 100) -> list[dict]:
        errors = []
        if not self._log_path.exists():
            return errors
        lines = self._log_path.read_text(encoding="utf-8").strip().split("\n")
        for line in lines[-last_n:]:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if entry.get("level") == "error":
                    errors.append(entry)
            except json.JSONDecodeError:
                if "ERROR" in line or "error" in line.lower():
                    errors.append({"raw": line})
        return errors
