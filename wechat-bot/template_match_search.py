import ctypes
import time

import cv2
import numpy as np
import pyautogui
import pygetwindow
from PIL import Image


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
    time.sleep(1.5)
    return win


def main():
    win = bring_personal_wechat()
    template_path = r"C:\Users\1\Desktop\赵老师照片\微信图片_20260909171436_161_30.png"
    template = cv2.cvtColor(np.array(Image.open(template_path).convert("RGB")), cv2.COLOR_RGB2BGR)
    screen = cv2.cvtColor(np.array(pyautogui.screenshot().convert("RGB")), cv2.COLOR_RGB2BGR)

    result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

    h, w = template.shape[:2]
    center = (int(max_loc[0] + w / 2), int(max_loc[1] + h / 2))
    print("MATCH_SCORE", round(float(max_val), 4))
    print("MATCH_CENTER", center)
    print("WINDOW_RECT", win.left, win.top, win.width, win.height)


if __name__ == "__main__":
    main()
