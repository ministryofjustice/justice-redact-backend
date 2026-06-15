import os
from pathlib import Path

import boto3

_BUCKET = os.environ["S3_BUCKET_NAME"]

s3_client = boto3.client(
    "s3",
    region_name=os.environ["S3_REGION"],
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
