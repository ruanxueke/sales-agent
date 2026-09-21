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


def paste_text(text):
    pyperclip.copy(text)
    time.sleep(0.2)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.35)


def send_to_file_transfer_helper():
    activate_wechat()

    # 打开微信搜索
    win = pygetwindow.getWindowsWithTitle("微信")[0]
    pyautogui.click(win.left + 200, win.top + 70)
    time.sleep(1.0)

    # 搜索文件传输助手
    paste_text("文件传输助手")
    time.sleep(1.2)

    # 进入会话
    pyautogui.press("enter")
    time.sleep(1.2)

    # 微信 4.x 搜索后焦点可能仍在搜索框，点击窗口底部输入区域
    win = pygetwindow.getWindowsWithTitle("微信")[0]
    click_x = win.left + int(win.width * 0.5)
    click_y = win.top + win.height - 90
    pyautogui.click(click_x, click_y)
    time.sleep(0.8)

    # 写入测试消息
    paste_text("这是销售智能体自动回复测试")
    time.sleep(0.5)

    # 发送
    pyautogui.press("enter")
    time.sleep(1.5)

    print("SENT_OK")


if __name__ == "__main__":
    send_to_file_transfer_helper()
