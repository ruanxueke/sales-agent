# 个人微信桥接

该模块把本机微信消息读取、销售智能体中台和微信 PC UI 草稿连接起来。

## 当前安全默认值

- 只处理配置文件中的白名单联系人。
- 默认 `dry_run=true`，只预览中台回复，不操作微信输入框。
- 自动发送默认关闭。
- 图片、语音等媒体占位符默认跳过。
- 同一消息和中台任务分别做本地去重。
- 每次运行结果写入 `wechat_bridge/data/audit.jsonl`。

## 启动前

1. 微信 PC 客户端保持登录。
2. 确保 `capture.py doctor` 已显示目标微信账号完成解密。
3. 启动销售智能体 API，默认地址为 `http://127.0.0.1:5000`。
4. 安装依赖：

```powershell
python -m pip install -r wechat_bridge\requirements.txt
```

## 配置

编辑 `wechat_bridge/config.json`：

- `account_id`：本机微信账号目录名。
- `targets`：联系人或群聊白名单。
- `target_username`：从 `capture.py locate` 获取的精确 ID。
- `mode`：`off`、`draft`、`auto` 或 `manual`。
- `self_names`：机器人账号自己的显示名，防止把自己的消息当成客户消息。
- `search_template_path`：微信搜索图标截图模板。

默认只允许草稿模式。全自动模式还要求全局 `auto_send_enabled=true`，当前保持关闭。

## 使用

只检查环境：

```powershell
python -m wechat_bridge.run --check
```

演练一次：

```powershell
python -m wechat_bridge.run --once
```

允许写入微信草稿：

```powershell
python -m wechat_bridge.run --once --live-draft
```

持续运行：

```powershell
start_wechat_bridge.bat
```

自动回复白名单客户：

```powershell
start_wechat_auto_reply.bat
```

自动启动本地中台并持续自动回复：

```powershell
start_local_auto_reply.bat
```

写入草稿并持续运行：

```powershell
start_wechat_bridge_live_draft.bat
```

## 数据文件

- `wechat_bridge/data/state.json`：本地消息和任务去重状态。
- `wechat_bridge/data/audit.jsonl`：本地操作审计。

这两个运行时文件不应提交到版本库。

## 自动接待链路

当前运行配置统一为专用微信账号模式：

- 账号自动选择当前活跃且已解密的微信账号
- 私聊客户自动识别，不维护联系人白名单
- 模式：自动回复
- 首次启动会先建立历史基线，不回复启动前已经存在的老消息。
- 后续读取到新消息后，会先发送 Windows 提醒，再同步中台。
- 中台生成回复后，本地发送器自动回发，并回读微信数据库确认发送成功。
- 客户展示名称使用微信昵称，不使用备注名或 `wxid`。

## 专用客户微信账号

正式启用时如果使用一个全新的微信账号，并且该账号只添加客户，可以直接使用：

- 配置模板：`config.dedicated-account.example.json`
- `auto_discover_contacts=true`
- `default_contact_mode=auto`
- `targets=[]`
- 客户档案只展示微信昵称，不把备注名或 `wxid` 当成客户名称。

该模式会自动处理所有私聊客户，不再维护联系人白名单，同时跳过：

- 群聊
- 公众号
- 文件传输助手
- 系统通知
- 其他配置的排除账号
