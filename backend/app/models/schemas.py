from typing import Dict, List, Literal
from pydantic import BaseModel, Field

class ChecklistItem(BaseModel):
    status: Literal["Pending", "Completed"] = Field(description="任务状态，只能是 Pending 或 Completed")
    assigned_agent: Literal["weather_agent", "attraction_agent", "hotel_agent", "summary_agent"] = Field(
        description="指派执行该任务的特定 Agent 名称"
    )

class PlanResponse(BaseModel):
    intent_analysis: str = Field(description="对用户出行意图的简要分析")
    plan: List[str] = Field(description="步骤列表，每个步骤注明负责的 Agent 和任务描述")
    checklist: Dict[str, ChecklistItem] = Field(description="状态维护清单，Key为任务名称")
    first_step: str = Field(description="当前排在第一步、需要立即执行的任务名称")
