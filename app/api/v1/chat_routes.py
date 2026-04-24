from fastapi import APIRouter, Depends, Query
from app.core.dependencies import get_current_user
from app.schemas.chat_schema import ChatMessageCreate, ChatMessageUpdate, ChatMessageResponse
from app.services.chat_service import (
    send_message,
    get_event_messages,
    update_message,
    delete_message,
)

router = APIRouter()


@router.post(
    "/{event_id}/messages",
    response_model=ChatMessageResponse,
    status_code=201,
    summary="Send a chat message",
    description=(
        "Post a new message to an event's chat room.\n\n"
        "**Requirements:**\n"
        "- You must be authenticated (Bearer JWT).\n"
        "- You must be a participant of the event.\n\n"
        "**Errors:**\n"
        "- `403` — not a participant of the event.\n"
        "- `400` — empty message content."
    ),
    responses={
        201: {"description": "Message sent successfully."},
        400: {"description": "Empty message content."},
        403: {"description": "Not a participant of this event."},
        401: {"description": "Missing or invalid JWT token."},
    },
)
def post_message(
    event_id: str,
    body: ChatMessageCreate,
    user=Depends(get_current_user),
):
    return send_message(user.id, event_id, body.content)


@router.get(
    "/{event_id}/messages",
    summary="Get event chat messages",
    description=(
        "Retrieve paginated chat messages for an event, ordered oldest-first.\n\n"
        "**Requirements:**\n"
        "- You must be authenticated (Bearer JWT).\n"
        "- You must be a participant of the event.\n\n"
        "**Query params:**\n"
        "- `page` — page number (default: 1)\n"
        "- `limit` — messages per page, max 100 (default: 50)"
    ),
    responses={
        200: {"description": "Paginated list of chat messages."},
        403: {"description": "Not a participant of this event."},
        401: {"description": "Missing or invalid JWT token."},
    },
)
def list_messages(
    event_id: str,
    page: int = Query(1, ge=1, description="Page number (starts at 1)."),
    limit: int = Query(50, le=100, description="Number of messages per page (max 100)."),
    user=Depends(get_current_user),
):
    return get_event_messages(user.id, event_id, page, limit)


@router.put(
    "/messages/{message_id}",
    response_model=ChatMessageResponse,
    summary="Edit a chat message",
    description=(
        "Update the content of an existing chat message.\n\n"
        "**Requirements:**\n"
        "- You must be authenticated (Bearer JWT).\n"
        "- You must be the **original sender** of the message.\n\n"
        "**Errors:**\n"
        "- `403` — you are not the sender.\n"
        "- `404` — message not found.\n"
        "- `400` — empty updated content."
    ),
    responses={
        200: {"description": "Message updated successfully."},
        400: {"description": "Empty updated content."},
        403: {"description": "You can only edit your own messages."},
        404: {"description": "Message not found."},
        401: {"description": "Missing or invalid JWT token."},
    },
)
def edit_message(
    message_id: int,
    body: ChatMessageUpdate,
    user=Depends(get_current_user),
):
    return update_message(user.id, message_id, body.content)


@router.delete(
    "/messages/{message_id}",
    summary="Delete a chat message",
    description=(
        "Permanently remove a chat message.\n\n"
        "**Requirements:**\n"
        "- You must be authenticated (Bearer JWT).\n"
        "- You must be the **original sender** of the message.\n\n"
        "**Errors:**\n"
        "- `403` — you are not the sender.\n"
        "- `404` — message not found."
    ),
    responses={
        200: {"description": "Message deleted successfully."},
        403: {"description": "You can only delete your own messages."},
        404: {"description": "Message not found."},
        401: {"description": "Missing or invalid JWT token."},
    },
)
def remove_message(
    message_id: int,
    user=Depends(get_current_user),
):
    return delete_message(user.id, message_id)
