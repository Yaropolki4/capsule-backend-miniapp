import logging

import httpx
from aiogram import Bot

from app.config import settings

logger = logging.getLogger(__name__)

_TG_API = "https://api.telegram.org"


async def get_profile_photos(bot: Bot, telegram_id: int, limit: int = 5) -> list[bytes]:
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
