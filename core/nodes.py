"""
All the nodes in the graph that is needed
"""
from typing import Dict, List, Optional
from langchain_core.messages import (
    AnyMessage,
    AIMessage,
    ToolMessage,
)
from langchain_openai import ChatOpenAI
from langgraph.graph import MessagesState
from langchain_core.tools import BaseTool
from .utils import ensure_system
from core import config


def _execute_tool_calls(ai_msg: AIMessage, tools_map: Dict[str, BaseTool]) -> List[ToolMessage]:
    """Execute tool calls from an AI message and return ToolMessage list."""
    results: List[ToolMessage] = []
    for call in getattr(ai_msg, "tool_calls", []) or []:
        name = call.get("name") if isinstance(call, dict) else getattr(call, "name", None)
        args = call.get("args", {}) if isinstance(call, dict) else getattr(call, "args", {})
        call_id = call.get("id") if isinstance(call, dict) else getattr(call, "id", None)
        tool = tools_map.get(name)
        if tool is None:
            results.append(ToolMessage(content=f"Tool '{name}' not found.", tool_call_id=call_id))
            continue
        try:
            # BaseTool.invoke expects a dict or str depending on schema
            output = tool.invoke(args)
        except Exception as e:
            output = f"Tool '{name}' error: {e}"
        results.append(ToolMessage(content=str(output), tool_call_id=call_id))
    return results


def router_node(state: MessagesState, llm: ChatOpenAI):
    """
    Router node: decide next step and optionally propose tool calls.
    :param state: Current MessageState
    :param llm: Model bound with tools
    :return: Dict
    """
    messages = ensure_system(state["messages"], override_prompt=config.ROUTER_SYSTEM_PROMPT)
    ai_msg = llm.invoke(messages)
    return {"messages": messages + [ai_msg]}


def planner_node(state: MessagesState, llm: ChatOpenAI):
    """
    Planner node: produce a plan or next reasoning step.
    """
    messages = ensure_system(state["messages"], override_prompt=config.PLANNER_SYSTEM_PROMPT)
    ai_msg = llm.invoke(messages)
    return {"messages": messages + [ai_msg]}


def executor_node(state: MessagesState, llm: ChatOpenAI, tools: Optional[List[BaseTool]] = None):
    """
    Executor node: execute tools requested by the last AI message and append ToolMessages.
    """
    messages: List[AnyMessage] = ensure_system(state["messages"], override_prompt=config.EXECUTOR_SYSTEM_PROMPT)
    tools_map: Dict[str, BaseTool] = {t.name: t for t in (tools or [])}
    last_ai = messages[-1] if messages else None
    tool_msgs: List[ToolMessage] = []
    if isinstance(last_ai, AIMessage) and getattr(last_ai, "tool_calls", None):
        tool_msgs = _execute_tool_calls(last_ai, tools_map)
    # After execution, return messages with tool outputs so LLM can continue
    return {"messages": messages + tool_msgs}


def critical_node(state: MessagesState, llm: ChatOpenAI):
    """
    Critic Node: perform a final check or provide final answer.
    """
    messages = ensure_system(state["messages"], override_prompt=config.CRITIC_SYSTEM_PROMPT)
    ai_msg = llm.invoke(messages)
    return {"messages": messages + [ai_msg]}
