"""桌面控制器：截图、点击、输入、粘贴、发送、聚焦窗口。依赖缺失时进入模拟模式。"""
from __future__ import annotations

import logging
import random
import time

logger = logging.getLogger(__name__)

try:
    import pyautogui
    import mss
    CONTROLLER_AVAILABLE = True
except Exception:
    pyautogui = None
    mss = None
    CONTROLLER_AVAILABLE = False


def _parse_region(value: str):
    try:
        parts = [int(x) for x in value.split(",")]
        if len(parts) == 4:
            return {"left": parts[0], "top": parts[1], "width": parts[2], "height": parts[3]}
    except Exception as e:
        logger.debug("_parse_region 异常已忽略: %s", e)
    return None


class Controller:
    """UI 自动化原语：截图 / 点击 / 输入 / 粘贴 / 回车 / 聚焦窗口。"""

    def __init__(self, region: str = ""):
        self.region = _parse_region(region)
        self.available = CONTROLLER_AVAILABLE

    def screenshot(self) -> bytes:
        if mss is None:
            logger.warning("mss 未安装，进入模拟模式")
            return b""
        try:
            with mss.mss() as sct:
                monitor = self.region or sct.monitors[1]
                raw = sct.grab(monitor)
                import os
                import tempfile
                from mss.tools import to_png
                tmp_path = tempfile.mktemp(suffix=".png")
                try:
                    to_png(raw.rgb, raw.size, output=tmp_path)
                    with open(tmp_path, "rb") as f:
                        return f.read()
                finally:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
        except Exception as e:
            logger.error("截图失败: %s", e)
            return b""

    def click(self, x: int, y: int):
        if pyautogui is None:
            logger.info("[模拟] 点击 (%s, %s)", x, y)
            return
        try:
            pyautogui.click(int(x), int(y))
        except Exception as e:
            logger.error("点击失败: %s", e)

    def type_text(self, text: str):
        text = text or ""
        if pyautogui is None:
            logger.info("[模拟] 输入: %s", text[:50])
            return
        try:
            import pyperclip
            pyperclip.copy(text)
            pyautogui.hotkey("ctrl", "v")
        except Exception:
            try:
                pyautogui.write(text, interval=0.03)
            except Exception as e:
                logger.error("输入失败: %s", e)

    def press_enter(self):
        if pyautogui is None:
            logger.info("[模拟] 回车发送")
            return
        try:
            pyautogui.press("enter")
        except Exception as e:
            logger.error("回车失败: %s", e)

    def type_and_send(self, text: str, input_box=None, min_delay: float = 2.5, max_delay: float = 8.0):
        text = (text or "").strip()
        if not text:
            return False
        if input_box and input_box.get("x") and input_box.get("y"):
            self.click(int(input_box["x"]), int(input_box["y"]))
        try:
            if pyautogui is not None:
                pyautogui.hotkey("ctrl", "a")
        except Exception as e:
            logger.debug("Controller.type_and_send 异常已忽略: %s", e)
        self.type_text(text)
        delay = random.uniform(min_delay, max_delay) + min(4.0, len(text) * 0.04)
        if pyautogui is not None:
            time.sleep(delay)
        else:
            logger.info("[模拟] 等待 %.1fs 后发送", delay)
        self.press_enter()
        return True

    def focus_window(self, title: str):
        if not title:
            return False
        try:
            import pygetwindow as gw
            wins = gw.getWindowsWithTitle(title)
            if wins:
                wins[0].activate()
                return True
        except Exception as e:
            logger.warning("聚焦窗口失败: %s", e)
        return False
