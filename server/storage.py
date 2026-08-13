from __future__ import annotations

from pathlib import Path
from typing import BinaryIO, Protocol

from server.config import ServerSettings


class ObjectStorage(Protocol):
    def put(self, *, key: str, stream: BinaryIO, content_type: str) -> None: ...

    def download_to(self, *, key: str, destination: Path) -> None: ...

    def delete(self, *, key: str) -> None: ...


class S3ObjectStorage:
    def __init__(self, settings: ServerSettings) -> None:
        if not all((settings.object_storage_endpoint, settings.object_storage_access_key, settings.object_storage_secret_key)):
            raise ValueError("object storage endpoint and credentials are required")
        import boto3

        self.bucket = settings.object_storage_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.object_storage_endpoint,
            aws_access_key_id=settings.object_storage_access_key,
            aws_secret_access_key=settings.object_storage_secret_key,
        )

    def put(self, *, key: str, stream: BinaryIO, content_type: str) -> None:
        self.client.upload_fileobj(stream, self.bucket, key, ExtraArgs={"ContentType": content_type})

    def download_to(self, *, key: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        self.client.download_file(self.bucket, key, str(destination))

    def delete(self, *, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)


def resource_key(*, tenant_id: str, resource_id: str, filename: str) -> str:
    safe_name = Path(filename).name.replace(" ", "_") or "upload"
    return f"{tenant_id}/resources/{resource_id}/{safe_name}"
