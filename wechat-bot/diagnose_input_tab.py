import ctypes
import time

import pyautogui
import pygetwindow
import pyperclip
from rapidocr_onnxruntime import RapidOCR


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
    time.sleep(1.0)
    return win


def main():
    bring_personal_wechat()

    # 尝试用 Tab 将焦点移到输入框
    pyautogui.press("tab")
    time.sleep(0.8)

    pyperclip.copy("你好")
    pyautogui.hotkey("ctrl", "v")
    time.sleep(1.2)

    out = r"C:\Users\1\Documents\销售客服智能体\docs\wechat_input_tab.png"
    pyautogui.screenshot(out)

    ocr = RapidOCR()
    result, _ = ocr(out)
    hits = []
    if result:
        for box, text, score in result:
            if any(k in str(text) for k in ["你好", "发送", "输入", "消息"]):
                xs = [p[0] for p in box]
                ys = [p[1] for p in box]
                hits.append((str(text), int(sum(xs) / 4), int(sum(ys) / 4), round(float(score), 3)))
    print("OCR_HITS", hits)


if __name__ == "__main__":
    main()
