"""Celery Beat 启动入口（兼容新版 Celery API）

注意：本文件必须"只定义、不执行"。原来 `celery.Beat(loglevel="info").run()`
直接写在模块顶层，于是**导入 `deploy.run_beat` 就等于让进程永久阻塞在调度循环里**
（发布前质量门的导入检查就是卡在这里超时的）。

另外 `sys.path.insert(0, "/app")` 是容器内路径，在本机跑时会把项目根目录挤出去，
所以改成按脚本位置回推。
"""
from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.tasks import celery  # noqa: E402  （必须在 sys.path 调整之后导入）


def main() -> None:
    celery.Beat(loglevel=os.environ.get("CELERY_LOGLEVEL", "info")).run()


if __name__ == "__main__":
    main()
