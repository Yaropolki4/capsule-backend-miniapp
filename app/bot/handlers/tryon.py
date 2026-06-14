import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.generation import generate_and_send, get_item_by_id
from app.bot.handlers.chat import run_ai_and_reply
from app.bot.handlers.start import SUGGESTIONS
from app.bot.utils import get_profile_photos
from app.config import settings
from app.crud.message import create_message, get_shown_item_ids
from app.crud.user import get_user_by_telegram_id, set_pending_item_id, set_waiting_for_photo
from app.database import AsyncSessionFactory
from app.services.s3 import upload_bytes

logger = logging.getLogger(__name__)
router = Router()


@router.callback_query(F.data.startswith("suggest:"))
async def handle_suggestion(callback: CallbackQuery, db: AsyncSession, bot: Bot) -> None:
    await callback.answer()
    try:
        idx = int(callback.data.split(":")[1])
        text = SUGGESTIONS[idx]
    except (IndexError, ValueError):
        return

    user = await get_user_by_telegram_id(db, callback.from_user.id)
    if not user:
        return

    if user.generations_left <= 0:
        await callback.message.answer("Генерации закончились. Зайди в приложение, чтобы получить ещё.")
        return

    shown_item_ids = await get_shown_item_ids(db, user.id)
    await create_message(db, user_id=user.id, type="user", content=text, content_type="text")
    await callback.message.answer(f"_{text}_", parse_mode="Markdown")

    await run_ai_and_reply(
        bot=bot,
        chat_id=callback.from_user.id,
        user_id=user.id,
        gender=user.gender,
        shown_item_ids=shown_item_ids,
    )


@router.callback_query(F.data == "cancel_rec")
async def handle_cancel_rec(callback: CallbackQuery, db: AsyncSession, bot: Bot) -> None:
    await callback.answer()
    user = await get_user_by_telegram_id(db, callback.from_user.id)
    if not user:
        return

    if user.generations_left <= 0:
        await callback.message.answer("Генерации закончились. Зайди в приложение, чтобы получить ещё.")
        return

    shown_item_ids = await get_shown_item_ids(db, user.id)
    await run_ai_and_reply(
        bot=bot,
        chat_id=callback.from_user.id,
        user_id=user.id,
        gender=user.gender,
        shown_item_ids=shown_item_ids,
        synthetic_user_msg="Эта вещь не подошла, предложи другой вариант",
    )


@router.callback_query(F.data.regexp(r"^try_on:\d+$"))
async def handle_try_on(callback: CallbackQuery, db: AsyncSession, bot: Bot) -> None:
    await callback.answer()
    item_id = int(callback.data.split(":")[1])
    telegram_id = callback.from_user.id

    user = await get_user_by_telegram_id(db, telegram_id)
    if not user:
        return

    if user.generations_left <= 0:
        await callback.message.answer(
            "Генерации закончились. Зайди в приложение, чтобы получить ещё."
        )
        return

    all_photos = await get_profile_photos(bot, telegram_id, limit=5)
    n = len(all_photos)
    logger.info("tid=%d try_on item_id=%d profile_photos=%d", telegram_id, item_id, n)

    if n == 0:
        await set_waiting_for_photo(db, user, True)
        await set_pending_item_id(db, user, item_id)
        await callback.message.answer(
            "Нет фото в профиле Telegram — пришли своё фото прямо в чат 📸"
        )
        return

    photo_buttons = [
        InlineKeyboardButton(text=f"Фото {i + 1}", callback_data=f"try_on:photo:{i}:{item_id}")
        for i in range(n)
    ]
    photo_buttons.append(
        InlineKeyboardButton(text="📸 Загрузить своё", callback_data=f"try_on:upload:{item_id}")
    )

    rows = [photo_buttons[i:i + 3] for i in range(0, len(photo_buttons), 3)]
    keyboard = InlineKeyboardMarkup(inline_keyboard=rows)

    await callback.message.answer(
        f"Нашёл {n} {'фото' if n == 1 else 'фото'} в профиле. Выбери, на каком примерим:",
        reply_markup=keyboard,
    )


@router.callback_query(F.data.regexp(r"^try_on:photo:\d+:\d+$"))
async def handle_try_on_profile_photo(callback: CallbackQuery, db: AsyncSession, bot: Bot) -> None:
    await callback.answer()
    try:
        _, _, idx_str, item_id_str = callback.data.split(":")
        photo_idx = int(idx_str)
        item_id = int(item_id_str)
    except (ValueError, IndexError):
        return

    telegram_id = callback.from_user.id
    user = await get_user_by_telegram_id(db, telegram_id)
    if not user:
        return

    if user.generations_left <= 0:
        await callback.message.answer("Генерации закончились. Зайди в приложение, чтобы получить ещё.")
        return

    item = get_item_by_id(item_id)
    if not item:
        await callback.message.answer("Вещь не найдена. Попробуй снова.")
        return

    all_photos = await get_profile_photos(bot, telegram_id, limit=5)
    if photo_idx >= len(all_photos):
        await callback.message.answer("Фото не найдено. Попробуй загрузить своё фото.")
        return

    photo_url = await upload_bytes(all_photos[photo_idx], "image/jpeg")
    logger.info("tid=%d profile photo[%d] uploaded url=%r", telegram_id, photo_idx, photo_url)

    await callback.message.answer("⏳ Примеряю образ, подожди немного...")
    asyncio.create_task(generate_and_send(bot, telegram_id, user.id, photo_url, item))


@router.callback_query(F.data.regexp(r"^try_on:upload:\d+$"))
async def handle_try_on_upload(callback: CallbackQuery, db: AsyncSession) -> None:
    await callback.answer()
    try:
        item_id = int(callback.data.split(":")[2])
    except (ValueError, IndexError):
        return

    telegram_id = callback.from_user.id
    user = await get_user_by_telegram_id(db, telegram_id)
    if not user:
        return

    await set_waiting_for_photo(db, user, True)
    await set_pending_item_id(db, user, item_id)
    await callback.message.answer("📸 Пришли своё фото в чат — и я сразу примерю образ!")
