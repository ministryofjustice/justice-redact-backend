import os

import boto3

_BUCKET = os.environ["S3_BUCKET_NAME"]

s3_client = boto3.client(
    "s3",
    region_name=os.environ["S3_REGION"],
)
