import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.crud.outfit import create_outfit, get_user_outfits
from app.crud.user import use_generation
from app.database import AsyncSessionFactory
from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.services.image_gen import generate_try_on
from app.services.s3 import upload_bytes
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/generate", tags=["generate"])

_TG_API = "https://api.telegram.org"


class TryOnRequest(BaseModel):
    photo_file_id: str | None = None
    photo_url: str | None = None
    item_image_url: str
    item_id: int | None = None
    item_title: str | None = None
    item_link: str | None = None
    generation_prompt: str | None = None


@router.post("/outfits")
async def list_outfits(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    outfits = await get_user_outfits(db, user.id)
    return [
        {
            "id": o.id,
            "item_title": o.item_title,
            "item_image_url": o.item_image_url,
            "item_link": o.item_link,
            "generated_image_url": o.generated_image_url,
            "created_at": o.created_at.isoformat(),
        }
        for o in outfits
    ]


@router.post("/try-on")
async def try_on(
    body: TryOnRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.generations_left <= 0:
        raise HTTPException(status_code=402, detail="No generations left")

    if not body.photo_file_id and not body.photo_url:
        raise HTTPException(status_code=400, detail="photo_file_id or photo_url required")

    if body.photo_url:
        user_photo_url = body.photo_url
    else:
        async with httpx.AsyncClient(timeout=30.0) as client:
            file_resp = await client.get(
                f"{_TG_API}/bot{settings.bot_token}/getFile",
                params={"file_id": body.photo_file_id},
            )
            file_data = file_resp.json()
            if not file_data.get("ok"):
                raise HTTPException(status_code=400, detail="Failed to get file info from Telegram")

            file_path = file_data["result"]["file_path"]
            photo_resp = await client.get(
                f"{_TG_API}/file/bot{settings.bot_token}/{file_path}"
            )
            photo_bytes = photo_resp.content

        user_photo_url = await upload_bytes(photo_bytes, "image/jpeg")

    result_bytes = await generate_try_on(user_photo_url, body.item_image_url, settings.open_router_key, body.generation_prompt)
    if not result_bytes:
        raise HTTPException(status_code=502, detail="Image generation failed")

    generated_url = await upload_bytes(result_bytes, "image/jpeg")

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

    await _notify_user(user.telegram_id, generated_url, body.item_title, body.item_link)

    return {"outfit_id": outfit.id, "generated_image_url": generated_url}


async def _notify_user(
    telegram_id: int,
    image_url: str,
    item_title: str | None,
    item_link: str | None,
) -> None:
    caption_parts = ["Ваш образ готов!"]
    if item_title:
        caption_parts.append(f"Товар: {item_title}")
    if item_link:
        caption_parts.append(f"Ссылка на WB: {item_link}")
    caption = "\n".join(caption_parts)

    async with httpx.AsyncClient(timeout=30.0) as client:
        await client.post(
            f"{_TG_API}/bot{settings.bot_token}/sendPhoto",
            json={
                "chat_id": telegram_id,
                "photo": image_url,
                "caption": caption,
            },
        )
