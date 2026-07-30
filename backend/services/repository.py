"""Repository 抽象接口（M3.1 架构加固）

为学习数据提供统一的存储接口，当前实现 JsonRepository，
未来可扩展 SqliteRepository。
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional
import threading


class Repository(ABC):
    """存储仓库接口"""

    @abstractmethod
    def load(self, key: str) -> Optional[dict]:
        """加载数据"""
        ...

    @abstractmethod
    def save(self, key: str, data: dict) -> None:
        """保存数据"""
        ...

    @abstractmethod
    def exists(self, key: str) -> bool:
        """检查数据是否存在"""
        ...

    @abstractmethod
    def delete(self, key: str) -> None:
        """删除数据"""
        ...

    @abstractmethod
    def list_keys(self) -> list[str]:
        """列出所有键"""
        ...


class JsonRepository(Repository):
    """JSON 文件存储实现"""

    def __init__(self, base_dir: Path):
        self._base_dir = base_dir
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _key_to_path(self, key: str) -> Path:
        """将 key 转换为文件路径（支持子目录）"""
        return self._base_dir / f"{key}.json"

    def load(self, key: str) -> Optional[dict]:
        path = self._key_to_path(key)
        if not path.exists():
            return None
        import json
        with self._lock:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)

    def save(self, key: str, data: dict) -> None:
        path = self._key_to_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        import json
        tmp_path = path.with_suffix(".tmp")
        with self._lock:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            tmp_path.replace(path)  # atomic write

    def exists(self, key: str) -> bool:
        return self._key_to_path(key).exists()

    def delete(self, key: str) -> None:
        path = self._key_to_path(key)
        if path.exists():
            with self._lock:
                path.unlink()

    def list_keys(self) -> list[str]:
        with self._lock:
            return [f.stem for f in self._base_dir.glob("*.json")]
