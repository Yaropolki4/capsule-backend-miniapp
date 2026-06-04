import json

from aiogram import F, Router
from aiogram.types import Message, PreCheckoutQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.user import add_generations

router = Router()

TARIFF_GENERATIONS = {"starter": 5, "stylist": 50}


@router.pre_checkout_query()
async def handle_pre_checkout(query: PreCheckoutQuery):
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def handle_successful_payment(message: Message, db: AsyncSession):
    payment = message.successful_payment
    print(f"[payment] successful_payment received: {payment}")
    try:
        data = json.loads(payment.invoice_payload)
        telegram_id: int = data["telegram_id"]
        tariff: str = data["tariff"]
        amount = TARIFF_GENERATIONS.get(tariff, 0)
        if amount > 0:
            await add_generations(db, telegram_id, amount)
            print(f"[payment] +{amount} generations for telegram_id={telegram_id}")
    except Exception as e:
        print(f"[payment] error: {e}")
