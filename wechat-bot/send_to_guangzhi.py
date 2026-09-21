import ctypes
import time

import pyautogui
import pygetwindow
import pyperclip


def bring_personal_wechat():
    win = None
    for w in pygetwindow.getAllWindows():
        if w.title == "微信":
            win = w
            break
    if not win:
        raise RuntimeError("NO_PERSONAL_WECHAT")
    hwnd = int(win._hWnd)
    u = ctypes.windll.user32
    u.ShowWindow(hwnd, 3)
    u.BringWindowToTop(hwnd)
    u.SetForegroundWindow(hwnd)
    u.SetFocus(hwnd)
    time.sleep(1.2)
    return win


def main():
    win = bring_personal_wechat()

    # 测试客户会话已打开，输入框位于发送按钮左侧
    pyautogui.click(1200, 1000)
    time.sleep(0.7)

    pyperclip.copy("你好")
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.6)

    pyautogui.press("enter")
    time.sleep(1.5)

    print("SENT_TO_GUANGZHI")


if __name__ == "__main__":
    main()
