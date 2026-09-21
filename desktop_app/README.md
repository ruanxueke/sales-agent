# 中台桌面版（.exe）

## 是什么

这是把“中台”和“视觉执行器”合并成的一个 Windows 桌面应用：

- 打开应用就是中台，需要登录（API Key）才能使用
- 登录后可以选择是否启用“视觉执行器”
- 启用后，在已经登录的企业微信/个人微信 PC 客户端上自动回复
- 关闭开关立即停止，服务器仍可单独暂停/恢复
- 服务端保留 API Key 鉴权和 IP 隔离，形成闭环

## 本地运行

```powershell
pip install -r desktop_app\requirements.txt
python desktop_app\main.py
```

## 打包成 exe

```powershell
powershell -ExecutionPolicy Bypass -File desktop_app\build_exe.ps1
```

生成文件：`dist\SalesAgentConsole.exe`

## 使用

1. 打开 `SalesAgentConsole.exe`
2. 在左侧登录框输入中台 API Key，点“保存并登录”
3. 中台正常打开后，点右上角“视觉执行器桌面控制”
4. 打开开关，确认状态变为“运行中”
5. 关闭开关即停止自动回复

## 日志

- 桌面应用日志：`vision_agent_data\desktop_app.log`
- 视觉执行器日志：`vision_agent_data\vision_agent_worker.log`

## 配置

`vision_agent_config.json` 里可改：

- `VISION_AGENT_API_BASE`：中台地址
- `VISION_AGENT_MODE`：`wecom` / `wechat`
- `VISION_AGENT_INSTANCE_ID`：每台电脑唯一
- `VISION_DEBUG_NO_SEND`：`1` 演练 / `0` 正式
- `VISION_IGNORE_CONTACTS`：不处理的联系人
