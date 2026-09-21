# 中台桌面版（正式版框架）

基于 Electron 的 Windows 桌面客户端：登录后进入本租户中台，内置视觉执行器开关。

## 开发运行

```powershell
cd C:\Users\1\Documents\销售客服智能体\desktop-client
npm install
npm start
```

## 冒烟测试（无界面自动退出）

```powershell
npm run smoke
```

看到 `SMOKE_OK` 表示主进程、页面加载正常。

## 打包 exe

```powershell
npm run build
```

生成：`desktop-client\dist\SalesAgentConsole Setup.exe`

## 说明

- 登录使用中台 API Key，Key 用系统安全存储加密保存在本地。
- 所有数据请求都走服务端 API，服务端按租户隔离。
- 视觉执行器开关由主进程启动/停止隐藏的 Python 进程，无黑框。
- 配置在 `vision_agent_config.json`。
