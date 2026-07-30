"""MCP Client 服务（M2.3 扩展层）

studyAgent 作为 MCP Host，接入外部 MCP Server。
JSON-RPC 2.0 over stdio 传输。
连接失败静默降级（铁律 13）。
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_ALLOWED_COMMANDS = {"python", "python3", "node", "npx", "uvx"}


@dataclass
class MCPToolInfo:
    name: str
    description: str
    input_schema: dict


class MCPClient:
    """单个 MCP Server 的客户端"""

    def __init__(self, name: str, command: str, args: list[str], env: Optional[dict] = None):
        self.name = name
        self.command = command
        self.args = args
        self.env = env or {}
        self._process: Optional[subprocess.Popen] = None
        self._tools: list[MCPToolInfo] = []
        self._connected = False
        self._lock = threading.Lock()
        self._next_id = 1

    def connect(self) -> bool:
        """连接到 MCP Server（stdio 传输）"""
        cmd_name = Path(self.command).name
        if cmd_name not in _ALLOWED_COMMANDS:
            logger.error("MCP command not allowed: %s", self.command)
            return False
        try:
            minimal_env = {"PATH": os.environ.get("PATH", "")}
            full_env = {**minimal_env, **self.env}
            self._process = subprocess.Popen(
                [self.command] + self.args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=full_env,
            )
            self._connected = True
            # 初始化握手
            self._send({"jsonrpc": "2.0", "id": self._next_id, "method": "initialize",
                        "params": {"protocolVersion": "2024-11-05"}})
            self._next_id += 1
            # 获取工具列表
            resp = self._send({"jsonrpc": "2.0", "id": self._next_id, "method": "tools/list"})
            self._next_id += 1
            if resp and "result" in resp:
                for t in resp["result"].get("tools", []):
                    self._tools.append(MCPToolInfo(
                        name=t["name"],
                        description=t.get("description", ""),
                        input_schema=t.get("inputSchema", {}),
                    ))
            return True
        except Exception as e:
            logger.warning("MCP connect failed [%s]: %s", self.name, e)
            self._connected = False
            return False

    def _readline_with_timeout(self, timeout: int = 10) -> Optional[bytes]:
        import selectors
        sel = selectors.DefaultSelector()
        sel.register(self._process.stdout, selectors.EVENT_READ)
        events = sel.select(timeout=timeout)
        sel.close()
        if events:
            return self._process.stdout.readline()
        return None

    def _send(self, message: dict) -> Optional[dict]:
        """发送 JSON-RPC 消息并等待响应（线程安全）"""
        if not self._process or not self._connected:
            return None
        with self._lock:
            try:
                data = json.dumps(message) + "\n"
                self._process.stdin.write(data.encode())
                self._process.stdin.flush()
                line = self._readline_with_timeout()
                if line:
                    resp = json.loads(line.decode())
                    # JSON-RPC 响应 id 校验：确保匹配请求
                    req_id = message.get("id")
                    if req_id is not None and resp.get("id") != req_id:
                        logger.warning(
                            "MCP response id mismatch [%s]: expected %s, got %s",
                            self.name, req_id, resp.get("id"))
                        return None
                    return resp
            except Exception as e:
                logger.warning("MCP _send failed [%s]: %s", self.name, e)
                return None

    def call_tool(self, tool_name: str, arguments: dict) -> Optional[dict]:
        """调用 MCP 工具"""
        req_id = self._next_id
        self._next_id += 1
        return self._send({
            "jsonrpc": "2.0", "id": req_id,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        })

    def get_tools(self) -> list[MCPToolInfo]:
        return self._tools

    def disconnect(self):
        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=2)
            for pipe in (self._process.stdin, self._process.stdout, self._process.stderr):
                if pipe:
                    try:
                        pipe.close()
                    except Exception:
                        pass
            self._process = None
            self._connected = False


class MCPClientPool:
    """管理多个 MCP Server 连接"""

    def __init__(self, config=None):
        self._config = config
        self._clients: dict[str, MCPClient] = {}
        self._lock = threading.RLock()

    def load_from_config(self) -> int:
        """从 settings.toml 加载并连接 MCP servers"""
        if not self._config:
            return 0
        mcp_section = self._config.data.get("mcp", {})
        servers = mcp_section.get("servers", []) if isinstance(mcp_section, dict) else []
        connected = 0
        with self._lock:
            for srv in servers:
                if not srv.get("enabled", True):
                    continue
                client = MCPClient(
                    name=srv["name"],
                    command=srv["command"],
                    args=srv.get("args", []),
                    env=srv.get("env", {}),
                )
                if client.connect():
                    self._clients[srv["name"]] = client
                    connected += 1
        return connected

    def get_all_tools(self) -> list[tuple[str, MCPToolInfo]]:
        """获取所有 MCP 工具（server_name, tool_info）"""
        with self._lock:
            tools = []
            for name, client in self._clients.items():
                for tool in client.get_tools():
                    tools.append((name, tool))
            return tools

    def call_tool(self, server_name: str, tool_name: str, arguments: dict) -> Optional[dict]:
        with self._lock:
            client = self._clients.get(server_name)
            if client:
                return client.call_tool(tool_name, arguments)
            return None

    def disconnect_all(self):
        with self._lock:
            for client in self._clients.values():
                client.disconnect()
