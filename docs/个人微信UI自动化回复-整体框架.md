# 个人微信 UI 自动化回复 · 整体框架

> 目标：基于现有 `wechat-info-capture` Skill 读取消息，使用 Windows UI 自动化完成个人微信回复。
> 边界：本框架只讨论技术链路，不接入未授权发送，不做批量群发。

---

## 1. 总体架构

```text
本地 Windows 电脑
├─ 微信 PC 客户端
│   ├─ 本地加密数据库
│   └─ 聊天窗口
│
├─ 微信消息读取 Skill
│   └─ wechat-info-capture / capture.py
│       ├─ unread：读取未读会话
│       ├─ sessions：读取最近会话
│       ├─ capture：读取指定群或联系人
│       └─ locate：定位群或联系人
│
├─ 个人微信 UI 回复服务
│   ├─ 消息轮询器
│   ├─ 消息清洗与去重
│   ├─ 白名单与路由策略
│   ├─ AI 回复决策器
│   ├─ UI 自动发送器
│   └─ 审计与状态记录
│
└─ 销售智能体后端
    ├─ 会话上下文
    ├─ 客户画像
    ├─ 知识库 RAG
    └─ 回复内容生成
```

---

## 2. 核心链路

```text
定时读取微信本地数据库
  ↓
拿到最新消息
  ↓
按白名单过滤目标联系人和目标群
  ↓
按消息 ID 或内容指纹去重
  ↓
交给销售智能体生成回复
  ↓
根据模式处理：
  ├─ 草稿模式：只填入输入框，不发送
  └─ 自动模式：填入后点击发送
  ↓
记录发送结果和审计日志
```

---

## 3. 模块职责

### 3.1 消息读取层

复用现有 Skill，不修改它的读取逻辑。

主要命令：

```bash
python capture.py unread
python capture.py sessions
python capture.py capture "群名或联系人" --hours 1
python capture.py locate "关键词"
```

输出字段：

```text
username, name, unread, time, summary, sender, text, is_self
```

### 3.2 消息清洗与路由层

职责：

- 过滤系统消息、公众号消息、群成员进出消息。
- 只处理白名单内的联系人、群、关键词。
- 区分单聊和群聊。
- 区分自己的消息和对方消息。
- 避免重复处理。

建议消息模型：

```python
{
  "message_id": "唯一消息指纹",
  "channel": "personal_wechat",
  "target_type": "contact | group",
  "target_name": "海青",
  "target_username": "wxid_xxx",
  "sender_name": "海青",
  "content": "客户消息内容",
  "created_at": 1730000000,
  "is_self": False
}
```

### 3.3 AI 回复决策层

复用现有 `sales_agent` 或 `core.agent`：

- 输入：消息内容、会话历史、客户画像、知识库检索结果。
- 输出：回复文本、是否转人工、是否停止自动回复、是否只生成草稿。

### 3.4 UI 自动发送层

这是新增的核心模块。

发送流程：

```text
1. 激活微信窗口
2. 打开搜索框
3. 输入 target_name
4. 等待搜索结果
5. 进入目标会话
6. 定位消息输入框
7. 通过剪贴板写入回复内容
8. 根据模式点击发送或等待人工确认
```

建议使用 Windows 原生 UI 自动化：

- `uiautomation`
- `pywinauto`
- `pyautogui`
- `pyperclip`

优先通过控件名和自动化树定位，不要只依赖固定坐标。

### 3.5 控制与安全层

必须包含：

- 默认关闭自动发送。
- 默认草稿模式。
- 白名单外不处理。
- 非目标群不处理。
- 关键词触发“人工、投诉、转人工”时停止。
- 每日、每小时、每分钟发送上限。
- 连续失败自动熔断。
- 每笔发送写审计。

---

## 4. 文件结构建议

```text
wechat_ui_bot/
├── config.json
├── wechat_reader.py        # 封装 capture.py
├── message_pipeline.py     # 清洗、去重、路由
├── reply_engine.py         # 调用销售智能体
├── ui_sender.py            # Windows UI 自动发送
├── supervisor.py           # 调度、轮询、风控
├── audit.py                # 本地审计
├── run.py                  # 启动入口
└── README.md
```

---

## 5. 伪代码

```python
import time

from wechat_reader import get_unread_messages
from message_pipeline import normalize_and_filter
from reply_engine import generate_reply
from ui_sender import send_message
from audit import write_audit
from config import TARGET_CONTACTS, TARGET_GROUPS, AUTO_SEND


def run_once():
    raw_messages = get_unread_messages()
    messages = normalize_and_filter(
        raw_messages,
        contacts=TARGET_CONTACTS,
        groups=TARGET_GROUPS,
    )

    for msg in messages:
        if should_stop(msg):
            write_audit("stop", msg)
            continue

        reply = generate_reply(msg)

        if AUTO_SEND:
            send_message(
                target=msg["target_name"],
                content=reply,
                mode="auto",
            )
        else:
            send_message(
                target=msg["target_name"],
                content=reply,
                mode="draft",
            )

        write_audit("replied", msg)


while True:
    run_once()
    time.sleep(10)
```

---

## 6. 草稿模式与自动模式

### 草稿模式，推荐先做

- 自动定位会话。
- 自动把回复粘贴到输入框。
- 不点击发送。
- 真人确认后再发送。

### 自动模式，后做

- 草稿模式跑稳后开放。
- 只对白名单联系人开启。
- 强制启用限流和审计。

---

## 7. 风控红线

- 不用于骚扰、群发、诈骗或未经授权的监控。
- 只处理用户本人账号和本人授权业务。
- 微信 PC 客户端必须保持登录和前台可操作。
- 微信升级后 UI 自动化控件可能变化，需要重新验证。
- 所有敏感信息本地处理，不上传聊天原文到外部服务。

---

## 8. 实施顺序

```text
P0：
1. 读取消息
2. 白名单过滤
3. 草稿模式发送
4. 本地审计

P1：
5. AI 自动回复
6. 自动模式
7. 转人工和熔断

P2：
8. 多账号管理
9. 定时任务
10. 与中台视觉执行器合并
```

---

## 9. 与现有项目的关系

现有 `vision_agent` 已经有“截图识别 + 模拟发送”的雏形。这个框架不是替换它，而是把它和 `wechat-info-capture` Skill 结合：

- `wechat-info-capture`：负责快速、低成本读取消息。
- `vision_agent`：负责可靠定位和模拟发送。
- `core.reply_dispatcher`：负责统一回复调度和审计。
