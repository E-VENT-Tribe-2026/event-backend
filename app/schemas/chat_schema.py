from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class ChatMessageCreate(BaseModel):
    """Payload for sending a new chat message in an event."""
    content: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="The text content of the message (max 2000 characters).",
        examples=["Hey everyone, can't wait for this event! 🎉"],
    )

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
        min_length=1,
        max_length=2000,
        description="The updated text content of the message.",
        examples=["Updated: see you all at the entrance at 6 PM!"],
    )

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
    sender_name: Optional[str] = Field(None, description="Full name of the sender.")
    sender_role: Optional[str] = Field(None, description="Role of the sender: organizer, participant, or system.")
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
                "content": "Hey everyone, can't wait for this event! 🎉",
                "created_at": "2026-04-22T16:00:00Z"
            }
        }
    }
