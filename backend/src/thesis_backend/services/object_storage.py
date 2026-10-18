from pathlib import Path
import time

from minio import Minio
from minio.error import S3Error

from thesis_backend.config import settings


client = Minio(
    endpoint=settings.minio_endpoint,
    access_key=settings.minio_access_key,
    secret_key=settings.minio_secret_key,
    secure=settings.minio_secure,
)


def initialize_bucket() -> None:
    for attempt in range(20):
        try:
            if not client.bucket_exists(settings.minio_bucket):
                client.make_bucket(settings.minio_bucket)
            return
        except Exception:
            if attempt == 19:
                raise
            time.sleep(1)


def upload_file(
    source: Path,
    object_key: str,
    content_type: str,
) -> None:
    client.fput_object(
        bucket_name=settings.minio_bucket,
        object_name=object_key,
        file_path=str(source),
        content_type=content_type,
    )


def get_file(object_key: str):
    return client.get_object(
        bucket_name=settings.minio_bucket,
        object_name=object_key,
    )


def remove_file(object_key: str) -> None:
    try:
        client.remove_object(
            bucket_name=settings.minio_bucket,
            object_name=object_key,
        )
    except S3Error:
        pass
