"""视觉分析服务（M3.5 补全）

支持图片分析：base64 编码或文件路径输入。
通过 OpenAI Vision API 或兼容接口分析图片内容。
"""
from __future__ import annotations
import base64
from pathlib import Path
from typing import Optional
from dataclasses import dataclass


@dataclass
class VisionResult:
    """图片分析结果"""
    description: str
    content_type: str  # "image/png", "image/jpeg" 等
    file_size: int
    analysis: str = ""  # LLM 分析结果


class VisionService:
    """图片分析服务"""
    
    def __init__(self, config=None):
        self._config = config
        self._max_size = 10 * 1024 * 1024  # 10MB
    
    def analyze_image(self, image_path: Path, prompt: str = "请描述这张图片的内容") -> Optional[VisionResult]:
        """分析本地图片文件"""
        if not image_path.exists():
            return None
        
        content_type = self._detect_content_type(image_path)
        file_size = image_path.stat().st_size
        
        if file_size > self._max_size:
            return None
        
        # 读取并编码
        with open(image_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")
        
        # 调用 LLM Vision API（如果有配置）
        analysis = self._call_vision_api(image_data, content_type, prompt)
        
        return VisionResult(
            description=prompt,
            content_type=content_type,
            file_size=file_size,
            analysis=analysis,
        )
    
    def analyze_base64(self, image_b64: str, content_type: str, prompt: str = "请描述这张图片的内容") -> Optional[VisionResult]:
        """分析 base64 编码的图片"""
        try:
            image_data = base64.b64decode(image_b64)
        except Exception:
            return None
        
        if len(image_data) > self._max_size:
            return None
        
        analysis = self._call_vision_api(image_b64, content_type, prompt)
        
        return VisionResult(
            description=prompt,
            content_type=content_type,
            file_size=len(image_data),
            analysis=analysis,
        )
    
    def _detect_content_type(self, path: Path) -> str:
        ext = path.suffix.lower()
        types = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }
        return types.get(ext, "application/octet-stream")
    
    def _call_vision_api(self, image_b64: str, content_type: str, prompt: str) -> str:
        """调用 LLM Vision API 分析图片"""
        # 当前为占位实现，未来接入 OpenAI Vision API
        # 或兼容的 Vision 模型
        if not self._config:
            return "[Vision API 未配置]"
        
        try:
            # 尝试通过 LLM factory 获取 vision-capable client
            from ..llm.factory import build_client
            client = build_client(self._config)
            if hasattr(client, "analyze_image"):
                return client.analyze_image(image_b64, content_type, prompt)
            return "[当前 LLM 不支持 Vision]"
        except Exception as e:
            return f"[Vision 分析失败: {e}]"
