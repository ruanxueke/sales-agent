"""Windows 新消息提醒。"""
from __future__ import annotations

import base64
import ctypes
import logging
import os
import subprocess
from html import escape

logger = logging.getLogger(__name__)


def _xml_text(value: str) -> str:
    return escape(str(value or ""), quote=False)


class DesktopNotifier:
    def __init__(self, enabled: bool = True, sound: bool = True):
        self.enabled = enabled
        self.sound = sound

    def notify(self, title: str, message: str) -> None:
        if not self.enabled:
            return
        if self.sound:
            self._beep()
        if os.name != "nt":
            return
        try:
            script = f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml('<toast><visual><binding template="ToastGeneric"><text>{_xml_text(title)}</text><text>{_xml_text(message)}</text></binding></visual></toast>')
$toast = New-Object Windows.UI.Notifications.ToastNotification $xml
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Sales Agent').Show($toast)
"""
            encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
            subprocess.Popen(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-WindowStyle",
                    "Hidden",
                    "-EncodedCommand",
                    encoded,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception as exc:
            logger.warning("Windows 通知发送失败: %s", exc)

    @staticmethod
    def _beep() -> None:
        try:
            ctypes.windll.user32.MessageBeep(0x00000040)
        except Exception as e:
            logger.debug("DesktopNotifier._beep 异常已忽略: %s", e)
