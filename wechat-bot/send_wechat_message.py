import sys
import time

import pyautogui
import pygetwindow
import pyperclip
import logging
logger = logging.getLogger(__name__)



def activate_wechat():
    windows = pygetwindow.getWindowsWithTitle("微信")
    if not windows:
        raise RuntimeError("未找到微信窗口")
    win = windows[0]
    try:
        win.restore()
    except Exception as e:
        logger.debug("activate_wechat 异常已忽略: %s", e)
    try:
        win.activate()
    except Exception as e:
        logger.debug("activate_wechat 异常已忽略: %s", e)
    time.sleep(1.2)
    return win


def paste_text(text):
    pyperclip.copy(text)
    time.sleep(0.2)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.35)


def send_message(target, content):
    win = activate_wechat()

    # 点击顶部搜索框区域
    pyautogui.click(win.left + 205, win.top + 72)
    time.sleep(0.8)

    # 输入目标会话
    paste_text(target)
    time.sleep(1.6)

    # 选中第一个搜索结果并进入会话
    pyautogui.press("enter")
    time.sleep(1.4)

    # 点击消息输入框区域
    pyautogui.click(win.left + int(win.width * 0.5), win.top + win.height - 55)
    time.sleep(0.7)

    # 写入消息并发送
    paste_text(content)
    time.sleep(0.5)
    pyautogui.press("enter")
    time.sleep(1.5)

    print("SEND_COMMAND_FINISHED")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: python send_wechat_message.py <target> <content>")
        sys.exit(1)
    send_message(sys.argv[1], sys.argv[2])
