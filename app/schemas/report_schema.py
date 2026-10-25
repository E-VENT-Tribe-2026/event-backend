from datetime import datetime
from typing import Optional, Union
from uuid import UUID

from pydantic import BaseModel, Field, StrictInt, StrictStr, field_validator, model_validator

from app.core.input_limits import REPORT_DESCRIPTION_MAX_LENGTH
from app.utils.schema_validators import validate_text_value

TARGET_EVENT = "event"
TARGET_USER = "user"
TARGET_MESSAGE = "message"

ORIGIN_EVENT_DETAILS = "event_details"
ORIGIN_PROFILE = "profile"
ORIGIN_EVENT_CHAT = "event_chat"

REASON_OTHER = "other"
REASON_MISLEADING_EVENT = "misleading_event"

REPORT_REASONS = (
    "spam",
    "inappropriate_content",
    "harassment_or_hate",
    "scam_or_fraud",
    REASON_MISLEADING_EVENT,
    REASON_OTHER,
)

# "Misleading event" only makes sense for an event.
EVENT_REASONS = REPORT_REASONS
USER_AND_MESSAGE_REASONS = tuple(r for r in REPORT_REASONS if r != REASON_MISLEADING_EVENT)

ALLOWED_ORIGINS = {
    TARGET_EVENT: (ORIGIN_EVENT_DETAILS, ORIGIN_EVENT_CHAT),
    TARGET_USER: (ORIGIN_PROFILE,),
    TARGET_MESSAGE: (ORIGIN_EVENT_CHAT,),
}

MAX_MESSAGE_ID = 9223372036854775807  # postgres bigint upper bound


class ReportCreate(BaseModel):
    """Payload for reporting an event, a user, or a message in an event chat."""
    target_type: str = Field(..., description='What is reported: "event", "user" or "message".')
    target_id: Union[StrictStr, StrictInt] = Field(
        ..., description="Event UUID, user UUID, or chat message id, depending on target_type."
    )
    reason: str = Field(..., description="One of: " + ", ".join(REPORT_REASONS) + ".")
    description: Optional[str] = Field(
        None,
        description=f"Optional text (max {REPORT_DESCRIPTION_MAX_LENGTH} characters); required when the reason is other.",
    )
    origin: str = Field(..., description='Where the report was opened: "event_details", "profile" or "event_chat".')

    @field_validator("target_type", "reason", "origin", mode="before")
    @classmethod
    def _plain_text(cls, v):
        if not isinstance(v, str):
            raise ValueError("Must be text.")
        return v.strip().lower()

    @field_validator("description", mode="before")
    @classmethod
    def _validate_description(cls, v):
        if v is None:
            return None
        # Whether it is required depends on the reason, so that is checked in _check_combination.
        return validate_text_value(
            v,
            field_label="Description",
            min_length=0,
            max_length=REPORT_DESCRIPTION_MAX_LENGTH,
        ) or None

    @model_validator(mode="after")
    def _check_combination(self):
        if self.target_type not in ALLOWED_ORIGINS:
            raise ValueError('target_type must be "event", "user" or "message".')
        if self.origin not in ALLOWED_ORIGINS[self.target_type]:
            raise ValueError(
                f"A report about a {self.target_type} cannot be opened from {self.origin}."
            )

        allowed = EVENT_REASONS if self.target_type == TARGET_EVENT else USER_AND_MESSAGE_REASONS
        if self.reason not in allowed:
            raise ValueError(
                f"Reason is not valid for a report about a {self.target_type}. "
                "Allowed: " + ", ".join(allowed) + "."
            )

        if self.reason == REASON_OTHER and not self.description:
            raise ValueError("Description is required when the reason is Other.")

        if self.target_type == TARGET_MESSAGE:
            raw = self.target_id
            if isinstance(raw, bool) or (isinstance(raw, str) and not raw.strip().isdigit()):
                raise ValueError("target_id must be a chat message id.")
            value = int(raw)
            if not 1 <= value <= MAX_MESSAGE_ID:
                raise ValueError("target_id must be a chat message id.")
            self.target_id = str(value)
        else:
            try:
                self.target_id = str(UUID(str(self.target_id)))
            except ValueError:
                raise ValueError(f"target_id must be the id of the {self.target_type}.")
        return self

    model_config = {
        "json_schema_extra": {
            "example": {
                "target_type": "message",
                "target_id": "42",
                "reason": "harassment_or_hate",
                "description": "Keeps insulting other participants.",
                "origin": "event_chat",
            }
        }
    }


class ReportConfirmation(BaseModel):
    id: int
    status: str
    target_type: str
    target_id: str
    reason: str
    origin: str
    created_at: Union[str, datetime]
    message: str
