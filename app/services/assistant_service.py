import logging

from fastapi import HTTPException
from openai import OpenAI

from app.core.config import settings
from app.schemas.assistant_schema import AssistantMessage


GEMINI_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
logger = logging.getLogger(__name__)
SYSTEM_PROMPT = (
    "You are the E-VENT product orientation assistant. Help users understand "
    "how to use the product. You do not have access to live event listings, "
    "account data, or the ability to create or modify events. Do not claim to "
    "have looked up or changed anything. If asked for live or account-specific "
    "information, explain this limitation and suggest where the user can find it."
)


def generate_reply(messages: list[AssistantMessage]) -> str:
    if not settings.GEMINI_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="AI assistant is not configured.",
        )

    provider_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    provider_messages.extend(message.model_dump() for message in messages)

    try:
        client = OpenAI(
            api_key=settings.GEMINI_API_KEY,
            base_url=GEMINI_OPENAI_BASE_URL,
            timeout=20.0,
            max_retries=0,
        )
        response = client.chat.completions.create(
            model=settings.GEMINI_MODEL,
            messages=provider_messages,
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