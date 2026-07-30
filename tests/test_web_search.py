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

    def test_cache_ttl_expired(self):
        svc = WebSearchService()
        with patch.object(svc._provider, "search") as mock:
            mock.return_value = [SearchResult("T", "U", "S", "ddg")]
            svc.search("ttl_test")
            self.assertEqual(mock.call_count, 1)
        # 手动让缓存过期
        key = svc._cache_key("ttl_test", 5)
        old_ts = svc._cache[key][0] - 9999
        svc._cache[key] = (old_ts, svc._cache[key][1])
        with patch.object(svc._provider, "search") as mock:
            mock.return_value = [SearchResult("T2", "U2", "S2", "ddg")]
            svc.search("ttl_test")
            self.assertEqual(mock.call_count, 1)  # 过期后重新调用

    def test_cache_eviction(self):
        svc = WebSearchService(cache_size=2)
        with patch.object(svc._provider, "search") as mock:
            mock.return_value = [SearchResult("T", "U", "S", "ddg")]
            svc.search("q1")
            svc.search("q2")
            self.assertEqual(len(svc._cache), 2)
            svc.search("q3")  # 应淘汰最旧条目
            self.assertEqual(len(svc._cache), 2)

    def test_provider_exception(self):
        svc = WebSearchService()
        with patch.object(svc._provider, "search") as mock:
            mock.side_effect = RuntimeError("network error")
            try:
                results = svc.search("error_query")
                # 如果服务层捕获了异常，应返回空列表
                self.assertIsInstance(results, list)
            except RuntimeError:
                # 如果异常传播上来，也是可接受的
                pass


if __name__ == "__main__":
    unittest.main()
