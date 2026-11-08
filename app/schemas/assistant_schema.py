from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AssistantMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    # Assistant replies list events and can be much longer than a user message.
    content: str = Field(min_length=1, max_length=12000)

    @model_validator(mode="after")
    def limit_user_message_length(self):
        if self.role == "user" and len(self.content) > 2000:
            raise ValueError("User messages must be at most 2000 characters.")
        return self


class AssistantChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: list[AssistantMessage] = Field(min_length=1, max_length=20)
    draft: Optional[dict[str, Any]] = None

    @model_validator(mode="after")
    def last_message_must_be_from_user(self):
        if self.messages[-1].role != "user":
            raise ValueError("The latest message must be from the user")
        return self


class AssistantChatResponse(BaseModel):
    reply: str = Field(min_length=1)
    draft: Optional[dict[str, Any]] = None
    validation_issues: Optional[list[str]] = None