# 个人微信群聊客服 · 独立模块

## 这是什么

把个人微信客服从主系统中独立出来，单独跑成一个群聊客服机器人：

- 只在你指定的一个群聊里回复
- 默认只有 @ 机器人 才回复，不会打扰群内其他聊天
- 私聊默认不回复，避免骚扰用户

## 配置群聊

编辑 `wechat-bot/bot-config.json`：

```json
{
  "target_room": "你的目标群名称",
  "require_mention": true,
  "personal_auto_reply": false,
  "welcome_on_join": true,
  "welcome_message": "欢迎加入 Work Buddy 降本增效实操群。\n本群聚焦降本增效落地实践，借助 AI 工具优化人力、营销、客服及流程成本。"
}
```

| 配置项 | 说明 |
|---|---|
| `target_room` | 群聊名称，必须和微信里的群名完全一致 |
| `require_mention` | `true` 只在 @ 机器人 时回复；`false` 群里所有文本都回复 |
| `personal_auto_reply` | `true` 私聊也自动回复；`false` 私聊不回复 |
| `welcome_on_join` | `true` 目标群新人入群自动发送欢迎语；`false` 关闭 |
| `welcome_message` | 欢迎语内容，支持用 `\n` 换行 |

## 启动

1. 确保这台电脑已经登录微信电脑版/微信本体可扫码
2. 编辑 `start_group_bot.bat`，把 `AI_API_URL` 改成你的中台地址，例如：

```bat
set AI_API_URL=https://your-domain.example/api/v1/chat
```

3. 双击 `start_group_bot.bat`
4. 首次运行会生成二维码，扫码登录
5. 登录后机器人会在启动日志里列出所有群，并确认是否能找到目标群

## 行为规则

- 非目标群消息：直接忽略
- 目标群内非 @ 消息：忽略（`require_mention=true` 时）
- 目标群内 @ 机器人：自动回复，回复前有自然延迟
- 每个发言人在群里有独立上下文，不会互相串记忆
- 语音/图片消息会转交 AI 处理，文字回复
- 目标群新人入群：自动发送欢迎语（`welcome_on_join=true` 时）

## 常见问题

- 找不到目标群：检查群名是否和微信显示完全一致（包括符号和空格）
- 回复没反应：看启动窗口日志，确认机器人已登录且 `[Bot] 群同步完成`
- 私聊也回复了：把 `personal_auto_reply` 改为 `false` 并重启
