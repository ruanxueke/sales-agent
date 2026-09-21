"""数据备份测试：备份目录、文件、最近备份状态"""
from __future__ import annotations
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config.settings as cfg
from core import backup


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="sales-backup-test-"))
    old_dir = cfg.settings.DATA_DIR
    try:
        (tmp / "customers.db").write_text("db")
        (tmp / "vector_index.json").write_text("{}")
        cfg.settings.DATA_DIR = tmp
        result = backup.backup_data(retain=2)
        assert set(result["files"]) == {"customers.db", "vector_index.json"}, result
        assert Path(result["dir"]).exists(), "备份目录不存在"
        info = backup.last_backup()
        assert info["exists"] is True and info["count"] == 1, info
        print("数据备份测试通过")
        return 0
    finally:
        cfg.settings.DATA_DIR = old_dir
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
