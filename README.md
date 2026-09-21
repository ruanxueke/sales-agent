# 销售客服智能体

基于 LangChain + RAG + ChromaDB + DeepSeek V4 Flash 的销售客服系统，接入个人微信。

> 项目状态：开发中。接口、数据结构和部署方式仍可能变化。

开源许可证：Apache-2.0。第三方归属见 `NOTICE` 与 `THIRD_PARTY_NOTICES.md`。

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 填写 DeepSeek API Key
```

### 3. 测试运行（控制台模式）

```bash
python main.py --channel console
```

### 4. 微信模式

```bash
cd wechat-bot
npm start
# 终端会显示二维码链接；用客服微信扫码后，机器人开始监听消息
```

### 5. 公众号模式

1. 在公众号后台开启服务器配置，URL 填 `http(s)://你的域名/wechat`。
2. 在 `.env` 中填写 `WECHAT_OFFICIAL_APP_ID`、`WECHAT_OFFICIAL_APP_SECRET`、`WECHAT_OFFICIAL_TOKEN`、`WECHAT_OFFICIAL_ENCODING_AES_KEY`。
3. 启动公众号服务：

```bash
python main.py --channel official
```

默认使用异步客服消息回复，避免微信 5 秒被动回复超时；需要在公众号后台配置服务器 IP 白名单。

## 发布前质量门

改动较大或发布之前，先跑一遍质量门；任何一项失败都会以非 0 退出，可直接接到 CI 或发布脚本里。

```bash
pip install -r requirements-dev.txt      # 仅开发机需要，生产镜像不装
python scripts/quality_gate.py           # 结构检查 + 自测脚本回归 + pytest
python scripts/quality_gate.py --only migrations   # 只跑某一项
python scripts/quality_gate.py --skip-tests        # 跳过自测脚本回归
```

三项结构检查（都是"改坏了就很难靠人眼发现"的那类问题）：

| 检查 | 抓什么 |
|---|---|
| import | 逐个导入全部一方模块（182 个）：语法错误、导入期副作用炸掉、`logger` 未定义这类只在 import 时才暴露的问题 |
| 乱码 | U+FFFD 替换字符、非法 UTF-8 编码，以及"整条字符串字面量只剩问号"的占位残留（会跳过 SQL 的 `?` 占位符，避免误报） |
| 迁移 | 迁移链必须单头线性；全新空库 `upgrade head` 后建出的表/列必须与 ORM 元数据**完全一致**；`deploy/migrate.sh` 里 stamp 的 revision 必须真实存在 |

> 迁移那一项是重点：历史上 `create_all` 和 alembic 各自维护过一套结构，导致"新加的字段在线上静默不生效"。这条检查就是为了在门口拦住它。

`tests/` 下的脚本是可直接 `python tests/xxx.py` 运行的自测（按退出码判定），
`scripts/quality_gate.py` 会用独立的临时 SQLite 库逐个跑；`pytest` 只收集真正的
`test_*` 用例，两者的分工写在 `pytest.ini` 注释里。

## 服务稳定性

- 双击 `start_services.bat` 可一次性启动并监控 AI 服务（5000/5002）和微信机器人，进程退出后 5 秒自动重启。
- 机器人默认对目标群全部文字、语音自动回复；恢复“仅 @回复”时设置 `REQUIRE_MENTION=true`。
- AI 服务日志写入 `api_server.log`，机器人日志写入 `wechat-bot/bot-runtime.log`。

## 并发与高可用

- AI 回复走有界线程池（8 个并发 worker + 200 任务队列），高并发时排队处理，队列满则提示“稍后再试”。
- 对话链路已接入限流（默认每用户 60 秒 10 次）和语义缓存（相同问题+相同客户画像直接复用回复）。
- 客户档案支持 Redis 后端：在 `.env` 配置 `REDIS_URL` 后自动切换，适合多实例部署；未配置时仍用 SQLite。
- 微信机器人单号受微信协议限制，本身不适合高并发；公众号/企业微信才适合规模化承接。

## 企业级数据层（可切换）

- 数据库：默认 SQLite；在 `.env` 配置 `DATABASE_URL` 后自动切换 SQLAlchemy 后端，支持 PostgreSQL / MySQL。
  - 示例：`postgresql://user:pass@host:5432/sales`、`mysql+pymysql://user:pass@host:3306/sales`
- 迁移：项目内置 Alembic，改表结构用 `bash deploy/migrate.sh`（发布流程已自动接入，见文末「数据库迁移」）。
- 对象存储：默认本地 `data/uploads/`；配置 `OBJECT_STORAGE_PROVIDER=s3` 或 `cos` 及 Bucket/Endpoint/Key 后切换 COS/S3。
- 运行状态：Redis 已在代码层支持（会话、缓存、限流、CRM），配置 `REDIS_URL` 后生效。

## Celery 异步队列（按需启用）

- 现阶段聊天主链路保持“有界线程池 + 同步回复”，不启用 Celery。
- 当出现以下情况再启用：多实例部署、流量上涨导致线程池排队、后台任务（通知/语音/报表）积压。
- 启用步骤：
  1. `.env` 配置 `REDIS_URL`。
  2. 启动 worker：`python -m celery -A core.queue worker --loglevel=info`。
  3. 把通知、语音转写、报表生成改为提交 Celery 任务；聊天主链路保持同步。
- `start_services.ps1` 里预留了 Celery Worker 的启动项，配置好 Redis 后取消注释即可。

## 项目结构

```
sales_agent/
├── config/settings.py      # 全局配置
├── core/
│   ├── llm.py              # DeepSeek 接入
│   ├── vector_store.py     # ChromaDB 向量库
│   ├── rag.py              # RAG 检索增强
│   ├── agent.py            # Agent 对话逻辑
│   └── memory.py           # 对话记忆
├── connectors/
│   └── wechat.py           # 微信连接器
├── knowledge/
│   └── knowledge_manager.py # 知识库管理
├── utils/
│   └── text_processor.py   # 文本工具
├── data/knowledge_base/    # 知识文档存放（待填充）
├── vector_store/chroma_db/ # 向量库持久化
└── main.py                 # 主入口
```

## 知识库

将产品文档放入 `data/knowledge_base/` 目录，支持 txt、md、csv 格式。
然后执行以下命令导入向量库：

```bash
python -c "from knowledge.knowledge_manager import KnowledgeManager; KnowledgeManager().import_from_directory()"
```

## 销售全链路（第一阶段）

- 客户档案：每次对话自动写入 `data/customers.db`（SQLite），记录姓名、电话、身份、基础、目标、预算、兴趣课程、当前阶段。
- 留存门槛：客户达到 `L3 意向明确` 后才建档留存；L1/L2 只参与对话，不写入客户库。
- 销售阶段：`new → understanding → recommended → high_intent → enrolled` 等，根据客户消息自动推进并记录变更。
- 意向等级：自动归一成 5 层：`L1 陌生/观望 → L2 兴趣了解 → L3 意向明确 → L4 高意向 → L5 已报名/已成交`。
- 销售线索通知：客户首次达到 L3 时，自动生成“客户信息 + 最近聊天记录”的通知，接收人先在 `.env` 的 `SALES_NOTIFY_TARGET` 留位置。
- 查看客户档案：
  - 单个客户：`GET http://127.0.0.1:5002/api/v1/customer/{session_id}`
  - 客户列表：`GET http://127.0.0.1:5002/api/v1/customers`
  - 通知列表：`GET http://127.0.0.1:5002/api/v1/notifications`

## 销售线索中台（方案A）

- 统一线索模型：线索与客户分离，沉淀姓名、手机号、微信号、unionid、来源渠道、广告位/活码ID、意向、阶段、归属人、下次跟进等字段。
- 批量导入：支持 CSV / Excel，自动按手机号、微信号、unionid、客户ID 去重；重复导入更新，缺失联系方式的错误行单独返回。
- 公海池：未认领线索在公海；默认 `3 天` 未跟进自动退回公海（可用 `LEAD_RECYCLE_AFTER_DAYS` 调整）。
- 自动分配：新线索、公众号关注/扫码、L3 客户建档时自动分配给 `叙白`（可用 `LEAD_DEFAULT_OWNER` 调整）。
- 公众号接入：关注/扫码事件自动沉淀线索，带参二维码的 `qrscene_xxx` 自动写入渠道位。
- 数据看板：`http://127.0.0.1:5000/static/dashboard.html` 的「线索管理」页支持导入、查询、认领、跟进、成交、流失和公海回收。
- 线索接口：
  - `GET /api/v1/leads`：线索列表（支持 status/owner/source/keyword）
  - `GET /api/v1/leads/ocean`：公海
  - `GET /api/v1/leads/stats`：线索统计
  - `GET /api/v1/leads/import/template`：下载导入模板
  - `POST /api/v1/leads/import`：批量导入
  - `POST /api/v1/leads`：手动建线索
  - `POST /api/v1/leads/{id}/claim`：认领
  - `POST /api/v1/leads/{id}/follow`：跟进
  - `POST /api/v1/leads/{id}/status`：成交/流失
  - `POST /api/v1/leads/recycle`：执行公海回收

## 企业级能力增强

- 接口安全：`/api/v1/*` 支持 API Key 鉴权与管理员权限，敏感操作写审计日志。
- 消息幂等：微信/公众号按 MsgId 去重，避免重复回复和重复建档。
- 定时任务：后台每 60 秒自动执行公海回收、自动跟进派发、每日质检扫描。
- 自动跟进：线索/客户可生成 1h/1d/3d/7d 跟进计划，到期通过公众号或微信机器人主动触达。
- 转人工：客户要求人工时自动生成接管请求并通知叙白。
- 动态意向评分：页面浏览、资料下载、报价查看等行为实时累加意向分。
- 成交闭环：订单、支付、售后模型与接口，支付后自动推进客户阶段和线索状态。
- 会话质检与陪练：绝对化承诺、强逼单、礼貌度、提问率自动评分，并支持 AI 模拟难缠客户。
- 知识库后台：上传、重建、文本添加、版本记录。
- 数据导出：客户、线索、订单、质检 CSV 导出。
- 部署：Dockerfile 已打包全项目，`docker-compose.yml` 同时启动 API 与公众号服务并挂载持久数据。
- 统一中台控制台：`http://127.0.0.1:5000/static/console.html`，客户档案、线索、订单、跟进、质检、知识库、系统设置全部在一个入口。

## 提示词约束

- 编辑 `config/sales_prompt.txt` 可以调整 DeepSeek 的角色、语气、回答长度、销售原则等，改完保存立即生效，无需重启。
- 保留 `{context}`、`{customer_profile}`、`{stage}`、`{chat_history}`、`{input}` 这些占位符。
- `.env` 中 `LLM_TEMPERATURE` 控制回答稳定性：数值越低越照规矩回答，越高越有发挥空间。

## 技术栈

- **LLM**: DeepSeek V4 Flash
- **向量库**: ChromaDB
- **框架**: LangChain
- **微信**: wechatpy + itchat
- **配置**: pydantic-settings

## 企业级销售中台（第二批补齐）

在原有获客、线索、订单、跟进、质检基础上，新增以下业务模块，统一在中台控制台 `http://127.0.0.1:5000/static/console.html` 使用：

- 商机管理：金额、预计成交、阶段、赢率预测、停滞预警、输单原因。
- 报价合同 CPQ：价目表、报价版本、折扣审批、合同条款、合同风险、通用审批流。
- 回款与 L2C：发货、开票、回款计划、应收核销、逾期检查。
- 360° 客户画像：工商信息、干系人图谱、标签、风险事件、跨渠道动线。
- 可配置销售 SOP：阶段模板、步骤下发、执行率统计、阶段变化自动联动。
- AI 主动经营：每日简报、赢单教练、合同风控、自然语言问数据。
- 个性化培育：按阶段/意向/行为触发，模板变量替换后自动触达。
- 服务工单：优先级 SLA、工单动态、回访记录、逾期检查。
- 营销中心：活动管理、广告 ROI、复购计划与到期派发。
- 平台化：自定义字段、角色权限、团队成员、BI 指标、多租户预留。

新增主要接口：

- `/api/v1/opportunities`、`/api/v1/quotes`、`/api/v1/contracts`、`/api/v1/approvals`
- `/api/v1/shipments`、`/api/v1/invoices`、`/api/v1/payment-plans`、`/api/v1/receivables`
- `/api/v1/portrait`、`/api/v1/sop/*`、`/api/v1/nurture/*`、`/api/v1/tickets`、`/api/v1/visits`
- `/api/v1/campaigns`、`/api/v1/ad-metrics`、`/api/v1/repurchases`
- `/api/v1/aiops/*`、`/api/v1/custom-fields`、`/api/v1/roles`、`/api/v1/team`、`/api/v1/bi/metrics`

数据库迁移：`bash deploy/migrate.sh`（等价于 `python -m alembic upgrade head`，并额外做形态判定与结构校验）。

- 发布流程请统一走 `deploy/migrate.sh`，不要依赖启动时的自动建表。
- `docker compose` 部署无需手工执行：`migrate` 一次性服务会在 api/official/worker 启动前跑完，失败即阻断发布。
- 首次对历史上由 `create_all` 建出的老库升级时，脚本会自动先 `stamp 0006_add_display_id` 再由 0007 补齐差异；全新空库则直接跑完整迁移链。
- 生产环境请设 `AUTO_CREATE_TABLES=false`：`create_all` 只建缺失的表，永远不改已有表，继续依赖它会让「给已有表加字段」在线上静默失效。
