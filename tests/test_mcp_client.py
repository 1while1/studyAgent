import unittest
from unittest.mock import patch, MagicMock
from backend.services.mcp_client_service import MCPClient, MCPClientPool, MCPToolInfo


class TestMCPClient(unittest.TestCase):
    def test_dataclass(self):
        tool = MCPToolInfo("test", "desc", {})
        self.assertEqual(tool.name, "test")

    def test_connect_failure_silent(self):
        client = MCPClient("test", "nonexistent_command", [])
        result = client.connect()
        self.assertFalse(result)  # 连接失败返回 False，不抛异常


class TestMCPClientPool(unittest.TestCase):
    def test_empty_config(self):
        pool = MCPClientPool()
        self.assertEqual(pool.load_from_config(), 0)

    def test_get_all_tools_empty(self):
        pool = MCPClientPool()
        self.assertEqual(pool.get_all_tools(), [])


if __name__ == "__main__":
    unittest.main()
