"""中台桌面客户端：登录中台 + 内置视觉执行器开关。

运行：python desktop_app/main.py
打包：powershell -ExecutionPolicy Bypass -File desktop_app\build_exe.ps1
"""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "vision_agent_config.json"
DATA_DIR = PROJECT_ROOT / "vision_agent_data"
LOG_FILE = DATA_DIR / "desktop_app.log"

DATA_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("desktop_app")


def _load_config() -> dict:
    try:
        if CONFIG_PATH.exists():
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("读取配置失败: %s", e)
    return {}


class DesktopApi:
    def __init__(self):
        self._api_key = ""
        self._enabled = False
        self._thread: threading.Thread | None = None
        self._stop_event: threading.Event | None = None
        self._config = _load_config()

    def set_api_key(self, key: str) -> dict:
        self._api_key = (key or "").strip()
        return {"ok": True, "api_key_set": bool(self._api_key)}

    def get_status(self) -> dict:
        return {
            "enabled": self._enabled,
            "running": bool(self._thread and self._thread.is_alive()),
            "api_key_set": bool(self._api_key),
            "config": {k: v for k, v in self._config.items() if k not in ("DASHSCOPE_API_KEY", "API_KEYS")},
        }

    def start(self) -> dict:
        if self._enabled and self._thread and self._thread.is_alive():
            return {"ok": True, "already": True}
        if not self._api_key:
            return {"ok": False, "error": "请先登录中台，保存 API Key 后再启用"}
        self._apply_env()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run_worker, daemon=True)
        self._thread.start()
        self._enabled = True
        logger.info("视觉执行器已启用")
        return {"ok": True}

    def stop(self) -> dict:
        self._enabled = False
        if self._stop_event:
            self._stop_event.set()
        logger.info("视觉执行器已停止")
        return {"ok": True}

    def _apply_env(self):
        for key, value in self._config.items():
            if value is not None:
                os.environ[key] = str(value)
        if self._api_key:
            os.environ["API_KEYS"] = self._api_key
            os.environ["VISION_AGENT_API_KEY"] = self._api_key

    def _run_worker(self):
        try:
            from vision_agent.worker import main_loop
            main_loop(self._stop_event)
        except Exception as e:
            logger.error("视觉执行器运行异常: %s", e)


def main():
    import webview
    api = DesktopApi()
    window = webview.create_window(
        "销售客服智能体 - 中台桌面版",
        "http://127.0.0.1:5000/static/desktop_console.html",
        width=1440,
        height=900,
        js_api=api,
    )
    try:
        webview.start(private_mode=False)
    except Exception as e:
        logger.exception("桌面窗口启动失败: %s", e)
        raise


if __name__ == "__main__":
    main()
