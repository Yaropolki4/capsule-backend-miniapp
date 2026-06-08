import asyncio
import html
import json
import logging
import re
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.config import settings

logger = logging.getLogger(__name__)
from app.crud.outfit import create_outfit, get_user_outfits, rate_outfit
from app.crud.user import use_generation
from app.database import AsyncSessionFactory
from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.services.image_gen import generate_try_on
from app.services.notify import notify_admin
from app.services.s3 import upload_bytes, to_proxy_url, proxy_url_to_s3_url
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/generate", tags=["generate"])

_TG_API = "https://api.telegram.org"
_CLOTHES_PATH = Path(__file__).parent.parent.parent / "clothes.json"


def _load_item(item_id: int) -> dict | None:
    with open(_CLOTHES_PATH, encoding="utf-8") as f:
        clothes = json.load(f)
    return next((c for c in clothes if c["id"] == item_id), None)


class TryOnRequest(BaseModel):
    photo_file_id: str | None = None
    photo_url: str | None = None
    item_image_url: str
    item_id: int | None = None
    item_title: str | None = None
    item_link: str | None = None
    generation_prompt: str | None = None


@router.post("/outfits")
async def list_outfits(request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    outfits = await get_user_outfits(db, user.id)
    api_base = str(request.base_url)
    return [
        {
            "id": o.id,
            "item_title": o.item_title,
            "item_image_url": to_proxy_url(o.item_image_url, api_base) if o.item_image_url else None,
            "item_link": o.item_link,
            "generated_image_url": to_proxy_url(o.generated_image_url, api_base),
            "created_at": o.created_at.isoformat(),
        }
        for o in outfits
    ]


@router.post("/try-on")
async def try_on(
    request: Request,
    body: TryOnRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    logger.info("try-on started | user=%s generations_left=%s", user.telegram_id, user.generations_left)

    if user.generations_left <= 0:
        logger.warning("try-on rejected: no generations left | user=%s", user.telegram_id)
        raise HTTPException(status_code=402, detail="No generations left")

    if not body.photo_file_id and not body.photo_url:
        raise HTTPException(status_code=400, detail="photo_file_id or photo_url required")

    if body.photo_url:
        user_photo_url = proxy_url_to_s3_url(body.photo_url, str(request.base_url))
    else:
        async with httpx.AsyncClient(timeout=30.0) as client:
            file_resp = await client.get(
                f"{_TG_API}/bot{settings.bot_token}/getFile",
                params={"file_id": body.photo_file_id},
            )
            file_data = file_resp.json()
            if not file_data.get("ok"):
                logger.error("Failed to get file from Telegram | user=%s file_id=%s", user.telegram_id, body.photo_file_id)
                raise HTTPException(status_code=400, detail="Failed to get file info from Telegram")

            file_path = file_data["result"]["file_path"]
            photo_resp = await client.get(
                f"{_TG_API}/file/bot{settings.bot_token}/{file_path}"
            )
            photo_bytes = photo_resp.content

        user_photo_url = await upload_bytes(photo_bytes, "image/jpeg")

    generation_prompt = body.generation_prompt
    item_type = None
    if body.item_id is not None:
        catalog_item = _load_item(body.item_id)
        if catalog_item:
            generation_prompt = catalog_item.get("generation_prompt") or generation_prompt
            item_type = catalog_item.get("item_type")

    logger.info("try-on generating | user=%s item=%s type=%s", user.telegram_id, body.item_title, item_type)
    result_bytes = await generate_try_on(user_photo_url, body.item_image_url, settings.open_router_key, generation_prompt, item_type)
    if not result_bytes:
        logger.error("Image generation returned no result | user=%s item=%s", user.telegram_id, body.item_title)
        raise HTTPException(status_code=502, detail="Image generation failed")

    generated_url = await upload_bytes(result_bytes, "image/jpeg")
    logger.info("try-on done | user=%s outfit_url=%s", user.telegram_id, generated_url)

    await use_generation(db, user.id)

    async with AsyncSessionFactory() as db2:
        outfit = await create_outfit(
            db2,
            user_id=user.id,
            generated_image_url=generated_url,
            item_id=body.item_id,
            item_title=body.item_title,
            item_image_url=body.item_image_url,
            item_link=body.item_link,
        )

    await _notify_user(user.telegram_id, generated_url, body.item_title, body.item_link, outfit_id=outfit.id)

    return {"outfit_id": outfit.id, "generated_image_url": to_proxy_url(generated_url, str(request.base_url))}


class RateIn(BaseModel):
    stars: int = Field(..., ge=1, le=5)


STARS = {1: "⭐", 2: "⭐⭐", 3: "⭐⭐⭐", 4: "⭐⭐⭐⭐", 5: "⭐⭐⭐⭐⭐"}


@router.post("/outfits/{outfit_id}/rate")
async def rate_outfit_endpoint(
    outfit_id: int,
    body: RateIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    outfit = await rate_outfit(db, outfit_id, user.id, body.stars)
    if outfit is None:
        raise HTTPException(status_code=409, detail="Already rated or not found")

    username = f"@{user.username}" if user.username else user.first_name or str(user.telegram_id)
    lines = [
        "🖼 <b>Оценка образа</b>",
        f"<b>От:</b> {username}",
        f"<b>Оценка:</b> {STARS[body.stars]}",
    ]
    if outfit.item_title:
        lines.append(f"<b>Образ:</b> {html.escape(outfit.item_title)}")
    lines.append(f"<b>Картинка:</b> {html.escape(outfit.generated_image_url)}")
    asyncio.create_task(notify_admin("\n".join(lines), settings.bot_token, settings.admin_chat_id))
    return {"ok": True}


def _extract_wb_article(link: str) -> str | None:
    m = re.search(r"/catalog/(\d+)/", link)
    return m.group(1) if m else None


async def _notify_user(
    telegram_id: int,
    image_url: str,
    item_title: str | None,
    item_link: str | None,
    outfit_id: int | None = None,
) -> None:
    caption_parts = ["Ваш образ готов!"]
    if item_title:
        caption_parts.append(f"Товар: {item_title}")
    if item_link:
        article = _extract_wb_article(item_link)
        if article:
            caption_parts.append(f"Артикул: <code>{article}</code>")
        caption_parts.append(f'<a href="{item_link}">Открыть на WB</a>')
    caption_parts.append("\nКак вам результат?")
    caption = "\n".join(caption_parts)

    reply_markup = None
    if outfit_id is not None:
        reply_markup = {
            "inline_keyboard": [[
                {"text": "★", "callback_data": f"rate:{outfit_id}:1"},
                {"text": "★★", "callback_data": f"rate:{outfit_id}:2"},
                {"text": "★★★", "callback_data": f"rate:{outfit_id}:3"},
                {"text": "★★★★", "callback_data": f"rate:{outfit_id}:4"},
                {"text": "★★★★★", "callback_data": f"rate:{outfit_id}:5"},
            ]]
        }

    async with httpx.AsyncClient(timeout=30.0) as client:
        await client.post(
            f"{_TG_API}/bot{settings.bot_token}/sendPhoto",
            json={
                "chat_id": telegram_id,
                "photo": image_url,
                "caption": caption,
                "parse_mode": "HTML",
                **({"reply_markup": reply_markup} if reply_markup else {}),
            },
        )
