import os

from langgraph.constants import END, START
from langgraph.graph import StateGraph

from app.services import MCPClientManager, ToolManager, MemoryManager, ToolExecutor
from app.base import RoundRobinState, AgentRuntime
from app.agents import router, create_memory_loader, orchestrator, create_weather_expert, create_attraction_expert,create_hotel_expert,create_traffic_expert,summary_expert,create_add_memory
import os

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

def get_checkpointer():
    memory_type = os.getenv("MEMORY_TYPE")

    if memory_type == "memory":
        return InMemorySaver()

    elif memory_type == "sqlite":
        return SqliteSaver.from_conn_string(
            "checkpoints.db"
        )
    elif memory_type == "postgres":
        return AsyncPostgresSaver.from_conn_string(
            "postgresql://postgres:postgre@localhost:5432/agent"
        )
    raise ValueError(
        f"Unknown MEMORY_TYPE: {memory_type}"
    )

async def init_runtime():
    mcp_manager = MCPClientManager()
    tool_manager = ToolManager(mcp_manager)
    tool_executor = ToolExecutor()
    memory_manager = MemoryManager()
    checkpointer_cm = AsyncPostgresSaver.from_conn_string(
        "postgresql://postgres:postgre@localhost:5432/agent"
    )

    checkpointer = await checkpointer_cm.__aenter__()

    await checkpointer.setup()
    mcp_manager.load_config(os.getenv("MCP_SERVERS_PATH"))
    await mcp_manager.connect()

    tool_manager.initialize(
        os.getenv("TOOL_REGISTRY_PATH"),
        os.getenv("AGENT_PERMISSIONS_PATH")
    )
    return AgentRuntime(
        tool_manager,
        tool_executor,
        memory_manager,
        checkpointer,
    )

def build_graph(runtime: AgentRuntime):
    tool_manager = runtime.tool_manager
    tool_executor = runtime.tool_executor
    memory_manager = runtime.memory_manager
    memory_checkpoint = runtime.memory_checkpoint

    # 模拟登录
    user_id = "0e287944-f3ee-45d3-a48f-72d2b32af793"
    session_id = "c1390202-838c-462c-807a-0bfaf11a1833"

    workflow = StateGraph(RoundRobinState)

    workflow.add_node("load_memory", create_memory_loader(memory_manager))
    workflow.add_node("orchestrator", orchestrator)
    workflow.add_node("weather_expert", create_weather_expert(tool_manager, tool_executor, memory_manager))
    workflow.add_node("attraction_expert", create_attraction_expert(tool_manager, tool_executor, memory_manager))
    workflow.add_node("hotel_expert", create_hotel_expert(tool_manager, tool_executor, memory_manager))
    workflow.add_node("traffic_expert", create_traffic_expert(tool_manager, tool_executor, memory_manager))
    workflow.add_node("summary_expert", summary_expert)
    workflow.add_node("add_memory", create_add_memory(memory_manager))

    workflow.add_edge(START, "load_memory")
    workflow.add_edge("load_memory", "orchestrator")
    workflow.add_conditional_edges(
        "orchestrator",
        router,
        {
            "weather_expert": "weather_expert",
            "hotel_expert": "hotel_expert",
            "attraction_expert": "attraction_expert",
            "traffic_expert": "traffic_expert",
            "summary_expert": "summary_expert",
        }
    )
    workflow.add_edge("weather_expert", "orchestrator")
    workflow.add_edge("hotel_expert", "orchestrator")
    workflow.add_edge("attraction_expert", "orchestrator")
    workflow.add_edge("traffic_expert", "orchestrator")
    workflow.add_edge("summary_expert", "add_memory")
    workflow.add_edge("add_memory", END)

    app = workflow.compile()
    return app