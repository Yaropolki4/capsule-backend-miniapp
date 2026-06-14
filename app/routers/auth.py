import json
import logging

from fastapi import APIRouter, Depends, HTTPException

logger = logging.getLogger(__name__)
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.user import get_or_create_user, mark_app_started
from app.database import get_db
from app.dependencies import verify_telegram_init_data
from app.schemas.user import UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/", response_model=UserOut)
async def auth(init_data: str, db: AsyncSession = Depends(get_db)):
    parsed = verify_telegram_init_data(init_data)

    tg_user = json.loads(parsed.get("user", "{}"))
    telegram_id = tg_user.get("id")

    if not telegram_id:
        raise HTTPException(status_code=400, detail="User data missing")

    user, created = await get_or_create_user(
        db,
        telegram_id=telegram_id,
        username=tg_user.get("username"),
        first_name=tg_user.get("first_name"),
    )
    if created:
        logger.info("New user registered | telegram_id=%s username=%s", telegram_id, tg_user.get("username"))
    else:
        logger.debug("User authenticated | telegram_id=%s", telegram_id)

    if not user.is_started_app:
        user = await mark_app_started(db, user)
        logger.info("First app open | telegram_id=%s generations_left=%s", telegram_id, user.generations_left)

    return user
