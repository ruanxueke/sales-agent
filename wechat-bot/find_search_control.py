import uiautomation as auto
import pygetwindow as gw
import logging
logger = logging.getLogger(__name__)



def main():
    wins = gw.getWindowsWithTitle("微信")
    if not wins:
        print("NO_WECHAT_WINDOW")
        return
    win = wins[0]
    control = auto.ControlFromHandle(int(win._hWnd))
    hits = []

    def walk(ctl, depth=0):
        if depth > 8:
            return
        try:
            name = ctl.Name or ""
            if "搜索" in name or "搜" in name:
                hits.append((depth, ctl.ControlTypeName, name, str(ctl.BoundingRectangle)))
        except Exception as e:
            logger.debug("main.walk 异常已忽略: %s", e)
        try:
            children = ctl.GetChildren()
        except Exception:
            children = []
        for child in children:
            walk(child, depth + 1)

    walk(control)
    print("HITS", len(hits))
    for h in hits[:80]:
        print(h)


if __name__ == "__main__":
    main()
