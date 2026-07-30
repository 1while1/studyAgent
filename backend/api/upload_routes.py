"""文件上传路由：/api/upload（上传）+ /uploads/{filename}（静态服务）。"""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import FileResponse

from ..services.upload_service import UploadService
from ..services.config_service import get_config

upload_router = APIRouter(tags=["文件上传"])
logger = logging.getLogger(__name__)


def _upload_service() -> UploadService:
    """创建 UploadService 实例（带配置）。"""
    config = get_config()
    upload_cfg = config.get("upload", {}) if config else {}
    max_size = int(upload_cfg.get("max_size_mb", 10))
    return UploadService(config=config, max_size_mb=max_size)


@upload_router.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    """上传文件（图片/文档）。

    支持类型：jpg/png/gif/webp（图片）、md/txt/pdf（文档）
    大小限制：可配（默认 10MB，settings.toml [upload] max_size_mb）

    Returns:
        {ok: true, file_id, filename, file_type, url, size_bytes} 或
        {ok: false, error: "错误信息"}
    """
    if not file.filename:
        return {"ok": False, "error": "未提供文件名"}

    # 读取文件内容
    try:
        content = await file.read()
    except Exception as e:
        return {"ok": False, "error": f"文件读取失败：{e}"}

    size = len(content)
    if size > 5 * 1024 * 1024:
        logger.info("大文件上传: %s, 大小: %d bytes", file.filename, size)

    if not content:
        return {"ok": False, "error": "文件内容为空"}

    svc = _upload_service()
    # M-S2: filename sanitization（防路径注入/特殊字符）
    safe_name = re.sub(r'[^\w\s\-.]', '_', file.filename or 'unnamed')
    safe_name = safe_name.strip()[:255]
    result = svc.save_upload(safe_name, content)

    # 返回错误字符串
    if isinstance(result, str):
        return {"ok": False, "error": result}

    return {
        "ok": True,
        "file_id": result.file_id,
        "filename": result.filename,
        "file_type": result.file_type,
        "url": result.url,
        "size_bytes": result.size_bytes,
    }


@upload_router.get("/uploads/{filename}")
async def serve_upload(filename: str):
    """提供已上传文件的静态访问。

    URL 格式：/uploads/{file_id}{ext}
    例如：/uploads/a1b2c3d4e5f6.png
    """
    # 安全检查：禁止路径遍历
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="非法文件名")

    svc = _upload_service()
    # 从文件名提取 file_id（去掉扩展名）
    from pathlib import Path
    file_id = Path(filename).stem

    file_path = svc.get_file_path(file_id)
    if not file_path or not file_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")

    # 根据扩展名确定 media type
    ext = file_path.suffix.lower()
    media_types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".md": "text/markdown",
        ".txt": "text/plain",
        ".pdf": "application/pdf",
    }
    media_type = media_types.get(ext, "application/octet-stream")

    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        filename=file_path.name,
    )
