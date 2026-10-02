from fastapi import APIRouter, Depends

from app.core.dependencies import get_current_user
from app.schemas.assistant_schema import AssistantChatRequest, AssistantChatResponse
from app.services.assistant_service import generate_reply


router = APIRouter()


@router.post("/chat", response_model=AssistantChatResponse)
def chat(body: AssistantChatRequest, _user=Depends(get_current_user)):
    return AssistantChatResponse(reply=generate_reply(body.messages))