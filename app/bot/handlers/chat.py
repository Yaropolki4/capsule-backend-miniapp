import asyncio
import json
import logging
import re
from pathlib import Path

import httpx
from aiogram import Bot, F, Router
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.generation import no_generations_message, open_app_keyboard
from app.config import settings
from app.crud.message import create_message, get_recent_messages, get_shown_item_ids
from app.crud.user import get_user_by_telegram_id, set_pending_item_id, set_waiting_for_photo
from app.database import AsyncSessionFactory
from app.services.ai import complete_ai_response
from app.services.stylist_prompt import build_system_prompt

logger = logging.getLogger(__name__)
router = Router()

_CLOTHES_PATH = Path(__file__).parent.parent.parent.parent / "clothes.json"
_ITEM_MARKER_RE = re.compile(r'\s*\[ITEM:(\d+)\]\s*$')


def _load_item(item_id: int) -> dict | None:
    with open(_CLOTHES_PATH, encoding="utf-8") as f:
        clothes = json.load(f)
    return next((c for c in clothes if c["id"] == item_id), None)


def _build_history(recent: list) -> list[dict]:
    messages = []
    for m in recent:
        role = "user" if m.type == "user" else "assistant"
        if m.content_type == "recommendation":
            try:
                content = json.loads(m.content).get("text", "")
            except Exception:
                content = m.content
        else:
            content = m.content
        messages.append({"role": role, "content": content})
    return messages


async def _typing_loop(bot: Bot, chat_id: int) -> None:
    while True:
        await bot.send_chat_action(chat_id, "typing")
        await asyncio.sleep(4)


async def run_ai_and_reply(
    bot: Bot,
    chat_id: int,
    user_id: int,
    gender: str | None,
    shown_item_ids: set[int],
    synthetic_user_msg: str | None = None,
) -> None:
    async with AsyncSessionFactory() as db:
        recent = await get_recent_messages(db, user_id, limit=5)

    history = [
        {"role": "system", "content": build_system_prompt(gender=gender, exclude_ids=shown_item_ids)}
    ] + _build_history(recent)

    if synthetic_user_msg:
        history.append({"role": "user", "content": synthetic_user_msg})

    typing_task = asyncio.create_task(_typing_loop(bot, chat_id))
    try:
        full_content = await complete_ai_response(history, settings.open_router_key)
    except Exception:
        logger.exception("tid=%d AI call failed", chat_id)
        typing_task.cancel()
        await bot.send_message(chat_id, "Что-то пошло не так. Попробуй написать ещё раз.")
        return
    finally:
        typing_task.cancel()

    match = _ITEM_MARKER_RE.search(full_content)
    if match:
        item_id = int(match.group(1))
        shown_item_ids.add(item_id)
        clean_text = _ITEM_MARKER_RE.sub("", full_content).rstrip()
        item = _load_item(item_id)

        if item:
            if clean_text:
                await bot.send_message(chat_id, clean_text, parse_mode="Markdown")

            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.get(item["image"])
                    resp.raise_for_status()
                    item_bytes = resp.content
            except Exception:
                logger.exception("tid=%d failed to download item image item_id=%d", chat_id, item_id)
                await bot.send_message(chat_id, f"*{item['title']}*\n{item['link']}", parse_mode="Markdown")
                item_bytes = None

            keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="👗 Примерить", callback_data=f"try_on:{item_id}"),
                InlineKeyboardButton(text="🔄 Другой вариант", callback_data="cancel_rec"),
            ]])

            if item_bytes:
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=BufferedInputFile(item_bytes, filename="item.jpg"),
                    caption=f"*{item['title']}*",
                    parse_mode="Markdown",
                    reply_markup=keyboard,
                )
            else:
                await bot.send_message(chat_id, f"*{item['title']}*", parse_mode="Markdown", reply_markup=keyboard)

            item_data = {
                "id": item["id"],
                "title": item["title"],
                "image": item.get("image", ""),
                "link": item["link"],
            }
            async with AsyncSessionFactory() as db:
                await create_message(
                    db,
                    user_id=user_id,
                    type="ai",
                    content=json.dumps({"text": clean_text, "item": item_data}, ensure_ascii=False),
                    content_type="recommendation",
                )
            return

    if full_content:
        await bot.send_message(chat_id, full_content, parse_mode="Markdown")
        async with AsyncSessionFactory() as db:
            await create_message(db, user_id=user_id, type="ai", content=full_content, content_type="text")


@router.message(F.text)
async def handle_text(message: Message, db: AsyncSession, bot: Bot) -> None:
    tg_user = message.from_user
    logger.info("tid=%d text received: %r", tg_user.id, message.text[:80])

    user = await get_user_by_telegram_id(db, tg_user.id)
    if not user:
        return

    if user.waiting_for_photo:
        await set_waiting_for_photo(db, user, False)
        await set_pending_item_id(db, user, None)
        logger.info("tid=%d text interrupted waiting_for_photo, routing to AI", tg_user.id)

    if user.generations_left <= 0:
        await message.answer(no_generations_message(user.is_started_app), reply_markup=open_app_keyboard())
        return

    shown_item_ids = await get_shown_item_ids(db, user.id)
    await create_message(db, user_id=user.id, type="user", content=message.text, content_type="text")

    await run_ai_and_reply(
        bot=bot,
        chat_id=tg_user.id,
        user_id=user.id,
        gender=user.gender,
        shown_item_ids=shown_item_ids,
    )
