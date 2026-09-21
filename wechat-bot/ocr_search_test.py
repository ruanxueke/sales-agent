import ctypes
import time

import pyautogui
import pygetwindow
from rapidocr_onnxruntime import RapidOCR


def bring_to_foreground(win):
    hwnd = int(win._hWnd)
    user32 = ctypes.windll.user32
    user32.ShowWindow(hwnd, 9)
    user32.SetForegroundWindow(hwnd)
    user32.SetFocus(hwnd)
    time.sleep(1.5)


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
    pyautogui.click(win.left + 500, win.top + 300)
    time.sleep(0.5)
    bring_to_foreground(win)

    out = r"C:\Users\1\Documents\销售客服智能体\docs\wechat_ocr_source.png"
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
