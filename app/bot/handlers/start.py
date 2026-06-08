import asyncio
import json
import random
from pathlib import Path

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

router = Router()

_CLOTHES_PATH = Path(__file__).parent.parent.parent.parent / "clothes.json"
_TG_API = "https://api.telegram.org"
_UPPER_TAGS = {"худи", "футболка", "лонгслив", "зип"}


def _load_upper_items() -> list[dict]:
    with open(_CLOTHES_PATH, encoding="utf-8") as f:
        clothes = json.load(f)
    return [c for c in clothes if any(tag in c["tags"].lower() for tag in _UPPER_TAGS)]


@router.message(CommandStart())
async def handle_start(message: Message, db: AsyncSession, bot: Bot):
    tg_user = message.from_user

    user, created = await get_or_create_user(
        db,
        telegram_id=tg_user.id,
        username=tg_user.username,
        first_name=tg_user.first_name,
    )

    if created:
        await message.answer(
            f"Привет, {tg_user.first_name}! Добро пожаловать в Capsule.\n"
            f"У тебя {user.generations_left} бесплатных генерации образов."
        )
    else:
        await message.answer(
            f"С возвращением, {tg_user.first_name}!\n"
            f"У тебя осталось {user.generations_left} генераций."
        )

    await message.answer(
        "✨ Подбираю тебе образ прямо сейчас — займёт около минуты.\n"
        "Пока ждёшь, можешь открыть приложение и выбрать что-то сам."
    )

    asyncio.create_task(
        _run_start_generation(bot, tg_user.id, user.id, tg_user.first_name)
    )


async def _run_start_generation(
    bot: Bot, telegram_id: int, user_id: int, first_name: str | None
) -> None:
    try:
        # Step 1: Resolve gender (detect via LLM if not yet set)
        async with AsyncSessionFactory() as db:
            user = await get_user_by_telegram_id(db, telegram_id)

        gender = user.gender
        if not gender:
            detected = await infer_gender_from_name(
                first_name or "", settings.open_router_key
            )
            if detected:
                gender = detected
                async with AsyncSessionFactory() as db:
                    user = await get_user_by_telegram_id(db, telegram_id)
                    await set_user_gender(db, user, gender)
        gender = gender or "male"

        # Step 2: Reset any stale waiting_for_photo state from a previous /start
        async with AsyncSessionFactory() as db:
            user = await get_user_by_telegram_id(db, telegram_id)
            if user.waiting_for_photo:
                await set_waiting_for_photo(db, user, False)

        # Step 3: Check generations
        async with AsyncSessionFactory() as db:
            user = await get_user_by_telegram_id(db, telegram_id)
        if not user or user.generations_left <= 0:
            await bot.send_message(
                chat_id=telegram_id,
                text="Генерации закончились. Зайди в приложение, чтобы получить ещё.",
                reply_markup=open_app_keyboard(),
            )
            return

        # Step 4: Fetch up to 5 Telegram profile photos
        all_photo_bytes = await _get_profile_photos(bot, telegram_id, limit=5)

        if not all_photo_bytes:
            await _no_photo_flow(bot, telegram_id, user_id, gender)
            return

        # Step 5: Ask LLM to pick the best photo
        best_idx = await select_best_photo(all_photo_bytes, gender, settings.open_router_key)

        if best_idx is None:
            await _no_photo_flow(bot, telegram_id, user_id, gender)
            return

        # Step 6: Upload chosen photo and generate
        photo_url = await upload_bytes(all_photo_bytes[best_idx], "image/jpeg")
        items = _load_upper_items()
        item = random.choice(items)
        await generate_and_send(bot, telegram_id, user_id, photo_url, item)

    except Exception as e:
        print(f"[start_generation] error for telegram_id={telegram_id}: {e}")
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
    item = default_item_for_gender(gender)
    if not item:
        await bot.send_message(
            chat_id=telegram_id,
            text="Не удалось найти подходящий образ. Зайди в приложение!",
            reply_markup=open_app_keyboard(),
        )
        return

    async with AsyncSessionFactory() as db:
        user = await get_user_by_telegram_id(db, telegram_id)
        await set_waiting_for_photo(db, user, True)

    # Download item image ourselves — Telegram can't fetch Wildberries CDN URLs directly
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(item["image"])
        resp.raise_for_status()
        item_bytes = resp.content

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


async def _get_profile_photos(bot: Bot, telegram_id: int, limit: int = 5) -> list[bytes]:
    photos = await bot.get_user_profile_photos(user_id=telegram_id, limit=limit)
    if not photos.photos:
        return []

    result: list[bytes] = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for photo_sizes in photos.photos:
            # Use the largest available size
            photo = photo_sizes[-1]
            try:
                file = await bot.get_file(photo.file_id)
                url = f"{_TG_API}/file/bot{settings.bot_token}/{file.file_path}"
                resp = await client.get(url)
                resp.raise_for_status()
                result.append(resp.content)
            except Exception as e:
                print(f"[get_profile_photos] failed to fetch photo: {e}")
                continue

    return result
