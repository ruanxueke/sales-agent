#!/usr/bin/env python3
"""密钥解密模块：支持 .env 中 enc: 前缀的加密值。

优先使用 cryptography(Fernet)，缺失时用内置算法兜底，避免依赖缺失导致服务不可用。
商用建议配合 KMS 使用。
"""
from __future__ import annotations
import base64
import hashlib
import logging

from config.settings import settings

logger = logging.getLogger(__name__)

_PREFIX = "enc:"
_cache: dict = {}


def _fallback_key() -> bytes:
    return hashlib.sha256((settings.SECRET_KEY or "").encode("utf-8")).digest()


def _xor_bytes(data: bytes) -> bytes:
    key = _fallback_key()
    out = bytearray()
    for i, b in enumerate(data):
        stream = hashlib.sha256(key + str(i).encode("utf-8")).digest()
        out.append(b ^ stream[0])
    return bytes(out)


def _encrypt(plain: str) -> str:
    try:
        from cryptography.fernet import Fernet
        key = base64.urlsafe_b64encode(hashlib.sha256((settings.SECRET_KEY or "").encode()).digest())
        return Fernet(key).encrypt(plain.encode("utf-8")).decode("utf-8")
    except Exception:
        return base64.urlsafe_b64encode(_xor_bytes(plain.encode("utf-8"))).decode("utf-8")


def _decrypt(cipher: str) -> str:
    try:
        from cryptography.fernet import Fernet
        key = base64.urlsafe_b64encode(hashlib.sha256((settings.SECRET_KEY or "").encode()).digest())
        try:
            return Fernet(key).decrypt(cipher.encode("utf-8")).decode("utf-8")
        except Exception as e:
            logger.debug("_decrypt 异常已忽略: %s", e)
    except Exception as e:
        logger.debug("_decrypt 异常已忽略: %s", e)
    return _xor_bytes(base64.urlsafe_b64decode(cipher.encode("utf-8"))).decode("utf-8")


def resolve(value: str) -> str:
    """如果值以 enc: 开头则解密，否则原样返回"""
    if not value or not str(value).startswith(_PREFIX):
        return str(value)
    cipher = str(value)[len(_PREFIX):]
    if cipher in _cache:
        return _cache[cipher]
    if not settings.SECRET_KEY:
        logger.warning("检测到加密配置但未设置 SECRET_KEY")
        return ""
    try:
        plain = _decrypt(cipher)
        _cache[cipher] = plain
        return plain
    except Exception:
        logger.error("配置解密失败：SECRET_KEY 不匹配")
        return ""


def encrypt(plain: str) -> str:
    """生成 enc: 前缀密文，用于写入 .env"""
    if not settings.SECRET_KEY:
        raise ValueError("请先设置 SECRET_KEY")
    return _PREFIX + _encrypt(plain)
