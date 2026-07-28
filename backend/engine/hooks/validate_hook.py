"""校验钩子：包装内置 resources/hooks/validate_study.py，供落盘编排调用。"""

from __future__ import annotations

import contextlib
import importlib.util
import io
from pathlib import Path

from ...services.config_service import ConfigService, HOOKS_DIR


def make_validator(config: ConfigService):
    """返回 validator() -> (ok: bool, output: str)，签名匹配 backup_service.atomic_persist。"""
    script: Path = HOOKS_DIR / "validate_study.py"

    def validator() -> tuple[bool, str]:
        try:
            spec = importlib.util.spec_from_file_location("validate_study", script)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            ws = config.workspace
            buf_out, buf_err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
                rc = module.main(str(config.docx_dir), ws.total_days, ws.replica_name)
            output = (buf_out.getvalue() + buf_err.getvalue()).strip()
            return rc == 0, output
        except Exception as e:
            # validator 自身异常（脚本损坏/版本不兼容）视为校验失败：
            # 走 atomic_persist 既有 not-ok 路径回滚，而非穿透留下半成品
            return False, f"validator 自身异常：{e}"

    return validator
