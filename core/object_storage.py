"""对象存储：备份/导出归档到 OSS/COS/S3，未配置时落到本地归档目录"""
from __future__ import annotations
import logging
import shutil
from pathlib import Path

from config.settings import settings

logger = logging.getLogger(__name__)


def _resolve(value: str) -> str:
    from core.secrets import resolve
    return resolve(value or "")

def remote_status() -> dict:
    provider = settings.OBJECT_STORAGE_PROVIDER or "local"
    configured = provider in ("s3", "cos") and bool(
        settings.OBJECT_STORAGE_BUCKET and _resolve(settings.OBJECT_STORAGE_ACCESS_KEY)
    )
    return {
        "provider": provider,
        "configured": configured,
        "bucket": settings.OBJECT_STORAGE_BUCKET or "",
        "endpoint": settings.OBJECT_STORAGE_ENDPOINT or "",
    }


def upload_file(local_path, object_key: str) -> dict:
    local_path = Path(local_path)
    if not local_path.exists():
        return {"ok": False, "error": f"文件不存在: {local_path}"}
    info = remote_status()
    if info["provider"] in ("s3", "cos") and info["configured"]:
        try:
            import boto3
            client = boto3.client(
                "s3",
                endpoint_url=settings.OBJECT_STORAGE_ENDPOINT or None,
                region_name=settings.OBJECT_STORAGE_REGION or None,
                aws_access_key_id=_resolve(settings.OBJECT_STORAGE_ACCESS_KEY),
                aws_secret_access_key=_resolve(settings.OBJECT_STORAGE_SECRET_KEY),
            )
            client.upload_file(str(local_path), settings.OBJECT_STORAGE_BUCKET, object_key)
            return {"ok": True, "key": object_key, "provider": info["provider"]}
        except Exception as e:
            logger.error(f"对象存储上传失败: {e}")
            return {"ok": False, "error": str(e)}
    # 本地归档（模拟对象存储），便于离线验证
    target = Path(settings.DATA_DIR) / "object_store" / object_key
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(local_path, target)
    return {"ok": True, "key": str(target), "provider": "local"}


def upload_backup(backup_dir, prefix: str = "backups") -> list[dict]:
    backup_dir = Path(backup_dir)
    results = []
    if not backup_dir.exists():
        return results
    for f in backup_dir.iterdir():
        if f.is_file():
            results.append(upload_file(f, f"{prefix}/{backup_dir.name}/{f.name}"))
    return results
