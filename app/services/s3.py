import asyncio
import uuid

import boto3
from botocore.config import Config

S3_BUCKET = "capsule-test"
S3_ENDPOINT = "https://storage.yandexcloud.net"
S3_REGION = "ru-central1"


def _get_client(access_key: str, secret_key: str):
    return boto3.client(
        "s3",
        region_name=S3_REGION,
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4"),
    )


async def upload_bytes(data: bytes, content_type: str, access_key: str, secret_key: str, prefix: str = "generated") -> str:
    key = f"{prefix}/{uuid.uuid4()}.jpg"

    def _upload():
        client = _get_client(access_key, secret_key)
        client.put_object(
            Bucket=S3_BUCKET,
            Key=key,
            Body=data,
            ContentType=content_type,
            ContentLength=len(data),
        )

    await asyncio.to_thread(_upload)
    return f"{S3_ENDPOINT}/{S3_BUCKET}/{key}"
