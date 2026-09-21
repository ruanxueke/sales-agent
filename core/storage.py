"""对象存储抽象：本地目录 / S3 / COS"""
from __future__ import annotations

from config.settings import settings


class Storage:
    def save(self, key: str, data: bytes) -> str:
        raise NotImplementedError

    def read(self, key: str) -> bytes:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError

    def url(self, key: str) -> str:
        raise NotImplementedError


class LocalStorage(Storage):
    def __init__(self):
        self._base = settings.DATA_DIR / "uploads"
        self._base.mkdir(parents=True, exist_ok=True)

    def save(self, key: str, data: bytes) -> str:
        path = self._base / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return str(path)

    def read(self, key: str) -> bytes:
        return (self._base / key).read_bytes()

    def delete(self, key: str) -> None:
        path = self._base / key
        if path.exists():
            path.unlink()

    def url(self, key: str) -> str:
        return str(self._base / key)


class ObjectStorage(Storage):
    """S3 / COS（兼容 S3 协议）"""

    def __init__(self):
        import boto3
        kwargs = {}
        if settings.OBJECT_STORAGE_ENDPOINT:
            kwargs["endpoint_url"] = settings.OBJECT_STORAGE_ENDPOINT
        if settings.OBJECT_STORAGE_REGION:
            kwargs["region_name"] = settings.OBJECT_STORAGE_REGION
        if settings.OBJECT_STORAGE_ACCESS_KEY:
            kwargs["aws_access_key_id"] = settings.OBJECT_STORAGE_ACCESS_KEY
        if settings.OBJECT_STORAGE_SECRET_KEY:
            kwargs["aws_secret_access_key"] = settings.OBJECT_STORAGE_SECRET_KEY
        self._client = boto3.client("s3", **kwargs)
        self._bucket = settings.OBJECT_STORAGE_BUCKET

    def save(self, key: str, data: bytes) -> str:
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data)
        return f"{self._bucket}/{key}"

    def read(self, key: str) -> bytes:
        return self._client.get_object(Bucket=self._bucket, Key=key)["Body"].read()

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)

    def url(self, key: str) -> str:
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=3600,
        )


def get_storage() -> Storage:
    provider = settings.OBJECT_STORAGE_PROVIDER.lower()
    if provider in ("s3", "cos"):
        return ObjectStorage()
    return LocalStorage()


storage = get_storage()
