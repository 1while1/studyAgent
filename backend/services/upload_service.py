"""文件上传服务（M2.2 扩展层）

支持图片（jpg/png/gif/webp）和文档（md/txt/pdf）上传。
存储路径：<docx_dir>/uploads/
文件大小限制可配（默认 10MB）。
文件类型白名单校验。
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# 允许的文件类型
ALLOWED_IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
ALLOWED_DOC_TYPES = {".md", ".txt", ".pdf"}
ALLOWED_TYPES = ALLOWED_IMAGE_TYPES | ALLOWED_DOC_TYPES

# 默认最大文件大小（10MB）
DEFAULT_MAX_SIZE_MB = 10


@dataclass
class UploadResult:
    file_id: str          # 唯一 ID
    filename: str         # 原始文件名
    file_type: str        # "image" 或 "document"
    path: str             # 存储路径
    size_bytes: int       # 文件大小
    url: str              # 访问 URL（相对路径）


class UploadService:
    def __init__(self, config=None, max_size_mb: int = DEFAULT_MAX_SIZE_MB):
        self._config = config
        self._max_size = max_size_mb * 1024 * 1024
    
    def _get_upload_dir(self) -> Path:
        """获取上传目录（<docx_dir>/uploads/）"""
        if self._config:
            ws = self._config.workspace
            docx_dir = Path(ws.docx_dir)
        else:
            docx_dir = Path(".")
        upload_dir = docx_dir / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        return upload_dir
    
    def _validate_file(self, filename: str, size: int) -> Optional[str]:
        """验证文件类型和大小，返回错误信息或 None"""
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_TYPES:
            return f"不支持的文件类型：{ext}（支持：{', '.join(sorted(ALLOWED_TYPES))}）"
        if size > self._max_size:
            return f"文件过大：{size / 1024 / 1024:.1f}MB（最大 {self._max_size / 1024 / 1024:.0f}MB）"
        return None
    
    def _get_file_type(self, filename: str) -> str:
        ext = Path(filename).suffix.lower()
        if ext in ALLOWED_IMAGE_TYPES:
            return "image"
        return "document"
    
    def save_upload(self, filename: str, content: bytes) -> UploadResult | str:
        """保存上传文件
        
        Returns:
            UploadResult 成功，或错误信息字符串
        """
        error = self._validate_file(filename, len(content))
        if error:
            return error
        
        file_id = uuid.uuid4().hex[:12]
        ext = Path(filename).suffix.lower()
        stored_name = f"{file_id}{ext}"
        
        upload_dir = self._get_upload_dir()
        file_path = upload_dir / stored_name
        file_path.write_bytes(content)
        
        file_type = self._get_file_type(filename)
        
        return UploadResult(
            file_id=file_id,
            filename=filename,
            file_type=file_type,
            path=str(file_path),
            size_bytes=len(content),
            url=f"/uploads/{stored_name}",
        )
    
    def get_file_path(self, file_id: str) -> Optional[Path]:
        """根据 file_id 获取文件路径"""
        upload_dir = self._get_upload_dir()
        for f in upload_dir.iterdir():
            if f.stem.startswith(file_id):
                return f
        return None
