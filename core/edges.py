"""
Edges and graph builder for the agent
"""
from typing import Callable, Dict
from langgraph.graph import END, StateGraph
from langgraph.graph import MessagesState
from .utils import router_decision


def build_graph(nodes: Dict[str, Callable[[MessagesState], dict]]):
    """Build and compile a MessagesState graph from provided node callables.

    Expected keys in nodes: router, planner, executor, critic
    Each value should be a callable(state) -> dict returning partial state updates.
    """
    graph = StateGraph(MessagesState)  # type: ignore[arg-type]

    graph.add_node("router", nodes["router"])
    graph.add_node("planner", nodes["planner"])
    graph.add_node("executor", nodes["executor"])
    graph.add_node("critic", nodes["critic"])

    graph.set_entry_point("router")

    # Router can branch to executor | planner | critic | END
    graph.add_conditional_edges(
        "router",
        router_decision,
        {"executor": "executor", "planner": "planner", "critic": "critic", "END": END},
    )

    # All work nodes return to router; router decides to continue or END
    graph.add_edge("executor", "router")
    graph.add_edge("planner", "router")
    graph.add_edge("critic", "router")

    return graph.compile()
