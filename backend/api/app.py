"""FastAPI 应用组装：依赖注入 + API 路由 + 前端静态托管 + 启动预热。"""

from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from ..engine.commands.base import Deps
from ..engine.hooks.pipeline import HookPipeline
from ..engine.hooks.validate_hook import make_validator
from ..engine.orchestrator import ChatOrchestrator
from ..engine.prompt_builder import PromptBuilder
from ..engine.quiz_engine import QuizEngine
from ..engine.session_store import SessionStore
from ..engine.stage_machine import StageMachine
from ..llm.factory import create_llm
from ..services.backup_service import BackupService
from ..services.config_service import get_config
from ..services.materials_service import MaterialsService
from ..services.memory_store import MemoryStore
from ..services.state_store import StateStore
from ..services.study_plan import StudyPlanStore
from ..services.template_service import TemplateService
from ..services.config_service import WEB_ROOT, SOP_DIR
from . import routes


def build_deps() -> Deps:
    config = get_config()
    state_store = StateStore(config)
    memory = MemoryStore(config)
    stages = StageMachine(config)
    llm = create_llm(config)
    quiz = QuizEngine(config, llm)
    hooks = HookPipeline()
    hooks.register_post_persist("validate_study", make_validator(config))
    return Deps(
        config=config,
        state_store=state_store,
        memory=memory,
        study_plan=StudyPlanStore(config),
        templates=TemplateService(config),
        backup=BackupService(config),
        stages=stages,
        llm=llm,
        quiz=quiz,
        prompts=PromptBuilder(config, state_store, memory, stages,
                              MaterialsService(config)),
        hooks=hooks,
        session_store=SessionStore(config.workspace.session_path),
    )


def _warmup_llm_cache(deps: Deps) -> None:
    """启动预热：把最长的 system prompt（含 SOP 卡全文）发一次，

    让提供商侧上下文缓存命中后续调用，降低首包延迟。
    仅消耗一次输入 token（max_tokens=1），后台线程执行不阻塞启动。
    """
    if deps.config.llm_config.get("provider") == "mock":
        return
    if not deps.config.llm_config.get("warmup_on_start", False):
        return

    def _run() -> None:
        try:
            session = deps.session_store.load()
            # 取首个 start_day 指令的 SOP 卡作为最长 prompt 预热样本
            card_name = next(
                (c.get("sop_card") for c in deps.config.commands.values()
                 if c.get("handler") == "start_day" and c.get("sop_card")), None)
            if not card_name:
                return
            card = (SOP_DIR / card_name).read_text(encoding="utf-8")
            system = deps.prompts.build(session, sop_card=card)
            from ..services.observer import task_scope
            with task_scope("warmup"):
                list(deps.llm.chat_stream(
                    [{"role": "system", "content": system},
                     {"role": "user", "content": "预热请求，回复 OK 即可。"}],
                    max_tokens=1))
            logging.getLogger("study-web").info("LLM 上下文缓存预热完成")
        except Exception as e:  # 预热失败不影响服务
            logging.getLogger("study-web").warning("LLM 预热失败（可忽略）: %s", e)

    threading.Thread(target=_run, daemon=True).start()


def assemble() -> Deps:
    """构建 deps + orchestrator 并绑定到路由。工作区切换后再次调用完成热切换。"""
    deps = build_deps()
    orchestrator = ChatOrchestrator(
        deps.config, deps.stages, deps.quiz,
        deps.state_store, deps.memory, deps.templates)
    routes.init(deps, orchestrator)
    return deps


def create_app() -> FastAPI:
    deps = assemble()
    routes.set_rebind(assemble)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        _warmup_llm_cache(deps)
        yield

    app = FastAPI(title=deps.config.workspace.title, version="0.2.0", lifespan=lifespan)

    @app.middleware("http")
    async def auth_gate(request, call_next):
        """访问密码门（M2）：实现在 middleware.make_auth_gate（可单测）。"""
        from .middleware import make_auth_gate
        return await make_auth_gate(deps.config)(request, call_next)

    @app.middleware("http")
    async def no_cache_static(request, call_next):
        """前端静态资源禁缓存，防止新旧 JS/HTML 混搭（API 不受影响）。"""
        response = await call_next(request)
        if not request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    app.include_router(router=routes.router)
    frontend = WEB_ROOT / "frontend"
    app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
    return app


app = create_app()
