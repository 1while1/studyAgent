"""可观测性：agent.log 结构化日志 + token 计量 + 状态聚合（M2）。

- `runtime/agent.log`（JSONL）：LLM 调用（渠道/耗时/token/失败）与工具调用，
  任何"没反应"可从这里定位
- token 三层通用方案（v3 设计拍板）：API usage 精确 → tiktoken cl100k
  通用估算 → 兜底公式（CJK×1.5 + 其他÷4）；usage 到达时反算实际比率
  0.8/0.2 滑动校准，按 provider/model 存 runtime/token_calibration.json
- 任务标签走 ContextVar（`task_scope`），LLM 接口零改动
"""

from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from .backup_service import atomic_write
from .config_service import ConfigService, WEB_ROOT, runtime_dir

_task_var: ContextVar[str] = ContextVar("llm_task", default="chat")


@contextmanager
def task_scope(name: str):
    """标记当前上下文的 LLM 调用任务类型（chat/warmup/init…）。

    恢复旧值用 set 而非 reset(token)：生成器跨线程/跨上下文恢复时
    reset 会校验 context 并抛 RuntimeError，set 不校验（线上真实踩坑）。
    """
    old = _task_var.get()
    _task_var.set(name)
    try:
        yield
    finally:
        _task_var.set(old)


# ---- token 估算（tiktoken 主路径，公式兜底） ----

_ENC = None
_ENC_FAILED = False


def _encoding():
    global _ENC, _ENC_FAILED
    if _ENC is None and not _ENC_FAILED:
        try:
            import tiktoken
            _ENC = tiktoken.get_encoding("cl100k_base")
        except Exception:
            _ENC_FAILED = True
    return _ENC


def est_tokens(text: str) -> int:
    """通用 token 估算：tiktoken cl100k（离线）→ 兜底 CJK×1.5+其他÷4。"""
    if not text:
        return 0
    enc = _encoding()
    if enc is not None:
        try:
            return len(enc.encode(text, disallowed_special=()))
        except Exception:
            pass
    cjk = sum(1 for c in text if "一" <= c <= "鿿")
    return int(cjk * 1.5 + (len(text) - cjk) / 4) + 1


class Observer:
    """结构化日志与计量。enabled=false 时全部空转（测试/关闭场景）。"""

    def __init__(self, config: ConfigService):
        self._config = config
        self._enabled = bool(config.get("agent_log_enabled", True))
        raw = config.get("agent_log_path", "")
        if raw:
            self._log_path = (WEB_ROOT / raw).resolve()
        else:
            self._log_path = runtime_dir(config) / "agent.log"
        self._calib_path = self._log_path.parent / "token_calibration.json"
        self._lock = threading.Lock()
        self._last_call: dict | None = None
        self._today = {"date": time.strftime("%Y-%m-%d"), "calls": 0,
                       "in_tokens": 0, "out_tokens": 0}

    # ---- 校准 ----

    def _load_calib(self) -> dict:
        try:
            return json.loads(self._calib_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _update_calib(self, key: str, actual_ratio: float) -> None:
        calib = self._load_calib()
        old = calib.get(key)
        ratio = actual_ratio if not old else 0.8 * old["ratio"] + 0.2 * actual_ratio
        calib[key] = {"ratio": round(ratio, 4),
                      "samples": (old["samples"] + 1) if old else 1}
        try:
            self._calib_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(self._calib_path,
                         json.dumps(calib, ensure_ascii=False, indent=1))
        except Exception:
            pass

    def _calib_ratio(self, key: str) -> float:
        return self._load_calib().get(key, {}).get("ratio", 1.0)

    def ratio(self, key: str) -> float:
        """公开读取校准比率（provider/model 或 :out 后缀键），供上下文预算估算。"""
        return self._calib_ratio(key)

    # ---- 写日志 ----

    def _write(self, record: dict) -> None:
        if not self._enabled:
            return
        record.setdefault("v", 1)
        record["ts"] = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            with self._lock:
                self._log_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self._log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass  # 日志绝不影响主流程

    def log_llm(self, provider: str, model: str, latency_ms: int,
                in_text: str, out_text: str, usage: dict | None,
                ok: bool, error: str = "") -> None:
        """LLM 调用记账。usage（prompt_tokens/completion_tokens）优先于估算。"""
        key = f"{provider}/{model}"
        est_flag = not usage
        if usage and usage.get("prompt_tokens") is not None:
            in_t = int(usage["prompt_tokens"])
            out_t = int(usage.get("completion_tokens") or 0)
            base_in, base_out = est_tokens(in_text), est_tokens(out_text)
            if base_in > 0:
                self._update_calib(key, in_t / base_in)
            if base_out > 0 and out_t > 0:
                self._update_calib(key + ":out", out_t / base_out)
        else:
            in_t = round(est_tokens(in_text) * self._calib_ratio(key))
            out_t = round(est_tokens(out_text) * self._calib_ratio(key + ":out"))
        self._write({
            "kind": "llm", "provider": provider, "model": model,
            "task": _task_var.get(), "latency_ms": latency_ms,
            "in_tokens": in_t, "out_tokens": out_t,
            "tokens_est": est_flag, "ok": ok, "error": error[:200]})
        today = time.strftime("%Y-%m-%d")
        with self._lock:
            if self._today["date"] != today:
                self._today = {"date": today, "calls": 0,
                               "in_tokens": 0, "out_tokens": 0}
            self._today["calls"] += 1
            self._today["in_tokens"] += in_t
            self._today["out_tokens"] += out_t
            self._last_call = {"provider": provider, "model": model,
                               "latency_ms": latency_ms, "ok": ok,
                               "error": error[:120],
                               "ts": time.strftime("%H:%M:%S")}

    def log_tool(self, name: str, ok: bool, detail: str = "") -> None:
        self._write({"kind": "tool", "name": name, "ok": ok,
                     "detail": detail[:200]})

    # ---- 聚合 ----

    def status(self) -> dict:
        with self._lock:
            return {"enabled": self._enabled,
                    "last_call": self._last_call,
                    "today": dict(self._today)}

    def usage_summary(self, days: int = 7) -> dict:
        """按 日×渠道×task 聚合 llm 记录；成本走 settings [pricing]（近似值）。"""
        cutoff = time.time() - days * 86400
        pricing = self._config.get("pricing", {}) or {}
        groups: dict[tuple, dict] = {}
        try:
            lines = self._log_path.read_text(encoding="utf-8").splitlines()
        except Exception:
            lines = []
        for line in lines[-50000:]:
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("kind") != "llm":
                continue
            try:
                ts = time.mktime(time.strptime(r["ts"], "%Y-%m-%d %H:%M:%S"))
            except Exception:
                continue
            if ts < cutoff:
                continue
            day = r["ts"][:10]
            k = (day, r.get("provider", "?"), r.get("model", "?"),
                 r.get("task", "?"))
            g = groups.setdefault(k, {
                "date": day, "provider": k[1], "model": k[2], "task": k[3],
                "calls": 0, "failures": 0, "in_tokens": 0, "out_tokens": 0,
                "est_calls": 0, "cost": 0.0, "currency": ""})
            g["calls"] += 1
            g["failures"] += 0 if r.get("ok") else 1
            g["in_tokens"] += r.get("in_tokens", 0)
            g["out_tokens"] += r.get("out_tokens", 0)
            g["est_calls"] += 1 if r.get("tokens_est") else 0
            price = pricing.get(k[2])
            if price:
                g["cost"] += (r.get("in_tokens", 0) / 1e6 * price.get("input_per_million", 0)
                              + r.get("out_tokens", 0) / 1e6 * price.get("output_per_million", 0))
                g["currency"] = price.get("currency", "")
        rows = sorted(groups.values(), key=lambda g: (g["date"], g["provider"], g["task"]))
        totals = {"calls": sum(g["calls"] for g in rows),
                  "failures": sum(g["failures"] for g in rows),
                  "in_tokens": sum(g["in_tokens"] for g in rows),
                  "out_tokens": sum(g["out_tokens"] for g in rows),
                  "cost": round(sum(g["cost"] for g in rows), 4)}
        for g in rows:
            g["cost"] = round(g["cost"], 4)
        return {"rows": rows, "totals": totals, "days": days,
                "log_path": str(self._log_path)}


_OBSERVERS: dict[str, Observer] = {}


def get_observer(config: ConfigService) -> Observer:
    """按配置文件路径缓存的进程级单例。"""
    key = str(config.path)
    if key not in _OBSERVERS:
        _OBSERVERS[key] = Observer(config)
    return _OBSERVERS[key]


def log_prefetch(config: ConfigService, sources: list[str]) -> None:
    """备课预取记账（tool 类）。"""
    get_observer(config).log_tool("prefetch", bool(sources), ",".join(sources))
