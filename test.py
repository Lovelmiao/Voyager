from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import Field, BaseModel


class RouteDecision(BaseModel):
    next_speaker: str = Field(
        description="下一步发言的专家，必须是以下之一: Hotel_Expert, Weather_Expert, Attraction_Expert, Flight_Expert, Summary_Expert, END"
    )

llm = ChatOpenAI(
    model="bailu-2.7",
    api_key="sk-269af1a07129f126b38d86b1df5a0c23",
    base_url="https://bailucode.com/openapi/v1",
    temperature=0.5,
    max_tokens=65535
)

messages = [SystemMessage(content="你是一个主持人，负责阅读清洗后的对话历史，严格决定下一个谁发言。请根据对话内容和当前看板数据，选择下一步发言的专家。")]
messages += [HumanMessage(content="""请问下一步应该由哪个专家发言？你可以从以下专家中选择: Hotel_Expert, Weather_Expert, Attraction_Expert, Flight_Expert, Summary_Expert, END。# Output Format
    请直接输出一个 JSON 对象（不要包含任何 markdown 块或普通文本），结构如下：
    {
      "next_speaker": "下一步发言的专家",
    }""")]
print(messages)

response = llm.invoke(
    messages
)

print(response)