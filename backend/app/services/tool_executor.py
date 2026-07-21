import asyncio
import uuid
from datetime import datetime
from langchain_core.messages import ToolMessage
from pydantic import ValidationError
from backend.app.base import AuditRecord

class ToolExecutor:
    def __init__(self, max_attempt=2):
        self.max_attempt = max_attempt

    async def execute(self, tool_calls, tools: list, node, trace_id):
        tool_map = {t.name: t for t in tools}
        tasks = []
        tool_messages = []
        audit_records = []
        for call in tool_calls:
            tool = tool_map.get(call["name"])
            if tool is None:
                tool_messages.append(
                    ToolMessage(
                        tool_call_id=call["id"],
                        name=call["name"],
                        content=(
                            f"Tool '{call['name']}' not found.\n"
                            "Please select another available tool."
                        )
                    )
                )
                audit_records.append(
                    AuditRecord(
                        {
                            "trace_id": trace_id,
                            "node": node,
                            "tool": call["name"],
                            "start_time": datetime.now(),
                            "end_time": datetime.now(),
                            "args": call.get("args", {}),
                            "result": None,
                            "status": "failed",
                            "attempt": 0,
                            "error": "Tool not found",
                        }
                    )
                )
            tasks.append(
                self.execute_one(
                    tool=tool,
                    call=call,
                    node=node,
                    trace_id=trace_id
                )
            )
        results = await asyncio.gather(*tasks)

        for msg, audits in results:
            tool_messages.append(msg)
            audit_records.extend(audits)

        return tool_messages, audit_records

    async def execute_one(self, tool, call, node, trace_id):
        args = call.get("args", {})
        attempt = 1
        audit_list = []
        while attempt <= self.max_attempt:
            start = datetime.now()
            try:
                schema = getattr(tool, "args_schema", None)
                if schema and hasattr(schema, "model_validate"):
                    schema.model_validate(args)
                result = await tool.ainvoke(args)
                end = datetime.now()
                audit = AuditRecord(
                    {
                        "trace_id": trace_id,
                        "node": node,
                        "tool": tool.name,
                        "start_time": start,
                        "end_time": end,
                        "args": args,
                        "result": result,
                        "status": "success",
                        "attempt": attempt,
                        "error": None,
                    }
                )
                audit_list.append(audit)

                return ToolMessage(
                    tool_call_id=call["id"],
                    content=str(result),
                    name=tool.name,
                ), audit_list

            except ValidationError as e:
                end = datetime.now()
                audit = AuditRecord(
                    {
                        "trace_id": trace_id,
                        "node": node,
                        "tool": tool.name,
                        "start_time": start,
                        "end_time": end,
                        "args": args,
                        "result": None,
                        "status": "failed",
                        "attempt": attempt,
                        "error": str(e),
                    }
                )
                audit_list.append(audit)

                return ToolMessage(
                    tool_call_id=call["id"],
                    name=tool.name,
                    content=(
                        "Tool parameter validation failed.\n"
                        f"{e}\n"
                        "Please regenerate valid tool arguments."
                    )), audit_list

            except Exception as e:
                end = datetime.now()
                audit = AuditRecord(
                    {
                        "trace_id": trace_id,
                        "node": node,
                        "tool": tool.name,
                        "start_time": start,
                        "end_time": end,
                        "args": args,
                        "result": None,
                        "status": "failed",
                        "attempt": attempt,
                        "error": str(e),
                    }
                )
                audit_list.append(audit)
                if attempt < self.max_attempt:
                    await asyncio.sleep(min(30, 2 ** attempt))
                    attempt += 1
                    continue

                return ToolMessage(
                    tool_call_id=call["id"],
                    name=tool.name,
                    content=(
                        "Tool execution failed after retry.\n"
                        f"{e}\n"
                        "已达到retry最大次数，请停止调用此工具，并尝试调用其他工具或者根据现有知识进行回复。"
                    )), audit_list
