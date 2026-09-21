import time

import pyautogui
import pygetwindow
import pyperclip


def main():
    wins = pygetwindow.getWindowsWithTitle("微信")
    if not wins:
        print("NO_WECHAT_WINDOW")
        return
    win = wins[0]
    win.restore()
    win.moveTo(0, 0)
    win.resizeTo(1000, 700)
    win.activate()
    time.sleep(1.5)

    # 点击左上角搜索框
    pyautogui.click(win.left + 175, win.top + 68)
    time.sleep(0.8)

    pyperclip.copy("测试客户")
    pyautogui.hotkey("ctrl", "v")
    time.sleep(2.2)

    out = r"C:\Users\1\Documents\销售客服智能体\docs\wechat_search_guangzhi.png"
    pyautogui.screenshot(out)
    print("SCREENSHOT_SAVED", out)
    print("WINDOW_RECT", win.left, win.top, win.width, win.height)


if __name__ == "__main__":
    main()
