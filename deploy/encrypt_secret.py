#!/usr/bin/env python3
"""把明文密钥加密成 enc: 密文，用于写入 .env

用法：
    python deploy/encrypt_secret.py 你的密钥 [SECRET_KEY]

先给 .env 设置 SECRET_KEY，再运行本脚本把每个密钥加密。

注意：本文件必须"只定义、不执行"。原来参数解析与 encrypt() 都写在模块顶层，
于是 `import deploy.encrypt_secret`（质量门会逐个导入所有模块）会因为缺参数
直接 SystemExit(1)，看起来像脚本坏了，其实是"导入一个 CLI"本就不该有副作用。
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python deploy/encrypt_secret.py 明文 [SECRET_KEY]")
        return 1

    if len(sys.argv) >= 3:
        os.environ["SECRET_KEY"] = sys.argv[2]

    from core.secrets import encrypt

    print(encrypt(sys.argv[1]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
