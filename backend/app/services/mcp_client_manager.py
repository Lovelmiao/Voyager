import json
import os
from typing import Dict, List, Optional
from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient


class MCPClientManager:

    def __init__(self):
        self._servers = {}
        self._client: Optional[MultiServerMCPClient] = None
        self._tools: List[BaseTool] = []

    def load_config(self, path):
        with open(path, "r", encoding="utf-8") as f:
            config = json.load(f)
        url = config["mcpServers"]["amap"]["url"]
        url = url.replace("${AMAP_API_KEY}", os.environ["AMAP_API_KEY"])

        config["mcpServers"]["amap"]["url"] = url
        self._servers = config.get("mcpServers", {})

    async def connect(self):
        self._client = MultiServerMCPClient(self._servers)
        self._tools = await self._client.get_tools()
        for tool in self._tools:
            print("=" * 50)
            print("name:", tool.name)
            print("type:", type(tool))
            print("coroutine:", getattr(tool, "coroutine", None))
            print("func:", getattr(tool, "func", None))

    async def refresh_tools(self):
        if not self._client:
            raise RuntimeError("MCP client not connected")

        self._tools = await self._client.get_tools()

    def get_tools(self):
        return self._tools

    @property
    def tool_names(self):
        return [t.name for t in self._tools]