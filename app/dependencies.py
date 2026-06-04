import hashlib
import hmac
import json
from urllib.parse import parse_qsl

from fastapi import Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.crud.user import get_user_by_telegram_id
from app.database import get_db
from app.models.user import User


def verify_telegram_init_data(init_data: str) -> dict:
    parsed = dict(parse_qsl(init_data, strict_parsing=True))
    received_hash = parsed.pop("hash", None)

    if not received_hash:
        raise HTTPException(status_code=401, detail="Missing hash")

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))

    secret_key = hmac.new(b"WebAppData", settings.bot_token.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected_hash, received_hash):
        raise HTTPException(status_code=401, detail="Invalid signature")

    return parsed


async def get_current_user(
    init_data: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> User:
    parsed = verify_telegram_init_data(init_data)
    tg_user = json.loads(parsed.get("user", "{}"))
    telegram_id = tg_user.get("id")

    if not telegram_id:
        raise HTTPException(status_code=400, detail="User data missing")

    user = await get_user_by_telegram_id(db, telegram_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return user
