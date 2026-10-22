from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.dependencies import get_current_user, require_regular_user
from app.schemas.block_schema import BlockItem, BlockMessage, BlockPage, BlockRequest
from app.services.block_service import block_user, get_blocked_users, unblock_user
from app.services.friendship_service import DEFAULT_PAGE_LIMIT, MAX_PAGE_LIMIT

router = APIRouter()

MAX_PAGE = 10000


@router.post("", status_code=201, response_model=BlockItem)
def block(body: BlockRequest, user=Depends(require_regular_user)):
    return block_user(user.id, str(body.user_id))


@router.get("", response_model=BlockPage)
def list_blocked(
    page: int = Query(1, ge=1, le=MAX_PAGE),
    limit: int = Query(DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
    user=Depends(require_regular_user),
):
    return get_blocked_users(user.id, page, limit)


@router.delete("/{user_id}", response_model=BlockMessage)
def unblock(user_id: UUID, user=Depends(require_regular_user)):
    return unblock_user(user.id, str(user_id))
