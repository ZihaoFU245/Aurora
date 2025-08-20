from typing import List

from langchain_core.messages import AnyMessage, SystemMessage, AIMessage
from langgraph.graph import MessagesState

from core import config


def ensure_system(messages: List[AnyMessage], override_prompt: str | None = None):
    """Ensure System Prompt is injected; allow override per node."""
    prompt = (override_prompt or config.SYSTEM_PROMPT or "You are Aurora Agent.")
    if messages and isinstance(messages[0], SystemMessage):
        return messages
    return [SystemMessage(content=prompt)] + messages


def has_tool_calls(state: MessagesState) -> bool:
    """Return True if the last AI message contains tool calls."""
    msgs = state.get("messages", [])
    if not msgs:
        return False
    last = msgs[-1]
    if isinstance(last, AIMessage) and getattr(last, "tool_calls", None):
        return True
    return False


def _truthy(val: str | None) -> bool:
    return str(val).strip().lower() in {"1", "true", "yes", "y"}


def router_decision(state: MessagesState) -> str:
    """Return next route from 'router': executor | planner | critic | END.
    Rule:
      - If AI proposed tool calls -> executor
      - Else if ROUTER_FORCE_PLANNER truthy -> planner
      - Else if ROUTER_FORCE_CRITIC truthy -> critic
      - Else -> END
    """
    if has_tool_calls(state):
        return "executor"
    if _truthy(getattr(config, "ROUTER_FORCE_PLANNER", "")):
        return "planner"
    if _truthy(getattr(config, "ROUTER_FORCE_CRITIC", "")):
        return "critic"
    return "END"


# Backward compatibility for older mapping

def need_tools(state: MessagesState) -> str:
    return "executor" if has_tool_calls(state) else "planner"
