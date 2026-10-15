from pydantic import BaseModel, Field, field_validator
from typing import Optional
from datetime import datetime

from app.core.input_limits import CHAT_MESSAGE_MIN_LENGTH, CHAT_MESSAGE_MAX_LENGTH
from app.schemas.profile_schema import UserSummary
from app.utils.schema_validators import validate_text_value


def _validate_message_content(v):
    return validate_text_value(
        v,
        field_label="Message",
        min_length=CHAT_MESSAGE_MIN_LENGTH,
        max_length=CHAT_MESSAGE_MAX_LENGTH,
    )


class ChatMessageCreate(BaseModel):
    """Payload for sending a new chat message in an event."""
    content: str = Field(
        ...,
        min_length=CHAT_MESSAGE_MIN_LENGTH,
        max_length=CHAT_MESSAGE_MAX_LENGTH,
        description="The text content of the message (max 2000 characters).",
        examples=["Hey everyone, can't wait for this event! 🎉"],
    )

    @field_validator("content", mode="before")
    @classmethod
    def validate_content(cls, v):
        return _validate_message_content(v)

    model_config = {
        "json_schema_extra": {
            "example": {
                "content": "Hey everyone, can't wait for this event! 🎉"
            }
        }
    }


class ChatMessageUpdate(BaseModel):
    """Payload for editing an existing chat message."""
    content: str = Field(
        ...,
        min_length=CHAT_MESSAGE_MIN_LENGTH,
        max_length=CHAT_MESSAGE_MAX_LENGTH,
        description="The updated text content of the message.",
        examples=["Updated: see you all at the entrance at 6 PM!"],
    )

    @field_validator("content", mode="before")
    @classmethod
    def validate_content(cls, v):
        return _validate_message_content(v)

    model_config = {
        "json_schema_extra": {
            "example": {
                "content": "Updated: see you all at the entrance at 6 PM!"
            }
        }
    }

class ChatMessageResponse(BaseModel):
    """Shape of a chat message returned from the API."""
    id: int = Field(..., description="Auto-incremented message ID.")
    event_id: str = Field(..., description="UUID of the event this message belongs to.")
    sender_id: Optional[str] = Field(None, description="UUID of the user who sent the message.")
    sender_name: Optional[str] = Field(
        None,
        description='Full name of the sender; "System" for system messages and "Unknown" when the sender has no full name on record.',
    )
    sender_role: Optional[str] = Field(None, description="Role of the sender: organizer, participant, or system.")
    sender: Optional[UserSummary] = Field(None, description="Username, full name, and profile picture of the sender; null for system messages.")
    content: str = Field(..., description="Text content of the message.")
    created_at: datetime = Field(..., description="Timestamp when the message was sent (UTC).")

    model_config = {
        "json_schema_extra": {
            "example": {
                "id": 42,
                "event_id": "550e8400-e29b-41d4-a716-446655440000",
                "sender_id": "a3bb189e-8bf9-3888-9912-ace4e6543002",
                "sender_name": "Jane Doe",
                "sender_role": "organizer",
                # Mirrors UserSummary (app.schemas.profile_schema).
                "sender": {
                    "id": "a3bb189e-8bf9-3888-9912-ace4e6543002",
                    "username": "jane_doe",
                    "full_name": "Jane Doe",
                    "display_name": "jane_doe",
                    "avatar_kind": "icon",
                    "icon_id": "icon_fox",
                    "avatar_url": None
                },
                "content": "Hey everyone, can't wait for this event! 🎉",
                "created_at": "2026-04-22T16:00:00Z"
            }
        }
    }
