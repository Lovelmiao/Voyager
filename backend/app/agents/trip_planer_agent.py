import json
import os
import re
from datetime import date
from typing import TypedDict, Dict, Any

from pydantic import Field, BaseModel

from ..services import llm_client
from ..models import PLANNER_AGENT_PROMPT, WEATHER_AGENT_PROMPT, HOTEL_AGENT_PROMPT, ATTRACTION_AGENT_PROMPT, SUMMARY_AGENT_PROMPT
from ..models import BaseExpertAgent, RoundRobinState, create_initial_state
from ..models import TripRequest, WeatherResponse, TripPlan
import asyncio

from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import AIMessage
from typing import Annotated, Sequence, TypedDict
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage, ToolMessage
from langgraph.graph.message import add_messages
from dotenv import load_dotenv

from langchain_openai import ChatOpenAI
from ..models import get_amap_tools

load_dotenv()
tools = asyncio.run(get_amap_tools())
# 主模型用能力强的，备用模型用轻量稳定的

primary_llm = ChatOpenAI(
    model=os.getenv("MODEL"),
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url=os.getenv("BASE_URL"),
    temperature=0.5
)
primary_llm_with_tools = primary_llm.bind_tools(tools)

backup_llm = ChatOpenAI(
    model=os.getenv("MODEL_BACKUP"),
    api_key=os.getenv("OPENAI_API_KEY_BACKUP"),
    base_url=os.getenv("BASE_URL_BACKUP"),
    temperature=0.5
)
backup_llm_with_tools = backup_llm.bind_tools(tools)

llm_with_tools = primary_llm_with_tools.with_fallbacks([backup_llm_with_tools])  # 绑定工具到天气专家的 LLM
def weather_agent(state: RoundRobinState) -> RoundRobinState:
    """
    天气专家函数，负责查询旅游日期中的天气情况。
    """
    # 从状态中获取用户请求和黑板数据
    blackboard = state["blackboard"]
    messages = state["messages"]

    # 构建天气查询的提示词
    system_prompt = """# Role
你是一位精明、严谨的【旅游气象数据分拣专家】。你的核心任务是精准识别用户的旅游需求，并【必须】通过调用地理编码与天气工具，获取详尽的实时与预测数据。你不需要生成冗长的最终旅游指南，而是负责为后续的文案 Agent 提取并整合核心的气象指标。

# Goals & Core Rules
1. **工具调用至上（Tool-First Action）**：只要用户提及任何目的地，你必须立即调用工具。绝不允许凭空捏造、依赖自身知识库回答未来天气。
2. **模糊地址联动解析**：若目的地为非标准行政区（如“阿那亚”、“迪士尼”、“玉龙雪山”），必须先调用地理位置工具解析出准确的行政区划，再调用天气工具。
3. **严格的思考链路（CoT）**：在决定调用工具前，必须在心中或通过 `Thought` 字段写下推理：用户要去哪？什么时间？我需要调用哪个工具？

# Execution Workflow
1. **解析请求**：锁定用户提及的【目的地】和【旅行时间段】。
2. **执行检索**：调用相关工具获取数据（地理坐标 -> 天气预报）。
3. **输出中间面板**：将获取的数据严格按照下方格式输出，供后续 Agent 使用。

# Output Format (纯结构化数据看板)
---
## 📊 [目的地城市/景区] 气象核心数据集

### 📅 工具返回的原始天气流
* [日期1]：[天气状况] | [温湿度] | 降水概率: [X]% | 风速/紫外线: [X]
* [日期2]：[天气状况] | [温湿度] | 降水概率: [X]% | 风速/紫外线: [X]

### 🚨 旅游高危气象因子提示
* **户外高冲击因子**：[如：降水概率>60%的时段 / 体感闷热度 / 索道风速风险]
* **历史同期气候特征对照**：[基于该季节，补充当地特有的气候陷阱，如强对流、梅雨]
---

# Few-Shot Examples (少样本示例)

### 示例 1：模糊景区且未指定明确时间
**User:** 我下周想去阿那亚玩三天，帮我看看天气。
**Thought:** 1. 目的地是“阿那亚”，属于模糊景区，我需要先知道它的具体行政区划。
2. 时间是“下周”，需要查询未来天气预报。
3. 动作：首先调用地理位置查询工具查找“阿那亚”。
**Call Tool:** `maps_regeocode(query="阿那亚")`
*(工具返回：河北省秦皇岛市昌黎县)*
**Thought:** 已经获取具体位置秦皇岛昌黎，现在调用天气工具查询下周（未来7天）的天气预报。
**Call Tool:** `maps_weather(location="秦皇岛", days=7)`
*(工具返回天气数据，Agent 格式化输出数据看板...)*

### 示例 2：标准城市且时间明确
**User:** 7月18号去重庆玩4天，天气怎么样？
**Thought:**
1. 目的地是标准城市“重庆”。
2. 时间是7月18号起共4天。
3. 动作：直接调用天气工具查询重庆该时段预报。
**Call Tool:** `maps_weather(location="重庆", date="2026-07-18", days=4)`
*(工具返回天气数据，Agent 格式化输出数据看板...)*
"""
    human_prompt = f"""
【当前数据板(Blackboard Data)】
{json.dumps(state['blackboard'], ensure_ascii=False)}

请严格结合上述数据板信息与你的系统规则，为我生成天气看板回复。
"""
    input = [SystemMessage(content=system_prompt)] + messages + [HumanMessage(content=human_prompt)]
    response = llm_with_tools.invoke(input)
    print(f"\n[🗣️ 发言中] 专家: Weather_agent")
    print(f"🌤️ [Weather Agent] 响应: {response}")
    if isinstance(response, AIMessage):
        blackboard["weather_result"] = response.content
    return {
        "messages": messages + [response],
        "blackboard": blackboard,
        "error_count": state.get("error_count", 0),
    }
def attraction_agent(state: RoundRobinState) -> RoundRobinState:
    """
    景点专家函数，负责查询旅游目的地的景点信息。
    """
    # 从状态中获取用户请求和黑板数据
    blackboard = state["blackboard"]
    messages = state["messages"]

    # 构建景点查询的提示词
    system_prompt = """# Role
你是一位高效、严谨的【旅游景点数据分拣与空间分析专家】。你的核心任务是精准识别用户的目的地与偏好，【必须】通过调用高德地图工具获取真实景点数据，并结合黑板（Blackboard）中的天气与距离，筛选出最优的景点数据集，为后续的规划 Agent 提供决策支撑。

# Goals & Core Rules
1. **真实性至上（No Hallucination）**：严禁凭空捏造不存在的景点。所有推荐的景点必须来自 `maps_text_search` 或 `maps_around_search` 的真实返回。
2. **工具链条联动（Tool Chain Reaction）**：
   - 模糊地标先用 `maps_geo` 获取坐标。
   - 多个景点间必须调用 `maps_distance` 评估距离合理性，严禁推荐地理冲突的行程。
3. **黑板天气强关联（Weather-Triggered Search）**：
   - 必须先检查黑板中是否有 `weather_result`。
   - **若有雨/极端天气**：关键词搜索自动增加“博物馆”、“室内”、“美术馆”、“科技馆”等词。
   - **若晴朗舒适**：关键词搜索偏向“公园”、“景区”、“户外地标”。
4. **严格的思考链路（CoT）**：在调用工具前，必须通过 `Thought` 明确：当前黑板天气是什么？用户有什么偏好？我该用什么搜索关键词？

# Execution Workflow
1. **解析请求与黑板**：获取目的地、天数、偏好，并读取黑板中的天气状态。
2. **执行检索与过滤**：
   - 调用 `maps_text_search` 获取景点。
   - 若有多个候选，调用 `maps_distance` 计算空间距离。
3. **输出中间数据集**：严格按下方格式输出，不废话，只提供核心干货数据。

# Output Format (纯结构化景点数据集)
---
## 📊 [目的地城市] 候选景点空间数据集

### 🌦️ 当前决策背景（黑板读取）
*   **黑板天气状态**：[如：有雨，触发室内检索机制 / 晴朗，触发户外检索机制]

### 📌 检索返回的真实景点列表
*   **景点 A**：[名称] | 📍 坐标: [经纬度] | ⏱️ 建议游玩: [X]小时 | 🏷️ 属性: [室内/户外]
*   **景点 B**：[名称] | 📍 坐标: [经纬度] | ⏱️ 建议游玩: [X]小时 | 🏷️ 属性: [室内/户外]

### 🚗 空间距离与路线可行性（工具计算结果）
*   **景点 A 到 景点 B 距离**：[X] 公里 | 🚦 顺路评估: [极佳/较远/不建议拼在一天]

### 🚨 景点准入与避坑因子
*   [景点 A]：[基于真实信息，标注是否需要提前预约、周一是否闭馆等硬性限制]
---

# Few-Shot Examples (少样本示例)

### 示例 1：黑板显示“有雨”，自动转向室内检索
**User:** 我后天去上海玩一天，推荐几个经典地方。
**Blackboard:** `{"weather_result": "2026-07-17 上海大雨，降水概率 85%"}`
**Thought:** 
1. 目的地是上海，时间是后天。
2. 检查黑板发现有大雨（降水概率85%），我必须触发“雨天室内检索机制”。
3. 动作：调用高德搜索工具，检索上海市内的博物馆和美术馆。
**Call Tool:** `maps_text_search(query="上海 博物馆 美术馆", city="上海")`
*(工具返回：上海博物馆、中华艺术宫等数据)*
**Thought:** 已经获取室内景点。为了评估它们之间是否离得近，我需要获取它们的距离。先用 `maps_distance` 计算上海博物馆到中华艺术宫的距离。
**Call Tool:** `maps_distance(origin="上海博物馆", destination="中华艺术宫")`
*(工具返回距离数据，Agent 格式化输出景点数据集...)*

### 示例 2：普通晴天检索与距离计算
**User:** 帮我看看杭州西湖周边的景点，想去两三个地方。
**Blackboard:** `{"weather_result": "2026-07-17 杭州多云，适宜户外"}`
**Thought:**
1. 目的地是杭州西湖周边。天气适宜户外。
2. 动作：首先获取“西湖”的经纬度。
**Call Tool:** `maps_geo(address="杭州西湖")`
*(工具返回西湖坐标: [120.14, 30.24])*
**Thought:** 拿到西湖坐标后，使用周边搜索工具检索周边的公园和人文景点。
**Call Tool:** `maps_around_search(location="120.14,30.24", keywords="景点", radius=3000)`
*(工具返回：苏堤、断桥、雷峰塔等数据，Agent 格式化输出景点数据集...)*"""
    human_prompt = f"""
【当前数据板(Blackboard Data)】
{json.dumps(state['blackboard'], ensure_ascii=False)}

请严格结合上述数据板信息与你的系统规则，为我生成景点看板回复。
"""
    input = [SystemMessage(content=system_prompt)] + messages + [HumanMessage(content=human_prompt)]
    response = llm_with_tools.invoke(input)
    print(f"\n[🗣️ 发言中] 专家: Attraction_agent")
    print(f"🌤️ [Attraction Agent] 响应: {response}")
    if isinstance(response, AIMessage):
        blackboard["attraction_result"] = response.content
    return {
        "messages": messages + [response],
        "blackboard": blackboard,
        "error_count": state.get("error_count", 0),
    }
def hotel_agent(state: RoundRobinState) -> RoundRobinState:
    """
    酒店专家函数，负责查询旅游目的地的酒店信息。
    """
    # 从状态中获取用户请求和黑板数据
    blackboard = state["blackboard"]
    messages = state["messages"]

    # 构建酒店查询的提示词
    system_prompt = """# Role
你是一位高效、精准的【旅游酒店数据分拣与空间分析专家】。你的核心任务是精准识别用户的住宿需求，【必须】调用高德地图工具获取真实的酒店数据，并结合黑板（Blackboard）中已有的景点坐标，确保酒店具有极佳的交通连贯性。

# Goals & Core Rules
1. **真实与空间联动（Location-Based Search）**：严禁凭空捏造酒店。必须优先读取黑板中的 `attraction_result`（景点数据集），围绕核心景点或其几何中心调用工具检索酒店，确保“住行合一”。
2. **预算与星级强过滤**：严格对照用户提及的预算（如“快捷酒店”、“高端度假”、“五星级”）选择对应的关键词进行检索。
3. **严格的思考链路（CoT）**：在调用工具前，必须通过 `Thought` 明确：景点黑板里推荐了哪几个核心位置？用户的预算级别是什么？我该围绕哪个坐标点搜索周边酒店？

# Execution Workflow
1. **解析黑板**：读取目的地、预算偏好，以及黑板中前序 Agent 存入的【核心景点坐标】。
2. **执行周边检索**：调用 `maps_around_search` 或 `maps_text_search` 查找酒店。
3. **输出中间数据集**：严格按下方格式输出数据，不废话。

# Output Format (纯结构化酒店数据集)
---
## 🏨 [目的地城市] 候选酒店空间数据集

### 🎯 空间定位背景（黑板读取）
*   **锚定核心景点/商圈**：[如：围绕黑板中的景点A（外滩）进行周边 2公里 检索]

### 📌 检索返回的真实酒店列表
*   **酒店 A**：[名称] | 📍 坐标: [经纬度] | 💰 档次/价格区间: [快捷/高档/豪华] | 🛣️ 距离核心景点: [X]米
*   **酒店 B**：[名称] | 📍 坐标: [经纬度] | 💰 档次/价格区间: [快捷/高档/豪华] | 🛣️ 距离核心景点: [X]米
---

# Few-Shot Examples (少样本示例)

**User:** 我想在西湖附近找个便宜点的快捷酒店住。
**Blackboard:** `{"attraction_result": "核心景点：雷峰塔[120.14, 30.23], 断桥[120.15, 30.26]"}`
**Thought:** 
1. 目的地是杭州西湖，用户明确要求在“西湖附近”。
2. 读取黑板发现核心景点雷峰塔坐标为 [120.14, 30.23]，用户预算是“便宜的快捷酒店”。
3. 动作：围绕雷峰塔坐标，半径2000米内，检索关键词为“快捷酒店”或“青年旅舍”的住宿。
**Call Tool:** `maps_around_search(location="120.14,30.23", keywords="快捷酒店", radius=2000)`
*(工具返回：汉庭酒店西湖店、如家酒店等数据，Agent 格式化输出酒店数据集...)*
"""
    human_prompt = f"""
    【当前数据板(Blackboard Data)】
    {json.dumps(state['blackboard'], ensure_ascii=False)}

    请严格结合上述数据板信息与你的系统规则，为我生成酒店看板回复。
    """
    input = [SystemMessage(content=system_prompt)] + messages + [HumanMessage(content=human_prompt)]
    response = llm_with_tools.invoke(input)
    print(f"\n[🗣️ 发言中] 专家: Hotel_agent")
    print(f"🌤️ [Hotel_Agent] 响应: {response}")
    if isinstance(response, AIMessage):
        blackboard["hotel_result"] = response.content
    return {
        "messages": messages + [response],
        "blackboard": blackboard,
        "error_count": state.get("error_count", 0),
    }

summary_llm = primary_llm.with_structured_output(TripPlan)
def summary_agent(state: RoundRobinState) -> RoundRobinState:
    """
    汇总专家函数，负责整合天气、景点、酒店等信息，生成最终的旅游行程规划。
    """
    messages = state.get("messages")
    blackboard = state.get("blackboard")
    system_prompt = f"""# Role
你是一位逻辑极其严密的【旅游时空数据融合专家】。你的核心职责是读取黑板中由各专家提供的【真实核心数据集】，将它们在时空逻辑上进行深度融合成一体化的旅游方案，为结构化输出模型提供无污染、高密度的推理逻辑链。

# Core Rules
1. **绝对禁止任何标记语言**：不要输出 Markdown 标题（如 #, ##）、不要输出 HTML/XML 标签（如 <Sequence>）、不要输出复杂的表格。只输出清晰、直观的段落和文字陈述。
2. **绝对忠于黑板数据**：严禁凭空捏造任何天气、景点或酒店。
3. **完成时空闭环推导**：
   - 将【天气数据】与【景点属性】融合：下雨天推导出的当天路线必须为室内景点；晴朗天推导出的当天路线必须为户外景区。
   - 将【景点位置】与【酒店选址】融合：分析出哪些酒店离这几天推荐的景点物理距离最近、交通最顺路。

# Input Data (当前黑板数据集)
---
【原始用户需求】：{blackboard["request"]}
【天气专家输入】：{blackboard["weather_result"]}
【景点专家输入】：{blackboard["attraction_result"]}
【酒店专家输入】：{blackboard["hotel_result"]}
---

# Output Context Guide
请将上述零散的数据，融合成一个包含以下要素的连续时空推导链：
1. 明确行程的目的地。
2. 按天（第1天、第2天...）详细梳理：包含具体日期、天气特征、推荐的游玩强度、串联的真实景点顺序，以及当天的天气防坑应对举措。
3. 从数据集中筛选出地理位置最顺路的酒店，并推导其空间和交通连贯性的具体优势。
4. 综合多日天气，推导出整体的白天与夜间穿搭方案，以及必须携带的防护装备。
"""
    human_prompt = f"""
    请严格结合上述数据板信息与你的系统规则，为我生成最终的旅游指南。
    """
    input = [SystemMessage(content=system_prompt)] + messages + [HumanMessage(content=human_prompt)]
    response = summary_llm.invoke(input)
    print(f"\n[🗣️ 发言中] 专家: Summary_agent")
    print(f"🌤️ [Summary_Agent] 响应: {response}")
class RouteDecision(BaseModel):
    next_speaker: str = Field(
        description="下一步发言的专家，必须是以下之一: Hotel_Expert, Weather_Expert, Attraction_Expert, Flight_Expert, Summary_Expert, END"
    )

orchestrator_llm = primary_llm.with_structured_output(RouteDecision)


def orchestrator_updater(state: RoundRobinState) -> dict:
    """
    智能主持人：阅读数据板（Blackboard）的完整度与清洗后的对话历史，
    动态或按序决定下一个发言的节点，并在模型故障时进行工程容错。
    """
    messages = state.get("messages", [])
    blackboard = state.get("blackboard", {})

    # 核心硬规则：如果上一条消息正在触发工具调用，绝对不切换发言人，由 router 接管去跑工具
    if messages and hasattr(messages[-1], "tool_calls") and messages[-1].tool_calls:
        return {}

        # 1. 组装让主持人能够“看清全局”的系统提示词
    # 注入当前数据板的状态，让主持人知道哪些专家已经交卷了
    system_prompt = f"""# Role
你是一个极其严谨的 Agent 智能圆桌会议主持人，负责调度旅游行程规划工作流。

# Available Experts
- Weather_Expert (天气专家): 负责获取并分析目的地天气。
- Attraction_Expert (景点专家): 负责筛选空间合理的真实景点。
- Hotel_Expert (酒店专家): 负责围绕景点寻找就近的顺路酒店。
- Summary_Expert (汇总专家): 负责将全量数据最终打包成结构化对象交付。

# Current Blackboard Status (当前数据板状态)
* 天气数据完成度: {"【已完成】" if blackboard.get("weather_result") else "【未开始/未完成】"}
* 景点数据完成度: {"【已完成】" if blackboard.get("attraction_result") else "【未开始/未完成】"}
* 酒店数据完成度: {"【已完成】" if blackboard.get("hotel_result") else "【未开始/未完成】"}

# Scheduling Logic & Rules
1. 你的核心目标是检查数据板。当且仅当 Weather, Attraction, Hotel 三个数据板【全部完成】时，才能调度 Summary_Expert 进行最终大汇总。
2. 推荐的线性推进流程为：Weather_Expert -> Attraction_Expert -> Hotel_Expert -> Summary_Expert。
3. 如果前面的专家因为数据缺失、地址模糊等原因需要补充信息，你可以允许其连续发言或相互补充，但若数据已齐备，请立刻推向下一个环节。
"""

    # 2. 修正：将真实的对话历史和上下文喂给模型
    chat_history = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"这是当前已产生的对话上下流水，请据此决策下一步谁发言：\n{messages[-5:]}")
        # 喂入最近几条关键对话，防止 Token 爆炸
    ]

    next_speaker = None

    # 3. 正常调用大模型决策（配合你已经绑定的 with_structured_output）
    try:
        # 确保你的 llm 已经绑定了结构化输出，如 llm_orchestrator = llm.with_structured_output(RouterSchema)
        res = orchestrator_llm.invoke(chat_history)
        next_speaker = res.next_speaker
        print(f"\n🎬 [主持人智能决策] 成功调度至: {next_speaker}")
    except Exception as e:
        print(f"⚠️ [主持人LLM异常] {e}，启动工程兜底轮转方案。")

    # 4. 容错与防死锁拦截（移至 LLM 决策之后，作为终极安全网）
    current_speaker = state.get("next_speaker")
    last_message_sender = getattr(messages[-1], "name", None) if messages else None

    # 状态退化判定：如果模型没给出结果，或者模型抽风指定了刚才刚发过言且没用工具的专家（造成死锁）
    if not next_speaker or (next_speaker == last_message_sender and next_speaker == current_speaker):
        fallback_flow = {
            None: "Weather_Expert",
            "Weather_Expert": "Attraction_Expert",
            "Attraction_Expert": "Hotel_Expert",
            "Hotel_Expert": "Summary_Expert",
            "Summary_Expert": "END"
        }
        # 如果当前数据板全部齐全，强制直跳 Summary
        if blackboard.get("weather_result") and blackboard.get("attraction_result") and blackboard.get("hotel_result"):
            next_speaker = "Summary_Expert"
        else:
            next_speaker = fallback_flow.get(current_speaker, "Weather_Expert")
        print(f"🔄 [防死锁硬拦截/兜底] 强制切换至下一物理节点: {next_speaker}")

    print(f"🎬 [主持人公告] 最终交出话权的专家是: {next_speaker}")
    return {"next_speaker": next_speaker}
# --- 条件路由函数（保持物理连线简洁清晰） ---
def router(state: RoundRobinState):
    """根据上一条消息是否包含 tool_calls，决定去跑工具还是去问主持人"""
    messages = state.get("messages", [])
    if not messages:
        return "call_orchestrator"

    last_message = messages[-1]
    current_speaker = state.get("next_speaker")

    # 检查当前发言的专家是否抛出了工具调用请求
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        routing_map = {
            "Weather_Expert": "call_weather_tools",
            "Attraction_Expert": "call_attraction_tools",
            "Hotel_Expert": "call_hotel_tools"
        }
        return routing_map.get(current_speaker, "call_orchestrator")

    return "call_orchestrator"

def router_after_orchestrator(state: RoundRobinState):
    """主持人决定发言人后，分流到对应的物理专家节点"""
    next_speaker = state.get("next_speaker", "END")

    if "Weather_Expert" in next_speaker: return "to_weather"
    if "Attraction_Expert" in next_speaker: return "to_attraction"
    if "Hotel_Expert" in next_speaker: return "to_hotel"
    if "Summary_Expert" in next_speaker: return "to_summary"
    return "end"


# ==========================================
# 6. 构建并编译图
# ==========================================
workflow = StateGraph(RoundRobinState)

# 注册专家节点
workflow.add_node("Hotel_Expert", hotel_agent)
workflow.add_node("Weather_Expert", weather_agent)
workflow.add_node("Attraction_Expert", attraction_agent)
workflow.add_node("Summary_Expert", summary_agent)
workflow.add_node("Orchestrator", orchestrator_updater)

# 🚀 【核心修复】：为 ToolNode 提供和 Agent 100% 对应的精准工具子集，绝不混用 tools 全量列表！
hotel_tools_list = tools
weather_tools_list = tools
attraction_tools_list = tools

workflow.add_node("Hotel_Tools", ToolNode(hotel_tools_list))
workflow.add_node("Weather_Tools", ToolNode(weather_tools_list))
workflow.add_node("Attraction_Tools", ToolNode(attraction_tools_list))

# 连线
workflow.add_edge(START, "Orchestrator")

workflow.add_conditional_edges(
    "Orchestrator",
    router_after_orchestrator,
    {
        "to_hotel": "Hotel_Expert",
        "to_weather": "Weather_Expert",
        "to_attraction": "Attraction_Expert",
        "to_summary": "Summary_Expert",
        "end": END
    }
)

expert_routing_targets = {
    "call_orchestrator": "Orchestrator",
    "call_hotel_tools": "Hotel_Tools",
    "call_weather_tools": "Weather_Tools",
    "call_attraction_tools": "Attraction_Tools"
}


workflow.add_conditional_edges("Hotel_Expert", router, expert_routing_targets)
workflow.add_conditional_edges("Weather_Expert", router, expert_routing_targets)
workflow.add_conditional_edges("Attraction_Expert", router, expert_routing_targets)

# 连线回流

workflow.add_edge("Hotel_Tools", "Hotel_Expert")
workflow.add_edge("Weather_Tools", "Weather_Expert")
workflow.add_edge("Attraction_Tools", "Attraction_Expert")
workflow.add_edge("Summary_Expert", END)

app = workflow.compile()



if __name__ == "__main__":
    trip = TripRequest(
        start_city="上海",
        end_city="北京",
        start_date=date(2026, 7, 15),
        end_date=date(2026, 7, 20),
        budget=2000,
        transportation="高铁",
        accommodation="经济型酒店",
        preferences=["历史文化", "美食"],
        addition_information="希望多安排一些博物馆"
    )
    request = f"规划从{trip.start_city}到{trip.end_city}的旅游行程，日期从{trip.start_date}到{trip.end_date}，预算为{trip.budget}元，交通方式为{trip.transportation}，住宿偏好为{trip.accommodation}，旅行偏好包括{', '.join(trip.preferences)}。额外要求：{trip.addition_information}"
    initial_input = create_initial_state(request)
    # 开启流式输出，观察圆桌会议的讨论动态
    async def main():
        async for namespace, event in app.astream(
                initial_input,
                subgraphs=True,
        ):
            print("事件：",namespace, event)
    asyncio.run(main())