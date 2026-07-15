import json
import re
from datetime import datetime, timedelta

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from typing import Annotated, Sequence, TypedDict, Dict, Any
from langchain_core.messages import BaseMessage, AIMessage, AnyMessage, HumanMessage
from langgraph.graph.message import add_messages
from ..models import TripRequest

class RoundRobinState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    # 结构化的公共看板，存放机票、酒店等最终敲定的数据
    blackboard: Dict[str, Any]
    # 错误计数器，用于局部重试和熔断机制
    error_count: int
    # 当前激活的专家（用于主持人控制发言权）
    next_speaker: str


def create_initial_state(request) -> RoundRobinState:
    """根据用户的请求，初始化黑板结构"""

    # 初始化黑板骨架
    initial_blackboard = {
        "request": request,
        "attraction_result": "",
        "weather_result": "",
        "hotel_result": "",
    }

    return {
        "messages": [HumanMessage(content=f"用户请求: {json.dumps(request, ensure_ascii=False)}")],
        "blackboard": initial_blackboard,
        "error_count": 0,
        "next_speaker": ""
    }

class BaseExpertAgent:
    def __init__(self, name: str, role_prompt: str, model, tools: list = None, fallback_model=None):
        self.name = name
        self.role_prompt = role_prompt
        self.fallback_model = fallback_model

        # 1. 组装 Prompt
        self.prompt = ChatPromptTemplate.from_messages([
            ("system",
             f"""你是【{name}】。职责：{role_prompt}\n请根据群聊历史和当前看板数据发表意见。"""),
            ("placeholder", "{messages}"),

        ])

        # 2. 绑定工具 (Tool Binding)
        if tools:
            self.runnable = self.prompt | model.bind_tools(tools)
        else:
            self.runnable = self.prompt | model

    # 3. Agent 核心执行逻辑（对应 LangGraph 的一个 Node）
    def __call__(self, state: RoundRobinState, config: RunnableConfig) -> dict:
        print(f"\n[🗣️ 发言中] 专家: {self.name}")
        inputs = {"messages": state["messages"]}
        blackboard = state["blackboard"]

        try:

            response = self.runnable.invoke(inputs, config)

            if isinstance(response, AIMessage):
                response.name = self.name
                # 🌟 核心修复：洗掉返回消息里的 think 推理内容，只留纯文本给下一个节点看
                if response.content and "<think>" in response.content:
                    response.content = re.sub(r"<think>.*?</think>", "", response.content, flags=re.DOTALL).strip()
            if isinstance(response, AIMessage):
                blackboard[f"{self.name.lower()}_result"] = response.content
            return {"messages": [response], "blackboard": blackboard ,"error_count": 0}
        except Exception as e:
            print(f"❌ {self.name} 发生错误: {str(e)}")
            return {"error_count": state.get("error_count", 0) + 1}