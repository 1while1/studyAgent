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

# Magic bytes 校验表
_MAGIC_BYTES = {
    ".jpg": b"\xff\xd8\xff",
    ".png": b"\x89PNG",
    ".gif": b"GIF8",
    ".pdf": b"%PDF",
    ".webp": b"RIFF",
}


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
        self._allowed_types = set(ALLOWED_TYPES)
        if config:
            upload_cfg = config.get("upload", {})
            img_types = upload_cfg.get("allowed_image_types")
            doc_types = upload_cfg.get("allowed_doc_types")
            if img_types or doc_types:
                self._allowed_types = set()
                if img_types:
                    self._allowed_types.update(img_types)
                if doc_types:
                    self._allowed_types.update(doc_types)
            max_mb = upload_cfg.get("max_size_mb")
            if max_mb:
                self._max_size = int(max_mb) * 1024 * 1024
    
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
    
    def _validate_file(self, filename: str, content: bytes, size: int) -> Optional[str]:
        """验证文件类型、大小和 magic bytes，返回错误信息或 None"""
        ext = Path(filename).suffix.lower()
        if ext not in self._allowed_types:
            return f"不支持的文件类型：{ext}"
        if size > self._max_size:
            return f"文件过大"
        magic = _MAGIC_BYTES.get(ext)
        if magic and len(content) >= len(magic):
            if not content[:len(magic)].startswith(magic):
                return "文件内容与扩展名不匹配"
        # 文本类型 NULL 字节检测（防止二进制伪装为文本）
        _TEXT_EXTS = {".md", ".txt"}
        if ext in _TEXT_EXTS and b'\x00' in content[:1024]:
            return "文本文件包含非法二进制内容"
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
        error = self._validate_file(filename, content, len(content))
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
        """根据 file_id 获取文件路径（精确匹配优先）"""
        upload_dir = self._get_upload_dir()
        # 精确匹配：file_id 即为文件 stem
        exact = upload_dir / file_id
        # 尝试带常见扩展名
        for ext in ALLOWED_TYPES:
            candidate = upload_dir / f"{file_id}{ext}"
            if candidate.exists():
                return candidate
        # 回退：遍历目录精确匹配 stem
        for f in upload_dir.iterdir():
            if f.stem == file_id:
                return f
        return None
