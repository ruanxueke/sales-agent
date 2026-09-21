import sys
import uiautomation as auto


def dump_control(control, depth=0, max_depth=4):
    if depth > max_depth:
        return
    indent = "  " * depth
    try:
        name = control.Name or ""
        ctype = control.ControlTypeName or ""
        class_name = control.ClassName or ""
        automation_id = control.AutomationId or ""
    except Exception:
        return
    if ctype or name:
        print(f"{indent}[{ctype}] name={name!r} id={automation_id!r} class={class_name!r}")
    try:
        children = control.GetChildren()
    except Exception:
        children = []
    for child in children:
        dump_control(child, depth + 1, max_depth)


def main():
    root = auto.GetRootControl()
    wx = None
    for c in root.GetChildren():
        title = c.Name or ""
        if "微信" in title or "Weixin" in str(c.ClassName or ""):
            wx = c
            break
    if not wx:
        print("NO_WECHAT_WINDOW")
        return
    print("WECHAT_WINDOW", wx.Name, wx.ClassName)
    dump_control(wx, 0, 6)


if __name__ == "__main__":
    main()
