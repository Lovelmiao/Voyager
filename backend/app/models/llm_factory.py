import os

from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
load_dotenv()

class LLMFactory:
    def __init__(self, temperature=0.5, max_token=65535):
        self.primary = ChatOpenAI(
            model=os.getenv("MODEL"),
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("BASE_URL"),
            temperature=temperature
        )

        self.fallback = ChatOpenAI(
            model=os.getenv("MODEL_BACKUP"),
            api_key=os.getenv("OPENAI_API_KEY_BACKUP"),
            base_url=os.getenv("BASE_URL_BACKUP"),
            temperature=temperature
        )

    def create(
            self,
            output_schema=None,
            tools=None,
    ):
        primary = self.primary
        fallback = self.fallback
        primary_with_no = primary.with_fallbacks([fallback])
        if tools:
            primary = primary.bind_tools(tools)
            fallback = fallback.bind_tools(tools)

        elif output_schema:
            primary = primary.with_structured_output(output_schema)

        return primary_with_no, primary.with_fallbacks([fallback])