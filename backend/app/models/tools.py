import os
import asyncio
from typing import List
from dotenv import load_dotenv
from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

load_dotenv()

_amap_tools: List[BaseTool] | None = None


async def _init_tools() -> List[BaseTool]:
    """Async initializer — call once at startup, not at import time."""
    global _amap_tools
    if _amap_tools is not None:
        return _amap_tools

    amap_key = os.getenv("AMAP_API_KEY")
    if not amap_key:
        raise ValueError("未找到 AMAP_API_KEY，请在环境变量或 .env 文件中配置。")

    client = MultiServerMCPClient(
        {
            "amap-maps-streamableHTTP": {
                "url": f"https://mcp.amap.com/mcp?key={amap_key}",
                "transport": "streamable_http",
            }
        }
    )

    print("【高德MCP】正在连接服务并下载地图工具箱...")
    _amap_tools = await client.get_tools()
    print(f"【高德MCP】成功加载工具: {[t.name for t in _amap_tools]}")
    return _amap_tools


def get_amap_tools_sync() -> List[BaseTool]:
    """
    Synchronous accessor.

    - If tools are already initialized, returns them immediately.
    - If no event loop is running (standalone CLI), initializes synchronously.
    - If an event loop is running (FastAPI) and tools aren't set, raises.
    """
    if _amap_tools is not None:
        return _amap_tools

    # No running event loop → safe to create one (CLI mode)
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_init_tools())
        finally:
            loop.close()

    # Running event loop exists → tools should have been set by lifespan
    raise RuntimeError(
        "Amap tools not initialized. Make sure _init_tools() was awaited at startup."
    )
