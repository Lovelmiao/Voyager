import os
from uuid import UUID

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from mem0 import MemoryClient

from datetime import datetime

import psycopg2
import psycopg2.extras
from psycopg2.extras import RealDictCursor
from ..base import ToolExperienceList, AuditRecord, CompareResult, ToolExperience
from langchain_core.messages import (
    HumanMessage,
    AIMessage,
    ToolMessage,
    SystemMessage,
)

load_dotenv()


class MemoryManager():
    def __init__(self):
        self.mem0_client = MemoryClient(api_key=os.getenv("MEMORY_API_KEY"))
        self.postgres_client = psycopg2.connect(
            os.getenv(
                "POSTGRES_URL"
            )
        )
        self.postgres_client.autocommit = True
        psycopg2.extras.register_uuid(conn_or_curs=self.postgres_client)
        self.llm = ChatOpenAI(
            model=os.getenv("MODEL"),
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("BASE_URL"),
            temperature=0,
        )
        self.extract_llm = self.llm.with_structured_output(list[ToolExperience])
        self.compare_llm = self.llm.with_structured_output(CompareResult)

    def add_chat_messages(self, messages, user_id):
        if len(messages) <= 5:
            return
        old_messages = messages[:-5]
        old_messages = self.convert_messages_for_mem0(old_messages)
        self.mem0_client.add(old_messages, user_id=user_id)

    def add_tools_memory(self, audit_records: list[AuditRecord]):
        self.save_audit(audit_records)
        learn_audit_list = self.filter_learning_audits(audit_records)
        if not learn_audit_list:
            return
        experiences = self.extract_tool_experience(learn_audit_list)
        print("experiences",experiences)
        if not experiences:
            return

        for exp in experiences:
            old = self.search_tool_experience(exp.tool)
            if not old:
                action = "new"
            else:
                action = self.compare_experience(old, exp)
            if action == "same":
                continue
            if action == "new":
                self.save_tool_experience(exp)

    def search_messages(self, query, user_id):
        response = self.mem0_client.search(query, filters={"user_id": user_id})
        return response

    def summarize_chat_messages(self, messages, session_id):
        # 如果总消息数不足 20 条，不需要压缩，直接返回
        if len(messages) <= 5:
            return

        # 获取需要压缩的旧消息
        old_messages = messages[:-5]
        history_text = self._messages_to_text(old_messages)

        # 获取已有的历史总结
        history_summary = self.get_summary(session_id) or "（暂无历史总结）"

        prompt = f"""你是一位专业的对话历史记录压缩专家。你的任务是将【旧历史总结】与【最新增的对话记录】进行增量融合，生成一份全新的、高密度的历史总结。

    【输入数据】
    === 旧历史总结 ===
    {history_summary}

    === 最新增对话记录 ===
    {history_text}

    【增量融合规则】
    1. **继承与更新**：旧总结中的关键信息（如用户偏好、长期背景）**必须保留**，除非最新增对话明确修正或废弃了旧信息。
    2. **信息提取重点**：
       - **用户画像与需求**：用户的身份背景、长期偏好、明确提出的目标。
       - **未完成事项**：当前尚未解决的问题、待办任务、未跟进的约定。
       - **核心事实约束**：对话中涉及的关键数据、决策结论、代码/系统参数。
    3. **垃圾过滤**：彻底剔除礼貌性寒暄、过渡性废话、误操作及重复的确认过程。
    4. **输出规范**：
       - 使用客观、紧凑的第三人称陈述句。
       - 严禁包含“根据对话”、“新增记录显示”、“旧总结提到”等元话术。
       - 控制总体长度在 500 字以内。
    """

        response = self.llm.invoke(prompt)
        new_summary = response.content.strip()

        self.save_summary(session_id, new_summary)

    def get_summary(self, session_id: UUID):

        with self.postgres_client.cursor(
                cursor_factory=RealDictCursor
        ) as cur:
            cur.execute(
                """
                SELECT summary
                FROM conversation_summary
                WHERE session_id=%s
                """,
                (
                    session_id,
                ),
            )

            row = cur.fetchone()

            if row:
                return row["summary"]

            return ""

    def save_summary(self, session_id, summary):
        with self.postgres_client.cursor() as cur:
            cur.execute(
                """
                INSERT INTO conversation_summary
                (
                    session_id,
                    summary,
                    updated_at
                )

                VALUES
                (%s,%s,NOW())

                ON CONFLICT (session_id)

                DO UPDATE

                SET
                    summary=EXCLUDED.summary,
                    updated_at=NOW();
                """,
                (
                    session_id,
                    summary,
                ),
            )

    def _messages_to_text(self, messages):
        lines = []
        for m in messages:
            if isinstance(m, HumanMessage):
                role = "User"
            elif isinstance(m, AIMessage):
                role = "Assistant"
            elif isinstance(m, ToolMessage):
                role = "Tool"
            elif isinstance(m, SystemMessage):
                role = "System"
            else:
                role = "Unknown"
            lines.append(f"{role}: {m.content}")
        return "\n".join(lines)

    def save_audit(self, tools_audit):
        with self.postgres_client.cursor() as cur:
            for audit in tools_audit:
                cur.execute(
                    """
                    INSERT INTO tools_audit
                    (
                        trace_id,
                        node,
                        tool,
                        start_time,
                        end_time,
                        args,
                        result,
                        status,
                        attempt,
                        error
                    )

                    VALUES
                    (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        audit["trace_id"],
                        audit["node"],
                        audit["tool"],
                        audit["start_time"],
                        audit["end_time"],
                        psycopg2.extras.Json(audit["args"]),
                        psycopg2.extras.Json(audit["result"]),
                        audit["status"],
                        audit["attempt"],
                        audit["error"],
                    ),
                )

    def convert_messages_for_mem0(self, messages):
        result = []
        for msg in messages:
            if isinstance(msg, HumanMessage):
                role = "user"
            elif isinstance(msg, AIMessage):
                role = "assistant"
            elif isinstance(msg, ToolMessage):
                role = "tool"
            else:
                continue
            result.append({"role": role, "content": msg.content})
        return result

    def extract_tool_experience(self, audit_records) -> list[ToolExperience]:
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
        return self.extract_llm.invoke(message_input)

    def search_tool_experience(self, tool: str, limit: int = 5):
        return self.mem0_client.search(
            query="tool experience",
            limit=limit,
            filters={
                "user_id": "tool_experience",
                "metadata": {
                    "tool": tool
                }
            }
        )

    def compare_experience(self, old_memory, new_exp: ToolExperience):
        prompt = f"""
        你是一位精通知识库去重的系统架构专家。你的任务是评估一条【新提取的工具经验】是否可以合并到【已有经验库】中，或者它是否提供了全新的价值。

        【判断原则】
        深入理解这两条经验的**核心语义、触发条件和解决方案**：
        - 返回 "same": 如果新经验描述的规则、错误原因或操作逻辑在已有经验中**已经存在**，或者只是已有经验的同义句转换、轻微措辞差异。
        - 返回 "new": 如果新经验补充了**全新**的参数规则、未见过的错误类型、不同的业务场景，或者是对已有经验的重大修正与实质性补充。

        【已有经验库】
        {old_memory}

        【新提取的经验】
        {new_exp}

        请根据上述原则进行对比并输出判断结果。
        """
        return self.compare_llm.invoke(prompt).action

    def save_tool_experience(self, exp: ToolExperience):
        self.mem0_client.add(
            messages=[
                {
                    "role": "assistant",
                    "content": f"""
    Tool: {exp.tool}
    Experience:
    {exp.content}
    """
                }],
            user_id="tool_experience",
            metadata={
                "tool": exp.tool,
                "namespace": "tool_experience",
            }
        )


    def filter_learning_audits(self, audit_list: list[AuditRecord]) -> list[AuditRecord]:
        """
        从 Audit 中筛选值得沉淀到长期经验库的记录。
        学习：
            - Tool 执行失败
            - 参数错误
            - Retry 后才成功
            - 返回异常
        不学习：
            - 一次成功
            - 网络瞬时异常
            - LLM限流
        """
        learn_list = []
        for audit in audit_list:
            # -------- Retry 才成功 --------
            if audit["error"] is None:
                continue
            # 其余失败全部学习
            learn_list.append(audit)
        return learn_list