"""口令哈希与校验：PBKDF2-HMAC-SHA256（纯标准库实现，零新增依赖）。

为什么不用 bcrypt / argon2
    本项目的发布流程是 `docker cp` 覆盖代码，**不重建镜像**；新增的第三方依赖不会被
    安装进正在运行的容器，会直接导致登录 `ImportError`。PBKDF2 在 `hashlib` 里就有，
    迭代次数可调，是 OWASP 认可的合规 KDF，因此在"零新增依赖"这个约束下，它是唯一
    不会把线上登录搞挂的正确选项。

历史遗留问题
    `system_users.password_hash` 里存的是 `sha256(用户名 + 口令)`：
      * 盐是固定的、而且就是用户名 → 可预计算；
      * 无迭代 → 单次 SHA-256，GPU 每秒可试数十亿次；
      * 撞库成本近似为零。
    本模块提供带随机盐 + 高迭代的新格式，同时**保留旧哈希可登录**，并在用户登录
    成功后原地升级为新格式（rehash on login），无需强制全员改密。

存储格式
    `pbkdf2_sha256$<迭代次数>$<base64盐>$<base64派生密钥>`
    自带算法与代价参数，将来调高迭代次数不会让老哈希失效——`needs_rehash()` 会在
    下次登录时自动把它升上来。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets

logger = logging.getLogger(__name__)

ALGO = "pbkdf2_sha256"
# OWASP 对 PBKDF2-HMAC-SHA256 的建议下限为 600,000 次。
DEFAULT_ITERATIONS = 600_000
SALT_BYTES = 16
DKLEN = 32
# 防御畸形哈希触发的 CPU 耗尽（迭代次数来自数据库字段）。
MAX_ACCEPTED_ITERATIONS = 5_000_000


def _b64e(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _b64d(txt: str) -> bytes:
    return base64.b64decode(txt.encode("ascii"))


def hash_password(password: str, iterations: int = DEFAULT_ITERATIONS) -> str:
    """生成新格式口令哈希（每次调用都带独立随机盐）。"""
    if not isinstance(password, str):
        raise TypeError("password 必须是字符串")
    iters = max(int(iterations), 1)
    salt = secrets.token_bytes(SALT_BYTES)
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iters, dklen=DKLEN
    )
    return f"{ALGO}${iters}${_b64e(salt)}${_b64e(dk)}"


def is_kdf_hash(stored: str) -> bool:
    """是否为新格式哈希（旧格式 = `sha256(盐+口令)` 的 64 位十六进制串）。"""
    return isinstance(stored, str) and stored.startswith(ALGO + "$")


def needs_rehash(stored: str, iterations: int = DEFAULT_ITERATIONS) -> bool:
    """是否应在本轮登录成功后把哈希升级（旧格式或迭代次数偏低）。"""
    if not is_kdf_hash(stored):
        return True
    try:
        _, iters, _salt, _dk = stored.split("$", 3)
        return int(iters) < iterations
    except Exception:
        return True


def verify_password(password: str, stored: str, *, legacy_salt: str = "") -> bool:
    """校验口令。

    `legacy_salt` 传入旧格式所需的盐（即用户名）；不传则旧格式一律判失败。
    校验过程使用 `hmac.compare_digest`，避免计时侧信道。
    """
    if not stored or not isinstance(password, str):
        return False

    if is_kdf_hash(stored):
        try:
            _, iters_s, salt_s, dk_s = stored.split("$", 3)
            iters = int(iters_s)
            salt = _b64d(salt_s)
            expected = _b64d(dk_s)
        except Exception:
            logger.warning("口令哈希格式损坏，拒绝校验")
            return False
        if iters <= 0 or iters > MAX_ACCEPTED_ITERATIONS:
            logger.warning("口令哈希迭代次数异常（%s），拒绝校验", iters)
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            iters,
            dklen=len(expected) or DKLEN,
        )
        return hmac.compare_digest(actual, expected)

    # 旧格式：sha256(salt + password)
    if not legacy_salt:
        return False
    expected = hashlib.sha256((legacy_salt + password).encode("utf-8")).hexdigest()
    return hmac.compare_digest(expected, stored)


def legacy_hash(password: str, salt: str) -> str:
    """旧格式哈希；仅供迁移/测试对照使用。"""
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
