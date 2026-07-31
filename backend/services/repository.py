"""Repository 抽象接口（M3.1 架构加固）

为学习数据提供统一的存储接口，当前实现 JsonRepository 和 SqliteRepository。
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional
import json
import sqlite3
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
        with self._lock:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)

    def save(self, key: str, data: dict) -> None:
        path = self._key_to_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
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


class SqliteRepository(Repository):
    """SQLite 存储实现（WAL 模式）"""

    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS kv (
                key TEXT PRIMARY KEY,
                data TEXT NOT NULL
            )
        """)
        self._conn.commit()
        self._lock = threading.Lock()

    def load(self, key: str) -> Optional[dict]:
        with self._lock:
            cursor = self._conn.execute("SELECT data FROM kv WHERE key = ?", (key,))
            row = cursor.fetchone()
            if row is None:
                return None
            return json.loads(row[0])

    def save(self, key: str, data: dict) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO kv (key, data) VALUES (?, ?)",
                (key, json.dumps(data, ensure_ascii=False))
            )
            self._conn.commit()

    def exists(self, key: str) -> bool:
        with self._lock:
            cursor = self._conn.execute("SELECT 1 FROM kv WHERE key = ?", (key,))
            return cursor.fetchone() is not None

    def delete(self, key: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM kv WHERE key = ?", (key,))
            self._conn.commit()

    def list_keys(self) -> list[str]:
        with self._lock:
            cursor = self._conn.execute("SELECT key FROM kv")
            return [row[0] for row in cursor.fetchall()]

    def close(self):
        self._conn.close()
