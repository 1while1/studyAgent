"""学习者模型服务（M3）：concepts 注册、evidence 写入、mastery 读取、迁移。

数据单源（工作区 docx_dir，规则 14 落盘）：
- `concepts.json`（schema_version=1）：{id, title, prerequisites[], materials[], code_refs[]}
- `learner_model.json`（schema_version=1）：concept → {title, mastery(冗余缓存),
  evidence[], last_review_day, review_due[]}；**mastery 读取时按衰减公式重算为准**
- `notes.json`（schema_version=1）：M3 仅迁移产物（卡壳/疑问条目，M4 做笔记层）

concept id 代码铸造（Day{N}-{单元id}）；prerequisites = 天内链 + 跨天链
（Study.md 天数顺序确定性边）；evidence 的 delta 写入时查 settings
[evidence_delta] 表定死，LLM 只选类型；source_ref 幂等去重。
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from .config_service import ConfigService
from .repository import JsonRepository
from ..domain.learner import (compute_mastery, concept_id, is_due,
                              review_interval, topo_order, upstream_closure)
from ..engine.learning_metrics import (
    bkt_mastery, fsrs_interval_from_evidence, compute_learning_metrics,
    LearningMetrics, BKT_DEFAULT_PARAMS,
)

SCHEMA_VERSION = 1


def _empty_model() -> dict:
    return {"schema_version": SCHEMA_VERSION, "concepts": {}}


class LearnerService:
    def __init__(self, config: ConfigService):
        self._config = config
        docx_dir = Path(config.docx_dir) if config else Path(".")
        self._repo = JsonRepository(docx_dir)
        # 保留 path 属性以兼容外部引用
        self.concepts_path = docx_dir / "concepts.json"
        self.model_path = docx_dir / "learner_model.json"
        self.notes_path = docx_dir / "notes.json"
        self.draft_path = docx_dir / "learner_model.migration-draft.json"

    # ---- 读写 ----

    def _load_json(self, path, default):
        """通过 JsonRepository 加载，保留损坏备份与 observer 记账。"""
        key = path.stem
        try:
            data = self._repo.load(key)
            return data if data is not None else default
        except Exception as e:
            try:
                import shutil
                bak = path.with_suffix(path.suffix + ".corrupt.bak")
                shutil.copy2(path, bak)
            except Exception:
                pass
            from .observer import get_observer
            get_observer(self._config).log_tool(
                "silent_learner_load", False, f"{path.name}: {repr(e)[:200]}")
            return default

    def _save(self, files: dict) -> None:
        """兼容旧接口；新代码应直接调用 self._repo.save()。"""
        for path, content_str in files.items():
            data = json.loads(content_str)
            self._repo.save(path.stem, data)

    def _deltas(self) -> dict:
        return self._config.get("evidence_delta", {}) or {}

    def _half_life(self) -> float:
        return float(self._config.get("model_half_life_days", 14))

    def _cap(self) -> float:
        return float(self._config.get("mastery_cap_without_code", 0.6))

    # ---- concepts 注册 ----

    def ensure_concepts(self, state: dict,
                        materials_map: dict[str, list[str]] | None = None
                        ) -> bool:
        """从 StudyState 全部 days 扫描 upsert concepts（确定性 id 与先修边）。"""
        concepts = self._load_json(self.concepts_path,
                                   {"schema_version": SCHEMA_VERSION,
                                    "concepts": {}})
        cmap = concepts["concepts"]
        changed = False
        ordered_days = sorted(state.get("days", {}).items(),
                              key=lambda kv: int(kv[0]))
        prev_last: str | None = None
        for day_key, day_data in ordered_days:
            day_n = int(day_key)
            prev_in_day: str | None = prev_last
            for unit in day_data.get("units", []):
                cid = concept_id(day_n, unit["id"])
                entry = cmap.get(cid)
                if entry is None:
                    entry = {"id": cid, "title": unit.get("title", ""),
                             "prerequisites": [], "materials": [],
                             "code_refs": []}
                    cmap[cid] = entry
                    changed = True
                if unit.get("title") and entry["title"] != unit["title"]:
                    entry["title"] = unit["title"]
                    changed = True
                if prev_in_day and prev_in_day not in entry["prerequisites"]:
                    entry["prerequisites"].append(prev_in_day)
                    changed = True
                mats = (materials_map or {}).get(cid)
                if mats:
                    merged = sorted(set(entry["materials"]) | set(mats))
                    if merged != entry["materials"]:
                        entry["materials"] = merged
                        changed = True
                prev_in_day = cid
            if day_data.get("units"):
                prev_last = prev_in_day
        if changed:
            concepts["schema_version"] = SCHEMA_VERSION
            self._save({self.concepts_path: json.dumps(
                concepts, ensure_ascii=False, indent=2)})
        return changed

    # ---- evidence 写入 ----

    def add_evidence(self, cid: str, etype: str, source_ref: str,
                     day: int, latency_s: float | None = None,
                     error_pattern_major: str | None = None,
                     error_pattern_minor: str | None = None) -> bool:
        """写入证据（source_ref 幂等）。返回是否真正写入。

        error_pattern_major / error_pattern_minor 为可选错误分类（M1.1）。
        """
        delta = self._deltas().get(etype)
        if delta is None:
            return False
        model = self._load_json(self.model_path, _empty_model())
        entry = model["concepts"].setdefault(cid, {
            "title": cid, "mastery": 0.0, "evidence": [],
            "last_review_day": 0, "review_due": []})
        if any(ev.get("source_ref") == source_ref for ev in entry["evidence"]):
            return False
        ev = {"type": etype, "source_ref": source_ref, "delta": delta,
              "ts": date.today().isoformat()}
        if latency_s is not None:
            ev["latency_s"] = latency_s
        if error_pattern_major is not None:
            ev["error_pattern_major"] = error_pattern_major
        if error_pattern_minor is not None:
            ev["error_pattern_minor"] = error_pattern_minor
        entry["evidence"].append(ev)
        mastery, _, _ = compute_mastery(
            entry["evidence"], date.today(), self._half_life(), self._cap())
        entry["mastery"] = round(mastery, 4)
        entry["last_review_day"] = day
        entry["review_due"] = [day + review_interval(mastery)]
        model["schema_version"] = SCHEMA_VERSION
        self._save({self.model_path: json.dumps(
            model, ensure_ascii=False, indent=2)})
        return True

    def record_quiz(self, day: int, unit_id: str, score: float) -> bool:
        """单元终期评分 → quiz 证据。"""
        passed = score >= float(self._config.get("mastery_pass_score", 3.0))
        etype = "quiz_right" if passed else "quiz_wrong"
        return self.add_evidence(concept_id(day, unit_id), etype,
                                 f"Day{day}-{unit_id}:quiz", day)

    def record_review(self, day: int, units: list[dict], score: float) -> int:
        """复盘评分 → 当日每单元一条 quiz 类证据。返回写入条数。"""
        passed = score >= float(self._config.get("mastery_pass_score", 3.0))
        etype = "quiz_right" if passed else "quiz_wrong"
        n = 0
        for u in units:
            if self.add_evidence(concept_id(day, u["id"]), etype,
                                 f"Day{day}-{u['id']}:review", day):
                n += 1
        return n

    def record_sync(self, day: int, unit_id: str | None, etype: str) -> bool:
        """[同步] 已掌握/卡壳 → sync 证据（同单元同类型幂等）。"""
        if not unit_id:
            return False
        kind = "mastered" if etype == "sync_mastered" else "stuck"
        return self.add_evidence(concept_id(day, unit_id), etype,
                                 f"Day{day}-{unit_id}:sync:{kind}", day)

    def record_verify(self, day: int, unit_id: str | None, passed: bool
                      ) -> bool:
        """[验证代码] 结果 → code_verify 证据（每日每单元一次）。"""
        if not unit_id:
            return False
        etype = "code_verify_pass" if passed else "code_verify_fail"
        ref = f"Day{day}-{unit_id}:verify:{date.today().isoformat()}"
        return self.add_evidence(concept_id(day, unit_id), etype, ref, day)

    # ---- BKT / FSRS / 学习效果度量（M1.3） ----

    def _bkt_params(self) -> dict:
        """从 settings.toml 读取 BKT 参数，缺失则用默认值。"""
        cfg = self._config.get("bkt_params", {}) or {}
        return {**BKT_DEFAULT_PARAMS, **cfg}

    def compute_bkt_mastery(self, cid: str) -> float:
        """计算指定 concept 的 BKT 掌握概率（纯读取，不写盘）。"""
        model = self._load_json(self.model_path, _empty_model())["concepts"]
        entry = model.get(cid, {})
        evidence = entry.get("evidence", [])
        return bkt_mastery(evidence, self._bkt_params())

    def compute_concept_metrics(self, cid: str, current_day: int) -> LearningMetrics:
        """计算指定 concept 的三指标学习效果度量。"""
        concepts = self._load_json(self.concepts_path,
                                   {"schema_version": SCHEMA_VERSION,
                                    "concepts": {}})["concepts"]
        model = self._load_json(self.model_path, _empty_model())["concepts"]
        entry = model.get(cid, {})
        evidence = entry.get("evidence", [])

        # 总天数：从 concept id 解析或取 1
        m = re.match(r"Day(\d+)-", cid)
        start_day = int(m.group(1)) if m else current_day
        total_days = max(1, current_day - start_day + 1)

        # quiz 结果
        quiz_results = [
            {"date": ev.get("ts", ""), "score": ev.get("delta", 0) * 5}
            for ev in evidence
            if ev.get("type") in ("quiz_right", "quiz_wrong", "quiz_score")
        ]
        has_code = any(ev.get("type") in ("code_verify_pass", "code_verify_fail")
                       for ev in evidence)
        code_pass = any(ev.get("type") == "code_verify_pass" for ev in evidence)

        weights_cfg = self._config.get("metrics_weights", (0.3, 0.3, 0.4))
        weights = tuple(weights_cfg) if len(weights_cfg) == 3 else (0.3, 0.3, 0.4)
        return compute_learning_metrics(
            concept_id=cid,
            evidence_list=evidence,
            total_days=total_days,
            quiz_results=quiz_results,
            code_verify_pass=code_pass,
            has_code_concept=has_code,
            weights=weights,
        )

    def compute_fsrs_interval(self, cid: str) -> dict:
        """计算指定 concept 的 FSRS 下次复习间隔。"""
        model = self._load_json(self.model_path, _empty_model())["concepts"]
        entry = model.get(cid, {})
        evidence = entry.get("evidence", [])
        return fsrs_interval_from_evidence(evidence)

    def get_consecutive_errors(self, concept_id: str) -> list[str]:
        """获取最近连续错误的错误模式列表（M1.2 教学行动策略输入）。

        从 evidence 列表末尾向前扫描，收集连续 quiz_wrong / quiz_score 负分
        证据的 error_pattern_major 值。遇到非错误证据即停止。

        Returns:
            错误模式 major 值列表（时间倒序），无连续错误返回 []
        """
        model = self._load_json(self.model_path, _empty_model())["concepts"]
        entry = model.get(concept_id, {})
        evidence = entry.get("evidence", [])
        patterns: list[str] = []
        # 从末尾向前扫描
        for ev in reversed(evidence):
            etype = ev.get("type", "")
            # quiz_wrong 一定是错误；quiz_score 负分也算错误
            is_error = (etype == "quiz_wrong"
                        or (etype == "quiz_score" and ev.get("delta", 0) < 0))
            if not is_error:
                break
            major = ev.get("error_pattern_major")
            if major:
                patterns.append(major)
        return patterns

    # ---- 读取 ----

    def get_model(self, current_day: int) -> dict:
        """热力图数据：每 concept 计算实时 mastery（含封顶与到期判定）。"""
        concepts = self._load_json(self.concepts_path,
                                   {"schema_version": SCHEMA_VERSION,
                                    "concepts": {}})["concepts"]
        model = self._load_json(self.model_path, _empty_model())["concepts"]
        today = date.today()

        def sort_key(cid: str):
            m = re.match(r"Day(\d+)-(.+)", cid)
            return (int(m.group(1)), m.group(2)) if m else (9999, cid)

        out = []
        for cid in sorted(set(concepts) | set(model), key=sort_key):
            centry = concepts.get(cid, {})
            mentry = model.get(cid, {})
            evidence = mentry.get("evidence", [])
            mastery, uncapped, capped = compute_mastery(
                evidence, today, self._half_life(), self._cap())
            due_days = mentry.get("review_due", [])
            out.append({
                "id": cid,
                "title": mentry.get("title") or centry.get("title") or cid,
                "prerequisites": centry.get("prerequisites", []),
                "materials": centry.get("materials", []),
                "mastery": round(mastery, 4),
                "uncapped": round(uncapped, 4),
                "capped": capped,
                "has_code_pass": any(ev.get("type") == "code_verify_pass"
                                     for ev in evidence),
                "review_due": due_days,
                "due": is_due(due_days, current_day),
                "evidence": evidence,
            })
        return {"concepts": out, "current_day": current_day,
                "exists": self.model_path.exists(),
                "has_ratings_source": False}  # 由路由按 StudyState 补充

    # ---- 图谱查询（M7 §4：复习感召与拓扑补弱的图基础） ----

    def _prereq_map(self) -> dict[str, list[str]]:
        concepts = self._load_json(
            self.concepts_path,
            {"schema_version": SCHEMA_VERSION, "concepts": {}})["concepts"]
        return {cid: c.get("prerequisites", []) for cid, c in concepts.items()}

    def _mastery_by_id(self, current_day: int) -> dict[str, dict]:
        """cid → {title, mastery, has_evidence}（get_model 同口径实时重算）。"""
        return {c["id"]: {"title": c.get("title", c["id"]),
                          "mastery": c.get("mastery", 0.0),
                          "has_evidence": bool(c.get("evidence"))}
                for c in self.get_model(current_day)["concepts"]}

    def upstream_chain(self, cid: str) -> list[str]:
        """cid 的传递上游闭包（根基在前、近邻在后）。"""
        return upstream_closure(cid, self._prereq_map())

    def unmastered_upstream(self, cids: list[str], current_day: int,
                            threshold: float = 0.7) -> list[dict]:
        """给定节点的上游未达标链（拓扑序，根基先补；**含零证据节点**——
        先修诊断"已会节点置初始 mastery"的核心场景）。

        返回 [{cid, title, mastery, has_evidence, prereq_of}]，prereq_of 记录
        它是哪个目标节点的上游（取最近的一个目标）。
        """
        pmap = self._prereq_map()
        nearest: dict[str, str] = {}
        pooled: set[str] = set()
        for cid in cids:
            for u in upstream_closure(cid, pmap):
                pooled.add(u)
                nearest.setdefault(u, cid)
        view = self._mastery_by_id(current_day)
        out = []
        for cid in topo_order(pooled, pmap):
            info = view.get(cid)
            if info is None or info["mastery"] >= threshold:
                continue
            out.append({"cid": cid, "title": info["title"],
                        "mastery": info["mastery"],
                        "has_evidence": info["has_evidence"],
                        "prereq_of": nearest.get(cid, "")})
        return out

    def remediation_order(self, current_day: int,
                          threshold: float = 0.7) -> list[str]:
        """全部**有证据且未达标** concept 的拓扑补弱序（上游先补，§13 拓扑计划 v1）。

        零证据节点不计入（标「未学」而非「未达标」，M5b R4 先例）。
        """
        model = self.get_model(current_day)["concepts"]
        weak = [c["id"] for c in model
                if c.get("evidence") and c.get("mastery", 0) < threshold]
        return topo_order(weak, self._prereq_map())

    # ---- 迁移（草稿 + 人审） ----

    def migrate_preview(self, state: dict,
                        memory_by_day: dict[int, str]) -> dict:
        """旧数据 → 迁移草稿（不写正式库）。

        ratings → quiz_score 证据（delta = rating/5 映射初值，ts = 学习日期）；
        卡壳/疑问散文 → notes 条目（status:open, needs_review:true，禁止直转证据）。
        """
        quiz = []
        for day_key, day_data in sorted(state.get("days", {}).items(),
                                        key=lambda kv: int(kv[0])):
            day_n = int(day_key)
            ts = day_data.get("date") or date.today().isoformat()
            for unit in day_data.get("units", []):
                rating = float(unit.get("rating") or 0)
                if rating <= 0:
                    continue
                cid = concept_id(day_n, unit["id"])
                quiz.append({
                    "concept_id": cid, "title": unit.get("title", ""),
                    "evidence": {
                        "type": "quiz_score",
                        "source_ref": f"migrate:Day{day_n}-{unit['id']}:rating",
                        "delta": round(rating / 5, 4), "ts": ts}})
        notes = []
        for day_n, content in sorted(memory_by_day.items()):
            for kind, label in (("stuck", "卡壳"), ("question", "疑问")):
                m = re.search(rf"^- {label}：(.+)$", content, re.MULTILINE)
                if not m:
                    continue
                text = m.group(1).strip()
                if text in ("无", "无。", ""):
                    continue
                notes.append({
                    "id": f"migrate-Day{day_n}-{kind}",
                    "kind": kind, "text": text, "status": "open",
                    "needs_review": True, "concept_id": "",
                    "source_ref": f"migrate:Day{day_n}:{kind}"})
        draft = {"quiz_scores": quiz, "notes": notes}
        self._save({self.draft_path: json.dumps(
            draft, ensure_ascii=False, indent=2)})
        return {"quiz_scores": len(quiz), "notes": len(notes),
                "draft_path": str(self.draft_path)}

    def migrate_apply(self) -> dict:
        """应用草稿：落 learner_model.json + notes.json。已有模型拒绝（幂等）。"""
        if self.model_path.exists():
            return {"ok": False, "error": "learner_model.json 已存在，禁止重复迁移"}
        draft = self._load_json(self.draft_path, None)
        if not draft:
            return {"ok": False, "error": "迁移草稿不存在，请先生成预览"}
        model = _empty_model()
        today = date.today()
        for item in draft.get("quiz_scores", []):
            cid = item["concept_id"]
            entry = model["concepts"].setdefault(cid, {
                "title": item.get("title", cid), "mastery": 0.0,
                "evidence": [], "last_review_day": 0, "review_due": []})
            entry["evidence"].append(item["evidence"])
        m = re.compile(r"Day(\d+)-")
        for cid, entry in model["concepts"].items():
            mastery, _, _ = compute_mastery(
                entry["evidence"], today, self._half_life(), self._cap())
            entry["mastery"] = round(mastery, 4)
            day_n = int(m.match(cid).group(1)) if m.match(cid) else 0
            entry["last_review_day"] = day_n
            entry["review_due"] = [day_n + review_interval(mastery)]
        notes = {"schema_version": SCHEMA_VERSION,
                 "notes": draft.get("notes", [])}
        self._save({self.model_path: json.dumps(
            model, ensure_ascii=False, indent=2),
            self.notes_path: json.dumps(notes, ensure_ascii=False, indent=2)})
        return {"ok": True, "concepts": len(model["concepts"]),
                "notes": len(notes["notes"])}
