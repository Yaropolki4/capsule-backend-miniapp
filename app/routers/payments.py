import json
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException

logger = logging.getLogger(__name__)

from app.config import settings
from app.dependencies import get_current_user
from app.models.user import User

router = APIRouter(prefix="/payments", tags=["payments"])

_TG_API = "https://api.telegram.org"

TARIFFS = {
    "starter": {
        "title": "СТАРТЕР",
        "description": "5 образов от AI-стилиста",
        "generations": 5,
        "stars": 25,
    },
    "stylist": {
        "title": "СТИЛИСТ",
        "description": "50 образов от AI-стилиста",
        "generations": 50,
        "stars": 200,
    },
}


@router.post("/create-invoice")
async def create_invoice(
    tariff: str,
    user: User = Depends(get_current_user),
):
    if tariff not in TARIFFS:
        raise HTTPException(status_code=400, detail="Unknown tariff")

    t = TARIFFS[tariff]
    payload = json.dumps({"telegram_id": user.telegram_id, "tariff": tariff})

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{_TG_API}/bot{settings.bot_token}/createInvoiceLink",
            json={
                "title": t["title"],
                "description": t["description"],
                "payload": payload,
                "provider_token": "",
                "currency": "XTR",
                "prices": [{"label": t["title"], "amount": t["stars"]}],
            },
        )
        data = resp.json()

    if not data.get("ok"):
        logger.error("Telegram createInvoiceLink failed | user=%s tariff=%s response=%s", user.telegram_id, tariff, data)
        raise HTTPException(status_code=500, detail="Failed to create invoice")

    logger.info("Invoice created | user=%s tariff=%s", user.telegram_id, tariff)
    return {"invoice_link": data["result"]}
