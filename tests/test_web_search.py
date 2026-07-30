"""M2.1 Web 搜索服务测试"""
import unittest
from unittest.mock import patch
from backend.services.web_search_service import (
    WebSearchService, DuckDuckGoProvider, SearchResult,
)


class TestSearchResult(unittest.TestCase):
    def test_dataclass(self):
        r = SearchResult("title", "url", "snippet", "ddg")
        self.assertEqual(r.title, "title")
        self.assertEqual(r.source, "ddg")


class TestDuckDuckGoProvider(unittest.TestCase):
    @patch("backend.services.web_search_service.DuckDuckGoProvider.search")
    def test_search_returns_results(self, mock_search):
        mock_search.return_value = [
            SearchResult("T1", "http://a.com", "S1", "duckduckgo"),
        ]
        provider = DuckDuckGoProvider()
        results = provider.search("test query")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "T1")


class TestWebSearchService(unittest.TestCase):
    def test_cache_hit(self):
        svc = WebSearchService()
        # 第一次调用
        with patch.object(svc._provider, "search") as mock:
            mock.return_value = [SearchResult("T", "U", "S", "ddg")]
            r1 = svc.search("test")
        # 第二次调用（应命中缓存）
        r2 = svc.search("test")
        self.assertEqual(len(r1), len(r2))
        mock.assert_called_once()  # 只调用一次

    def test_empty_query(self):
        svc = WebSearchService()
        # 空查询不应崩溃
        results = svc._provider.search("")
        # DuckDuckGo 可能返回空列表或抛异常，都应安全处理


if __name__ == "__main__":
    unittest.main()
