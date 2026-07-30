"""Web 搜索服务（M2.2 扩展层）

多 provider 可插拔架构，默认 DuckDuckGo（免费无需 API key）。
结果缓存避免重复查询，API key 走 .env（铁律 7）。
连接失败静默降级（铁律 13）。
"""
from __future__ import annotations

import hashlib
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    source: str  # provider name


class WebSearchProvider(ABC):
    @abstractmethod
    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        ...


class DuckDuckGoProvider(WebSearchProvider):
    """DuckDuckGo 免费搜索（无需 API key）"""

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        try:
            from duckduckgo_search import DDGS
            results = []
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=top_k):
                    results.append(SearchResult(
                        title=r.get("title", ""),
                        url=r.get("href", ""),
                        snippet=r.get("body", ""),
                        source="duckduckgo",
                    ))
            return results
        except Exception:
            return []


class WebSearchService:
    def __init__(self, config=None, cache_size: int = 100):
        self._config = config
        self._cache: dict[str, tuple[float, list[SearchResult]]] = {}
        self._cache_size = cache_size
        self._provider = self._build_provider()

    def _build_provider(self) -> WebSearchProvider:
        # 默认 DuckDuckGo，未来可扩展 Tavily/Serper
        return DuckDuckGoProvider()

    def _cache_key(self, query: str, top_k: int) -> str:
        return hashlib.sha256(f"{query}:{top_k}".encode()).hexdigest()

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        key = self._cache_key(query, top_k)
        if key in self._cache:
            ts, results = self._cache[key]
            if time.time() - ts < 3600:  # 1 小时缓存
                return results

        results = self._provider.search(query, top_k)

        # 缓存管理
        if len(self._cache) >= self._cache_size:
            oldest = min(self._cache, key=lambda k: self._cache[k][0])
            del self._cache[oldest]
        self._cache[key] = (time.time(), results)

        return results
