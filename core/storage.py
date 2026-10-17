"""Where uploaded files are kept.

If S3_BUCKET is set, files go to S3 (s3://bucket/uploads/<file_id>/<filename>).
Otherwise they go to a local folder (DATA_DIR/uploads), which is what tests use.

On EC2 the server gets S3 access from its IAM role, so no keys are needed.
On your laptop, boto3 uses the credentials from `aws configure`.
"""

import os
import shutil
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def save_upload(src_path, file_id: str, filename: str) -> str:
    """Store the file and return where it lives (an s3:// URL or a local path)."""
    bucket = os.getenv("S3_BUCKET")
    if bucket:
        import boto3
        key = f"uploads/{file_id}/{filename}"
        boto3.client("s3", region_name=os.getenv("AWS_REGION", "ap-south-1")).upload_file(
            str(src_path), bucket, key)
        return f"s3://{bucket}/{key}"
    folder = Path(os.getenv("DATA_DIR", "data")) / "uploads"
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{file_id}_{filename}"
    shutil.copyfile(src_path, dest)
    return str(dest)
