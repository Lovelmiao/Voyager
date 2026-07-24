import os
from datetime import datetime

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from mem0 import MemoryClient
load_dotenv()


def extract_tool_experience(audit_records):
    extract_llm = ChatOpenAI(
          model=os.getenv("MODEL"),
          api_key=os.getenv("OPENAI_API_KEY"),
          base_url=os.getenv("BASE_URL"),
          temperature=0.5,
  )
    system_prompt = f"""
      你是一位专精于 Agent 工具调用分析的系统优化专家。
  
      【任务】
      仔细分析下方给出的 Agent 工具调用审计日志（Audit Records），从中提炼出**可跨会话长期复用、泛化性强**的工具使用经验。
  
      【提取原则】
      1. **注重长期价值**：仅提取抽象的规则、模式和避坑指南。严禁输出任何与“本次执行/具体数据/特定时间/今天/本次查询”相关的临时状态或具体数值。
      2. **严禁无意义总结**：不要复述执行流程（例如：“首先调用了A，然后输出了B”）。只提炼出“后续遇到同类场景时该如何更好地使用工具”的规则。
      3. **保持精准度**：如果审计日志中只是正常的标准调用，没有产生任何值得留存的通用经验、错误惩罚或调优提示，请直接返回空列表。
      4. **合并相同工具**：如果Audit Records包含相同的工具则合并抽取信息，否则分别提取信息。 
      """
    human_prompt = f"""
      【待提取日志】
      {audit_records}
      """
    message_input = [SystemMessage(content=system_prompt), HumanMessage(content=human_prompt)]
    response = extract_llm.invoke(message_input)
    print(response)
    return response

audit_records = [{'trace_id': 'f5da52dd-d6e6-4153-821e-4fab04caba02', 'node': 'weather_agent', 'tool': 'maps_weather', 'start_time': datetime(2026, 7, 21, 15, 48, 56, 977014), 'end_time': datetime(2026, 7, 21, 15, 48, 58, 298059), 'args': {'city': '南京'}, 'result': [{'type': 'text', 'text': '{"city":"南京市","forecasts":[{"date":"2026-07-21","week":"2","dayweather":"阴","nightweather":"雷阵雨","daytemp":"32","nighttemp":"25","daywind":"东北","nightwind":"东北","daypower":"4","nightpower":"4","daytemp_float":"32.0","nighttemp_float":"25.0"},{"date":"2026-07-22","week":"3","dayweather":"中雨","nightweather":"雷阵雨","daytemp":"29","nighttemp":"25","daywind":"南","nightwind":"南","daypower":"1-3","nightpower":"1-3","daytemp_float":"29.0","nighttemp_float":"25.0"},{"date":"2026-07-23","week":"4","dayweather":"中雨","nightweather":"中雨","daytemp":"31","nighttemp":"25","daywind":"南","nightwind":"南","daypower":"1-3","nightpower":"1-3","daytemp_float":"31.0","nighttemp_float":"25.0"},{"date":"2026-07-24","week":"5","dayweather":"小雨","nightweather":"多云","daytemp":"30","nighttemp":"26","daywind":"南","nightwind":"南","daypower":"1-3","nightpower":"1-3","daytemp_float":"30.0","nighttemp_float":"26.0"}]}', 'id': 'lc_dcbdb30c-e6c0-4a1a-8449-d2027634b1fa'}], 'status': 'success', 'attempt': 1, 'error': None}]
extract_tool_experience(audit_records)