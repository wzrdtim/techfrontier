from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from app.core.config import get_settings

CACHE_CONTROL_IMMUTABLE = "public, max-age=31536000, immutable"


@dataclass(frozen=True)
class StoredObject:
    key: str
    url: str
    size: int
    modified: datetime


class ObjectStorage(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> str:
        """Store bytes and return the public URL."""

    def delete(self, key: str) -> None:
        """Delete an object; no-op if missing."""

    def exists(self, key: str) -> bool:
        ...

    def list_objects(self) -> list[StoredObject]:
        ...


class LocalStorage:
    """Filesystem storage under frontend/static/uploads (dev / tests)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def public_url(self, key: str) -> str:
        return f"/static/uploads/{key}"

    def put(self, key: str, data: bytes, content_type: str) -> str:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return self.public_url(key)

    def delete(self, key: str) -> None:
        path = self.root / key
        if path.is_file():
            path.unlink()

    def exists(self, key: str) -> bool:
        return (self.root / key).is_file()

    def list_objects(self) -> list[StoredObject]:
        items: list[StoredObject] = []
        for path in self.root.iterdir():
            if not path.is_file() or path.name.startswith("."):
                continue
            stat = path.stat()
            items.append(
                StoredObject(
                    key=path.name,
                    url=self.public_url(path.name),
                    size=stat.st_size,
                    modified=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                )
            )
        items.sort(key=lambda item: item.modified, reverse=True)
        return items


class R2Storage:
    """Cloudflare R2 via the S3 API."""

    def __init__(self) -> None:
        import boto3
        from botocore.config import Config

        settings = get_settings()
        self.bucket = settings.r2_bucket_name.strip()
        self.public_base = settings.image_cdn_base
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.r2_endpoint,
            aws_access_key_id=settings.r2_access_key_id.strip(),
            aws_secret_access_key=settings.r2_secret_access_key.strip(),
            region_name="auto",
            config=Config(signature_version="s3v4"),
        )

    def public_url(self, key: str) -> str:
        return f"{self.public_base}/{key.lstrip('/')}"

    def put(self, key: str, data: bytes, content_type: str) -> str:
        self._client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
            CacheControl=CACHE_CONTROL_IMMUTABLE,
        )
        return self.public_url(key)

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self.bucket, Key=key)

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False

    def list_objects(self) -> list[StoredObject]:
        items: list[StoredObject] = []
        continuation: str | None = None
        while True:
            kwargs: dict = {"Bucket": self.bucket}
            if continuation:
                kwargs["ContinuationToken"] = continuation
            response = self._client.list_objects_v2(**kwargs)
            for obj in response.get("Contents") or []:
                key = obj["Key"]
                if not key or key.endswith("/"):
                    continue
                modified = obj.get("LastModified") or datetime.now(tz=timezone.utc)
                if modified.tzinfo is None:
                    modified = modified.replace(tzinfo=timezone.utc)
                items.append(
                    StoredObject(
                        key=key,
                        url=self.public_url(key),
                        size=int(obj.get("Size") or 0),
                        modified=modified,
                    )
                )
            if not response.get("IsTruncated"):
                break
            continuation = response.get("NextContinuationToken")
        items.sort(key=lambda item: item.modified, reverse=True)
        return items


_LOCAL_UPLOAD_DIR = (
    Path(__file__).resolve().parents[2] / "frontend" / "static" / "uploads"
)


def get_storage() -> ObjectStorage:
    settings = get_settings()
    if settings.r2_configured:
        return R2Storage()
    return LocalStorage(_LOCAL_UPLOAD_DIR)


def safe_object_key(filename: str) -> str | None:
    """Return a basename key, or None if the name is unsafe."""
    key = Path(filename).name
    if not key or key in {".", ".."} or key.startswith("."):
        return None
    if "/" in key or "\\" in key:
        return None
    return key
