# 本地 UI 自动发送器 · 实施方式

> 适用对象：Windows 微信 PC 版 + 个人微信。
> 目标：根据中台下发的回复内容，自动激活微信、搜索会话、写入回复、发送。
> 原则：优先控件定位，不依赖固定坐标；先草稿，后自动；所有发送可审计。

---

## 1. 核心状态机

```text
IDLE
  ↓
LOCATE_WINDOW    激活微信窗口
  ↓
OPEN_SEARCH      打开微信搜索
  ↓
SEARCH_TARGET    输入联系人或群名称
  ↓
SELECT_CHAT      选中目标会话
  ↓
FILL_DRAFT       把回复粘贴到输入框
  ↓
SEND             点击发送或等待人工
  ↓
VERIFY           检查发送结果
  ↓
DONE / ERROR
```

---

## 2. 第一步：激活微信窗口

### 2.1 查找窗口

优先按进程名或窗口标题查找。

```python
import pygetwindow as gw

windows = gw.getWindowsWithTitle("微信")
if windows:
    win = windows[0]
    win.restore()
    win.activate()
```

也可以使用 Win32：

```python
import win32gui
import win32con

hwnd = win32gui.FindWindow(None, "微信")
if hwnd:
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    win32gui.SetForegroundWindow(hwnd)
```

### 2.2 注意事项

- 微信可能最小化到托盘，需要先 `restore`。
- `SetForegroundWindow` 有时会被 Windows 限制，可以临时按一次 Alt 再尝试。
- 激活后要短暂等待窗口绘制完成。

---

## 3. 第二步：打开搜索

优先使用键盘快捷键，兼容性比固定坐标好。

微信通常支持：

```text
Ctrl + F
```

实现：

```python
import pyautogui

pyautogui.hotkey("ctrl", "f")
time.sleep(0.5)
```

也可以使用 UI Automation 找到搜索框：

```text
ControlType = Edit
Name = 搜索
```

---

## 4. 第三步：搜索目标会话

不要直接点击坐标，建议通过剪贴板输入搜索词。

```python
import pyperclip

def type_text(text):
    pyperclip.copy(text)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.3)
```

这样能避免中文输入法切换问题。

---

## 5. 第四步：选择正确会话

搜索后可能返回多个结果。规则：

1. 优先精确匹配备注名。
2. 再匹配昵称。
3. 最后匹配 `username`。

如果存在多个候选，草稿模式下必须暂停，等人工确认，不能自动选第一个。

---

## 6. 第五步：定位消息输入框

优先通过 UI Automation 找输入控件。

常见策略：

```text
- 找窗口底部的 Edit 控件
- 找可输入文本的 ControlType.Edit
- 排除搜索框
```

实现示例：

```python
import uiautomation as auto

wechat = auto.WindowControl(searchDepth=1, Name="微信")
edits = wechat.EditControl()
for edit in edits:
    print(edit.Name, edit.AutomationId, edit.BoundingRectangle)
```

调试时先打印所有 `EditControl` 的：

- `Name`
- `AutomationId`
- `ClassName`
- 坐标

找到稳定的 `AutomationId` 后写进配置，不写死屏幕坐标。

---

## 7. 第六步：写入回复

使用剪贴板粘贴，避免输入法问题。

```python
def fill_draft(content):
    pyperclip.copy(content)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.4)
```

---

## 8. 第七步：草稿模式与自动模式

### 草稿模式

```text
只写入输入框，不发送，等待真人确认。
```

### 自动模式

```python
pyautogui.press("enter")
```

或者点击“发送”按钮。

建议自动模式前，先通过草稿模式连续验证 30 到 50 次，没有误发后再开放。

---

## 9. 第八步：发送结果验证

发送后不能只看“点击了按钮”，要验证是否真的发出。

方式：

1. 再次用 `wechat-info-capture` 读取该会话。
2. 检查最新一条消息是否为自己发送的内容。
3. 超时未读到，标记失败。

```text
发送后 3 秒
  ↓
capture.py capture "目标会话" --hours 1
  ↓
检查最后一条消息
```

---

## 10. 建议代码结构

```text
ui_sender/
├── config.json
├── window_controller.py      # 激活微信
├── search_controller.py      # 搜索和选中会话
├── editor_controller.py      # 定位输入框、写入
├── send_controller.py        # 草稿 / 自动发送
├── verify_controller.py      # 验证发送结果
├── sender.py                 # 对外统一入口
└── README.md
```

统一入口示例：

```python
def send_wechat_reply(
    target: str,
    content: str,
    mode: str = "draft",
):
    activate_wechat()
    open_search()
    type_text(target)
    select_target(target)
    fill_draft(content)
    if mode == "auto":
        press_send()
    verify_result(target, content)
```

---

## 11. 错误处理

| 问题 | 处理方式 |
|---|---|
| 找不到微信窗口 | 提示用户登录微信并保持运行 |
| 搜索不到会话 | 停止发送，记录错误 |
| 多个搜索结果 | 草稿模式暂停，等人工确认 |
| 输入框定位失败 | 切换到备用坐标，只对当前版本临时使用 |
| 发送失败 | 不自动重试，进入人工处理 |
| 微信被遮挡 | 先最小化其他窗口，再重新激活微信 |
| 连续失败 3 次 | 自动熔断，停止当前任务 |

---

## 12. 安全要求

- 默认草稿模式。
- 自动模式只对白名单联系人开放。
- 每次发送记录：目标、内容、时间、模式、结果。
- 敏感关键词触发转人工。
- 不进行批量群发。
- 微信版本升级后，先重新运行 UI 控件调试脚本。

---

## 13. 技术依赖

推荐使用：

```text
uiautomation
pywinauto
pygetwindow
pyautogui
pyperclip
```

可选：

```text
pywin32
pillow  # 截图调试
```

---

## 14. 调试顺序

```text
1. 打印微信窗口标题
2. 打印所有 EditControl
3. 自动激活微信
4. 自动打开搜索
5. 自动输入一个联系人名
6. 自动选中该联系人
7. 自动粘贴草稿，不发送
8. 自动发送一条测试消息给文件传输助手
```

每完成一步，再进入下一步，不要一开始就全自动发送。
