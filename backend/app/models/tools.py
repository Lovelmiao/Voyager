# tools.py
import os
import asyncio
from typing import List
from dotenv import load_dotenv
from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

load_dotenv()


class AmapToolManager:
    """高德 MCP 工具管理器（单例模式，避免重复连接）"""
    _instance = None
    _tools: List[BaseTool] = []
    _client: MultiServerMCPClient = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(AmapToolManager, cls).__new__(cls, *args, **kwargs)
        return cls._instance

    async def initialize(self):
        """异步初始化高德 MCP 客户端并加载工具"""
        if self._tools:
            return self._tools

        amap_key = os.getenv("AMAP_API_KEY", "4cd31aba1a0bde0420bdea9950e2172c")
        if not amap_key:
            raise ValueError("未找到 AMAP_API_KEY，请在环境变量或环境变量文件中配置。")

        # 初始化高德 MCP 客户端 (Streamable HTTP 模式)
        self._client = MultiServerMCPClient(
            {
                "amap-maps-streamableHTTP": {
                    "url": f"https://mcp.amap.com/mcp?key={amap_key}",
                    "transport": "streamable_http"
                }
            }
        )

        print("【高德MCP】正在连接服务并下载地图工具箱...")
        # 核心：动态获取高德的所有工具并转化为 LangChain 的 BaseTool 格式
        self._tools = await self._client.get_tools()
        print(f"【高德MCP】成功加载工具: {[t.name for t in self._tools]}")
        return self._tools

    async def close(self):
        """关闭 MCP 客户端连接"""
        if self._client:
            await self._client.close()
            self._tools = []
            print("【高德MCP】服务连接已安全关闭。")


# 导出两个核心快捷函数供外部使用
async def get_amap_tools() -> List[BaseTool]:
    """获取高德 MCP 的所有工具列表"""
    manager = AmapToolManager()
    return await manager.initialize()


async def close_amap_connection():
    """关闭高德 MCP 连接"""
    await AmapToolManager().close()