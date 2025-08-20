"""
Bindings for all tools, which the agent engine would use that
"""
from typing import Iterable, List, Union
from langchain_core.tools import BaseTool

class ToolBindings:
    """
    This class holds a list of tools.
    Design:
      - Each model (router/planner/...) may have its own tool bindings in future.
      - User added tools are available to models that support tools (e.g., router).
    """
    tools: List[BaseTool]

    def __init__(self):
        self.tools = []

    def addTool(self, tools: Union[BaseTool, List[BaseTool]]):
        """Add a tool or a list of tools."""
        if tools is None:
            return
        if isinstance(tools, list):
            self.tools.extend(tools)
        else:
            self.tools.append(tools)

    def getTools(self) -> List[BaseTool]:
        return self.tools