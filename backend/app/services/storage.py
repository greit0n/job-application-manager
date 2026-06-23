"""Object storage: Cloudflare R2 (S3 API) in prod, local filesystem in dev.

Downloads are served through authenticated API endpoints (which call `get`),
so per-user scoping is enforced by our code rather than by presigned URLs.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..config import Settings, get_settings


class Storage(ABC):
    @abstractmethod
    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None: ...

    @abstractmethod
    def get(self, key: str) -> bytes: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...


class LocalStorage(Storage):
    """Filesystem store for local dev (no R2/MinIO needed). Gitignored dir."""

    def __init__(self, base_dir: Path):
        self.base = base_dir
        self.base.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # Prevent traversal; keys are app-generated but be defensive.
        p = (self.base / key).resolve()
        if not str(p).startswith(str(self.base.resolve())):
            raise ValueError("Invalid storage key")
        return p

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        p = self._path(key)
        if p.exists():
            p.unlink()


class S3Storage(Storage):
    """Cloudflare R2 via the S3 API (boto3)."""

    def __init__(self, settings: Settings):
        import boto3
        from botocore.config import Config

        self.bucket = settings.r2_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.r2_endpoint_url,
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key,
            region_name=settings.r2_region,
            config=Config(signature_version="s3v4"),
        )

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    def get(self, key: str) -> bytes:
        obj = self.client.get_object(Bucket=self.bucket, Key=key)
        return obj["Body"].read()

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)


_REPO_ROOT = Path(__file__).resolve().parents[3]


def get_storage(settings: Settings | None = None) -> Storage:
    settings = settings or get_settings()
    if settings.r2_endpoint_url and settings.r2_access_key_id:
        return S3Storage(settings)
    return LocalStorage(_REPO_ROOT / "backend" / "local-uploads")
