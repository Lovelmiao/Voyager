import os

from langchain_core.messages import SystemMessage, HumanMessage
from openai import OpenAI
from dotenv import load_dotenv
from typing import Dict, List, Literal
from pydantic import BaseModel, Field
from openai import OpenAI
from langchain_openai import ChatOpenAI
from backend.app.models import PlanResponse

load_dotenv()


class llm_client:
    def __init__(self, api_key: str = None, base_url: str = None, model: str = None, temperature: float = 0.7, max_tokens: int = 65535):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = base_url or os.getenv("BASE_URL")
        self.model = model or os.getenv("MODEL")
        self.temperature = temperature or os.getenv("TEMPERATURE")
        self.max_token = max_tokens or os.getenv("MAX_TOKENS")

        self._parameter_check()

        self._client = self._create_client()

    def _parameter_check(self):
        if not self.api_key:
            raise ValueError("API Key is required.")
        if not self.model:
            raise ValueError("Model is required.")
        if not self.base_url:
            raise ValueError("Base URL is required.")

    def _create_client(self):
        # 核心：将 model, temperature 等参数在初始化时传给 ChatOpenAI
        return ChatOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_token
        )

    def invoke(self, messages: list[dict[str, str]], response_format: BaseModel) -> BaseModel:
        """同步调用，并直接返回解析后的 Pydantic 对象"""
        try:
            # 1. 将原生的 {"role": "...", "content": "..."} 格式转换为 LangChain 的 Message 对象
            formatted_messages = []
            for msg in messages:
                if msg["role"] == "system":
                    formatted_messages.append(SystemMessage(content=msg["content"]))
                else:
                    formatted_messages.append(HumanMessage(content=msg["content"]))

            # 2. 使用 LangChain 官方推荐的结构化输出包装器
            if response_format:
                structured_llm = self._client.with_structured_output(response_format)
                # 3. 使用同步的 invoke 进行调用
                response = structured_llm.invoke(formatted_messages)
            else:
                response = self._client.invoke(formatted_messages)

            # 4. with_structured_output 会直接返回一个 response_format (即 PlanResponse) 的实例对象
            return response

        except Exception as e:
            raise RuntimeError(f"LLM调用失败: {e}")

    def add_tools(self, tools):
        self._client = self._client.bind_tools(tools)


if __name__ == "__main__":
    llm_client = llm_client()

    PLANNER_AGENT_PROMPT = """# Role
    你是一个高智能、严谨的旅游规划专家 Agent (Trip Planner)。你的核心任务是作为整个旅游管线的第一步：识别用户意图，利用你可支配的专业 Agent 资源，制定出一份结构化的执行计划（Plan）并初始化状态清单（Checklist）。

    # Available Agents (可用对象)
    你拥有以下 4 个下游专业 Agent。在拆解任务时，你必须且只能将步骤指派给它们：
    1. `weather_agent`：负责查询目的地的实时天气、历史气候趋势、最佳旅游季节以及穿衣建议。
    2. `attraction_agent`：负责根据用户偏好推荐景点、规划路线、计算景点间距离及游玩时间。
    3. `hotel_agent`：负责根据用户的预算、位置偏好、出行人数筛选和推荐酒店或民宿。
    4. `summary_agent`：负责在所有数据收集完成后，将天气、景点、酒店信息融合成一份完美的、格式优雅的最终旅游行程单。

    # Goals & Rules
    1. **意图拆解**：分析用户需求，将其拆解为具体的可执行步骤。
    2. **精准指派**：每一个步骤必须【有且仅有】一个上述定义的 Available Agent 负责。
    3. **顺序合理**：通常建议先了解天气/气候（weather），再规划景点路线（attraction），然后围绕路线选酒店（hotel），最后由 summary_agent 汇总。请根据用户具体输入调整顺序。
    4. **拒绝回答细节**：你只负责规划和任务分发，绝对不要包含任何具体的景点、天气或酒店推荐内容。

    # Output Format
    请直接输出一个 JSON 对象（不要包含任何 markdown 块或普通文本），结构如下：
    {
      "intent_analysis": "对用户出行意图的简要分析",
      "plan": [
        "步骤1：[负责的Agent] 具体任务描述",
        "步骤2：[负责的Agent] 具体任务描述"
      ],
      "checklist": {
        "任务A(如:查询天气)": {
          "status": "Pending",
          "assigned_agent": "weather_agent"
        },
        "任务B(如:规划景点)": {
          "status": "Pending",
          "assigned_agent": "attraction_agent"
        }
      },
      "first_step": "第一步需要执行的任务名称"
    }
    """

    test_message = [
        {"role": "system", "content": PLANNER_AGENT_PROMPT},
        {"role": "user", "content": "我想去北京旅游，帮我规划一个三天的行程，包括景点、酒店和天气信息。"}
    ]
    response = llm_client.invoke(test_message, response_format=PlanResponse)
    print("LLM响应:", response)

