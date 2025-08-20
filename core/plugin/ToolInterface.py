"""
An interface for tool plugins
"""
from abc import ABC, abstractmethod
from typing import List
from langchain_core.tools import tool

class ToolInterface(ABC):
    """
    An interface for tool plugins
    """
    @abstractmethod
    def toolCollections(self) -> List[tool]:
        """Return a list of tool collections"""
        pass
