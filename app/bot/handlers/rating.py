import asyncio
import html
import logging

from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.crud.outfit import rate_outfit
from app.crud.user import get_user_by_telegram_id
from app.services.notify import notify_admin

logger = logging.getLogger(__name__)

router = Router()

STARS = {1: "⭐", 2: "⭐⭐", 3: "⭐⭐⭐", 4: "⭐⭐⭐⭐", 5: "⭐⭐⭐⭐⭐"}


@router.callback_query(F.data.startswith("rate:"))
async def handle_rate_callback(callback: CallbackQuery, db: AsyncSession):
    try:
        _, outfit_id_str, stars_str = callback.data.split(":")
        outfit_id = int(outfit_id_str)
        stars = int(stars_str)
    except (ValueError, AttributeError):
        await callback.answer()
        return

    user = await get_user_by_telegram_id(db, callback.from_user.id)
    if not user:
        await callback.answer()
        return

    outfit = await rate_outfit(db, outfit_id, user.id, stars)

    if outfit is None:
        await callback.answer("Вы уже оценили этот образ", show_alert=False)
        return

    await callback.answer(f"Спасибо! {STARS[stars]}", show_alert=False)

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    username = f"@{user.username}" if user.username else user.first_name or str(user.telegram_id)
    lines = [
        "🖼 <b>Оценка образа</b>",
        f"<b>От:</b> {username}",
        f"<b>Оценка:</b> {STARS[stars]}",
    ]
    if outfit.item_title:
        lines.append(f"<b>Образ:</b> {html.escape(outfit.item_title)}")
    lines.append(f"<b>Картинка:</b> {html.escape(outfit.generated_image_url)}")
    asyncio.create_task(notify_admin("\n".join(lines), settings.bot_token, settings.admin_chat_id))
