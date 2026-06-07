import asyncio

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.config import settings
from app.dependencies import get_current_user
from app.models.user import User
from app.services.notify import notify_admin

router = APIRouter(prefix="/feedback", tags=["feedback"])

STARS = {1: "⭐", 2: "⭐⭐", 3: "⭐⭐⭐", 4: "⭐⭐⭐⭐", 5: "⭐⭐⭐⭐⭐"}


class FeedbackIn(BaseModel):
    stars: int = Field(..., ge=1, le=5)
    text: str | None = Field(None, max_length=2000)


@router.post("")
async def submit_feedback(
    body: FeedbackIn,
    user: User = Depends(get_current_user),
):
    username = f"@{user.username}" if user.username else user.first_name or str(user.telegram_id)
    lines = [
        f"💬 <b>Фидбэк</b>",
        f"<b>От:</b> {username}",
        f"<b>Оценка:</b> {STARS[body.stars]}",
    ]
    if body.text:
        lines.append(f"<b>Комментарий:</b> {body.text}")

    asyncio.create_task(notify_admin("\n".join(lines), settings.bot_token, settings.admin_chat_id))
    return {"ok": True}
