"""系统自检接口测试：数据库、向量库、模型、通道、备份状态"""
from __future__ import annotations
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_tmp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
_tmp_db.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp_db.name}"

import config.settings as cfg
cfg.settings.API_KEYS = ""
cfg.settings.ADMIN_API_KEYS = ""

from fastapi.testclient import TestClient
from api_server import app

client = TestClient(app)


def main() -> int:
    r = client.get("/api/v1/system/self-check")
    assert r.status_code == 200, r.text
    data = r.json()
    assert "checks" in data and isinstance(data["checks"], list), data
    names = [c["name"] for c in data["checks"]]
    for expected in ("数据库", "向量库", "DeepSeek 模型", "公众号通道", "数据备份"):
        assert expected in names, f"缺少自检项: {expected}"
    print("系统自检接口测试通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
