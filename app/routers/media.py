import re

from botocore.exceptions import ClientError
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.services.s3 import download_bytes

router = APIRouter(prefix="/media", tags=["media"])

_SAFE_KEY = re.compile(r'^[\w\-./]+$')


@router.get("/{path:path}")
async def proxy_media(path: str):
    if not _SAFE_KEY.match(path):
        raise HTTPException(status_code=400, detail="Invalid key")
    try:
        data, content_type = await download_bytes(path)
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("NoSuchKey", "404"):
            raise HTTPException(status_code=404, detail="Not found")
        raise HTTPException(status_code=502, detail="Storage error")
    return Response(content=data, media_type=content_type)
