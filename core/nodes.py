"""
All the nodes in the graph that is needed
"""
from typing import Any, Dict, List, Optional, Tuple
import asyncio
import inspect
import json

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
from core.observability.tracing import get_tracer


def _serialize_output(output: Any) -> str:
    if isinstance(output, str):
        return output
    try:
        return json.dumps(output, default=str)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


async def _execute_tool_calls(
    ai_msg: AIMessage, tools_map: Dict[str, BaseTool]
) -> List[ToolMessage]:
    """Execute tool calls, awaiting async tools concurrently."""
    tracer = get_tracer()
    results: List[ToolMessage] = []
    async_calls: List[Tuple[str, BaseTool, Dict[str, Any], str]] = []

    for call in getattr(ai_msg, "tool_calls", []) or []:
        name = call.get("name") if isinstance(call, dict) else getattr(call, "name", None)
        args = call.get("args", {}) if isinstance(call, dict) else getattr(call, "args", {})
        call_id = call.get("id") if isinstance(call, dict) else getattr(call, "id", None)
        tracer.log("tool_call_start", tool=name, tool_call_id=call_id)
        tool = tools_map.get(name)
        if tool is None:
            tracer.log("tool_call_missing", tool=name, tool_call_id=call_id)
            results.append(ToolMessage(content=f"Tool '{name}' not found.", tool_call_id=call_id))
            continue

        if getattr(tool, "coroutine", False) or inspect.iscoroutinefunction(getattr(tool, "ainvoke", None)):
            async_calls.append((call_id, tool, args, name))
        else:
            try:
                output = tool.invoke(args)
                tracer.log("tool_call_end", tool=name, tool_call_id=call_id)
            except Exception as e:
                tracer.log("tool_call_error", tool=name, tool_call_id=call_id, error=str(e))
                output = {"success": False, "error": str(e)}
            results.append(ToolMessage(content=_serialize_output(output), tool_call_id=call_id))

    if async_calls:
        tasks = [tool.ainvoke(args) for _, tool, args, _ in async_calls]
        outputs = await asyncio.gather(*tasks, return_exceptions=True)
        for (call_id, _, _, name), output in zip(async_calls, outputs):
            if isinstance(output, Exception):
                tracer.log("tool_call_error", tool=name, tool_call_id=call_id, error=str(output))
                payload = {"success": False, "error": str(output)}
            else:
                tracer.log("tool_call_end", tool=name, tool_call_id=call_id)
                payload = output
            results.append(ToolMessage(content=_serialize_output(payload), tool_call_id=call_id))

    return results


def router_node(state: MessagesState, llm: ChatOpenAI):
    """
    Router node: decide next step and optionally propose tool calls.
    :param state: Current MessageState
    :param llm: Model bound with tools
    :return: Dict
    """
    tracer = get_tracer()
    tracer.log("node_start", node="router", messages_len=len(state.get("messages", [])))
    messages = ensure_system(state["messages"], override_prompt=config.ROUTER_SYSTEM_PROMPT)
    ai_msg = llm.invoke(messages)
    tracer.log(
        "node_end",
        node="router",
        ai_has_tool_calls=bool(getattr(ai_msg, "tool_calls", None)),
    )
    return {"messages": messages + [ai_msg]}


def planner_node(state: MessagesState, llm: ChatOpenAI):
    """
    Planner node: produce a plan or next reasoning step.
    """
    tracer = get_tracer()
    tracer.log("node_start", node="planner", messages_len=len(state.get("messages", [])))
    messages = ensure_system(state["messages"], override_prompt=config.PLANNER_SYSTEM_PROMPT)
    ai_msg = llm.invoke(messages)
    tracer.log("node_end", node="planner")
    return {"messages": messages + [ai_msg]}


async def executor_node(state: MessagesState, llm: ChatOpenAI, tools: Optional[List[BaseTool]] = None):
    """
    Executor node: execute tools requested by the last AI message and append ToolMessages.
    """
    tracer = get_tracer()
    tracer.log("node_start", node="executor", messages_len=len(state.get("messages", [])))
    messages: List[AnyMessage] = ensure_system(state["messages"], override_prompt=config.EXECUTOR_SYSTEM_PROMPT)
    tools_map: Dict[str, BaseTool] = {t.name: t for t in (tools or [])}
    last_ai = messages[-1] if messages else None
    tool_msgs: List[ToolMessage] = []
    if isinstance(last_ai, AIMessage) and getattr(last_ai, "tool_calls", None):
        tool_msgs = await _execute_tool_calls(last_ai, tools_map)
    tracer.log("node_end", node="executor", tool_msgs=len(tool_msgs))
    return {"messages": messages + tool_msgs}


def critical_node(state: MessagesState, llm: ChatOpenAI):
    """
    Critic Node: perform a final check or provide final answer.
    """
    tracer = get_tracer()
    tracer.log("node_start", node="critic", messages_len=len(state.get("messages", [])))
    messages = ensure_system(state["messages"], override_prompt=config.CRITIC_SYSTEM_PROMPT)
    ai_msg = llm.invoke(messages)
    tracer.log("node_end", node="critic")
    return {"messages": messages + [ai_msg]}
