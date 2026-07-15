from datetime import date
from typing import Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field, computed_field, field_validator
class TripRequest(BaseModel):
    start_city: str = Field(..., description="出发城市", example="上海")
    end_city: str = Field(..., description="目的地城市", example="北京")

    start_date: date = Field(..., description="出发日期，格式 YYYY-MM-DD", examples=["2025-06-01"])
    end_date: date = Field(..., description="返回日期，格式 YYYY-MM-DD", examples=["2025-06-05"])

    budget: int = Field(..., description="预算", example=2000)
    transportation: str = Field(..., description="交通方式", example="高铁")
    accommodation: str = Field(..., description="住宿偏好", example="经济型酒店")
    preferences: List[str] = Field(default=[], description="旅行偏好标签", example=["历史文化", "美食"])
    addition_information: Optional[str] = Field(default="", description="额外要求", example="希望多安排一些博物馆")

    class Config:
        json_schema_extra = {
            "example": {
                "start_city": "北京",
                "end_city": "上海",
                "start_date": "2025-06-01",
                "end_date": "2025-06-03",
                "transportation": "公共交通",
                "accommodation": "经济型酒店",
                "preferences": ["历史文化", "美食"],
                "addition_information": "希望多安排一些博物馆"
            }
        }
    @computed_field
    @property
    def travel_days(self) -> int:
        return (self.end_date - self.start_date).days + 1

class Location(BaseModel):
    """地理位置"""
    address: str = Field(..., description="地址", example="北京市朝阳区阜通东大街6号")
    longitude: float = Field(..., description="经度")
    latitude: float = Field(..., description="纬度")

class Attraction(BaseModel):
    name: str = Field(..., description="景点名称", example="故宫")
    location: Location = Field(..., description="景点地理位置,包含经纬度坐标")
    visit_duration: int = Field(..., description="建议游览时长，单位为分钟", example=120)
    description: str = Field(..., description="景点简介", example="故宫是中国明清两代的皇家宫殿，位于北京市中心，是世界上现存规模最大、保存最为完整的木质结构古建筑之一。")
    ticket_price: int = Field(..., description="门票价格(元)", example=60)

    category: Optional[str] = Field(default="景点", description="景点类别")
    rating: Optional[float] = Field(default=None, description="评分")
    photos: Optional[List[str]] = Field(default_factory=list, description="景点图片URL列表")
    poi_id: Optional[str] = Field(default="", description="POI ID")
    image_url: Optional[str] = Field(default=None, description="图片URL")

class Meal(BaseModel):
    """餐饮信息"""
    name: str = Field(..., description="餐厅名称", example="全聚德烤鸭店")
    type: str = Field(..., description="餐饮类型", example="中餐")
    location: Location = Field(..., description="餐厅地理位置,包含经纬度坐标")
    estimated_cost: int = Field(default=0, description="预估费用(元)", example=100)
    description: Optional[str] = Field(default=None, description="描述")

class Hotel(BaseModel):
    """酒店信息"""
    name: str = Field(..., description="酒店名称")
    location: Location = Field(..., description="酒店地理位置,包含经纬度坐标")
    type: str = Field(default="", description="酒店类型", example="经济型酒店")
    estimated_cost: str = Field(default="", description="预估费用(元/晚)", example="200-500元/晚")
    rating: str = Field(default="", description="评分")
    distance: str = Field(default="", description="距离景点距离")

class DayPlan(BaseModel):
    date: str = Field(..., description="日期，格式 YYYY-MM-DD", example="2025-06-01")
    day_index: int = Field(..., description="第几天的行程，从1开始", example=1)
    description: str = Field(..., description="当日行程描述")
    transportation: str = Field(..., description="交通方式")
    hotel: Optional[Hotel] = Field(default=None, description="推荐酒店")
    attractions: List[Attraction] = Field(default=[], description="景点列表")
    meals: List[Meal] = Field(default=[], description="餐饮列表")

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

class TripPlan(BaseModel):
    """旅行计划"""
    start_city : str = Field(..., description="出发城市")
    end_city: str = Field(..., description="目的地城市")
    start_date: str = Field(..., description="开始日期")
    end_date: str = Field(..., description="结束日期")
    days: List[DayPlan] = Field(..., description="每日行程")
    weather_info: List[WeatherInfo] = Field(default=[], description="天气信息")
    overall_suggestions: str = Field(..., description="总体建议")
    budget: Optional[Budget] = Field(default=None, description="预算信息")



class WeatherResponse(BaseModel):
    """大模型结构化输出的最终格式"""
    weather_list: List[WeatherInfo] = Field(
        ...,
        description="包含整个行程中每一天天气预报信息的列表"
    )

