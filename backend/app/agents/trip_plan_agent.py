import json
import asyncio
import sys
import uuid

from langchain_core.exceptions import OutputParserException
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langchain_core.messages import SystemMessage, HumanMessage, RemoveMessage, AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.constants import START, END
from langgraph.graph import StateGraph
from pydantic_core import ValidationError

from ..base import RoundRobinState, BaseAgent, TripPlan, RouteDecision
from ..services import MCPClientManager, ToolManager, MemoryManager
from ..services import ToolExecutor
from ..models import LLMFactory

from contextlib import nullcontext
import os


def basemessage_to_messages(messages: list) -> list[dict]:
    """
    将 BaseMessage 对象列表转换为字典列表，方便序列化和存储。
    """
    chat_history = []
    for m in messages:
        if isinstance(m, HumanMessage):
            role = "user"
        elif isinstance(m, AIMessage):
            role = "assistant"
        chat_history.append(
            {
                "role": role,
                "content": m.content,
            }
        )
    return chat_history


def get_checkpointer():
    memory_type = os.getenv("MEMORY_TYPE")

    if memory_type == "memory":
        from langgraph.checkpoint.memory import InMemorySaver
        return nullcontext(InMemorySaver())

    elif memory_type == "sqlite":
        from langgraph.checkpoint.sqlite import SqliteSaver
        return SqliteSaver.from_conn_string("checkpoints.db")

    elif memory_type == "postgres":
        return AsyncPostgresSaver.from_conn_string(
            "postgresql://postgres:postgre@localhost:5432/agent"
        )
    raise ValueError(f"Unknown MEMORY_TYPE: {memory_type}")


def fallback_router(blackboard):
    if not blackboard.get("weather_result"):
        return "weather_expert"

    if not blackboard.get("attraction_result"):
        return "attraction_expert"

    if not blackboard.get("hotel_result"):
        return "hotel_expert"

    if not blackboard.get("traffic_result"):
        return "traffic_expert"

    return "summary_expert"


def _load_memory(state: RoundRobinState, config: RunnableConfig, memory_manager) -> RoundRobinState:
    session_id = config["configurable"]["thread_id"]
    user_id = config["configurable"]["user_id"]
    user_input = state["messages"][0].content
    session_summary = memory_manager.get_summary(session_id)
    user_preference = memory_manager.search_messages(
        query=user_input,
        user_id=user_id
    )
    print("\n提取到的用户偏好信息：", user_preference)
    print("\n提取到的历史信息：", session_summary)
    if "blackboard" not in state:
        return {
            "blackboard": {},
            "next_speaker": "orchestrator",
            "session_summary": session_summary,
            "user_preference": user_preference
        }
    return {
        "next_speaker": "orchestrator",
        "session_summary": session_summary,
        "user_preference": user_preference
    }


def create_memory_loader(memory_manager):
    def memory_loader(state: RoundRobinState, config: RunnableConfig) -> RoundRobinState:
        return _load_memory(state, config, memory_manager)

    return memory_loader


def orchestrator(state: RoundRobinState) -> RoundRobinState:
    """
    智能主持人：阅读数据板（Blackboard）的完整度与清洗后的对话历史，
    动态或按序决定下一个发言的节点，并在模型故障时进行工程容错。
    """
    llm_factory = LLMFactory()
    llm_with_no, llm_with_structured_output = llm_factory.create(RouteDecision)
    messages = state["messages"]
    messages = basemessage_to_messages(messages)
    blackboard = state["blackboard"]
    # 1. 组装让主持人能够"看清全局"的系统提示词
    # 注入当前数据板的状态，让主持人知道哪些专家已经交卷了
    output_format = """
    {
        "next_speaker": "下一步发言的专家"
    }
    """
    system_prompt = f"""# Role
你是一个极其严谨的 Agent 智能圆桌会议主持人，负责调度旅游行程规划工作流。

# Available Experts
- Weather_Expert (天气专家): 负责获取并分析目的地天气。
- Attraction_Expert (景点专家): 负责筛选空间合理的真实景点。
- Hotel_Expert (酒店专家): 负责围绕景点寻找就近的顺路酒店。
- Traffic_Expert (交通规划专家): 负责规划出行路线和交通工具。
- Summary_Expert (汇总专家): 负责将全量数据最终打包成结构化对象交付。

# Current Blackboard Status (当前数据板状态)
* 天气数据完成度: {blackboard.get("weather_result") if blackboard.get("weather_result") else "【未开始/未完成】"}
* 景点数据完成度: {blackboard.get("attraction_result") if blackboard.get("attraction_result") else "【未开始/未完成】"}
* 酒店数据完成度: {blackboard.get("hotel_result") if blackboard.get("hotel_result") else "【未开始/未完成】"}
* 交通数据完成度: {blackboard.get("traffic_result") if blackboard.get("traffic_result") else "【未开始/未完成】"}

# Scheduling Logic & Rules
1. 你的核心目标是检查数据板。当且仅当 Weather, Attraction, Hotel, Traffic 四个数据板【全部完成】时，才能调度 Summary_Expert 进行最终大汇总。
2. 你需要审核数据板的内容，如果发生数据冲突，你必须要求前序专家补充或修正数据，而不是直接跳过。
3. 如果用户有新的需求，则根据用户需求调用对应的专家进行数据更新。
4. 推荐的线性推进流程为：Weather_Expert -> Attraction_Expert -> Hotel_Expert -> Traffic_Expert -> Summary_Expert。
5. 如果前面的专家因为数据缺失、地址模糊等原因需要补充信息，你可以允许其连续发言或相互补充，但若数据已齐备且无数据冲突，请立刻推向下一个环节。
6. 请直接输出一个 JSON 对象（不要包含任何 markdown 块或普通文本），结构如下：
{output_format}
"""
    # 2. 修正：将真实的对话历史和上下文喂给模型
    chat_history = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"这是当前已产生的对话上下流水，请据此决策下一步谁发言：\n{messages}")
    ]

    # 3. 正常调用大模型决策（配合你已经绑定的 with_structured_output）
    try:
        # 确保你的 llm 已经绑定了结构化输出，如llm.with_structured_output(RouterSchema)
        res = llm_with_structured_output.invoke(chat_history)
        next_speaker = res.next_speaker
        print(f"\n🎬 [主持人智能决策] 成功调度至: {next_speaker}")
    except Exception as e:
        print(f"⚠️ [主持人LLM异常] {e}，启动工程兜底轮转方案。")
        next_speaker = fallback_router(blackboard)

    print(f"🎬 [主持人公告] 最终交出话权的专家是: {next_speaker}")
    return {
        "next_speaker": next_speaker
    }


async def _weather_expert(state: RoundRobinState, config: RunnableConfig, tool_manager, tool_executor,
                          memory_manager) -> RoundRobinState:
    weather_tools = tool_manager.get_tools("weather_agent")
    trace_id = config["configurable"]["trace_id"]
    system_prompt = f"""# Role
    你是一位精明、严谨的【旅游气象数据分拣专家】。你的核心任务是精准识别用户的旅游需求，并【必须】通过调用地理编码与天气工具，获取详尽的实时与预测数据。你不需要生成冗长的最终旅游指南，而是负责为后续的文案 Agent 提取并整合核心的气象指标。

    # Goals & Core Rules
    1. **工具调用至上（Tool-First Action）**：只要用户提及任何目的地，你必须立即调用工具。绝不允许凭空捏造、依赖自身知识库回答未来天气。
    2. **模糊地址联动解析**：若目的地为非标准行政区（如"阿那亚"、"迪士尼"、"玉龙雪山"），必须先调用地理位置工具解析出准确的行政区划，再调用天气工具。
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
    **Thought:** 1. 目的地是"阿那亚"，属于模糊景区，我需要先知道它的具体行政区划。
    2. 时间是"下周"，需要查询未来天气预报。
    3. 动作：首先调用地理位置查询工具查找"阿那亚"。
    **Call Tool:** `maps_regeocode(query="阿那亚")`
    *(工具返回：河北省秦皇岛市昌黎县)*
    **Thought:** 已经获取具体位置秦皇岛昌黎，现在调用天气工具查询下周（未来7天）的天气预报。
    **Call Tool:** `maps_weather(location="秦皇岛", days=7)`
    *(工具返回天气数据，Agent 格式化输出数据看板...)*

    ### 示例 2：标准城市且时间明确
    **User:** 7月18号去重庆玩4天，天气怎么样？
    **Thought:**
    1. 目的地是标准城市"重庆"。
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
    weather_agent = BaseAgent(name="weather_agent", tools=weather_tools, system_prompt=system_prompt,
                              human_prompt=human_prompt, tool_executor=tool_executor, memory_manager=memory_manager)
    state: RoundRobinState = await weather_agent.run(state, trace_id)
    return state


def create_weather_expert(tool_manager, tool_executor, memory_manager):
    async def weather_expert(state: RoundRobinState, config: RunnableConfig) -> RoundRobinState:
        return await _weather_expert(state, config, tool_manager, tool_executor, memory_manager)

    return weather_expert


async def _attraction_expert(state: RoundRobinState, config: RunnableConfig, tool_manager, tool_executor,
                             memory_manager) -> RoundRobinState:
    attraction_tools = tool_manager.get_tools("attraction_agent")
    trace_id = config["configurable"]["trace_id"]
    system_prompt = """# Role
    你是一位高效、严谨的【旅游景点数据分拣与空间分析专家】。你的核心任务是精准识别用户的目的地与偏好，【必须】通过调用高德地图工具获取真实景点数据，并结合黑板（Blackboard）中的天气与距离，筛选出最优的景点数据集，为后续的规划 Agent 提供决策支撑。

    # Goals & Core Rules
    1. **真实性至上（No Hallucination）**：严禁凭空捏造不存在的景点。所有推荐的景点必须来自 `maps_text_search` 或 `maps_around_search` 的真实返回。
    2. **工具链条联动（Tool Chain Reaction）**：
       - 模糊地标先用 `maps_geo` 获取坐标。
       - 多个景点间必须调用 `maps_distance` 评估距离合理性，严禁推荐地理冲突的行程。
    3. **黑板天气强关联（Weather-Triggered Search）**：
       - 必须先检查黑板中是否有 `weather_result`。
       - **若有雨/极端天气**：关键词搜索自动增加"博物馆"、"室内"、"美术馆"、"科技馆"等词。
       - **若晴朗舒适**：关键词搜索偏向"公园"、"景区"、"户外地标"。
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

    ### 示例 1：黑板显示"有雨"，自动转向室内检索
    **User:** 我后天去上海玩一天，推荐几个经典地方。
    **Blackboard:** `{"weather_result": "2026-07-17 上海大雨，降水概率 85%"}`
    **Thought:**
    1. 目的地是上海，时间是后天。
    2. 检查黑板发现有大雨（降水概率85%），我必须触发"雨天室内检索机制"。
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
    2. 动作：首先获取"西湖"的经纬度。
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
    attraction_agent = BaseAgent(name="attraction_agent", tools=attraction_tools, system_prompt=system_prompt,
                                 human_prompt=human_prompt, tool_executor=tool_executor, memory_manager=memory_manager)
    state: RoundRobinState = await attraction_agent.run(state, trace_id)
    return state


def create_attraction_expert(tool_manager, tool_executor, memory_manager):
    async def attraction_expert(state: RoundRobinState, config: RunnableConfig) -> RoundRobinState:
        return await _attraction_expert(state, config, tool_manager, tool_executor, memory_manager)

    return attraction_expert


async def _hotel_expert(state: RoundRobinState, config: RunnableConfig, tool_manager, tool_executor,
                        memory_manager) -> RoundRobinState:
    hotel_tools = tool_manager.get_tools("hotel_agent")
    trace_id = config["configurable"]["trace_id"]
    system_prompt = """# Role
    你是一位高效、精准的【旅游酒店数据分拣与空间分析专家】。你的核心任务是精准识别用户的住宿需求，【必须】调用高德地图工具获取真实的酒店数据，并结合黑板（Blackboard）中已有的景点坐标，确保酒店具有极佳的交通连贯性。

    # Goals & Core Rules
    1. **真实与空间联动（Location-Based Search）**：严禁凭空捏造酒店。必须优先读取黑板中的 `attraction_result`（景点数据集），围绕核心景点或其几何中心调用工具检索酒店，确保"住行合一"。
    2. **预算与星级强过滤**：严格对照用户提及的预算（如"快捷酒店"、"高端度假"、"五星级"）选择对应的关键词进行检索。
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
    1. 目的地是杭州西湖，用户明确要求在"西湖附近"。
    2. 读取黑板发现核心景点雷峰塔坐标为 [120.14, 30.23]，用户预算是"便宜的快捷酒店"。
    3. 动作：围绕雷峰塔坐标，半径2000米内，检索关键词为"快捷酒店"或"青年旅舍"的住宿。
    **Call Tool:** `maps_around_search(location="120.14,30.23", keywords="快捷酒店", radius=2000)`
    *(工具返回：汉庭酒店西湖店、如家酒店等数据，Agent 格式化输出酒店数据集...)*
    """
    human_prompt = f"""
    【当前数据板(Blackboard Data)】
    {json.dumps(state['blackboard'], ensure_ascii=False)}

    请严格结合上述数据板信息与你的系统规则，为我生成酒店看板回复。
    """
    hotel_agent = BaseAgent(name="hotel_agent", tools=hotel_tools, system_prompt=system_prompt,
                            human_prompt=human_prompt, tool_executor=tool_executor, memory_manager=memory_manager)
    state: RoundRobinState = await hotel_agent.run(state, trace_id)
    return state


def create_hotel_expert(tool_manager, tool_executor, memory_manager):
    async def hotel_expert(state: RoundRobinState, config: RunnableConfig) -> RoundRobinState:
        return await _hotel_expert(state, config, tool_manager, tool_executor, memory_manager)

    return hotel_expert


async def _traffic_expert(state: RoundRobinState, config: RunnableConfig, tool_manager, tool_executor,
                          memory_manager) -> RoundRobinState:
    traffic_tools = tool_manager.get_tools("traffic_agent")
    trace_id = config["configurable"]["trace_id"]
    system_prompt = """# Role
    你是一位精明、严谨的【旅游气象数据分拣专家】。你的核心任务是精准识别用户的旅游需求，并【必须】通过调用地理编码与天气工具，获取详尽的实时与预测数据。你不需要生成冗长的最终旅游指南，而是负责为后续的文案 Agent 提取并整合核心的气象指标。

    # Goals & Core Rules
    1. **工具调用至上（Tool-First Action）**：只要用户提及任何目的地，你必须立即调用工具。绝不允许凭空捏造、依赖自身知识库回答未来天气。
    2. **模糊地址联动解析**：若目的地为非标准行政区（如"阿那亚"、"迪士尼"、"玉龙雪山"），必须先调用地理位置工具解析出准确的行政区划，再调用天气工具。
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
    **Thought:** 1. 目的地是"阿那亚"，属于模糊景区，我需要先知道它的具体行政区划。
    2. 时间是"下周"，需要查询未来天气预报。
    3. 动作：首先调用地理位置查询工具查找"阿那亚"。
    **Call Tool:** `maps_regeocode(query="阿那亚")`
    *(工具返回：河北省秦皇岛市昌黎县)*
    **Thought:** 已经获取具体位置秦皇岛昌黎，现在调用天气工具查询下周（未来7天）的天气预报。
    **Call Tool:** `maps_weather(location="秦皇岛", days=7)`
    *(工具返回天气数据，Agent 格式化输出数据看板...)*

    ### 示例 2：标准城市且时间明确
    **User:** 7月18号去重庆玩4天，天气怎么样？
    **Thought:**
    1. 目的地是标准城市"重庆"。
    2. 时间是7月18号起共4天。
    3. 动作：直接调用天气工具查询重庆该时段预报。
    **Call Tool:** `maps_weather(location="重庆", date="2026-07-18", days=4)`
    *(工具返回天气数据，Agent 格式化输出数据看板...)*
    """
    human_prompt = f"""
    【当前数据板(Blackboard Data)】
    {json.dumps(state['blackboard'], ensure_ascii=False)}

    请严格结合上述数据板信息与你的系统规则，为我生成交通看板回复。
    """
    traffic_agent = BaseAgent(name="traffic_agent", tools=traffic_tools, system_prompt=system_prompt,
                              human_prompt=human_prompt, tool_executor=tool_executor, memory_manager=memory_manager)
    state: RoundRobinState = await traffic_agent.run(state, trace_id)
    return state


def create_traffic_expert(tool_manager, tool_executor, memory_manager):
    async def traffic_expert(state: RoundRobinState, config: RunnableConfig) -> RoundRobinState:
        return await _traffic_expert(state, config, tool_manager, tool_executor, memory_manager)

    return traffic_expert


async def summary_expert(state: RoundRobinState) -> RoundRobinState:
    llm_factory = LLMFactory(temperature=0)
    blackboard = state["blackboard"]
    weather_res = blackboard["weather_result"]
    attraction_res = blackboard["attraction_result"]
    hotel_res = blackboard["hotel_result"]
    traffic_res = blackboard["traffic_result"]

    system_prompt = f"""你是一位逻辑极其严密的【旅游时空数据融合专家】。
    你的任务是读取黑板中由各专家的【真实核心数据集】，进行时空逻辑推理融合，并提取填充到目标数据结构中。

    【核心推理规则】
    1. **严格忠于黑板**：严禁凭空捏造任何未在数据集中出现的景点、酒店或天气信息。
    2. **时空闭环逻辑**：
       - **天气与景点**：雨天优先安排室内景点，晴天安排户外景区。
       - **景点与酒店**：根据推荐景点的空间分布，筛选离景点最近、交通最顺路的酒店，并在 day.hotel 中阐明选址理由。
       - **行程顺畅度**：按实际日期排布，确保同一天内的景点距离相近、交通接驳合理。

    【黑板数据集】
    ---
    【天气专家输入】：{weather_res}
    【景点专家输入】：{attraction_res}
    【酒店专家输入】：{hotel_res}
    【交通专家输入】：{traffic_res}
    ---
    """
    human_prompt = "请根据黑板中的数据集，结合时空融合推理规则，生成最终的结构化旅游计划。"
    messages_input = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt)
    ]
    llm_with_no, llm_with_structured_output = llm_factory.create(output_schema=TripPlan)
    try:
        response = llm_with_structured_output.invoke(messages_input)
        return {
            "messages": [AIMessage(content=response.model_dump_json())],
            "trip_plan": response.model_dump_json(),
        }
    except (ValidationError, OutputParserException) as e:
        response = llm_with_no.invoke(messages_input)
        return {
            "messages": [response],
            "trip_plan": response.content,
        }




def _add_memory(state: RoundRobinState, config: RunnableConfig, memory_manager: MemoryManager) -> RoundRobinState:
    messages = state["messages"]
    user_id = config["configurable"]["user_id"]
    session_id = config["configurable"]["thread_id"]
    if len(state["messages"]) >= 5:
        memory_manager.add_chat_messages(state["messages"], user_id=user_id)
        memory_manager.summarize_chat_messages(state["messages"], session_id)
        return {
            "messages": [RemoveMessage(id=m.id) for m in messages[:-20]]
        }
    return


def create_add_memory(memory_manager):
    def add_memory(state: RoundRobinState, config: RunnableConfig) -> RoundRobinState:
        return _add_memory(state, config, memory_manager)

    return add_memory


def router(state: RoundRobinState):
    return state["next_speaker"].lower()


if sys.platform == "win32":
    asyncio.set_event_loop_policy(
        asyncio.WindowsSelectorEventLoopPolicy()
    )

if __name__ == "__main__":
    async def main():
        mcp_manager = MCPClientManager()
        tool_manager = ToolManager(mcp_manager)
        tool_executor = ToolExecutor()
        memory_manager = MemoryManager()
        memory_checkpoint = get_checkpointer()
        mcp_manager.load_config(os.getenv("MCP_SERVERS_PATH"))
        await mcp_manager.connect()

        tool_manager.initialize(
            os.getenv("TOOL_REGISTRY_PATH"),
            os.getenv("AGENT_PERMISSIONS_PATH")
        )

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

        async with memory_checkpoint as memory_checkpoint:
            app = workflow.compile(checkpointer=memory_checkpoint)
            while True:
                print("\n🎬 [主持人公告] 新一轮旅游规划任务启动，请输入用户需求：")
                user_input = input()
                graph_input = {"messages": [HumanMessage(content=user_input)]}
                config = {
                    "configurable": {
                        "thread_id": session_id,
                        "user_id": user_id,
                        "trace_id": str(uuid.uuid4()),
                    }
                }
                try:
                    state = await app.ainvoke(graph_input, config)
                except Exception as e:
                    print("执行失败:", e)

                    # 不需要重新传 graph_input
                    state = await app.ainvoke(None, config)
                print("\n--------------已完成规划--------------")
                print("\n", state["trip_plan"])


    asyncio.run(main())
