from typing import Any, Optional, TypedDict, Literal


class AgentState(TypedDict, total=False):
    """Shared state for the 2-agent LangGraph architecture."""

    # Multi-turn conversation messages
    messages: list[dict[str, str]]
    user_id: Optional[str]

    # Entity slot tracking across conversation turns
    entity_slots: dict[str, Any]

    # Intent classification
    intent: Optional[Literal["chat", "search_events", "get_event_details", "draft_new_event", "clarification", "blocked"]]

    # Deterministic tool dispatching
    tool_name: Optional[str]
    tool_input: Optional[dict[str, Any]]
    tool_output: Optional[dict[str, Any]]
    tool_executed: bool

    # GuardianAgent dual-gate status
    input_guard_passed: bool
    output_guard_passed: bool
    guard_block_reason: Optional[str]

    # Final synthesized reply and UI card metadata
    reply: Optional[str]
    metadata: Optional[dict[str, Any]]
