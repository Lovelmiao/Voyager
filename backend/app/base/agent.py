import time
import uuid

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from ..base import RoundRobinState
from ..models import LLMFactory
from datetime import datetime

class BaseAgent:
    def __init__(self, name, system_prompt, human_prompt, tools, tool_executor, memory_manager):
        self.name = name
        self.system_prompt = system_prompt
        self.human_prompt = human_prompt
        self.tool_executor = tool_executor
        self.tools = tools or []
        self.memory_manager = memory_manager
        self.llm_with_no, self.llm = self._init_llm()

    def _init_llm(self):
        llm_factory = LLMFactory()
        return llm_factory.create(tools=self.tools)

    async def run(self, state: RoundRobinState, trace_id: uuid.UUID) -> RoundRobinState:
        print(f"{self.name}开始工作...\n")
        start_time = datetime.now()

        tool_memory = []
        for tool in self.tools:
            memories = self.memory_manager.search_tool_experience(tool.name, limit=5)
            tool_memory.extend(memories["results"])
        tools_memory = "\n".join(memory["memory"]for memory in tool_memory)

        model = self.llm.bind_tools(self.tools)
        result_key = self.name.replace("_agent", "_result")
        blackboard = state["blackboard"]
        history_summary = state["session_summary"]
        user_preference = state["user_preference"]
        # tools_messages = []
        messages = state["messages"]
        audit_list = []
        messages_input = [SystemMessage(content=self.system_prompt+f"\n\n工具调用历史记录：{tools_memory}"+f"\n\n历史聊天记录总结：{history_summary}" + f"\n\n用户偏好：{user_preference}")] + messages + [HumanMessage(content=self.human_prompt)]
        for attempt in range(5):
            response = await model.ainvoke(messages_input)
            messages_input.append(response)
            print(f"{self.name} finished in {datetime.now() - start_time}")
            if not response.tool_calls:
                blackboard[result_key] = response.content
                print("当前数据板数据：\n",blackboard)
                self.memory_manager.add_tools_memory(audit_records=audit_list)
                return {
                    "messages": [response],
                    "blackboard": blackboard,
                    "next_speaker": "orchestrator"
                }
            tool_messages_record, audit_records = await self.tool_executor.execute(response.tool_calls,
                                                                                   tools=self.tools,
                                                                                   node=self.name, trace_id=trace_id)
            messages_input.extend(tool_messages_record)
            # tools_messages.extend(tool_messages_record)
            audit_list.extend(audit_records)

        messages_input.append(HumanMessage(content="请不要继续调用任何工具，直接依据已有 ToolMessage 给出最终回答。"))
        response = await self.llm_with_no.ainvoke(messages_input)
        blackboard[result_key] = response.content
        print(f"{self.name} finished in {datetime.now() - start_time}")
        print("当前数据板数据：\n", blackboard)
        self.memory_manager.add_tools_memory(audit_records=audit_list)
        return {
            "messages": [response],
            "blackboard": blackboard,
            "next_speaker": "orchestrator"
        }
