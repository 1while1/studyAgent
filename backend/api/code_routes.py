"""代码浏览器 + 进程管理路由：/api/code/* /api/demo/* /api/processes/*。"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from ..services.code_browser import CodeBrowser, CodeBrowserError
from ..services.config_writer import update_code_roots
from ..services.process_mgr import ProcessError, ProcessManager, split_cmd
from ..services.workshop_service import WorkshopError, WorkshopService

code_router = APIRouter(tags=["代码浏览器"])


def _deps():
    """延迟读 routes._deps（避免循环导入初始化顺序问题）。"""
    from . import routes
    return routes._deps


def _code_browser() -> CodeBrowser:
    return CodeBrowser(_deps().config)


def _workshop() -> WorkshopService:
    return WorkshopService(_deps().config)


def _process_mgr() -> ProcessManager:
    return ProcessManager(_deps().config)


# ---------- 代码浏览器 ----------

@code_router.get("/api/code/roots")
def code_roots():
    return {"roots": _code_browser().roots()}


@code_router.post("/api/code/roots")
def add_code_root(body: dict):
    deps = _deps()
    name = (body or {}).get("name", "").strip()
    raw_path = (body or {}).get("path", "").strip()
    if not name or not raw_path:
        return {"ok": False, "error": "name 和 path 不能为空"}
    # C3：名称白名单（XSS 防线——name 会进 settings 并回显到前端 DOM）
    import re as _re
    if not _re.fullmatch(r"[A-Za-z0-9_-]{1,40}", name):
        return {"ok": False,
                "error": "项目根名称仅限字母/数字/_/-（≤40 字符）"}
    if any(r["name"] == name for r in deps.config.code_roots):
        return {"ok": False, "error": f"项目根已存在: {name}"}
    all_roots = list(deps.config.data.get("code_roots", []))
    new_roots = all_roots + [{"name": name, "path": raw_path,
                              "workspace": deps.config.workspace.slug}]
    try:
        cb = CodeBrowser(deps.config)
        from ..services.config_service import WEB_ROOT
        from pathlib import Path as _P
        p = _P(raw_path) if _P(raw_path).is_absolute() else (WEB_ROOT / raw_path).resolve()
        if not p.is_dir():
            return {"ok": False, "error": f"目录不存在: {raw_path}"}
        update_code_roots(deps.config.path, new_roots)
        deps.config.reload()
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}
    return {"ok": True, "roots": _code_browser().roots()}


@code_router.post("/api/code/roots/delete")
def delete_code_root(body: dict):
    deps = _deps()
    name = (body or {}).get("name", "").strip()
    all_roots = list(deps.config.data.get("code_roots", []))
    slug = deps.config.workspace.slug
    new_roots = [r for r in all_roots
                 if not (r["name"] == name and r.get("workspace", slug) == slug)]
    if len(new_roots) == len(all_roots):
        return {"ok": False, "error": f"项目根不存在: {name}"}
    try:
        update_code_roots(deps.config.path, new_roots)
        deps.config.reload()
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}
    return {"ok": True, "roots": _code_browser().roots()}


@code_router.get("/api/code/tree")
def code_tree(root: str, path: str = ""):
    try:
        return {"ok": True, "entries": _code_browser().list_dir(root, path)}
    except CodeBrowserError as e:
        return {"ok": False, "error": str(e)}


@code_router.get("/api/code/file")
def code_file(root: str, path: str):
    try:
        data = _code_browser().read_file(root, path)
        data["editable"] = _workshop().editable(root, path)
        data["mtime"] = _workshop().file_mtime(root, path)
        return {"ok": True, **data}
    except CodeBrowserError as e:
        return {"ok": False, "error": str(e)}


@code_router.post("/api/code/save")
def code_save(body: dict):
    """UI 保存（M6）：仅 demo/replica 白名单可写，atomic_write 落盘。"""
    root = str((body or {}).get("root", "") or "")
    path = str((body or {}).get("path", "") or "")
    content = (body or {}).get("content")
    if not root.strip() or not path.strip() or content is None:
        return {"ok": False, "error": "root / path / content 均不能为空"}
    mtime = (body or {}).get("mtime")
    if mtime is not None:
        try:
            client_mtime = float(mtime)
        except (TypeError, ValueError):
            client_mtime = None
        current = _workshop().file_mtime(root, path)
        if client_mtime is None or current is None \
                or abs(current - client_mtime) > 1e-3:
            return {"ok": False, "conflict": True,
                    "error": "文件已被外部修改（AI 或编辑器），请刷新后重试"}
    try:
        result = _workshop().save_via_root(root, path, str(content))
        result["mtime"] = _workshop().file_mtime(root, path)
        return {"ok": True, **result}
    except WorkshopError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"保存失败: {e}"}


@code_router.get("/api/demo/scaffolds")
def demo_scaffolds():
    return {"ok": True, "scaffolds": _workshop().scaffold_types()}


@code_router.post("/api/demo/scaffold")
def demo_scaffold(body: dict):
    """平台内建 demo（M6）：脚手架复制到 demo 根 + 自动注册代码根。"""
    try:
        r = _workshop().scaffold_create((body or {}).get("type", ""),
                                        (body or {}).get("name", ""))
        return {"ok": True, **r}
    except WorkshopError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"创建 demo 失败: {e}"}


@code_router.get("/api/code/resolve")
def code_resolve(path: str):
    """把 AI 回答中的路径引用解析到已配置代码根下的真实文件。"""
    hit = _code_browser().resolve(path)
    if not hit:
        return {"ok": False}
    return {"ok": True, **hit}


# ---------- 进程管理（M6 实战工坊） ----------

@code_router.get("/api/processes")
def process_list():
    return {"ok": True, "processes": _process_mgr().list(),
            "allowed_cwds": {k: str(v)
                             for k, v in _process_mgr().allowed_cwds().items()}}


@code_router.post("/api/processes/start")
def process_start(body: dict):
    cwd = (body or {}).get("cwd", "")
    raw_cmd = (body or {}).get("cmd")
    name = (body or {}).get("name", "")
    if isinstance(raw_cmd, str):
        cmd = split_cmd(raw_cmd)
    elif isinstance(raw_cmd, list):
        cmd = [str(c) for c in raw_cmd]
    else:
        cmd = []
    if not cmd:
        return {"ok": False, "error": "cmd 不能为空（字符串或字符串数组）"}
    try:
        return {"ok": True, **_process_mgr().start(cwd, cmd, name)}
    except ProcessError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"启动失败: {e}"}


@code_router.post("/api/processes/stop")
def process_stop(body: dict):
    pid_id = (body or {}).get("id", "")
    try:
        return {"ok": True, **_process_mgr().stop(str(pid_id))}
    except ProcessError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"停止失败: {e}"}


@code_router.post("/api/processes/clear-stopped")
def process_clear_stopped():
    """移除登记簿中全部已停止条目（running 不受影响）。"""
    try:
        return {"ok": True, "cleared": _process_mgr().clear_stopped()}
    except Exception as e:
        return {"ok": False, "error": f"清理失败: {e}"}


@code_router.get("/api/processes/logs")
def process_logs(id: str, tail: int = 200):
    try:
        return {"ok": True, **_process_mgr().logs_tail(str(id), tail)}
    except ProcessError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"日志读取失败: {e}"}


@code_router.get("/api/processes/logs/stream")
def process_logs_stream(id: str):
    """SSE 日志 tail：只转增量；进程退出且读尽后服务端发 end 并关流。"""
    from .routes import sse as _sse
    mgr = _process_mgr()

    def gen():
        try:
            for ev in mgr.logs_stream(id):
                yield _sse(ev)
        except ProcessError as e:
            yield _sse({"type": "error", "content": str(e)})

    return StreamingResponse(gen(), media_type="text/event-stream")
