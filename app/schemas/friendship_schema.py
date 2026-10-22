from datetime import datetime
from typing import List, Union
from uuid import UUID

from pydantic import AliasChoices, BaseModel, Field

from app.schemas.profile_schema import UserSummary


class SendFriendRequest(BaseModel):
    receiver_id: UUID = Field(
        validation_alias=AliasChoices("receiver_id", "user_id", "receiverId", "userId")
    )


class FriendRequestItem(BaseModel):
    request_id: int
    created_at: Union[str, datetime]
    user: UserSummary


class FriendItem(BaseModel):
    friend_since: Union[str, datetime]
    user: UserSummary


class FriendRequestPage(BaseModel):
    page: int
    limit: int
    has_more: bool
    data: List[FriendRequestItem]


class FriendPage(BaseModel):
    page: int
    limit: int
    has_more: bool
    data: List[FriendItem]


class SuggestionItem(BaseModel):
    user: UserSummary


class SuggestionPage(BaseModel):
    page: int
    limit: int
    has_more: bool
    data: List[SuggestionItem]


class FriendRequestCount(BaseModel):
    count: int


class MessageResponse(BaseModel):
    message: str
