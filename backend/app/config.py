import os

from dotenv import load_dotenv

load_dotenv()

from typing import List
from langchain_core.tools import BaseTool

# Import after load_dotenv so env vars are available.
from ..models.tools import _init_tools, get_amap_tools_sync

# LLM
MODEL = os.getenv("MODEL", "bailu-apex")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
BASE_URL = os.getenv("BASE_URL")

MODEL_BACKUP = os.getenv("MODEL_BACKUP")
OPENAI_API_KEY_BACKUP = os.getenv("OPENAI_API_KEY_BACKUP")
BASE_URL_BACKUP = os.getenv("BASE_URL_BACKUP")

# Amap
AMAP_API_KEY = os.getenv("AMAP_API_KEY", "4cd31aba1a0bde0420bdea9950e2172c")

# Server
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "9000"))
