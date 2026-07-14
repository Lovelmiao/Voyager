import os
import re
from typing import TypedDict, Dict, Any

from pydantic import Field, BaseModel

from ..services import llm_client
from ..models import PLANNER_AGENT_PROMPT, WEATHER_AGENT_PROMPT, HOTEL_AGENT_PROMPT, ATTRACTION_AGENT_PROMPT, SUMMARY_AGENT_PROMPT
from ..models import BaseExpertAgent, RoundRobinState
import asyncio


from typing import Annotated, Sequence, TypedDict
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage
from langgraph.graph.message import add_messages
from dotenv import load_dotenv

from langchain_openai import ChatOpenAI
from ..models import get_amap_tools

load_dotenv()
# 主模型用能力强的，备用模型用轻量稳定的
primary_llm = ChatOpenAI(
    model=os.getenv("MODEL"),
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url=os.getenv("BASE_URL"),
    temperature=0.5
)
backup_llm = ChatOpenAI(
    model=os.getenv("MODEL_BACKUP"),
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url=os.getenv("BASE_URL"),
    temperature=0.5
)


tools = asyncio.run(get_amap_tools())

attraction_agent = BaseExpertAgent(
    name="Attraction_Agent",
    role_prompt="负责根据用户的城市和偏好搜索景点，并提供详细的景点信息。",
    model=primary_llm,
    tools=tools,
    fallback_model=backup_llm
)

weather_agent = BaseExpertAgent(
    name="Weather_Agent",
    role_prompt="负责查询目的地天气情况，包括实时天气、未来天气以及穿衣建议。",
    model=primary_llm,
    tools=tools, # 景点专家拿地图工具
    fallback_model=backup_llm
)

# 实例化机票专家（带工具）
flight_agent = BaseExpertAgent(
    name="Flight_Agent",
    role_prompt="负责处理大交通。如果是国内航线用高德，国际航线查 Amadeus 工具。",
    model=primary_llm,
    tools=tools,
    fallback_model=backup_llm # 配备降级模型
)

# 实例化酒店专家（带工具）
hotel_agent = BaseExpertAgent(
    name="Hotel_Agent",
    role_prompt="负责根据用户需求，在预算内寻找评分最高的酒店。",
    model=primary_llm,
    tools=tools,
    fallback_model=backup_llm
)

summary_agent = BaseExpertAgent(
    name="Summary_Agent",
    role_prompt="负责整合天气、景点、酒店信息，生成最终的旅游行程单。",
    model=primary_llm,
    fallback_model=backup_llm
)


class RouteDecision(BaseModel):
    next_speaker: str = Field(
        description="下一步发言的专家，必须是以下之一: Hotel_Expert, Weather_Expert, Attraction_Expert, Flight_Expert, Summary_Expert, END"
    )


llm = ChatOpenAI(
    model="bailu-2.7",
    api_key="sk-269af1a07129f126b38d86b1df5a0c23",
    base_url="https://bailucode.com/openapi/v1",
    temperature=0.5
)
llm = llm.with_structured_output(RouteDecision)
def orchestrator_updater(state: RoundRobinState) -> dict:
    """主持人：阅读清洗后的对话历史，严格决定下一个谁发言"""

    messages = state.get("messages", [])
    if not messages:
        return {"next_speaker": "Hotel_Expert"}  # 按你 prompt 的新流程：从酒店开始

    last_message = messages[-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return {}  # 工具调用中，不切换发言人

    system_prompt = (
        "你是一个圆桌会议的主持人。当前会议的主题是规划旅游行程。\n"
        "参与专家：Hotel_Expert, Weather_Expert, Attraction_Expert, Flight_Expert, Summary_Expert。\n"
        "推荐标准流程：Hotel_Expert -> Weather_Expert -> Attraction_Expert -> Flight_Expert -> Summary_Expert。\n"
        "请根据对话历史判断进度。如果所有专家都确认完成了，请指定 Summary_Expert 行程大汇总。\n"
        """请直接输出一个 JSON 对象（不要包含任何 markdown 块或普通文本），结构如下：
        {
          "next_speaker": "下一步发言的专家",
        }
    """)

    chat_history = [SystemMessage(content=system_prompt)]

    # 🌟 核心修复：过滤并用正则清洗掉所有 <think> 标签，防止污染主持人
    for m in messages:
        if isinstance(m, (HumanMessage, AIMessage)) and m.content:
            clean_content = re.sub(r"<think>.*?</think>", "", m.content, flags=re.DOTALL).strip()
            if clean_content:
                chat_history.append(HumanMessage(content=f"{m.name or 'User'}: {clean_content}"))

    # 3. 如果大模型抽风导致硬死锁（上一句是某个专家说的，但它又指定这个专家，且没用工具）
    current_speaker = state.get("next_speaker", "Hotel_Expert")
    last_message_sender = getattr(messages[-1], "name", None)

    if last_message_sender == current_speaker:
        fallback_flow = {
            "Hotel_Expert": "Weather_Expert",
            "Weather_Expert": "Attraction_Expert",
            "Attraction_Expert": "Flight_Expert",
            "Flight_Expert": "Summary_Expert",
            "Summary_Expert": "END"
        }
        next_node = fallback_flow.get(current_speaker, "Summary_Expert")
        print(f"🔄 [防死锁硬拦截] 专家 {current_speaker} 未正常交出话权，主持人强行切换至: {next_node}")
        return {"next_speaker": next_node}

    # 4. 正常调用结构化模型
    try:
        res = llm.invoke(chat_history)
        print(type(res))
        print(f"🎬 [主持人] 决策结果: {res}")
        next_speaker = res.next_speaker
    except Exception:
        # 兜底降级方案
        print("❌ [主持人] 决策失败，使用默认轮转方案。")
        next_speaker = "Weather_Expert"

    print(f"🎬 [主持人公告] 下一位发言专家是: {next_speaker}")
    return {"next_speaker": next_speaker}
# --- 条件路由函数：决定物理连线的走向 ---

from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode


def router(state: RoundRobinState):
    messages = state.get("messages", [])
    if not messages:
        return "call_orchestrator"

    last_message = messages[-1]
    current_speaker = state.get("next_speaker")

    # 检查是否调用工具
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        if current_speaker == "Flight_Expert": return "call_flight_tools"
        if current_speaker == "Hotel_Expert": return "call_hotel_tools"
        if current_speaker == "Weather_Expert": return "call_weather_tools"
        if current_speaker == "Attraction_Expert": return "call_attraction_tools"

    return "call_orchestrator"


def router_after_orchestrator(state: RoundRobinState):
    next_speaker = state.get("next_speaker")
    if "Flight_Expert" in next_speaker: return "to_flight"
    if "Hotel_Expert" in next_speaker: return "to_hotel"
    if "Weather_Expert" in next_speaker: return "to_weather"
    if "Attraction_Expert" in next_speaker: return "to_attraction"
    if "Summary_Expert" in next_speaker: return "to_summary"
    return "end"


# ==========================================
# 6. 构建并编译图
# ==========================================
workflow = StateGraph(RoundRobinState)

# 注册专家节点
workflow.add_node("Flight_Expert", flight_agent)
workflow.add_node("Hotel_Expert", hotel_agent)
workflow.add_node("Weather_Expert", weather_agent)
workflow.add_node("Attraction_Expert", attraction_agent)
workflow.add_node("Summary_Expert", summary_agent)
workflow.add_node("Orchestrator", orchestrator_updater)

# 🚀 【核心修复】：为 ToolNode 提供和 Agent 100% 对应的精准工具子集，绝不混用 tools 全量列表！
flight_tools_list = tools
hotel_tools_list = tools
weather_tools_list = tools
attraction_tools_list = tools

workflow.add_node("Flight_Tools", ToolNode(flight_tools_list))
workflow.add_node("Hotel_Tools", ToolNode(hotel_tools_list))
workflow.add_node("Weather_Tools", ToolNode(weather_tools_list))
workflow.add_node("Attraction_Tools", ToolNode(attraction_tools_list))

# 连线
workflow.add_edge(START, "Orchestrator")

workflow.add_conditional_edges(
    "Orchestrator",
    router_after_orchestrator,
    {
        "to_flight": "Flight_Expert",
        "to_hotel": "Hotel_Expert",
        "to_weather": "Weather_Expert",
        "to_attraction": "Attraction_Expert",
        "to_summary": "Summary_Expert",
        "end": END
    }
)

expert_routing_targets = {
    "call_orchestrator": "Orchestrator",
    "call_flight_tools": "Flight_Tools",
    "call_hotel_tools": "Hotel_Tools",
    "call_weather_tools": "Weather_Tools",
    "call_attraction_tools": "Attraction_Tools"
}

workflow.add_conditional_edges("Flight_Expert", router, expert_routing_targets)
workflow.add_conditional_edges("Hotel_Expert", router, expert_routing_targets)
workflow.add_conditional_edges("Weather_Expert", router, expert_routing_targets)
workflow.add_conditional_edges("Attraction_Expert", router, expert_routing_targets)

# 连线回流
workflow.add_edge("Flight_Tools", "Flight_Expert")
workflow.add_edge("Hotel_Tools", "Hotel_Expert")
workflow.add_edge("Weather_Tools", "Weather_Expert")
workflow.add_edge("Attraction_Tools", "Attraction_Expert")
workflow.add_edge("Summary_Expert", END)

app = workflow.compile()



if __name__ == "__main__":
    initial_input = {
        "messages": [
            HumanMessage(content="我想上海去成都玩3天，时间为2026年7月14日到7月16日，预算1500一天，请帮我规划出行、酒店、天气和景点。")
        ],
        "blackboard": {},
        "error_count": 0,
        "next_speaker": "",
    }

    # 开启流式输出，观察圆桌会议的讨论动态
    async def main():
        async for namespace, event in app.astream(
                initial_input,
                subgraphs=True,
        ):
            print(namespace, event)
    asyncio.run(main())