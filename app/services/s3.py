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

    base_url = settings.s3_public_url or f"{settings.s3_endpoint}/{settings.s3_bucket}"
    return f"{base_url}/{key}"
