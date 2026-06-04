from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.message import clear_messages, get_messages
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.message import MessageOut

router = APIRouter(prefix="/messages", tags=["messages"])


@router.post("/all", response_model=list[MessageOut])
async def list_messages(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await get_messages(db, user.id)


@router.post("/clear")
async def clear(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await clear_messages(db, user.id)
    return {"ok": True}
