import logging
from typing import Any
from langgraph.graph import StateGraph, START, END

from app.agents.state import AgentState
from app.agents.guardian import GuardianAgent
from app.agents.main_agent import MainAgent
from app.agents.tools import TOOL_REGISTRY

logger = logging.getLogger(__name__)


def guardian_input_node(state: AgentState) -> AgentState:
    """Evaluate incoming user prompt through the input gate."""
    return GuardianAgent.evaluate_input(state)


def main_agent_node(state: AgentState) -> AgentState:
    """Execute main conversational reasoning, intent identification, and response formatting."""
    return MainAgent.execute(state)


def tools_node(state: AgentState) -> AgentState:
    """Execute deterministic backend tools per specification."""
    tool_name = state.get("tool_name")
    tool_input = state.get("tool_input") or {}

    tool_fn = TOOL_REGISTRY.get(tool_name)
    if tool_fn:
        try:
            output = tool_fn(tool_input)
        except Exception as exc:
            logger.error("Error executing tool %s: %s", tool_name, exc, exc_info=True)
            output = {
                "success": False,
                "error": {"code": "INTERNAL_ERROR", "message": f"Failed executing {tool_name}."}
            }
    else:
        output = {
            "success": False,
            "error": {"code": "TOOL_NOT_FOUND", "message": f"Tool {tool_name} is not registered."}
        }

    state["tool_output"] = output
    state["tool_executed"] = True
    return state


def guardian_output_node(state: AgentState) -> AgentState:
    """Sanitize the generated response through the output gate."""
    return GuardianAgent.sanitize_output(state)


def route_after_input_guard(state: AgentState) -> str:
    """Route to output gate if input blocked, otherwise proceed to main agent."""
    if not state.get("input_guard_passed", True):
        return "guardian_output"
    return "main_agent"


def route_after_main_agent(state: AgentState) -> str:
    """Route to tools if a tool dispatch was requested and not yet executed."""
    if state.get("tool_name") and not state.get("tool_executed", False):
        return "tools"
    return "guardian_output"


def create_agent_graph():
    """Build and compile the 2-agent LangGraph workflow."""
    workflow = StateGraph(AgentState)

    # Register nodes
    workflow.add_node("guardian_input", guardian_input_node)
    workflow.add_node("main_agent", main_agent_node)
    workflow.add_node("tools", tools_node)
    workflow.add_node("guardian_output", guardian_output_node)

    # Define edges
    workflow.add_edge(START, "guardian_input")

    workflow.add_conditional_edges(
        "guardian_input",
        route_after_input_guard,
        {
            "guardian_output": "guardian_output",
            "main_agent": "main_agent",
        },
    )

    workflow.add_conditional_edges(
        "main_agent",
        route_after_main_agent,
        {
            "tools": "tools",
            "guardian_output": "guardian_output",
        },
    )

    # After tools execution, route back to main_agent to format response
    workflow.add_edge("tools", "main_agent")

    # Output gate leads to END
    workflow.add_edge("guardian_output", END)

    return workflow.compile()
