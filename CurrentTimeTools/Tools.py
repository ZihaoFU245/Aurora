"""
Time tools for agents
"""
from langchain_core.tools import tool
import datetime

@tool
def getCurrentTime() -> str:
    """Return local system time in 'YYYY-MM-DD HH:MM:SS'."""
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


