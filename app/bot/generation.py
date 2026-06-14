import json
import logging
import time
from pathlib import Path

from aiogram import Bot
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from app.config import settings
from app.crud.outfit import create_outfit
from app.crud.user import use_generation
from app.database import AsyncSessionFactory
from app.services.image_gen import generate_try_on
from app.services.s3 import upload_bytes

logger = logging.getLogger(__name__)

_CLOTHES_PATH = Path(__file__).parent.parent.parent / "clothes.json"

DEFAULT_ITEM_ID_MALE = 5
DEFAULT_ITEM_ID_FEMALE = 115


def open_app_keyboard() -> InlineKeyboardMarkup | None:
    if not settings.miniapp_url:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🛍 Открыть Capsule", web_app=WebAppInfo(url=settings.miniapp_url))
    ]])


def get_item_by_id(item_id: int) -> dict | None:
    with open(_CLOTHES_PATH, encoding="utf-8") as f:
        clothes = json.load(f)
    for item in clothes:
        if item["id"] == item_id:
            return item
    return None


def default_item_for_gender(gender: str) -> dict | None:
    item_id = DEFAULT_ITEM_ID_FEMALE if gender == "female" else DEFAULT_ITEM_ID_MALE
    return get_item_by_id(item_id)


async def generate_and_send(
    bot: Bot,
    telegram_id: int,
    user_id: int,
    photo_url: str,
    item: dict,
) -> None:
    t0 = time.monotonic()
    logger.info("tid=%d generate_and_send start item_id=%s title=%r", telegram_id, item.get("id"), item.get("title"))
    try:
        logger.info("tid=%d calling generate_try_on photo_url=%r item_image=%r", telegram_id, photo_url, item.get("image", "")[:60])
        t_gen = time.monotonic()
        result_bytes = await generate_try_on(
            photo_url,
            item["image"],
            settings.open_router_key,
            item.get("generation_prompt"),
        )
        logger.info("tid=%d generate_try_on -> %s (%.1fs)", telegram_id, f"{len(result_bytes)} bytes" if result_bytes else "None", time.monotonic() - t_gen)

        if not result_bytes:
            logger.warning("tid=%d generation returned no bytes", telegram_id)
            await bot.send_message(
                chat_id=telegram_id,
                text="Не удалось создать образ. Попробуй ещё раз в приложении.",
                reply_markup=open_app_keyboard(),
            )
            return

        generated_url = await upload_bytes(result_bytes, "image/jpeg")
        logger.info("tid=%d generated image uploaded url=%r", telegram_id, generated_url)

        async with AsyncSessionFactory() as db:
            await use_generation(db, user_id)
        logger.info("tid=%d generation credit used user_id=%d", telegram_id, user_id)

        async with AsyncSessionFactory() as db:
            outfit = await create_outfit(
                db,
                user_id=user_id,
                generated_image_url=generated_url,
                item_id=item["id"],
                item_title=item["title"],
                item_image_url=item["image"],
                item_link=item["link"],
            )
        logger.info("tid=%d outfit created outfit_id=%d", telegram_id, outfit.id)

        caption = (
            f"🎉 Твой образ готов!\n\n"
            f"Вещь: {item['title']}\n"
            f"Купить на WB: {item['link']}\n\n"
            "Хочешь подобрать что-то своё? Открой приложение и попробуй AI-подбор!\n\n"
            "Как тебе результат?"
        )

        extra_row = []
        if settings.miniapp_url:
            extra_row = [InlineKeyboardButton(text="🛍 Открыть приложение", web_app=WebAppInfo(url=settings.miniapp_url))]

        rating_keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="★", callback_data=f"rate:{outfit.id}:1"),
                InlineKeyboardButton(text="★★", callback_data=f"rate:{outfit.id}:2"),
                InlineKeyboardButton(text="★★★", callback_data=f"rate:{outfit.id}:3"),
                InlineKeyboardButton(text="★★★★", callback_data=f"rate:{outfit.id}:4"),
                InlineKeyboardButton(text="★★★★★", callback_data=f"rate:{outfit.id}:5"),
            ],
            *([extra_row] if extra_row else []),
        ])

        await bot.send_photo(
            chat_id=telegram_id,
            photo=BufferedInputFile(result_bytes, filename="outfit.jpg"),
            caption=caption,
            reply_markup=rating_keyboard,
        )
        await bot.send_message(
            chat_id=telegram_id,
            text="Готов подбирать вещи дальше — пиши, что ищешь 👇",
        )
        logger.info("tid=%d outfit photo sent (%.1fs total)", telegram_id, time.monotonic() - t0)

    except Exception:
        logger.exception("tid=%d generate_and_send failed (%.1fs elapsed)", telegram_id, time.monotonic() - t0)
        try:
            await bot.send_message(
                chat_id=telegram_id,
                text="Что-то пошло не так при создании образа. Попробуй в приложении.",
                reply_markup=open_app_keyboard(),
            )
        except Exception:
            pass
