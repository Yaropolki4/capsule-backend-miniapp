import asyncio
import json
import random
from pathlib import Path

import httpx
from aiogram import Bot, Router
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.crud.outfit import create_outfit
from app.crud.user import get_or_create_user, get_user_by_telegram_id, use_generation
from app.database import AsyncSessionFactory
from app.services.image_gen import generate_try_on
from app.services.s3 import upload_bytes

router = Router()

_CLOTHES_PATH = Path(__file__).parent.parent.parent.parent / "clothes.json"
_TG_API = "https://api.telegram.org"
_UPPER_TAGS = {"худи", "футболка", "лонгслив", "зип"}


def _load_upper_items() -> list[dict]:
    with open(_CLOTHES_PATH, encoding="utf-8") as f:
        clothes = json.load(f)
    return [c for c in clothes if any(tag in c["tags"].lower() for tag in _UPPER_TAGS)]


def _open_app_keyboard() -> InlineKeyboardMarkup | None:
    if not settings.miniapp_url:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🛍 Открыть Capsule", web_app=WebAppInfo(url=settings.miniapp_url))
    ]])


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

    asyncio.create_task(_run_start_generation(bot, tg_user.id, user.id))


async def _run_start_generation(bot: Bot, telegram_id: int, user_id: int) -> None:
    try:
        photo_url = await _get_profile_photo_url(bot, telegram_id)

        if not photo_url:
            async with AsyncSessionFactory() as db:
                user = await get_user_by_telegram_id(db, telegram_id)
            if user and user.photos:
                photo_url = user.photos[-1]

        if not photo_url:
            await bot.send_message(
                chat_id=telegram_id,
                text=(
                    "📸 Твоё фото в профиле недоступно.\n\n"
                    "Зайди в приложение, загрузи своё фото — и AI подберёт тебе идеальный образ!"
                ),
                reply_markup=_open_app_keyboard(),
            )
            return

        async with AsyncSessionFactory() as db:
            user = await get_user_by_telegram_id(db, telegram_id)
        if not user or user.generations_left <= 0:
            await bot.send_message(
                chat_id=telegram_id,
                text="Генерации закончились. Зайди в приложение, чтобы получить ещё.",
                reply_markup=_open_app_keyboard(),
            )
            return

        items = _load_upper_items()
        item = random.choice(items)

        result_bytes = await generate_try_on(
            photo_url,
            item["image"],
            settings.open_router_key,
            item.get("generation_prompt"),
        )
        if not result_bytes:
            await bot.send_message(
                chat_id=telegram_id,
                text="Не удалось создать образ. Попробуй ещё раз в приложении.",
                reply_markup=_open_app_keyboard(),
            )
            return

        generated_url = await upload_bytes(
            result_bytes,
            "image/jpeg",
            settings.s3_access_key_id,
            settings.s3_secret_access_key_id,
        )

        async with AsyncSessionFactory() as db:
            await use_generation(db, user_id)

        async with AsyncSessionFactory() as db:
            await create_outfit(
                db,
                user_id=user_id,
                generated_image_url=generated_url,
                item_id=item["id"],
                item_title=item["title"],
                item_image_url=item["image"],
                item_link=item["link"],
            )

        caption = (
            f"🎉 Твой образ готов!\n\n"
            f"Вещь: {item['title']}\n"
            f"Купить на WB: {item['link']}\n\n"
            f"Хочешь подобрать что-то своё? Открой приложение и попробуй AI-подбор!"
        )

        await bot.send_photo(
            chat_id=telegram_id,
            photo=generated_url,
            caption=caption,
            reply_markup=_open_app_keyboard(),
        )

    except Exception as e:
        print(f"[start_generation] error for telegram_id={telegram_id}: {e}")
        try:
            await bot.send_message(
                chat_id=telegram_id,
                text="Что-то пошло не так при создании образа. Попробуй ещё раз в приложении.",
                reply_markup=_open_app_keyboard(),
            )
        except Exception:
            pass


async def _get_profile_photo_url(bot: Bot, telegram_id: int) -> str | None:
    photos = await bot.get_user_profile_photos(user_id=telegram_id, limit=1)
    if not photos.photos:
        return None

    photo = photos.photos[0][-1]
    file = await bot.get_file(photo.file_id)
    file_url = f"{_TG_API}/file/bot{settings.bot_token}/{file.file_path}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(file_url)
        photo_bytes = resp.content

    return await upload_bytes(
        photo_bytes,
        "image/jpeg",
        settings.s3_access_key_id,
        settings.s3_secret_access_key_id,
    )
