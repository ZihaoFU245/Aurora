"""
Unified configuration from env file
"""
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
    OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")
    # Models
    ROUTER_MODEL = os.getenv("ROUTER_MODEL")
    PLANNER_MODEL = os.getenv("PLANNER_MODEL")
    EXECUTOR_MODEL = os.getenv("EXECUTOR_MODEL")
    CRITIC_MODEL = os.getenv("CRITIC_MODEL")
    # Temperature
    ROUTER_TEMP = os.getenv("ROUTER_TEMP")
    PLANNER_TEMP = os.getenv("PLANNER_TEMP")
    EXECUTOR_TEMP = os.getenv("EXECUTOR_TEMP")
    CRITIC_TEMP = os.getenv("CRITIC_TEMP")
    # Prompts
    SYSTEM_PROMPT = os.getenv("SYSTEM_PROMPT")
    ROUTER_SYSTEM_PROMPT = os.getenv("ROUTER_SYSTEM_PROMPT")
    PLANNER_SYSTEM_PROMPT = os.getenv("PLANNER_SYSTEM_PROMPT")
    EXECUTOR_SYSTEM_PROMPT = os.getenv("EXECUTOR_SYSTEM_PROMPT")
    CRITIC_SYSTEM_PROMPT = os.getenv("CRITIC_SYSTEM_PROMPT")
    # Tracing
    TRACE_LOG_FILE = os.getenv("TRACE_LOG_FILE") or "aurora_trace.log"
