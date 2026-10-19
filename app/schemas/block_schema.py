from datetime import datetime
from typing import List, Union
from uuid import UUID

from pydantic import BaseModel

from app.schemas.profile_schema import UserSummary


class BlockRequest(BaseModel):
    user_id: UUID


class BlockItem(BaseModel):
    blocked_at: Union[str, datetime]
    user: UserSummary


class BlockPage(BaseModel):
    page: int
    limit: int
    has_more: bool
    data: List[BlockItem]


class BlockMessage(BaseModel):
    message: str
