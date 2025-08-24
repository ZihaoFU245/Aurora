"""
Core components that graph is compiled
"""
from typing import Dict, List, Optional, cast, Any

from langchain_core.messages import AnyMessage, HumanMessage, AIMessage

from .models import Models
from .edges import build_graph
from .nodes import router_node, planner_node, executor_node, critical_node
from langchain_core.tools import BaseTool
from core import config as core_config
from core.observability.tracing import get_tracer
from langgraph.errors import GraphRecursionError


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
        async def _executor(state, llm=self._executor_llm, tools=self._tools):
            return await executor_node(state, llm, tools)

        self.app = build_graph(
            {
                "router": lambda state: router_node(state, self._router_llm),
                "planner": lambda state: planner_node(state, self._planner_llm),
                "executor": _executor,
                "critic": lambda state: critical_node(state, self._critic_llm),
            }
        )

        self._tracer.log("engine_init", tools_count=len(self._tools))

    def _prompt_on_recursion(self) -> str:
        """Prompt the user for action when recursion limit is hit.

        Returns:
            A command string among: 'continue', 'pause', 'stop'
        """
        while True:
            print(
                "Warning: Reached the graph execution recursion limit (default 25). Continue?\n"
                "- Type y or press Enter to continue (increase the limit)\n"
                "- Type n to stop this run\n"
                "- Type /pause to pause progress (you can resume later)"
            )
            try:
                choice = input("Choice> ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                return "stop"

            if choice in ("/pause", "pause"):
                return "pause"
            if choice in ("y", "yes", ""):
                return "continue"
            if choice in ("n", "no", "/stop", "stop", "/quit", "quit"):
                return "stop"
            print("Invalid input, please try again.")

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

        # Default recursion limit used by LangGraph is 25.
        current_limit = 25
        attempt = 0
        while True:
            attempt += 1
            try:
                # When current_limit is 25, passing no config matches default behavior.
                if current_limit == 25:
                    raw_result: Any = self.app.invoke({"messages": messages})
                else:
                    raw_result: Any = self.app.invoke({"messages": messages}, config={"recursion_limit": current_limit})
                # Defensive: ensure result is a dict with messages
                if raw_result is None:
                    raw_result = {"messages": messages}
                result = cast(Dict[str, List[AnyMessage]], raw_result)
                self._tracer.log("run_end", messages_len=len(result.get("messages", [])), attempts=attempt, recursion_limit=current_limit)
                return result
            except GraphRecursionError as e:
                # Ask user what to do next instead of exiting.
                self._tracer.log("recursion_limit_hit", attempts=attempt, recursion_limit=current_limit, error=str(e))
                action = self._prompt_on_recursion()
                if action == "pause":
                    pause_msg = AIMessage(content=f"Execution paused (recursion depth reached {current_limit}). You can resume later.")
                    out: Dict[str, List[AnyMessage]] = {"messages": messages + [pause_msg]}
                    self._tracer.log("paused", recursion_limit=current_limit)
                    return out
                if action == "stop":
                    stop_msg = AIMessage(content="Stopped: recursion limit reached, not continuing.")
                    out: Dict[str, List[AnyMessage]] = {"messages": messages + [stop_msg]}
                    self._tracer.log("stopped", recursion_limit=current_limit)
                    return out
                # continue -> increase limit and retry
                increment = 25
                current_limit += increment
                print(f"Continuing: increasing recursion limit to {current_limit}.")
                self._tracer.log("recursion_limit_increase", new_limit=current_limit)
                continue
