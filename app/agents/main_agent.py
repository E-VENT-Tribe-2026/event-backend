import json
import re
import logging
from typing import Any, Callable, Optional
from app.agents.state import AgentState

logger = logging.getLogger(__name__)

MAIN_AGENT_PROMPT = (
    "You are the E-VENT Main Assistant, the primary conversational and execution engine for the E-VENT platform.\n\n"
    "Your responsibilities:\n"
    "1. Intent Classification & Guidance: Help users understand the platform, explore features, and answer product questions.\n"
    "2. Ambiguity & Clarification: If the user makes an ambiguous, incomplete, or underspecified request (e.g. asking to create an event with no details, or asking for event details without specifying which event), ask clear, polite clarifying questions.\n"
    "3. Entity Tracking & Tool Selection: When the user wants to perform an action, determine the appropriate tool and parameters:\n"
    "   - search_events: To find, search, or list events (parameters: query, category, city, date, page, limit).\n"
    "   - get_event_details: To retrieve details for a specific event (parameter: event_id in UUID format).\n"
    "   - draft_new_event: To draft/preview a new event (parameters: title, start_datetime, end_datetime, description, category, cost, max_capacity, location_name, latitude, longitude). Note: You only draft previews; events are never published autonomously.\n\n"
    "Response Format Guidelines:\n"
    "- If you decide to invoke a tool, output a tool call block in the following exact format:\n"
    "```tool_call\n"
    '{"tool": "<tool_name>", "parameters": {<tool_parameters>}}\n'
    "```\n"
    "- If no tool call is needed (e.g. general product guidance, FAQ, or asking for clarification), respond directly to the user in friendly, helpful markdown.\n"
    "- If you are provided with tool execution results, synthesize those results into an informative, user-friendly markdown response."
)


class MainAgent:
    """
    MainAgent powered by LLM reasoning with a single system prompt.
    All intent classification, slot tracking, clarification, and tool decisions
    are handled by the LLM rather than deterministic if-else rules.
    """

    @classmethod
    def execute(cls, state: AgentState, llm_caller: Optional[Callable[[list[dict[str, str]]], str]] = None) -> AgentState:
        """Execute MainAgent reasoning turn via LLM."""
        if llm_caller is None:
            from app.services.assistant_service import call_llm
            llm_caller = call_llm

        # If a tool was executed, synthesize the final response
        if state.get("tool_executed", False) and state.get("tool_output") is not None:
            return cls._synthesize_tool_result(state, llm_caller)

        # Build prompt messages for the LLM
        messages = state.get("messages", [])
        prompt_messages = [{"role": "system", "content": MAIN_AGENT_PROMPT}]
        prompt_messages.extend(messages)

        # Call the LLM to perform intent classification, clarification, or tool dispatch
        response_text = llm_caller(prompt_messages)
        return cls._process_llm_response(state, response_text)

    @classmethod
    def _process_llm_response(cls, state: AgentState, response_text: str) -> AgentState:
        """Inspect LLM output to detect if a tool call was requested or if a direct reply was provided."""
        tool_call = cls._extract_tool_call(response_text)

        if tool_call:
            tool_name = tool_call.get("tool") or tool_call.get("action")
            params = tool_call.get("parameters") or tool_call.get("arguments") or {}

            state["intent"] = tool_name
            state["tool_name"] = tool_name
            state["tool_input"] = params

            # Accumulate extracted entity slots from LLM tool parameters
            slots = state.get("entity_slots") or {}
            slots.update(params)
            state["entity_slots"] = slots
            state["reply"] = None
        else:
            # LLM provided a direct response (orientation, FAQ, or clarification)
            state["reply"] = response_text.strip()
            state["tool_name"] = None
            state["tool_input"] = None
            state["intent"] = "clarification" if any(q in response_text.lower() for q in ["could you", "please provide", "which event"]) else "chat"

        return state

    @classmethod
    def _extract_tool_call(cls, text: str) -> Optional[dict[str, Any]]:
        """Extract tool call JSON from tool_call code block or raw JSON object."""
        # Check ```tool_call ... ``` or ```json ... ```
        block_match = re.search(r"```(?:tool_call|json)?\s*(\{[\s\S]*?\})\s*```", text)
        if block_match:
            try:
                data = json.loads(block_match.group(1))
                if isinstance(data, dict) and ("tool" in data or "action" in data):
                    return data
            except json.JSONDecodeError:
                pass

        # Check standalone JSON object
        raw_match = re.search(r"\{\s*[\"'](?:tool|action)[\"']\s*:\s*[\"'][^\"']+[\"'][\s\S]*?\}", text)
        if raw_match:
            try:
                data = json.loads(raw_match.group(0))
                if isinstance(data, dict) and ("tool" in data or "action" in data):
                    return data
            except json.JSONDecodeError:
                pass

        return None

    @classmethod
    def _synthesize_tool_result(cls, state: AgentState, llm_caller: Callable[[list[dict[str, str]]], str]) -> AgentState:
        """Format or synthesize the tool execution results into the final reply."""
        tool_name = state.get("tool_name")
        output = state.get("tool_output", {})

        # Populate rich metadata card
        if tool_name == "search_events":
            events = output.get("events", [])
            state["metadata"] = {"type": "event_search_results", "events": events}
            if not events:
                state["reply"] = "I searched for events matching your criteria, but didn't find any active listings."
            else:
                lines = ["Here are the events I found for you:\n"]
                for ev in events:
                    lines.append(f"- **{ev.get('title')}** ({ev.get('category')}) at {ev.get('location_name', 'TBA')} — {ev.get('start_datetime')}")
                state["reply"] = "\n".join(lines)

        elif tool_name == "get_event_details":
            ev = output.get("event")
            if not ev or not output.get("success"):
                err = output.get("error", {}).get("message", "Event not found.")
                state["reply"] = f"Could not retrieve event details: {err}"
                state["metadata"] = None
            else:
                state["metadata"] = {"type": "event_details_card", "event": ev}
                state["reply"] = (
                    f"### {ev.get('title')}\n"
                    f"- **Category:** {ev.get('category')}\n"
                    f"- **Location:** {ev.get('location_name', 'TBA')}\n"
                    f"- **Time:** {ev.get('start_datetime')} to {ev.get('end_datetime')}\n"
                    f"- **Cost:** €{ev.get('cost', 0)}\n"
                    f"- **Description:** {ev.get('description') or 'No description provided.'}"
                )

        elif tool_name == "draft_new_event":
            success = output.get("success", False)
            draft = output.get("draft")
            issues = output.get("validation_issues", [])
            state["metadata"] = {
                "type": "draft_event_preview",
                "draft": draft,
                "validation_issues": issues,
            }

            if success and draft:
                state["reply"] = (
                    f"### Draft Event Preview\n"
                    f"Here is your event draft:\n"
                    f"- **Title:** {draft.get('title')}\n"
                    f"- **Starts:** {draft.get('start_datetime')}\n"
                    f"- **Ends:** {draft.get('end_datetime')}\n"
                    f"- **Location:** {draft.get('location_name', 'TBA')}\n"
                    f"- **Cost:** €{draft.get('cost', 0)}\n\n"
                    f"> **Note:** This is a draft preview only. To publish this event, please review and confirm in the application interface."
                )
            else:
                issue_lines = [f"- {iss.get('field')}: {iss.get('message')}" for iss in issues]
                state["reply"] = (
                    f"I couldn't complete the draft preview because of the following validation issues:\n"
                    + "\n".join(issue_lines)
                )

        return state
