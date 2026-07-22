"""Study state consistency validator（study-web 内置版）.

校验 StudyState.json（单一事实源）与 StudyMemory/Day_<NN>.md、Study.md 之间的一致性。
规则见 resources/sop/_GLOBAL_RULES.md 规则 4（状态枚举 / WAL）与规则 14（验证 Hook）。

由 engine/hooks/validate_hook.py 调用：main(docx_dir, total_days, replica_name)。
也可 CLI 直接运行：python validate_study.py <docx_dir> [total_days] [replica_name]

退出码：0 = 通过（允许有警告）；1 = 校验失败。无第三方依赖。
"""

import datetime
import json
import os
import re
import sys

VALID_STATUSES = {"not_started", "in_progress", "completed", "postponed"}

DAY_FILE_RE = re.compile(r"^Day_(\d+)\.md$")

# 运行期参数（由 main() 注入）
TOTAL_DAYS = 25
REQUIRED_MD_HEADERS: list[str] = []

errors = []
warnings = []


def err(msg):
    errors.append(msg)


def warn(msg):
    warnings.append(msg)


def load_state(docx_dir):
    state_json_path = os.path.join(docx_dir, "StudyState.json")
    if not os.path.exists(state_json_path):
        err(f"StudyState.json not found at {state_json_path}")
        return None
    try:
        with open(state_json_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        err(f"Failed to parse StudyState.json: {e}")
        return None


def check_current_day(state):
    raw = state.get("current_day")
    try:
        current_day = int(str(raw))
    except (TypeError, ValueError):
        err(f"current_day is not a valid integer: {raw!r}")
        return None
    if not 1 <= current_day <= TOTAL_DAYS:
        err(f"current_day out of range 1-{TOTAL_DAYS}: {current_day}")
        return None
    return current_day


def check_last_active_date(state):
    raw = state.get("last_active_date")
    if not raw:
        err("last_active_date missing in StudyState.json")
        return
    try:
        datetime.datetime.strptime(str(raw), "%Y-%m-%d")
    except ValueError:
        err(f"last_active_date is not a valid YYYY-MM-DD date: {raw!r}")


def check_units_schema(state):
    days = state.get("days")
    if not isinstance(days, dict):
        err("StudyState.json: 'days' must be an object")
        return
    for day_key, day_data in days.items():
        units = day_data.get("units", [])
        if not isinstance(units, list):
            err(f"Day {day_key}: 'units' must be a list")
            continue
        for unit in units:
            uid = unit.get("id", "?")
            status = unit.get("status")
            if status not in VALID_STATUSES:
                err(f"Day {day_key} unit {uid}: invalid status {status!r} "
                    f"(allowed: {sorted(VALID_STATUSES)})")
            if status == "completed":
                rating = unit.get("rating")
                if not isinstance(rating, (int, float)) or rating <= 0:
                    err(f"Day {day_key} unit {uid}: completed but rating is {rating!r}")


def check_memory_dir_naming(docx_dir):
    mem_dir = os.path.join(docx_dir, "StudyMemory")
    if not os.path.isdir(mem_dir):
        err(f"StudyMemory directory not found: {mem_dir}")
        return
    seen = {}
    for name in sorted(os.listdir(mem_dir)):
        full = os.path.join(mem_dir, name)
        if os.path.isdir(full):
            continue
        m = DAY_FILE_RE.match(name)
        if m:
            nn = int(m.group(1))
            if nn in seen:
                err(f"Duplicate StudyMemory files for Day {nn}: "
                    f"'{seen[nn]}' and '{name}' (keep only zero-padded Day_<NN>.md, "
                    f"move leftovers to archive/)")
            else:
                seen[nn] = name
        elif name.endswith(".md"):
            warn(f"Non-standard file in StudyMemory (should be archived): {name}")


def find_day_md(docx_dir, current_day):
    mem_dir = os.path.join(docx_dir, "StudyMemory")
    padded = os.path.join(mem_dir, f"Day_{current_day:02d}.md")
    unpadded = os.path.join(mem_dir, f"Day_{current_day}.md")
    if os.path.exists(padded):
        return padded
    if os.path.exists(unpadded):
        warn(f"StudyMemory file for Day {current_day} is not zero-padded: "
             f"Day_{current_day}.md (rename to Day_{current_day:02d}.md)")
        return unpadded
    err(f"StudyMemory markdown file not found: checked {padded} and {unpadded}")
    return None


def parse_md(md_path):
    with open(md_path, "r", encoding="utf-8") as f:
        content = f.read()
    md_units = {}
    md_scores = {}
    for line in content.splitlines():
        m = re.match(r"^\s*-\s*\[([ xX])\]\s*单元([A-Za-z0-9_]+)[:：]", line)
        if m:
            md_units[m.group(2)] = m.group(1).lower() == "x"
        m = re.match(r"^\s*-\s*单元([A-Za-z0-9_]+)[:：]\s*(\d+(?:\.\d+)?)分", line)
        if m:
            md_scores[m.group(1)] = float(m.group(2))
    return content, md_units, md_scores


def check_day_consistency(state, current_day, docx_dir):
    day_data = state.get("days", {}).get(str(current_day))
    if not day_data:
        err(f"Day {current_day} data not found in StudyState.json")
        return
    md_path = find_day_md(docx_dir, current_day)
    if not md_path:
        return
    content, md_units, md_scores = parse_md(md_path)

    for header in REQUIRED_MD_HEADERS:
        if header not in content:
            err(f"Missing required section '{header}' in {os.path.basename(md_path)}")

    json_units = day_data.get("units", [])
    json_ids = set()
    for unit in json_units:
        uid = unit.get("id")
        status = unit.get("status")
        title = unit.get("title")
        json_ids.add(uid)
        if uid not in md_units:
            err(f"Unit {uid} ('{title}') present in JSON but missing in MD list")
            continue
        checked = md_units[uid]
        if status == "completed":
            if not checked:
                err(f"Consistency error: Unit {uid} is completed in JSON "
                    f"but unchecked ([ ]) in MD")
            score = md_scores.get(uid, 0)
            if score == 0:
                err(f"Validation failed: Unit {uid} is completed but score "
                    f"in MD is 0分 or missing")
            else:
                rating = unit.get("rating")
                if isinstance(rating, (int, float)) and abs(score - float(rating)) > 1e-9:
                    err(f"Score mismatch: Unit {uid} MD score {score}分 "
                        f"!= JSON rating {rating}")
        elif status in VALID_STATUSES:
            if checked:
                err(f"Consistency error: Unit {uid} is {status} in JSON "
                    f"but checked ([x]) in MD")

    for uid in md_units:
        if uid not in json_ids:
            warn(f"Unit {uid} present in MD but missing in JSON days['{current_day}'].units")


def check_study_md(state, current_day, docx_dir):
    study_path = os.path.join(docx_dir, "Study.md")
    if not os.path.exists(study_path):
        warn("Study.md not found; skipping Study.md consistency checks")
        return
    with open(study_path, "r", encoding="utf-8") as f:
        content = f.read()
    m = re.search(r"当前天数：Day\s*(\d+)", content)
    if not m:
        err("Study.md: header line '当前天数：Day X' not found")
    elif int(m.group(1)) != current_day:
        err(f"Study.md says 当前天数 Day {m.group(1)} "
            f"but JSON current_day is {current_day}")

    days = state.get("days", {})
    completed_days = sum(
        1 for d in days.values()
        if d.get("review_completed") or d.get("active_day_completed")
    )
    expected = round(completed_days * 100 / TOTAL_DAYS)
    actual = state.get("overall_completion_percentage")
    if actual != expected:
        err(f"overall_completion_percentage is {actual} "
            f"but {completed_days} completed day(s) => expected {expected}")
    m = re.search(r"整体完成度：(\d+(?:\.\d+)?)%", content)
    if not m:
        warn("Study.md: header line '整体完成度：X%' not found")
    elif float(m.group(1)) != float(expected):
        err(f"Study.md 整体完成度 is {m.group(1)}% but expected {expected}%")


def main(docx_dir, total_days=25, replica_name="replica"):
    """校验入口。docx_dir = 工作区学习数据目录（含 StudyState.json 等）。"""
    global TOTAL_DAYS, REQUIRED_MD_HEADERS, errors, warnings
    TOTAL_DAYS = int(total_days)
    REQUIRED_MD_HEADERS = [
        "### 今日导学单元",
        "### [同步] 记录",
        "### 掌握度评分",
        f"### {replica_name} 进度",
        "### AI 拷打评语",
    ]
    errors, warnings = [], []

    docx_dir = os.path.abspath(str(docx_dir))
    state = load_state(docx_dir)
    if state is not None:
        current_day = check_current_day(state)
        check_last_active_date(state)
        check_units_schema(state)
        check_memory_dir_naming(docx_dir)
        if current_day is not None:
            check_day_consistency(state, current_day, docx_dir)
            check_study_md(state, current_day, docx_dir)

    for msg in warnings:
        print(f"[WARNING] {msg}", file=sys.stderr)
    for msg in errors:
        print(f"[VALIDATION ERROR] {msg}", file=sys.stderr)

    if errors:
        print(f"[FAILED] {len(errors)} error(s), {len(warnings)} warning(s).")
        return 1
    print(f"[SUCCESS] Study state validation hook passed successfully. "
          f"({len(warnings)} warning(s))")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: validate_study.py <docx_dir> [total_days] [replica_name]")
        sys.exit(2)
    sys.exit(main(
        sys.argv[1],
        int(sys.argv[2]) if len(sys.argv) > 2 else 25,
        sys.argv[3] if len(sys.argv) > 3 else "replica",
    ))
