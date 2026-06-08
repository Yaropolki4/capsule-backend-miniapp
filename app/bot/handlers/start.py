import asyncio
import logging
import time

import httpx
from aiogram import Bot, Router
from aiogram.filters import CommandStart
from aiogram.types import BufferedInputFile, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.generation import default_item_for_gender, generate_and_send, open_app_keyboard
from app.config import settings
from app.crud.user import (
    get_or_create_user,
    get_user_by_telegram_id,
    set_user_gender,
    set_waiting_for_photo,
)
from app.database import AsyncSessionFactory
from app.services.ai import infer_gender_from_name, select_best_photo
from app.services.s3 import upload_bytes

logger = logging.getLogger(__name__)
router = Router()

_TG_API = "https://api.telegram.org"


@router.message(CommandStart())
async def handle_start(message: Message, db: AsyncSession, bot: Bot):
    tg_user = message.from_user
    logger.info("tid=%d /start received name=%r username=%r", tg_user.id, tg_user.first_name, tg_user.username)

    user, created = await get_or_create_user(
        db,
        telegram_id=tg_user.id,
        username=tg_user.username,
        first_name=tg_user.first_name,
    )
    logger.info("tid=%d user_id=%d created=%s generations_left=%d", tg_user.id, user.id, created, user.generations_left)

    if created:
        await message.answer(
            f"Привет, {tg_user.first_name}! Добро пожаловать в Capsule.\n"
            f"У тебя {user.generations_left} бесплатных генерации образов."
        )
        await message.answer(
            "✨ Подбираю тебе образ прямо сейчас — займёт около минуты.\n"
            "Пока ждёшь, можешь открыть приложение и выбрать что-то сам."
        )
        asyncio.create_task(
            _run_start_generation(bot, tg_user.id, user.id, tg_user.first_name)
        )
    else:
        await message.answer(
            f"С возвращением, {tg_user.first_name}!\n"
            f"У тебя осталось {user.generations_left} генераций."
        )


async def _run_start_generation(
    bot: Bot, telegram_id: int, user_id: int, first_name: str | None
) -> None:
    t0 = time.monotonic()
    logger.info("tid=%d pipeline start", telegram_id)
    try:
        # Step 1: Resolve gender
        async with AsyncSessionFactory() as db:
            user = await get_user_by_telegram_id(db, telegram_id)

        gender = user.gender
        if gender:
            logger.info("tid=%d gender=%r (from db)", telegram_id, gender)
        else:
            logger.info("tid=%d gender not set, inferring from name=%r", telegram_id, first_name)
            t_gender = time.monotonic()
            detected = await infer_gender_from_name(first_name or "", settings.open_router_key)
            logger.info("tid=%d gender inference -> %r (%.1fs)", telegram_id, detected, time.monotonic() - t_gender)
            if detected:
                gender = detected
                async with AsyncSessionFactory() as db:
                    user = await get_user_by_telegram_id(db, telegram_id)
                    await set_user_gender(db, user, gender)
        gender = gender or "male"
        logger.info("tid=%d resolved gender=%r", telegram_id, gender)

        # Step 2: Reset any stale waiting_for_photo flag
        async with AsyncSessionFactory() as db:
            user = await get_user_by_telegram_id(db, telegram_id)
            if user.waiting_for_photo:
                logger.info("tid=%d clearing stale waiting_for_photo flag", telegram_id)
                await set_waiting_for_photo(db, user, False)

        # Step 3: Check generations
        async with AsyncSessionFactory() as db:
            user = await get_user_by_telegram_id(db, telegram_id)
        if not user or user.generations_left <= 0:
            logger.info("tid=%d no generations left, aborting", telegram_id)
            await bot.send_message(
                chat_id=telegram_id,
                text="Генерации закончились. Зайди в приложение, чтобы получить ещё.",
                reply_markup=open_app_keyboard(),
            )
            return

        # Step 4: Fetch up to 5 Telegram profile photos
        logger.info("tid=%d fetching telegram profile photos", telegram_id)
        t_photos = time.monotonic()
        all_photo_bytes = await _get_profile_photos(bot, telegram_id, limit=5)
        logger.info("tid=%d fetched %d profile photo(s) (%.1fs)", telegram_id, len(all_photo_bytes), time.monotonic() - t_photos)

        if not all_photo_bytes:
            logger.info("tid=%d no photos found -> no_photo_flow", telegram_id)
            await _no_photo_flow(bot, telegram_id, user_id, gender)
            return

        # Step 5: Ask LLM to pick the best photo
        logger.info("tid=%d selecting best photo via LLM (gender=%r, %d candidates)", telegram_id, gender, len(all_photo_bytes))
        t_select = time.monotonic()
        best_idx = await select_best_photo(all_photo_bytes, gender, settings.open_router_key)
        logger.info("tid=%d select_best_photo -> %r (%.1fs)", telegram_id, best_idx, time.monotonic() - t_select)

        if best_idx is None:
            logger.info("tid=%d LLM returned None, falling back to photo index 0", telegram_id)
            best_idx = 0

        # Step 6: Upload chosen photo and generate
        logger.info("tid=%d uploading photo index=%d to S3", telegram_id, best_idx)
        photo_url = await upload_bytes(all_photo_bytes[best_idx], "image/jpeg")
        logger.info("tid=%d photo uploaded url=%r", telegram_id, photo_url)

        item = default_item_for_gender(gender)
        if not item:
            logger.error("tid=%d default item not found for gender=%r", telegram_id, gender)
            await bot.send_message(
                chat_id=telegram_id,
                text="Не удалось найти подходящий образ. Зайди в приложение!",
                reply_markup=open_app_keyboard(),
            )
            return
        logger.info("tid=%d selected item id=%s title=%r", telegram_id, item.get("id"), item.get("title"))

        await generate_and_send(bot, telegram_id, user_id, photo_url, item)
        logger.info("tid=%d pipeline complete (%.1fs total)", telegram_id, time.monotonic() - t0)

    except Exception:
        logger.exception("tid=%d pipeline failed (%.1fs elapsed)", telegram_id, time.monotonic() - t0)
        try:
            await bot.send_message(
                chat_id=telegram_id,
                text="Что-то пошло не так при создании образа. Попробуй ещё раз в приложении.",
                reply_markup=open_app_keyboard(),
            )
        except Exception:
            pass


async def _no_photo_flow(
    bot: Bot, telegram_id: int, user_id: int, gender: str
) -> None:
    logger.info("tid=%d no_photo_flow gender=%r", telegram_id, gender)
    item = default_item_for_gender(gender)
    if not item:
        logger.error("tid=%d default item not found for gender=%r", telegram_id, gender)
        await bot.send_message(
            chat_id=telegram_id,
            text="Не удалось найти подходящий образ. Зайди в приложение!",
            reply_markup=open_app_keyboard(),
        )
        return

    logger.info("tid=%d default item id=%s title=%r", telegram_id, item.get("id"), item.get("title"))

    async with AsyncSessionFactory() as db:
        user = await get_user_by_telegram_id(db, telegram_id)
        await set_waiting_for_photo(db, user, True)
    logger.info("tid=%d waiting_for_photo=True set", telegram_id)

    # Download item image ourselves — Telegram can't fetch Wildberries CDN URLs directly
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(item["image"])
        resp.raise_for_status()
        item_bytes = resp.content
    logger.info("tid=%d item image downloaded %d bytes", telegram_id, len(item_bytes))

    await bot.send_photo(
        chat_id=telegram_id,
        photo=BufferedInputFile(item_bytes, filename="item.jpg"),
        caption=(
            f"👗 Мы подготовили для тебя этот образ — *{item['title']}*.\n\n"
            "Но нам не удалось найти твоё фото в профиле Telegram, "
            "поэтому мы не можем примерить его на тебя автоматически 😔\n\n"
            "📸 Просто отправь своё фото в этот чат — и мы сразу же создадим твой образ!"
        ),
        parse_mode="Markdown",
    )
    logger.info("tid=%d no_photo_flow message sent", telegram_id)


async def _get_profile_photos(bot: Bot, telegram_id: int, limit: int = 5) -> list[bytes]:
    photos = await bot.get_user_profile_photos(user_id=telegram_id, limit=limit)
    logger.info("tid=%d get_user_profile_photos total_count=%d", telegram_id, photos.total_count)
    if not photos.photos:
        return []

    result: list[bytes] = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for i, photo_sizes in enumerate(photos.photos):
            photo = photo_sizes[-1]
            try:
                file = await bot.get_file(photo.file_id)
                url = f"{_TG_API}/file/bot{settings.bot_token}/{file.file_path}"
                resp = await client.get(url)
                resp.raise_for_status()
                result.append(resp.content)
                logger.debug("tid=%d photo[%d] downloaded %d bytes", telegram_id, i, len(resp.content))
            except Exception:
                logger.exception("tid=%d photo[%d] download failed", telegram_id, i)
                continue

    return result
