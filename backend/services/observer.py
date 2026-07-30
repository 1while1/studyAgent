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
import sys
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from .backup_service import atomic_write
from .config_service import ConfigService, WEB_ROOT, get_config, runtime_dir

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
        self._seed_today()
        self._write_warned = threading.Event()

    def _seed_today(self) -> None:
        """启动时从日志尾部回填今日累计（重启不归零，顶栏速览可信）。"""
        today = time.strftime("%Y-%m-%d")
        try:
            lines = self._log_path.read_text(encoding="utf-8").splitlines()
        except Exception:
            return
        for line in lines[-20000:]:
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("kind") != "llm" or not str(r.get("ts", "")).startswith(today):
                continue
            self._today["calls"] += 1
            self._today["in_tokens"] += r.get("in_tokens", 0)
            self._today["out_tokens"] += r.get("out_tokens", 0)

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

    # 日志滚动上限：超过即轮转（M3.3 多文件轮转）
    _ROTATE_BYTES = 50 * 1024 * 1024  # 50MB
    _MAX_LOG_FILES = 5

    def _rotate_log(self) -> None:
        """日志轮转：agent.log → agent.log.1 → ... → agent.log.N"""
        try:
            if not self._log_path.exists():
                return
            # 删除最旧档（而非覆盖）
            oldest = self._log_path.parent / f"{self._log_path.name}.{self._MAX_LOG_FILES}"
            if oldest.exists():
                oldest.unlink()
            for i in range(self._MAX_LOG_FILES - 1, 0, -1):
                src = self._log_path.parent / f"{self._log_path.name}.{i}"
                dst = self._log_path.parent / f"{self._log_path.name}.{i + 1}"
                if src.exists():
                    src.replace(dst)
            self._log_path.replace(
                self._log_path.parent / f"{self._log_path.name}.1")
        except Exception:
            pass  # 轮转失败不丢本条记录，下回再试

    def _write(self, record: dict) -> None:
        if not self._enabled:
            return
        record.setdefault("v", 1)
        record["ts"] = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            with self._lock:
                self._log_path.parent.mkdir(parents=True, exist_ok=True)
                if (self._log_path.exists()
                        and self._log_path.stat().st_size >= self._ROTATE_BYTES):
                    self._rotate_log()
                with open(self._log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            if not self._write_warned.is_set():
                self._write_warned.set()
                print(f"[observer] agent.log 写入失败: {e}", file=sys.stderr)
            # 日志绝不影响主流程

    # 校准样本下限（估算 token）：Agnes 等网关有每请求固定计数开销
    # （"Say OK" 也报 ~254 prompt），小样本的 实测/估算 比率被固定开销
    # 主导（实测可达 25×），EWMA 会被拉到失真——低于下限的样本不参与学习
    _CALIB_MIN_EST_IN = 400
    _CALIB_MIN_EST_OUT = 100

    def log_llm(self, provider: str, model: str, latency_ms: int,
                in_text: str, out_text: str, usage: dict | None,
                ok: bool, error: str = "", workspace: str = "") -> None:
        """LLM 调用记账。usage（prompt_tokens/completion_tokens）优先于估算。"""
        key = f"{provider}/{model}"
        est_flag = not usage
        if usage and usage.get("prompt_tokens") is not None:
            in_t = int(usage["prompt_tokens"])
            out_t = int(usage.get("completion_tokens") or 0)
            cache_hit = int(usage.get("cache_hit_tokens") or 0)
            base_in, base_out = est_tokens(in_text), est_tokens(out_text)
            if base_in >= self._CALIB_MIN_EST_IN:
                self._update_calib(key, in_t / base_in)
            if base_out >= self._CALIB_MIN_EST_OUT and out_t > 0:
                self._update_calib(key + ":out", out_t / base_out)
        else:
            in_t = round(est_tokens(in_text) * self._calib_ratio(key))
            out_t = round(est_tokens(out_text) * self._calib_ratio(key + ":out"))
            cache_hit = 0
        self._write({
            "kind": "llm", "provider": provider, "model": model,
            "task": _task_var.get(), "latency_ms": latency_ms,
            "in_tokens": in_t, "out_tokens": out_t,
            "cache_hit": cache_hit, "ws": workspace,
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

    def log_plan(self, action: str, args: dict, reason: str, ok: bool,
                 detail: str = "") -> None:
        """plan 决策记账（M5c §10）：JSON action + reason + 执行结果。"""
        try:
            args_s = json.dumps(args or {}, ensure_ascii=False)[:200]
        except Exception:
            args_s = str(args)[:200]
        self._write({"kind": "plan", "action": action, "args": args_s,
                     "reason": (reason or "")[:200], "ok": ok,
                     "detail": detail[:200]})

    def log_learning_metrics(self, concept_id: str,
                             indicator_a: float, indicator_b: float,
                             indicator_c: float, mastery_score: float,
                             bkt_prob: float = 0.0,
                             fsrs_interval: int = 0) -> None:
        """学习效果指标落盘（M1.3）：三指标 + BKT + FSRS 间隔。"""
        self._write({
            "kind": "metrics",
            "concept_id": concept_id,
            "indicator_a": round(indicator_a, 4),
            "indicator_b": round(indicator_b, 4),
            "indicator_c": round(indicator_c, 4),
            "mastery_score": round(mastery_score, 4),
            "bkt_prob": round(bkt_prob, 4),
            "fsrs_interval": fsrs_interval,
        })

    # ---- 聚合 ----

    def status(self) -> dict:
        with self._lock:
            return {"enabled": self._enabled,
                    "last_call": self._last_call,
                    "today": dict(self._today)}

    # 无 ws 字段的历史记录归属桶
    LEGACY_WS = "（旧记录）"

    def _peak_multiplier(self, ts: float) -> float:
        """按记录时间套峰谷倍率（[pricing.peak]，未配置恒 1）。
        时段只支持同日 [起, 止) 小时区间，不支持跨午夜。"""
        peak = self._config.get("pricing", {}).get("peak", {}) or {}
        mult = peak.get("multiplier", 1)
        hours = peak.get("hours", [])
        if not mult or mult == 1 or not hours:
            return 1
        hh = time.localtime(ts).tm_hour
        for span in hours:
            try:
                if int(span[0]) <= hh < int(span[1]):
                    return float(mult)
            except Exception:
                continue
        return 1

    def _record_cost(self, r: dict, pricing: dict) -> tuple[float, str]:
        """单条 llm 记录成本：未命中×input + 命中×cache_hit + 输出×output，
        再乘峰谷倍率。旧记录无 cache_hit 字段 → 全按未命中价（略高估）。"""
        price = pricing.get(r.get("model", ""))
        if not price or "input_per_million" not in price:
            return 0.0, ""
        hit = r.get("cache_hit", 0) or 0
        in_t = r.get("in_tokens", 0)
        cost = (max(0, in_t - hit) / 1e6 * price.get("input_per_million", 0)
                + hit / 1e6 * price.get("cache_hit_per_million",
                                        price.get("input_per_million", 0))
                + r.get("out_tokens", 0) / 1e6 * price.get("output_per_million", 0))
        try:
            ts = time.mktime(time.strptime(r["ts"], "%Y-%m-%d %H:%M:%S"))
            cost *= self._peak_multiplier(ts)
        except Exception:
            pass
        return cost, price.get("currency", "")

    def usage_summary(self, days: int = 7, ws: str = "") -> dict:
        """按 日×项目×渠道×模型×task 聚合 llm 记录；成本走 settings [pricing]
        （缓存命中分开计价 + 峰谷倍率，近似值）。ws 非空时只统计该项目。
        口径：today 随 ws 过滤（过滤视图下=该项目今日；顶栏胶囊的今日来自
        status()，是全工作区合计）；聚合窗口 ≤ 当前日志卷（轮转后的
        agent.log.1 不参与统计）。"""
        cutoff = time.time() - days * 86400 if days > 0 else 0
        pricing = self._config.get("pricing", {}) or {}
        try:
            lines = self._log_path.read_text(encoding="utf-8").splitlines()
        except Exception:
            lines = []
        groups: dict[tuple, dict] = {}
        by_ws: dict[str, dict] = {}
        by_model: dict[str, dict] = {}
        by_task: dict[str, dict] = {}
        daily: dict[str, dict] = {}
        ws_seen: set[str] = set()
        today_s = time.strftime("%Y-%m-%d")
        today = {"calls": 0, "in_tokens": 0, "out_tokens": 0, "cost": 0.0,
                 "costs_by_currency": {}}

        def _acc(bucket: dict, key: str, r: dict, cost: float,
                 currency: str) -> None:
            g = bucket.setdefault(key, {"calls": 0, "failures": 0,
                                        "in_tokens": 0, "out_tokens": 0,
                                        "cost": 0.0,
                                        "costs_by_currency": {}})
            g["calls"] += 1
            g["failures"] += 0 if r.get("ok") else 1
            g["in_tokens"] += r.get("in_tokens", 0)
            g["out_tokens"] += r.get("out_tokens", 0)
            g["cost"] += cost
            if currency:
                g["costs_by_currency"][currency] = (
                    g["costs_by_currency"].get(currency, 0.0) + cost)

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
            rec_ws = r.get("ws") or self.LEGACY_WS
            ws_seen.add(rec_ws)
            if ws and rec_ws != ws:
                continue
            cost, currency = self._record_cost(r, pricing)
            day = r["ts"][:10]
            k = (day, rec_ws, r.get("provider", "?"), r.get("model", "?"),
                 r.get("task", "?"))
            g = groups.setdefault(k, {
                "date": day, "ws": rec_ws, "provider": k[2], "model": k[3],
                "task": k[4], "calls": 0, "failures": 0, "in_tokens": 0,
                "out_tokens": 0, "cache_hit": 0, "est_calls": 0,
                "cost": 0.0, "currency": ""})
            g["calls"] += 1
            g["failures"] += 0 if r.get("ok") else 1
            g["in_tokens"] += r.get("in_tokens", 0)
            g["out_tokens"] += r.get("out_tokens", 0)
            g["cache_hit"] += r.get("cache_hit", 0) or 0
            g["est_calls"] += 1 if r.get("tokens_est") else 0
            g["cost"] += cost
            g["currency"] = g["currency"] or currency
            if currency:
                g.setdefault("costs_by_currency", {})
                g["costs_by_currency"][currency] = (
                    g["costs_by_currency"].get(currency, 0.0) + cost)
            _acc(by_ws, rec_ws, r, cost, currency)
            _acc(by_model, r.get("model", "?"), r, cost, currency)
            _acc(by_task, r.get("task", "?"), r, cost, currency)
            d = daily.setdefault(day, {"date": day, "in_tokens": 0,
                                       "out_tokens": 0})
            d["in_tokens"] += r.get("in_tokens", 0)
            d["out_tokens"] += r.get("out_tokens", 0)
            if day == today_s:
                today["calls"] += 1
                today["in_tokens"] += r.get("in_tokens", 0)
                today["out_tokens"] += r.get("out_tokens", 0)
                today["cost"] += cost
                if currency:
                    today["costs_by_currency"][currency] = (
                        today["costs_by_currency"].get(currency, 0.0) + cost)

        def _rows(bucket: dict, name_key: str) -> list[dict]:
            out = []
            for name, g in bucket.items():
                row = {name_key: name, **g}
                row["cost"] = round(row["cost"], 4)
                row["costs_by_currency"] = {
                    c: round(v, 4) for c, v in row["costs_by_currency"].items()}
                out.append(row)
            return sorted(out, key=lambda x: -x["cost"])

        rows = sorted(groups.values(),
                      key=lambda g: (g["date"], g["ws"], g["provider"], g["task"]))
        total_in = sum(g["in_tokens"] for g in rows)
        total_out = sum(g["out_tokens"] for g in rows)
        total_hit = sum(g["cache_hit"] for g in rows)
        total_calls = sum(g["calls"] for g in rows)
        # 汇总 costs_by_currency
        total_currencies: dict[str, float] = {}
        for g in rows:
            for cur, v in g.get("costs_by_currency", {}).items():
                total_currencies[cur] = total_currencies.get(cur, 0.0) + v
        totals = {"calls": total_calls,
                  "failures": sum(g["failures"] for g in rows),
                  "in_tokens": total_in, "out_tokens": total_out,
                  "cache_hit": total_hit,
                  "cost": round(sum(g["cost"] for g in rows), 4),
                  "costs_by_currency": {c: round(v, 4)
                                        for c, v in total_currencies.items()}}
        for g in rows:
            g["cost"] = round(g["cost"], 4)
            g["costs_by_currency"] = {
                c: round(v, 4) for c, v in g.get("costs_by_currency", {}).items()}
        return {
            "rows": rows, "totals": totals, "days": days,
            "log_path": str(self._log_path),
            "workspaces": sorted(ws_seen),
            "kpi": {"calls": total_calls, "in_tokens": total_in,
                    "out_tokens": total_out, "cost": totals["cost"],
                    "costs_by_currency": totals["costs_by_currency"],
                    "cache_hit_rate": (round(total_hit / total_in, 4)
                                       if total_in else None),
                    "fail_rate": (round(totals["failures"] / total_calls, 4)
                                  if total_calls else None)},
            "daily": [daily[d] for d in sorted(daily)],
            "today": {"calls": today["calls"], "in_tokens": today["in_tokens"],
                      "out_tokens": today["out_tokens"],
                      "cost": round(today["cost"], 4),
                      "costs_by_currency": {
                          c: round(v, 4) for c, v in today["costs_by_currency"].items()}},
            "by_workspace": _rows(by_ws, "ws"),
            "by_model": _rows(by_model, "model"),
            "by_task": _rows(by_task, "task"),
        }


_OBSERVERS: dict[str, Observer] = {}


def get_observer(config: ConfigService) -> Observer:
    """按配置文件路径缓存的进程级单例。"""
    key = str(config.path)
    if key not in _OBSERVERS:
        _OBSERVERS[key] = Observer(config)
    return _OBSERVERS[key]


def get_log_path(config: ConfigService | None = None) -> Path:
    """返回 agent.log 的绝对路径（供日志分析器使用）。"""
    if config is None:
        config = get_config()
    raw = config.get("agent_log_path", "")
    if raw:
        return (WEB_ROOT / raw).resolve()
    return runtime_dir(config) / "agent.log"


def log_prefetch(config: ConfigService, sources: list[str]) -> None:
    """备课预取记账（tool 类）。"""
    get_observer(config).log_tool("prefetch", bool(sources), ",".join(sources))
