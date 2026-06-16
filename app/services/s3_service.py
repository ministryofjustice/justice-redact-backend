from pathlib import Path
import boto3
from app.core.settings import settings

_BUCKET = settings.s3_bucket_name

s3_client = boto3.client(
    "s3",
    region_name=settings.s3_region,
)


def upload_file_to_s3(local_path: Path, key: str) -> None:
    s3_client.upload_file(str(local_path), _BUCKET, key)


def download_file_from_s3(key: str, local_path: Path) -> None:
    local_path.parent.mkdir(parents=True, exist_ok=True)

    s3_client.download_file(
        _BUCKET,
        key,
        str(local_path),
    )


def get_object_from_s3(key: str) -> bytes:
    response = s3_client.get_object(
        Bucket=_BUCKET,
        Key=key,
    )

    return response["Body"].read()
