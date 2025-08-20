from typing import List

from langchain_core.tools import tool

from .Tools import getCurrentTime
from core import ToolInterface

class TimeTools(ToolInterface):
    def toolCollections(self) -> List[tool]:
        """Return a list of tool collections"""
        return [getCurrentTime]
