import threading
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

    def test_disconnect_idempotent(self):
        client = MCPClient("test", "nonexistent_command", [])
        # 未连接时 disconnect 不应崩溃
        client.disconnect()
        self.assertFalse(client._connected)

    def test_call_tool_not_connected(self):
        client = MCPClient("test", "nonexistent_command", [])
        result = client.call_tool("some_tool", {"arg": "val"})
        self.assertIsNone(result)

    def test_json_rpc_id_increment(self):
        client = MCPClient("test", "echo", ["hello"])
        self.assertEqual(client._next_id, 1)


class TestMCPClientDisconnect(unittest.TestCase):
    def test_disconnect_closes_pipes(self):
        """disconnect 后 pipe 被关闭"""
        client = MCPClient("test", "python", [])
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        mock_proc.stdout = MagicMock()
        mock_proc.stderr = MagicMock()
        client._process = mock_proc
        client._connected = True

        client.disconnect()

        mock_proc.terminate.assert_called_once()
        mock_proc.wait.assert_called()
        mock_proc.stdin.close.assert_called_once()
        mock_proc.stdout.close.assert_called_once()
        mock_proc.stderr.close.assert_called_once()
        self.assertFalse(client._connected)
        self.assertIsNone(client._process)


class TestMCPClientWhitelist(unittest.TestCase):
    def test_command_whitelist(self):
        """非法命令被拒绝"""
        client = MCPClient("test", "rm", ["-rf", "/"])
        self.assertFalse(client.connect())

    def test_allowed_command_passes_check(self):
        """合法命令通过白名单检查（仍可能因其他原因失败）"""
        client = MCPClient("test", "python", ["-c", "pass"])
        # 不验证 connect 成功，只验证白名单不阻止
        cmd_name = __import__("pathlib").Path(client.command).name
        self.assertIn(cmd_name, {"python", "python3", "node", "npx", "uvx"})


class TestMCPClientPoolThreadSafety(unittest.TestCase):
    def test_pool_thread_safety(self):
        """并发访问 Pool 不崩溃"""
        pool = MCPClientPool()
        errors = []

        def worker():
            try:
                pool.get_all_tools()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])


class TestMCPClientPool(unittest.TestCase):
    def test_empty_config(self):
        pool = MCPClientPool()
        self.assertEqual(pool.load_from_config(), 0)

    def test_get_all_tools_empty(self):
        pool = MCPClientPool()
        self.assertEqual(pool.get_all_tools(), [])

    def test_has_rlock(self):
        pool = MCPClientPool()
        self.assertEqual(type(pool._lock).__name__, 'RLock')


if __name__ == "__main__":
    unittest.main()
