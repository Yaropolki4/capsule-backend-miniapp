import asyncio
import uuid

import boto3
from botocore.config import Config

from app.config import settings


def _get_client():
    return boto3.client(
        "s3",
        region_name=settings.s3_region,
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key_id,
        config=Config(signature_version="s3v4"),
    )


def _s3_base_url() -> str:
    base = settings.s3_public_url or f"{settings.s3_endpoint}/{settings.s3_bucket}"
    return base.rstrip("/")


def s3_key_from_url(url: str) -> str | None:
    base = _s3_base_url()
    if url.startswith(base + "/"):
        return url[len(base) + 1:]
    return None


def to_proxy_url(s3_url: str, api_base: str) -> str:
    key = s3_key_from_url(s3_url)
    if key is None:
        return s3_url
    return f"{api_base.rstrip('/')}/media/{key}"


async def upload_bytes(data: bytes, content_type: str, prefix: str = "generated") -> str:
    key = f"{prefix}/{uuid.uuid4()}.jpg"

    def _upload():
        client = _get_client()
        client.put_object(
            Bucket=settings.s3_bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
            ContentLength=len(data),
        )

    await asyncio.to_thread(_upload)

    base_url = _s3_base_url()
    return f"{base_url}/{key}"


async def download_bytes(key: str) -> tuple[bytes, str]:
    def _download():
        client = _get_client()
        resp = client.get_object(Bucket=settings.s3_bucket, Key=key)
        return resp["Body"].read(), resp.get("ContentType", "image/jpeg")

    return await asyncio.to_thread(_download)
