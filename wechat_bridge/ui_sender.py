"""微信 PC 搜索、目标确认和草稿写入。"""
from __future__ import annotations

import ctypes
import time
from dataclasses import dataclass
from pathlib import Path

from wechat_bridge.config import BridgeConfig


@dataclass
class SendResult:
    ok: bool
    status: str
    detail: str = ""
    failure_code: str = ""
    diagnostic_path: str = ""


class WechatUiSender:
    def __init__(self, config: BridgeConfig):
        self.config = config
        self._active_window = None

    def send(self, task: dict, mode: str, on_stage=None) -> SendResult:
        def stage(name: str) -> None:
            if on_stage:
                try:
                    on_stage(name)
                except Exception:
                    pass

        def fail(pyautogui, detail: str, failure_code: str) -> SendResult:
            diagnostic_path = ""
            try:
                diagnostic_dir = Path(self.config.queue_path).parent / "diagnostics"
                diagnostic_dir.mkdir(parents=True, exist_ok=True)
                diagnostic_path = str(
                    diagnostic_dir
                    / f"{task.get('task_id') or 'task'}-{int(time.time())}.png"
                )
                pyautogui.screenshot().save(diagnostic_path)
            except Exception:
                diagnostic_path = ""
            return SendResult(
                False,
                "failed",
                detail,
                failure_code=failure_code,
                diagnostic_path=diagnostic_path,
            )

        if mode not in {"draft", "auto"}:
            return SendResult(False, "skipped", f"不支持的发送模式: {mode}")
        if mode == "auto" and not self.config.auto_send_enabled:
            return SendResult(False, "skipped", "全局自动发送开关未开启")

        try:
            import pyautogui
            import pygetwindow
            import pyperclip
        except ImportError as exc:
            return SendResult(False, "failed", f"缺少 UI 自动化依赖: {exc}")

        try:
            stage("resolving")
            window = self._activate_wechat(pygetwindow)
        except Exception as exc:
            return SendResult(
                False,
                "failed",
                str(exc),
                failure_code="WINDOW_FOCUS_LOST",
            )

        try:
            stage("target_found")
            self._click_search(pyautogui)
            self._paste(pyautogui, pyperclip, task.get("target_name") or "")
            time.sleep(1.8)
            if not self._click_target_result(
                pyautogui,
                window,
                task.get("target_name") or "",
            ):
                return fail(pyautogui, "搜索结果中没有精确匹配的目标", "TARGET_NOT_FOUND")
            time.sleep(1.4)
            if not self._verify_target(pyautogui, window, task.get("target_name") or ""):
                return fail(pyautogui, "打开会话后的标题与目标不一致", "RETRYABLE_UI")
            stage("target_verified")
            self._assert_foreground(window)
            self._click_input(pyautogui, window)
            self._paste(pyautogui, pyperclip, task.get("content") or "")
            time.sleep(0.6)
            if mode == "auto":
                stage("before_enter")
                pyautogui.press("enter")
                stage("entered")
                time.sleep(1.0)
                return SendResult(True, "sent", "已执行自动发送")
            return SendResult(True, "drafted", "已写入草稿，未发送")
        except Exception as exc:
            return fail(pyautogui, str(exc), "RETRYABLE_UI")

    def _activate_wechat(self, pygetwindow):
        window = None
        for candidate in pygetwindow.getAllWindows():
            title = str(getattr(candidate, "title", "") or "")
            if title == self.config.window_title:
                window = candidate
                break
        if window is None:
            raise RuntimeError("未找到微信窗口")
        hwnd = int(window._hWnd)
        user32 = ctypes.windll.user32
        user32.ShowWindow(hwnd, 3)
        user32.BringWindowToTop(hwnd)
        # Windows 会阻止后台进程直接抢焦点；发送一次 Alt 键事件后再激活。
        vk_menu = 0x12
        key_up = 0x0002
        user32.keybd_event(vk_menu, 0, 0, 0)
        user32.keybd_event(vk_menu, 0, key_up, 0)
        user32.SetForegroundWindow(hwnd)
        user32.SetFocus(hwnd)
        time.sleep(0.8)
        if int(user32.GetForegroundWindow()) != hwnd:
            raise RuntimeError("微信窗口未能取得前台焦点，已停止自动化操作")
        self._active_window = window
        return window

    @staticmethod
    def _assert_foreground(window) -> None:
        hwnd = int(window._hWnd)
        if int(ctypes.windll.user32.GetForegroundWindow()) != hwnd:
            raise RuntimeError("微信窗口已失去前台焦点，已停止自动化操作")

    def _click_search(self, pyautogui) -> None:
        center = self._find_search_by_template(pyautogui)
        if center is None:
            window = self._active_window
            center = (
                int(window.left + 175),
                int(window.top + 68),
            )
        pyautogui.click(*center)
        time.sleep(0.7)

    def _find_search_by_template(self, pyautogui) -> tuple[int, int] | None:
        path = Path(self.config.search_template_path) if self.config.search_template_path else None
        if not path or not path.exists():
            return None
        try:
            import cv2
            import numpy as np
            from PIL import Image

            template = cv2.cvtColor(
                np.array(Image.open(path).convert("RGB")),
                cv2.COLOR_RGB2BGR,
            )
            screen = cv2.cvtColor(
                np.array(pyautogui.screenshot().convert("RGB")),
                cv2.COLOR_RGB2BGR,
            )
            result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
            _, max_value, _, max_location = cv2.minMaxLoc(result)
            if max_value < self.config.template_match_threshold:
                return None
            height, width = template.shape[:2]
            return (
                int(max_location[0] + width / 2),
                int(max_location[1] + height / 2),
            )
        except Exception:
            return None

    @staticmethod
    def _paste(pyautogui, pyperclip, text: str) -> None:
        pyperclip.copy(text)
        time.sleep(0.15)
        pyautogui.hotkey("ctrl", "v")

    def _click_input(self, pyautogui, window) -> None:
        x = int(window.left + window.width * self.config.input_x_ratio)
        y = int(window.top + window.height - self.config.input_bottom_offset)
        pyautogui.click(x, y)
        time.sleep(0.5)
        pyautogui.hotkey("ctrl", "a")
        time.sleep(0.1)
        pyautogui.press("backspace")
        time.sleep(0.2)

    def _click_target_result(self, pyautogui, window, expected: str) -> bool:
        """从搜索结果 OCR 中点击精确匹配项。"""
        try:
            from rapidocr_onnxruntime import RapidOCR

            left = max(0, int(window.left))
            top = max(0, int(window.top))
            width = int(window.width)
            height = int(window.height * 0.72)
            image = pyautogui.screenshot(region=(left, top, width, height))
            result, _ = RapidOCR()(image)
            candidates = []
            expected = expected.strip()
            for box, text, score in result or []:
                label = str(text).strip()
                if not label:
                    continue
                exact = label == expected
                contained = expected and (expected in label or label in expected)
                if not exact and not contained:
                    continue
                xs = [point[0] for point in box]
                ys = [point[1] for point in box]
                center_x = int(sum(xs) / 4) + left
                center_y = int(sum(ys) / 4) + top
                in_result_column = center_x < left + int(width * 0.35)
                below_header = center_y > top + 80
                if not in_result_column or not below_header:
                    continue
                candidates.append((0 if exact else 1, center_y, center_x, float(score)))
            if not candidates:
                return False
            candidates.sort()
            _, center_y, center_x, _ = candidates[0]
            pyautogui.click(center_x, center_y)
            return True
        except Exception:
            return False

    def _verify_target(self, pyautogui, window, expected: str) -> bool:
        if not self.config.verify_target_with_ocr:
            return self.config.allow_unverified_target
        try:
            from rapidocr_onnxruntime import RapidOCR

            left = max(0, int(window.left))
            top = int(window.top)
            width = int(window.width)
            height = max(80, int(window.height * 0.24))
            image = pyautogui.screenshot(region=(left, top, width, height))
            result, _ = RapidOCR()(image)
            texts = [str(text).strip() for _, text, _ in (result or []) if str(text).strip()]
            expected = expected.strip()
            search_open = any(
                keyword in text
                for text in texts
                for keyword in ("搜索网络结果", "包含：", "聊天记录")
            )
            title_found = bool(expected) and any(
                expected == text or expected in text or text in expected for text in texts
            )
            return title_found and not search_open
        except Exception:
            return self.config.allow_unverified_target
