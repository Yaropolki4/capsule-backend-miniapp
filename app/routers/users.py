import httpx
from fastapi import APIRouter, Depends, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.crud.user import add_user_photo
from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.services.s3 import upload_bytes

router = APIRouter(prefix="/users", tags=["users"])

_TG_API = "https://api.telegram.org"


@router.post("/photos")
async def get_user_photos(user: User = Depends(get_current_user)):
    bot_token = settings.bot_token

    user_photos = [
        {"file_id": None, "url": u, "width": 0, "height": 0, "source": "user"}
        for u in (user.photos or [])
    ]

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            f"{_TG_API}/bot{bot_token}/getUserProfilePhotos",
            params={"user_id": user.telegram_id, "limit": 10},
        )
        data = resp.json()

        tg_photos = []
        if data.get("ok"):
            for photo_sizes in data["result"]["photos"]:
                largest = photo_sizes[-1]
                file_resp = await client.get(
                    f"{_TG_API}/bot{bot_token}/getFile",
                    params={"file_id": largest["file_id"]},
                )
                file_data = file_resp.json()
                if file_data.get("ok"):
                    tg_photos.append({
                        "file_id": largest["file_id"],
                        "url": f"{_TG_API}/file/bot{bot_token}/{file_data['result']['file_path']}",
                        "width": largest["width"],
                        "height": largest["height"],
                        "source": "telegram",
                    })

    return {"ok": True, "photos": user_photos + tg_photos}


@router.post("/upload-photo")
async def upload_photo(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    data = await file.read()
    url = await upload_bytes(data, file.content_type or "image/jpeg", prefix="user-photos")
    user = await add_user_photo(db, user, url)
    return {"ok": True, "url": url, "photos": user.photos}
