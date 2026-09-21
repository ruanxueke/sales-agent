import sys
import time

import pyautogui
import pygetwindow
import pyperclip
import logging
logger = logging.getLogger(__name__)



def paste_text(text):
    pyperclip.copy(text)
    time.sleep(0.2)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.35)


def send_message(target, content):
    windows = pygetwindow.getWindowsWithTitle("微信")
    if not windows:
        raise RuntimeError("未找到微信窗口")
    win = windows[0]

    # 1. 打开微信
    try:
        win.restore()
    except Exception as e:
        logger.debug("send_message 异常已忽略: %s", e)
    try:
        win.activate()
    except Exception as e:
        logger.debug("send_message 异常已忽略: %s", e)
    time.sleep(1.5)

    # 2. 点击左上角搜索框
    pyautogui.click(win.left + 175, win.top + 68)
    time.sleep(0.8)

    # 3. 输入搜索目标
    paste_text(target)
    time.sleep(2.0)

    # 4. 打开对话
    pyautogui.press("enter")
    time.sleep(1.8)

    # 5. 用 Tab 尝试让焦点进入消息输入框
    pyautogui.click(win.left + int(win.width * 0.5), win.top + win.height - 55)
    time.sleep(0.8)

    # 6. 写入消息
    paste_text(content)
    time.sleep(0.6)

    # 7. 发送
    pyautogui.press("enter")
    time.sleep(1.5)

    print("SEND_COMMAND_FINISHED")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: python send_wechat_exact.py <target> <content>")
        sys.exit(1)
    send_message(sys.argv[1], sys.argv[2])
