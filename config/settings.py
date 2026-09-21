"""
销售客服智能体 - 全局配置
"""
from __future__ import annotations
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings
import logging
logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
    DATA_DIR: Path = PROJECT_ROOT / "data"
    KNOWLEDGE_BASE_DIR: Path = DATA_DIR / "knowledge_base"
    VECTOR_STORE_DIR: Path = PROJECT_ROOT / "vector_store" / "chroma_db"

    LLM_PROVIDER: str = "deepseek"
    DEEPSEEK_API_KEY: Optional[str] = None
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com/v1"
    LLM_MODEL: str = "deepseek-chat"
    LLM_TEMPERATURE: float = 0.7
    LLM_MAX_TOKENS: int = 2048
    LLM_SLOW_MS: int = 30000

    # ===== 多模型路由（备用模型预留） =====
    LLM_ROUTER_ENABLED: bool = True
    BACKUP_LLM_PROVIDER: str = ""
    BACKUP_LLM_MODEL: str = ""
    BACKUP_LLM_API_KEY: str = ""
    BACKUP_LLM_BASE_URL: str = ""

    EMBEDDING_MODEL: str = 'BAAI/bge-small-zh-v1.5'
    EMBEDDING_PROVIDER: str = 'huggingface'
    EMBEDDING_DIMENSION: int = 512
    DASHSCOPE_API_KEY: Optional[str] = None
    DASHSCOPE_EMBEDDING_URL: str = "https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding"

    # ===== 语音识别 =====
    VOSK_MODEL_PATH: Optional[str] = None

    # ===== 销售线索通知 =====
    SALES_NOTIFY_TARGET: str = ""
    BOT_NOTIFY_PORT: int = 3900
    # 个人微信机器人所在主机（Docker 内访问宿主机时配置 host.docker.internal）
    BOT_HOST: str = "host.docker.internal"
    MIN_REPLY_DELAY_SECONDS: float = 5.0
    REPLY_MAX_LENGTH: int = 50
    REPLY_SPLIT_DELAY_SECONDS: float = 1.5

    # ===== 销售线索中台 =====
    LEAD_DEFAULT_OWNER: str = "叙白"
    LEAD_RECYCLE_AFTER_DAYS: int = 3
    LEAD_IMPORT_MAX_ROWS: int = 5000
    WECHAT_OFFICIAL_WELCOME: str = "您好，欢迎关注！我是这里的课程顾问，可以叫我小助手。您是想先了解一下，还是对 AI 学习有具体想聊的方向？"

    # ===== 付款成功交付 =====
    DELIVERY_MESSAGE: str = "付款后课程马上就能看，随时可以开始学。\n别忘记转发海报到朋友圈3天，截图发我，我邀请您进群。\n【飞书文档】https://ycn3z00fx2vc.feishu.cn/wiki/EN8JwTvesiAZ5pkxcJ9cqERPnzf\n进群后，找海青授权\n交付"
    PAYMENT_WEBHOOK_SECRET: str = ""
    ALLOW_UNSIGNED_PAYMENT_WEBHOOK: bool = False

    CHROMA_COLLECTION_NAME: str = "sales_knowledge"
    CHROMA_PERSIST_DIR: str = str(VECTOR_STORE_DIR)

    RAG_TOP_K: int = 5
    RAG_SCORE_THRESHOLD: float = 0.35
    RAG_CHUNK_SIZE: int = 256
    RAG_CHUNK_OVERLAP: int = 32
    RAG_BACKEND: str = "auto"  # auto / pgvector / json

    MEMORY_MAX_TOKENS: int = 2000
    MEMORY_SESSION_TTL: int = 3600

    # ===== 个人微信配置 =====
    WECHAT_TYPE: str = "personal"
    WECHAT_PERSONAL_HOT_RELOAD: bool = True
    WECHAT_PERSONAL_QR_PATH: str = "qr.png"

    # ===== 企业微信客户联系配置 =====
    WECOM_CORP_ID: str = ""
    WECOM_CONTACT_SECRET: str = ""
    WECOM_AGENT_ID: str = ""
    WECOM_TOKEN: str = ""
    WECOM_ENCODING_AES_KEY: str = ""
    WECOM_KF_SECRET: str = ""
    WECOM_KF_OPEN_KFID: str = ""
    WECOM_KF_HANDOVER_KEYWORDS: str = "人工,投诉,退款,转人工,转客服,客服处理,投诉处理"
    # 明文模式回调开关。企业微信明文模式不提供签名，任何人都能伪造一条"客户消息"
    # 直接喂给 Agent（烧 token、污染会话与合规证据链），因此默认拒绝；确需明文模式
    # 时显式打开，并按官方建议尽早改配 AES 密钥走安全模式。
    WECOM_ALLOW_PLAINTEXT_CALLBACK: bool = False
    # 转人工关键词的全局唯一来源（各渠道未单独配置时使用它）
    HANDOVER_KEYWORDS: str = "人工,转人工,人工客服,找人工,转客服,客服电话,电话联系,投诉,退款,投诉处理,客服处理"
    # ===== 视觉受管执行器（仿识流，企业授权后开启）=====
    VISION_AGENT_ENABLED: bool = False
    VISION_AGENT_MODE: str = ""  # wecom / wechat
    VISION_AGENT_API_BASE: str = "http://127.0.0.1:5010"
    VISION_AGENT_MAX_SENDS_PER_DAY: int = 300
    VISION_AGENT_POLL_INTERVAL: int = 2
    VISION_MODEL: str = "qwen-vl-max"
    VISION_HANDOVER_KEYWORDS: str = "人工,投诉,退款,转人工,转客服,客服处理,投诉处理,真人,电话联系"
    VISION_AGENT_MONITOR: str = ""

    # ===== 公众号配置 =====
    WECHAT_OFFICIAL_APP_ID: Optional[str] = None
    WECHAT_OFFICIAL_APP_SECRET: Optional[str] = None
    WECHAT_OFFICIAL_TOKEN: Optional[str] = None
    WECHAT_OFFICIAL_ENCODING_AES_KEY: Optional[str] = None
    WECHAT_OFFICIAL_SERVER_HOST: str = "0.0.0.0"
    WECHAT_OFFICIAL_SERVER_PORT: int = 8080
    WECHAT_OFFICIAL_REPLY_MODE: str = "async"

    # ===== 日志配置 =====
    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = "sales_agent.log"

    DEEPSEEK_API_KEYS: list[str] = []

    # ===== 密钥管理 =====
    SECRET_KEY: str = ""
    AUDIT_RETENTION_DAYS: int = 180
    CHAT_RETENTION_DAYS: int = 180
    DELETION_SLA_DAYS: int = 15
    DATA_CLASSIFICATION_ENABLED: bool = True

    # ===== Redis =====
    REDIS_URL: Optional[str] = None

    # ===== 正式数据库（留空则继续用内置 SQLite） =====
    # 示例：postgresql://user:pass@host:5432/sales
    #       mysql+pymysql://user:pass@host:3306/sales
    DATABASE_URL: str = ""
    READ_DATABASE_URL: str = ""
    # 是否允许 init_db() 用 Base.metadata.create_all() 直接建表。
    #
    # 背景：create_all 只会创建「缺失的表」，**永远不会修改已存在的表**。
    # 因此只要给已有表新增字段，线上库就不会跟进，代码按新字段查询就直接报错。
    # 正式部署请置为 false，并把 `alembic upgrade head` 接进发布流程
    # （见 deploy/migrate.sh）；本地开发保留 true，可零配置起步。
    AUTO_CREATE_TABLES: bool = True
    DB_POOL_SIZE: int = 20
    DB_READ_POOL_SIZE: int = 30
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_RECYCLE: int = 3600
    DB_SLOW_QUERY_MS: int = 500
    UVICORN_WORKERS: int = 2
    # 是否暴露 /docs、/redoc、/openapi.json。默认关闭：这三个端点会完整公开接口清单
    # 与参数结构，属于给攻击者送情报。仅本地开发按需打开。
    ENABLE_API_DOCS: bool = False
    # 是否把 /health 的详细指标（连接池、迁移版本等）一并返回。
    # 默认关闭：/health 通常不鉴权且可能被探活机器人扫到，详细信息放
    # 需鉴权的 /api/v1/aiops/health。
    HEALTH_EXPOSE_DETAIL: bool = False

    # ===== 对象存储（文件走 COS/S3） =====
    OBJECT_STORAGE_PROVIDER: str = "local"  # local / s3 / cos
    OBJECT_STORAGE_BUCKET: str = ""
    OBJECT_STORAGE_ENDPOINT: str = ""
    OBJECT_STORAGE_REGION: str = ""
    OBJECT_STORAGE_ACCESS_KEY: str = ""
    OBJECT_STORAGE_SECRET_KEY: str = ""

    # ===== 限流 =====
    RATE_LIMIT_PER_USER: int = 10
    RATE_LIMIT_WINDOW: int = 60
    RATE_LIMIT_GLOBAL: int = 100
    # 按 2000 用户规模预留 2.5 倍余量
    RATE_LIMIT_MEMORY_MAX_IDS: int = 5000

    # ===== 接口安全 =====
    # 逗号分隔的 API Key；留空表示本地开发模式不校验
    API_KEYS: str = ""
    # 逗号分隔的管理员 Key；留空时所有已配置 Key 均为管理员
    ADMIN_API_KEYS: str = ""
    # API Key 与租户的绑定关系，格式 key=租户ID，逗号分隔，例如：
    #   API_KEY_TENANTS=sk-a=1,sk-b=2
    # 未绑定的 Key 落到 DEFAULT_TENANT_ID。机器桥接、控制台都用各自的 Key 确定租户，
    # 因此不再需要客户端在请求体里自报 tenant_id（自报值不可信，也不会被采用）。
    API_KEY_TENANTS: str = ""
    # 允许跨租户查看全部数据的 Key（留空表示没有任何 Key 拥有跨租户视角）
    SUPER_ADMIN_API_KEYS: str = ""
    DEFAULT_TENANT_ID: int = 0
    MESSAGE_DEDUP_TTL_HOURS: int = 24

    # ===== 定时任务 =====
    ENABLE_SCHEDULER: bool = True
    SCHEDULER_INTERVAL_SECONDS: int = 60

    # ===== 自动跟进与转人工 =====
    FOLLOWUP_ENABLED: bool = True
    FOLLOWUP_NODES_HOURS: str = "1,24,72,168"
    HANDOVER_ENABLED: bool = True

    # ===== 语义缓存 =====
    CACHE_ENABLED: bool = True
    CACHE_TTL: int = 3600
    CACHE_SIMILARITY_THRESHOLD: float = 0.9
    # 2000 用户 × 每用户约 10 条缓存问题
    CACHE_MAX_ENTRIES: int = 20000
    # 语义缓存专用 Redis（留空则复用 REDIS_URL）。
    # 建议指向独立实例/DB：缓存需要 allkeys-lru 淘汰，而锁/去重/限流键绝不能被淘汰。
    CACHE_REDIS_URL: Optional[str] = None
    # 每次相似度检索最多比对的候选数量（按最近使用倒序取），避免全量 SCAN
    CACHE_SEARCH_LIMIT: int = 300

    # ===== 聊天记录保留策略 =====
    CHAT_LOG_MAX_ENTRIES_PER_CUSTOMER: int = 200
    CHAT_LOG_ARCHIVE_MAX_ENTRIES_PER_CUSTOMER: int = 2000

    # ===== Celery 异步任务 =====
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"
    CELERY_TASK_DEFAULT_QUEUE: str = "sales_agent"
    CELERY_WORKER_CONCURRENCY: int = 1

    # ===== 企业级：支付网关（占位，未配置时仅生成待支付账单） =====
    PAYMENT_PROVIDER: str = ""
    PAYMENT_APP_ID: str = ""
    PAYMENT_MCH_ID: str = ""
    PAYMENT_API_KEY: str = ""

    # ===== 企业级：多模态视觉（占位，未配置时降级） =====
    MULTIMODAL_PROVIDER: str = ""
    MULTIMODAL_MODEL: str = ""
    MULTIMODAL_API_KEY: str = ""
    MULTIMODAL_BASE_URL: str = ""
    MULTIMODAL_PROMPT: str = "请用中文详细描述这张图片的内容，包括图中文字、商品、场景和关键信息，供销售助手理解客户意图。"

    # ===== 企业级：多 Agent 编排 =====
    AGENT_ORCHESTRATOR_ENABLED: bool = False

    # ===== 企业级：实时语音（占位） =====
    VOICE_PROVIDER: str = ""
    VOICE_API_KEY: str = ""
    VOICE_MODEL: str = "qwen3-tts-flash"
    VOICE_TTS_VOICE: str = "Cherry"
    VOICE_ASR_MODEL: str = "paraformer-v2"
    PUBLIC_BASE_URL: str = "http://127.0.0.1:5000"
    # ===== 网页客服安全 =====
    PUBLIC_WEBCHAT_ENABLED: bool = True
    PUBLIC_WEBCHAT_MAX_SESSIONS_PER_IP: int = 20
    PUBLIC_WEBCHAT_RATE_LIMIT: int = 10
    PUBLIC_WEBCHAT_RATE_WINDOW: int = 60
    # ===== 企业级：监控告警 =====
    ALERT_WEBHOOK_URL: str = ""
    ALERT_CHECK_INTERVAL_SECONDS: int = 60

    # ===== 企业级：开放平台与外部集成占位 =====
    WEBHOOK_SECRET: str = ""
    FEISHU_APP_ID: str = ""
    FEISHU_APP_SECRET: str = ""
    DINGTALK_APP_KEY: str = ""
    DINGTALK_APP_SECRET: str = ""
    ERP_PROVIDER: str = ""
    ERP_API_URL: str = ""
    ERP_API_KEY: str = ""

    class Config:
        # API 服务可从任意工作目录启动，配置仍固定从项目根目录读取。
        env_file = Path(__file__).resolve().parent.parent / ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True

settings = Settings()

# 兼容处理：如果 DEEPSEEK_API_KEY 已设置，也填入列表
if not settings.DEEPSEEK_API_KEYS and settings.DEEPSEEK_API_KEY:
    settings.DEEPSEEK_API_KEYS = [settings.DEEPSEEK_API_KEY]

# 运行时目录兜底创建：镜像里不再打包 data/、vector_store/（改由 volume 挂载），
# 若挂载缺失也能自行创建，避免启动即报「unable to open database file」。
for _d in (settings.DATA_DIR, settings.KNOWLEDGE_BASE_DIR, settings.VECTOR_STORE_DIR):
    try:
        Path(_d).mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.debug("config/settings.py 异常已忽略: %s", e)
