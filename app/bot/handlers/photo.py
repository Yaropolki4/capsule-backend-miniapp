import asyncio
import logging

import httpx
from aiogram import Bot, F, Router
from aiogram.types import Message

from app.bot.generation import default_item_for_gender, generate_and_send, open_app_keyboard
from app.config import settings
from app.crud.user import get_user_by_telegram_id, set_waiting_for_photo
from app.database import AsyncSessionFactory
from app.services.s3 import upload_bytes

logger = logging.getLogger(__name__)
router = Router()

_TG_API = "https://api.telegram.org"


@router.message(F.photo)
async def handle_user_photo(message: Message, bot: Bot) -> None:
    telegram_id = message.from_user.id
    logger.info("tid=%d user sent photo", telegram_id)

    async with AsyncSessionFactory() as db:
        user = await get_user_by_telegram_id(db, telegram_id)

    if not user or not user.waiting_for_photo:
        logger.debug("tid=%d photo ignored (waiting_for_photo=%s)", telegram_id, user.waiting_for_photo if user else "no user")
        return

    logger.info("tid=%d waiting_for_photo=True, processing user photo", telegram_id)

    # Clear the waiting flag before anything else so duplicate sends don't re-trigger
    async with AsyncSessionFactory() as db:
        user = await get_user_by_telegram_id(db, telegram_id)
        await set_waiting_for_photo(db, user, False)
    logger.info("tid=%d waiting_for_photo cleared", telegram_id)

    if user.generations_left <= 0:
        logger.info("tid=%d no generations left", telegram_id)
        await message.answer(
            "Генерации закончились. Зайди в приложение, чтобы получить ещё.",
            reply_markup=open_app_keyboard(),
        )
        return

    # Download the photo the user sent
    photo = message.photo[-1]
    logger.info("tid=%d downloading user photo file_id=%r size=%dx%d", telegram_id, photo.file_id, photo.width, photo.height)
    file = await bot.get_file(photo.file_id)
    file_url = f"{_TG_API}/file/bot{settings.bot_token}/{file.file_path}"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(file_url)
            resp.raise_for_status()
            photo_bytes = resp.content
        logger.info("tid=%d user photo downloaded %d bytes", telegram_id, len(photo_bytes))
    except Exception:
        logger.exception("tid=%d failed to download user photo", telegram_id)
        await message.answer("Не удалось загрузить фото. Попробуй отправить ещё раз.")
        async with AsyncSessionFactory() as db:
            user = await get_user_by_telegram_id(db, telegram_id)
            await set_waiting_for_photo(db, user, True)
        return

    photo_url = await upload_bytes(photo_bytes, "image/jpeg")
    logger.info("tid=%d user photo uploaded to S3 url=%r", telegram_id, photo_url)

    gender = user.gender or "male"
    item = default_item_for_gender(gender)
    if not item:
        logger.error("tid=%d default item not found for gender=%r", telegram_id, gender)
        await message.answer(
            "Не удалось найти подходящий образ. Зайди в приложение!",
            reply_markup=open_app_keyboard(),
        )
        return

    logger.info("tid=%d kicking off generation item_id=%s gender=%r", telegram_id, item.get("id"), gender)
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
        logger.info("tid=%d text received while waiting_for_photo, re-prompting", telegram_id)
        await message.answer("📸 Жду твоё фото! Просто отправь его в этот чат.")
