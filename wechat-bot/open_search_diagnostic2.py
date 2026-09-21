import ctypes
import time

import pyautogui
import pygetwindow
import pyperclip


def bring_to_foreground(win):
    hwnd = int(win._hWnd)
    user32 = ctypes.windll.user32
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    user32.SetFocus(hwnd)
    time.sleep(1.8)


def main():
    wins = pygetwindow.getWindowsWithTitle("微信")
    if not wins:
        print("NO_WECHAT_WINDOW")
        return
    win = wins[0]
    win.restore()
    win.moveTo(0, 0)
    win.resizeTo(1000, 700)
    bring_to_foreground(win)

    # 激活后再点击微信窗口中心，确保前台
    pyautogui.click(win.left + 500, win.top + 300)
    time.sleep(0.8)
    bring_to_foreground(win)

    # 点击左上角搜索框
    pyautogui.click(win.left + 90, win.top + 68)
    time.sleep(1.0)

    pyperclip.copy("测试客户")
    pyautogui.hotkey("ctrl", "v")
    time.sleep(2.0)

    out = r"C:\Users\1\Documents\销售客服智能体\docs\wechat_search_guangzhi_v2.png"
    pyautogui.screenshot(out)
    print("SCREENSHOT_SAVED", out)
    print("WINDOW_RECT", win.left, win.top, win.width, win.height)


if __name__ == "__main__":
    main()
