"""Give a LangGraph agent durable, semantic, per-user memory with Crowkis.

    pip install crowkis        # CrowkisMemory needs NO extra dependency

CrowkisMemory works in any framework (LangGraph, CrewAI, AutoGen, or your own
loop). Here it is wired into two LangGraph nodes: recall context before the model
runs, then remember the turn afterwards.
"""

from crowkis import CrowkisMemory

mem = CrowkisMemory(agent="planner", user="alice", tenant="demo")


def recall_node(state: dict) -> dict:
    """Pull the most relevant long-term memories into the state."""
    state["memory"] = mem.recall(state["input"], k=5)
    return state


def remember_node(state: dict) -> dict:
    """Persist what happened so the next session remembers it."""
    mem.remember(f"user asked: {state['input']}")
    return state


# In LangGraph:
#   from langgraph.graph import StateGraph
#   g = StateGraph(dict)
#   g.add_node("recall", recall_node)
#   g.add_node("remember", remember_node)
#   ...
#
# Tip: also call set_llm_cache(CrowkisCache(...)) (see python_langchain_cache.py)
# so the model calls inside your graph are semantically cached too.
