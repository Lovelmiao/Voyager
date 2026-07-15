from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from openai import OpenAI
from pydantic import Field, BaseModel
class RouteDecision(BaseModel):
    next_speaker: str = Field(
        description="下一步发言的专家，必须是以下之一: Hotel_Expert, Weather_Expert, Attraction_Expert, Flight_Expert, Summary_Expert, END"
    )

llm = ChatOpenAI(
    api_key="sk-uXmiPD6Dueng0qZ8vEw3ZXivrulhMXzGlH0qhdPJ3mXooVmt",
    base_url="http://223.82.83.6:3000/v1",
    model="bailu-apex",
    temperature=0.7,
    max_tokens=65535
).with_structured_output(RouteDecision)

messages = [SystemMessage(content=f"""
你是一个圆桌会议的主持人。当前会议的主题是规划旅游行程。\n
参与专家：Hotel_Expert, Weather_Expert, Attraction_Expert, Flight_Expert, Summary_Expert。\n
推荐标准流程：Hotel_Expert -> Weather_Expert -> Attraction_Expert -> Flight_Expert -> Summary_Expert。\n
请根据对话历史判断进度。如果所有专家都确认完成了，请指定 Summary_Expert 行程大汇总。\n
请你根据当前会议程序，严格决定下一步谁发言。\n
""")]
messages.append(HumanMessage(content=f"""当前专家: Weather_Expert"""))

print(messages)
response = llm.invoke(
    messages
)
print(response)

