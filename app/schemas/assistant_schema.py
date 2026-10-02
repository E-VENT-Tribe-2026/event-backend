from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AssistantMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class AssistantChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: list[AssistantMessage] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def last_message_must_be_from_user(self):
        if self.messages[-1].role != "user":
            raise ValueError("The latest message must be from the user")
        return self


class AssistantChatResponse(BaseModel):
    reply: str = Field(min_length=1)