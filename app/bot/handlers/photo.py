import asyncio

import httpx
from aiogram import Bot, F, Router
from aiogram.types import Message

from app.bot.generation import default_item_for_gender, generate_and_send, open_app_keyboard
from app.config import settings
from app.crud.user import get_user_by_telegram_id, set_waiting_for_photo
from app.database import AsyncSessionFactory
from app.services.s3 import upload_bytes

router = Router()

_TG_API = "https://api.telegram.org"


@router.message(F.photo)
async def handle_user_photo(message: Message, bot: Bot) -> None:
    telegram_id = message.from_user.id

    async with AsyncSessionFactory() as db:
        user = await get_user_by_telegram_id(db, telegram_id)

    if not user or not user.waiting_for_photo:
        return

    # Clear the waiting flag before anything else so duplicate sends don't re-trigger
    async with AsyncSessionFactory() as db:
        user = await get_user_by_telegram_id(db, telegram_id)
        await set_waiting_for_photo(db, user, False)

    if user.generations_left <= 0:
        await message.answer(
            "Генерации закончились. Зайди в приложение, чтобы получить ещё.",
            reply_markup=open_app_keyboard(),
        )
        return

    # Download the photo the user sent
    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    file_url = f"{_TG_API}/file/bot{settings.bot_token}/{file.file_path}"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(file_url)
            resp.raise_for_status()
            photo_bytes = resp.content
    except Exception as e:
        print(f"[handle_user_photo] failed to download photo: {e}")
        await message.answer(
            "Не удалось загрузить фото. Попробуй отправить ещё раз.",
        )
        # Restore waiting flag so the user can retry
        async with AsyncSessionFactory() as db:
            user = await get_user_by_telegram_id(db, telegram_id)
            await set_waiting_for_photo(db, user, True)
        return

    photo_url = await upload_bytes(photo_bytes, "image/jpeg")

    gender = user.gender or "male"
    item = default_item_for_gender(gender)
    if not item:
        await message.answer(
            "Не удалось найти подходящий образ. Зайди в приложение!",
            reply_markup=open_app_keyboard(),
        )
        return

    await message.answer("⏳ Примеряю образ, подожди минутку...")
    asyncio.create_task(
        generate_and_send(bot, telegram_id, user.id, photo_url, item)
    )


@router.message(F.text)
async def handle_text_while_waiting(message: Message) -> None:
    telegram_id = message.from_user.id

    async with AsyncSessionFactory() as db:
        user = await get_user_by_telegram_id(db, telegram_id)

    if user and user.waiting_for_photo:
        await message.answer("📸 Жду твоё фото! Просто отправь его в этот чат.")
