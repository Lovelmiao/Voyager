import uuid
from typing import TypedDict, Annotated

import requests
from langchain_core.messages import BaseMessage, AIMessage, HumanMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
import os
from dotenv import load_dotenv
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.constants import START
from langgraph.graph import add_messages, StateGraph
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel, Field
from langgraph.checkpoint.memory import InMemorySaver
load_dotenv()
InMemorySaver()
class WeatherInput(BaseModel):
    city: str = Field(
        description="需要查询天气的城市名称，例如：北京、上海、Singapore"
    )
class State(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]

@tool(args_schema=WeatherInput)
def get_weather(city: str) -> str:
    """
    通过 wttr.in API查询指定城市的实时天气。
    """
    url = f"https://wttr.in/{city}?format=j1"

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        current_condition = data['current_condition'][0]
        weather_desc = current_condition['weatherDesc'][0]['value']
        temperature = current_condition['temp_C']

        return {
            "city": city,
            "weather": weather_desc,
            "temperature": temperature,
        }

    except requests.exceptions.RequestException as e:
        return f"查询天气时发生错误网络: {e}"

    except (KeyError, IndexError) as e:
        return "查询天气时发生错误，无法解析返回的数据。"

llm = ChatOpenAI(
        model=os.getenv("MODEL"),
        api_key=os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("BASE_URL"),
        temperature=0.5,
)
tools = [get_weather]
llm_with_tools = llm.bind_tools(tools)

def chatbot(state: State) -> str:
    response = llm_with_tools.invoke(state["messages"])
    return {
        "messages": response,
    }

tool_node = ToolNode(tools)

def should_continue(state: State):
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        return "tools"
    return "__end__"

builder = StateGraph(State)
builder.add_node("chatbot", chatbot)
builder.add_node("tools", tool_node)

builder.add_edge(START, "chatbot")
builder.add_conditional_edges(
    "chatbot",
    should_continue,
)
builder.add_edge("tools", "chatbot")

# MEMORY_TYPE = "memory"
MEMORY_TYPE="sqlite"
# MEMORY_TYPE="postgres"


def get_checkpointer():
    if MEMORY_TYPE == "memory":
        from langgraph.checkpoint.memory import InMemorySaver
        return InMemorySaver()
    if MEMORY_TYPE == "sqlite":
        from langgraph.checkpoint.sqlite import SqliteSaver
        return SqliteSaver.from_conn_string(
            "checkpoints.db"
        )
    if MEMORY_TYPE == "postgres":
        from langgraph.checkpoint.postgres import PostgresSaver
        saver = PostgresSaver.from_conn_string(
            "postgresql://postgres:postgre@localhost:5432/agent"
        )
        return saver
    raise ValueError("Unknown memory type")
memory = get_checkpointer()


with memory as memory:
    memory.setup()
    graph = builder.compile(
        checkpointer=memory
    )

    config = {
        "configurable": {
            "thread_id": "8ac7f87e-5e2f-4a3b-87b6-d742147ba67a"
        }
    }

    while True:
        question = input("User: ")

        if question == "exit":
            break

        result = graph.invoke(
            {
                "messages": [
                    HumanMessage(content=question)
                ]
            },
            config=config
        )

        print(result["messages"][-1])