import json
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional, TypedDict, Any, Annotated, Sequence, Dict, List, Union, Literal

from langchain_core.messages import BaseMessage, ToolMessage, HumanMessage
from langgraph.graph import add_messages
from pydantic import BaseModel, Field, field_validator


class Location(BaseModel):
    """地理位置"""
    address: str = Field(..., description="地址", json_schema_extra={"example": "北京市朝阳区阜通东大街6号"})
    longitude: float = Field(..., description="经度")
    latitude: float = Field(..., description="纬度")


class Attraction(BaseModel):
    name: str = Field(..., description="景点名称", json_schema_extra={"example": "故宫"})
    location: Location = Field(..., description="景点地理位置,包含经纬度坐标")
    visit_duration: int = Field(..., description="建议游览时长，单位为分钟", json_schema_extra={"example": 120})
    description: str = Field(..., description="景点简介", json_schema_extra={
        "example": "故宫是中国明清两代的皇家宫殿，位于北京市中心，是世界上现存规模最大、保存最为完整的木质结构古建筑之一。"})
    ticket_price: int = Field(..., description="门票价格(元)", json_schema_extra={"example": 60})

    category: Optional[str] = Field(default="景点", description="景点类别")
    rating: Optional[float] = Field(default=None, description="评分")
    photos: Optional[List[str]] = Field(default_factory=list, description="景点图片URL列表")
    poi_id: Optional[str] = Field(default="", description="POI ID")
    image_url: Optional[str] = Field(default=None, description="图片URL")


class Meal(BaseModel):
    """餐饮信息"""
    name: str = Field(..., description="餐厅名称", json_schema_extra={"example": "全聚德烤鸭店"})
    type: str = Field(..., description="餐饮类型", json_schema_extra={"example": "中餐"})
    location: Location = Field(..., description="餐厅地理位置,包含经纬度坐标")
    estimated_cost: int = Field(default=0, description="预估费用(元)", json_schema_extra={"example": 100})
    description: Optional[str] = Field(default=None, description="描述")


class Hotel(BaseModel):
    """酒店信息"""
    name: str = Field(..., description="酒店名称")
    location: Location = Field(..., description="酒店地理位置,包含经纬度坐标")
    type: str = Field(default="", description="酒店类型", json_schema_extra={"example": "经济型酒店"})
    estimated_cost: str = Field(default="", description="预估费用(元/晚)",
                                json_schema_extra={"example": "200-500元/晚"})
    rating: str = Field(default="", description="评分")
    distance: str = Field(default="", description="距离景点距离")


class DayPlan(BaseModel):
    date: str = Field(..., description="日期，格式 YYYY-MM-DD", json_schema_extra={"example": "2025-06-01"})
    description: str = Field(..., description="当日整体行程逻辑概述（含天气防坑提示及游玩强度安排）")
    transportation: str = Field(..., description="推荐的交通方式及顺路接驳建议")
    hotel: str = Field(..., description="当天推荐住宿的酒店名称及选址理由")
    attractions: List[str] = Field(..., description="当天推荐串联游玩的景点名称列表（已按时空顺路逻辑排序）")
    meals: List[str] = Field(..., description="推荐的餐饮安排或特色美食列表")


class TripPlan(BaseModel):
    """旅游规划最终推导方案"""
    weather_info: str = Field(..., description="综合多日天气分析，包含白天夜间穿搭方案及必备防护装备指南")
    overall_suggestions: str = Field(..., description="基于景点位置与交通连贯性的总体避坑与游玩建议")
    budget: str = Field(..., description="基于黑板数据集推导出的预算评估与支出建议")
    days: List[DayPlan] = Field(..., description="按天梳理的具体行程明细列表")


class WeatherInfo(BaseModel):
    """天气信息"""
    date: str = Field(..., description="日期 YYYY-MM-DD")
    day_weather: str = Field(default="", description="白天天气")
    night_weather: str = Field(default="", description="夜间天气")
    day_temp: Union[int, str] = Field(default=0, description="白天温度")
    night_temp: Union[int, str] = Field(default=0, description="夜间温度")
    wind_direction: str = Field(default="", description="风向")
    wind_power: str = Field(default="", description="风力")

    @field_validator('day_temp', 'night_temp', mode='before')
    @classmethod
    def parse_temperature(cls, v):
        """解析温度,移除°C等单位"""
        if isinstance(v, str):
            # 移除°C, ℃等单位符号
            v = v.replace('°C', '').replace('℃', '').replace('°', '').strip()
            try:
                return int(v)
            except ValueError:
                return 0
        return v


class Budget(BaseModel):
    """预算信息"""
    total_attractions: int = Field(default=0, description="景点门票总费用")
    total_hotels: int = Field(default=0, description="酒店总费用")
    total_meals: int = Field(default=0, description="餐饮总费用")
    total_transportation: int = Field(default=0, description="交通总费用")
    total: int = Field(default=0, description="总费用")


class AuditRecord(TypedDict):
    """
    Represents an audit record for tracking changes made to entities in the system.
    """
    trace_id: str
    node: str
    tool: str
    start_time: datetime
    end_time: datetime
    args: dict[str, Any]
    result: Any | None
    status: str  # success / failed
    retry: int
    error: str | None


class RoundRobinState(TypedDict):
    # Represents the state of a round-robin conversation among multiple experts.
    messages: Annotated[Sequence[BaseMessage], add_messages]
    # 结构化的公共看板，存放已敲定的数据
    blackboard: Dict[str, Any]

    session_summary: str

    user_preference: List

    trip_plan: str

    next_speaker: str


class RouteDecision(BaseModel):
    next_speaker: str = Field(
        description="下一步发言的专家，必须是以下之一: hotel_expert, weather_expert, attraction_expert, traffic_expert, summary_expert"
    )


ExperienceCategory = Literal["parameter", "order", "error", "retry", "output"]


class ToolExperience(BaseModel):
    tool: str = Field(
        description="工具名称，必须与 audit_records 中实际调用的 tool 名称完全一致"
    )
    description: str = Field(
        description="提炼出的通用、可跨会话长期复用的经验指导规则"
    )


class ToolExperienceList(BaseModel):
    """经验列表容器"""
    experiences: List[ToolExperience] = Field(
        default_factory=list,
        description="提炼出的工具经验列表。如果没有值得留存的经验，返回空列表 []"
    )


class CompareResult(BaseModel):
    action: Literal["same", "new"]
