from pathlib import Path
import boto3
import json
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


def object_exists_in_s3(key: str) -> bool:
    try:
        s3_client.head_object(
            Bucket=_BUCKET,
            Key=key,
        )
        return True
    except s3_client.exceptions.ClientError:
        return False


def upload_json_to_s3(data: dict, key: str) -> None:
    s3_client.put_object(
        Bucket=_BUCKET,
        Key=key,
        Body=json.dumps(data).encode("utf-8"),
        ContentType="application/json",
    )


def download_json_from_s3(key: str) -> dict:
    response = s3_client.get_object(
        Bucket=_BUCKET,
        Key=key,
    )

    return json.loads(response["Body"].read())


def delete_s3_prefix(prefix: str) -> None:
    paginator = s3_client.get_paginator("list_objects_v2")

    for page in paginator.paginate(
        Bucket=_BUCKET,
        Prefix=prefix,
    ):
        objects = [{"Key": item["Key"]} for item in page.get("Contents", [])]

        if not objects:
            continue

        s3_client.delete_objects(
            Bucket=_BUCKET,
            Delete={
                "Objects": objects,
                "Quiet": True,
            },
        )
