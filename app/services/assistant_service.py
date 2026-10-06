import logging
from typing import Any, Optional

from fastapi import HTTPException
from openai import OpenAI

from app.core.config import settings
from app.schemas.assistant_schema import AssistantMessage
from app.agents.graph import create_agent_graph
from app.agents.guardian import GuardianAgent, GUARDIAN_PROMPT
from app.agents.main_agent import MAIN_AGENT_PROMPT
from app.agents.state import AgentState


GEMINI_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
logger = logging.getLogger(__name__)

# Re-export for compatibility
SYSTEM_PROMPT = MAIN_AGENT_PROMPT

_COMPILED_GRAPH = None


def get_agent_graph():
    """Lazily initialize and return the compiled LangGraph workflow."""
    global _COMPILED_GRAPH
    if _COMPILED_GRAPH is None:
        _COMPILED_GRAPH = create_agent_graph()
    return _COMPILED_GRAPH


def call_llm(messages: list[dict[str, str]]) -> str:
    """Invoke the LLM provider via OpenAI compatibility layer."""
    if not settings.GEMINI_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="AI assistant is not configured.",
        )

    try:
        client = OpenAI(
            api_key=settings.GEMINI_API_KEY,
            base_url=GEMINI_OPENAI_BASE_URL,
            timeout=20.0,
            max_retries=0,
        )
        response = client.chat.completions.create(
            model=settings.GEMINI_MODEL,
            messages=messages,
        )
        reply = response.choices[0].message.content
        if not isinstance(reply, str) or not reply.strip():
            raise ValueError("Provider returned an empty response")
        return reply.strip()

    except Exception as exc:
        logger.error(
            "Gemini request failed (type=%s, status=%s)",
            type(exc).__name__,
            getattr(exc, "status_code", None),
        )
        raise HTTPException(
            status_code=502,
            detail="AI assistant is temporarily unavailable.",
        ) from None


def run_agent_workflow(messages: list[dict[str, str]], user_id: Optional[str] = None) -> AgentState:
    """Execute the multi-turn 2-agent LangGraph workflow."""
    graph = get_agent_graph()
    initial_state: AgentState = {
        "messages": messages,
        "user_id": user_id,
        "entity_slots": {},
        "input_guard_passed": False,
        "output_guard_passed": False,
    }
    return graph.invoke(initial_state)


def generate_reply(messages: list[AssistantMessage]) -> str:
    """Generate assistant reply using the 2-agent LangGraph pipeline."""
    if not settings.GEMINI_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="AI assistant is not configured.",
        )

    raw_messages = [message.model_dump() for message in messages]
    result_state = run_agent_workflow(raw_messages)
    return result_state.get("reply", "")