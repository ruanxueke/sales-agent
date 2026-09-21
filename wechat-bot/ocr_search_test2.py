import ctypes
import time

import pyautogui
import pygetwindow
from rapidocr_onnxruntime import RapidOCR


def bring_to_foreground(win):
    hwnd = int(win._hWnd)
    user32 = ctypes.windll.user32
    user32.ShowWindow(hwnd, 3)
    user32.SetForegroundWindow(hwnd)
    user32.BringWindowToTop(hwnd)
    user32.SetFocus(hwnd)
    time.sleep(1.5)


def main():
    win = None
    for w in pygetwindow.getAllWindows():
        if w.title == "微信":
            win = w
            break
    if not win:
        print("NO_PERSONAL_WECHAT_WINDOW")
        return

    bring_to_foreground(win)

    out = r"C:\Users\1\Documents\销售客服智能体\docs\wechat_ocr_personal.png"
    pyautogui.screenshot(out)

    ocr = RapidOCR()
    result, _ = ocr(out)
    hits = []
    if result:
        for box, text, score in result:
            if any(k in str(text) for k in ["搜索", "搜", "测试客户", "微信"]):
                xs = [p[0] for p in box]
                ys = [p[1] for p in box]
                cx = int(sum(xs) / 4)
                cy = int(sum(ys) / 4)
                hits.append((text, cx, cy, round(float(score), 3)))

    print("OCR_HITS", len(hits))
    for h in hits:
        print(h)


if __name__ == "__main__":
    main()
