# 改进4: routes.py 按功能域拆分

> 状态：✅ 已完成（2026-07-29，refactor/routes-split）

## 背景

`backend/api/routes.py` 原 1387 行，包含 ~45 个端点函数，单文件过大难以维护。需要按功能域拆分为多个子路由文件，同时保持向后兼容（12-14 个测试文件 `from backend.api import routes`）。

## 拆分方案

| 子路由文件 | 功能域 | 端点前缀 | 行数 |
|-----------|--------|---------|------|
| `code_routes.py` | 代码浏览器 + 进程管理 | `/api/code/*` `/api/demo/*` `/api/processes/*` | ~238 |
| `auth_routes.py` | 访问密码门 | `/api/auth/*` | ~80 |
| `learner_routes.py` | 学习者模型 + 笔记 + 话术 + 资料库 | `/api/learner/*` `/api/notes/*` `/api/qa/*` `/api/materials/*` | ~278 |
| `workspace_routes.py` | 工作区 + 会话 + 配置 | `/api/workspaces/*` `/api/session/*` `/api/config/*` | ~194 |
| `llm_config_routes.py` | 可观测性 + 模型配置 + 上下文状态 | `/api/observability/*` `/api/llm-config/*` `/api/context-status` | ~244 |

核心 SSE 路由（chat/command/slash/state/history/doc/commands）保留在 `routes.py`。

## 关键设计决策

1. **延迟 `_deps` 读取**：每个子路由文件定义 `_deps()` 函数，运行时 `from . import routes; return routes._deps`，避免循环导入初始化顺序问题
2. **兼容层 re-export**：`routes.py` 底部 re-export 所有子路由函数/类，确保 `from backend.api import routes; routes.xxx()` 调用不断裂
3. **`LLMStreamer` 保留在 routes.py**：`test_materials.py` 4 处直接 `from backend.api.routes import LLMStreamer`
4. **`SETTINGS_PATH` re-export**：`test_context_manager.py` monkey-patch `routes.SETTINGS_PATH`
5. **APIRouter 带 tags**：每个子路由 `APIRouter(tags=[...])` 协同 API 文档

## app.py 修改

`create_app()` 中 include 所有子路由：
```python
from .code_routes import code_router
from .auth_routes import auth_router
from .learner_routes import learner_router
from .workspace_routes import workspace_router
from .llm_config_routes import config_router
app.include_router(code_router)
app.include_router(auth_router)
app.include_router(learner_router)
app.include_router(workspace_router)
app.include_router(config_router)
```

## 验证

- 583 测试全绿（零回归）
- 14 个测试文件 `from backend.api import routes` 无需修改
