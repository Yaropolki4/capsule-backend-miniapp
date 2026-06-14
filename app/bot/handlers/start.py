import logging

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.generation import open_app_keyboard
from app.crud.user import get_or_create_user, set_user_gender
from app.services.ai import infer_gender_from_name
from app.config import settings

logger = logging.getLogger(__name__)
router = Router()

SUGGESTIONS = [
    "Хочу оверсайз худи — покажи варианты и помоги примерить",
    "Посоветуй что-то уютное и тёплое на каждый день",
    "Есть что-то на вечеринку или романтический выход?",
]


def _suggestions_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=text, callback_data=f"suggest:{i}")]
        for i, text in enumerate(SUGGESTIONS)
    ])


@router.message(CommandStart())
async def handle_start(message: Message, db: AsyncSession):
    tg_user = message.from_user
    logger.info("tid=%d /start received name=%r username=%r", tg_user.id, tg_user.first_name, tg_user.username)

    user, created = await get_or_create_user(
        db,
        telegram_id=tg_user.id,
        username=tg_user.username,
        first_name=tg_user.first_name,
    )
    logger.info("tid=%d user_id=%d created=%s", tg_user.id, user.id, created)

    if created:
        detected = await infer_gender_from_name(tg_user.first_name or "", settings.open_router_key)
        if detected:
            await set_user_gender(db, user, detected)

        await message.answer(
            "Привет! Я — твой AI-стилист: помогу подобрать нужную вещь и виртуально примерить её на тебе."
        )
        await message.answer(
            "Расскажи, что ищешь — тип вещи, повод, цвет или стиль. Чем точнее опишешь, тем лучше подберу.",
            reply_markup=_suggestions_keyboard(),
        )
    else:
        await message.answer(
            f"С возвращением, {tg_user.first_name}!\n"
            f"У тебя осталось {user.generations_left} генераций.",
            reply_markup=open_app_keyboard(),
        )
