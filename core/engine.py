"""
Core components that graph is compiled
"""
from typing import Dict, List, Optional

from langchain_core.messages import AnyMessage, HumanMessage

from .models import Models
from .edges import build_graph
from .nodes import router_node, planner_node, executor_node, critical_node
from langchain_core.tools import BaseTool
from core import config as core_config
from core.observability.tracing import get_tracer


class Engine:
    """Engine that wires models, tools, and the graph, and exposes a run() method."""

    def __init__(self, tools: Optional[List[BaseTool]] = None):
        self._tracer = get_tracer(core_config.TRACE_LOG_FILE)
        # Initialize models using singleton core.config
        self._models = Models(core_config)
        self._router_llm = self._models.getRouterModel()
        self._planner_llm = self._models.getPlannerModel()
        self._executor_llm = self._models.getExecutorModel()
        self._critic_llm = self._models.getCriticModel()

        # Tools to bind and execute
        self._tools: List[BaseTool] = tools or []

        # Bind tools to all models if supported
        for attr in ("_router_llm", "_planner_llm", "_executor_llm", "_critic_llm"):
            llm = getattr(self, attr)
            try:
                if self._tools:
                    setattr(self, attr, llm.bind_tools(self._tools))
            except AttributeError:
                pass

        # Build graph with closures capturing LLMs and tools
        self.app = build_graph(
            {
                "router": lambda state: router_node(state, self._router_llm),
                "planner": lambda state: planner_node(state, self._planner_llm),
                "executor": lambda state: executor_node(state, self._executor_llm, self._tools),
                "critic": lambda state: critical_node(state, self._critic_llm),
            }
        )

        self._tracer.log("engine_init", tools_count=len(self._tools))

    def run(self, user_input: str, history: Optional[List[AnyMessage]] = None) -> Dict[str, List[AnyMessage]]:
        """Run the agent graph once for a given user input and return updated messages.

        Args:
            user_input: The user's message content.
            history: Optional previous messages to preserve conversation context.
        Returns:
            A dict with key "messages" containing the updated list of messages.
        """
        messages: List[AnyMessage] = list(history or []) + [HumanMessage(content=user_input)]
        self._tracer.log("run_start", input_len=len(user_input), history_len=len(history or []))
        result = self.app.invoke({"messages": messages})
        self._tracer.log("run_end", messages_len=len(result.get("messages", [])))
        return result
