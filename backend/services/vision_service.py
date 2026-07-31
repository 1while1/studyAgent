"""视觉分析服务（M3.5 补全）

支持图片分析：base64 编码或文件路径输入。
通过 OpenAI Vision API 或兼容接口分析图片内容。
"""
from __future__ import annotations
import base64
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

from ..domain.sensitive import is_sensitive

ALLOWED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


@dataclass
class VisionResult:
    """图片分析结果"""
    description: str
    content_type: str  # "image/png", "image/jpeg" 等
    file_size: int
    analysis: str = ""  # LLM 分析结果


class VisionService:
    """图片分析服务"""
    
    def __init__(self, config=None, allowed_root: str = None):
        self._config = config
        self._max_size = 10 * 1024 * 1024  # 10MB
        self._allowed_root = allowed_root
        if config and not allowed_root:
            ws = config.get("active_workspace", "")
            if ws:
                workspaces = config.get("workspaces", [])
                for w in workspaces:
                    if isinstance(w, dict) and w.get("slug") == ws:
                        self._allowed_root = w.get("docx_dir", "")
    
    def analyze_image(self, image_path: Path, prompt: str = "请描述这张图片的内容") -> Optional[VisionResult]:
        """分析本地图片文件"""
        if not image_path.exists() or not image_path.is_file():
            return None
        
        # 安全检查：路径白名单
        resolved = image_path.resolve()
        if self._allowed_root:
            root = Path(self._allowed_root).resolve()
            if not str(resolved).startswith(str(root)):
                return None
        
        # 安全检查：敏感文件
        if is_sensitive(image_path.name):
            return None
        
        # 安全检查：扩展名白名单
        if image_path.suffix.lower() not in ALLOWED_IMAGE_EXTS:
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
        if not self._config:
            return "[Vision API 未配置]"
        
        try:
            from ..llm.factory import create_llm
            client = create_llm(self._config)
            # 解包 ObservedLLM / FallbackClient 获取底层 OpenAI 客户端
            raw = self._unwrap_client(client)
            if raw is not None:
                openai_client = raw._client  # OpenAI 实例
                model = raw._model           # 模型名称
                response = openai_client.chat.completions.create(
                    model=model,
                    messages=[{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {
                                "url": f"data:{content_type};base64,{image_b64}"
                            }}
                        ]
                    }],
                    max_tokens=1024,
                )
                return response.choices[0].message.content
            return "[当前 LLM 不支持 Vision]"
        except Exception as e:
            return f"[Vision 分析失败: {e}]"
    
    @staticmethod
    def _unwrap_client(client):
        """解包 ObservedLLM / FallbackClient，返回底层 OpenAICompatClient 或 None"""
        from ..llm.observed import ObservedLLM
        from ..llm.fallback import FallbackClient
        from ..llm.openai_compat import OpenAICompatClient
        seen = set()
        while id(client) not in seen:
            seen.add(id(client))
            if isinstance(client, OpenAICompatClient):
                return client
            if isinstance(client, ObservedLLM):
                client = client.inner
                continue
            if isinstance(client, FallbackClient):
                client = client._primary
                continue
            break
        return None
