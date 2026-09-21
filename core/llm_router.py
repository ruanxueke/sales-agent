"""多模型路由：主模型 + 备用模型框架（备用未配置时自动降级提示）

降级状态（连续失败次数 / 临时降级截止时间 / 手动指定）全部放在 `core.llm_state`
里——Redis 优先、内存兜底。原因是这些值原来挂在 `LLMRouter` 单例上，属于**进程内
状态**：api 容器起多个 uvicorn worker 时，worker A 判定主模型挂了并切备用，worker B
不知道；运维在 `/api/v1/system/llm/switch` 点了"切到备用"，也只改了接住请求的那一个
worker，其余照旧走主模型。
"""
from __future__ import annotations
import logging

from langchain_openai import ChatOpenAI

from config.settings import settings
from core import llm_state

logger = logging.getLogger(__name__)

DEFAULT_BACKUP_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


class LLMRouter:
    def __init__(self):
        self._primary = None
        self._backup = None

    def primary(self):
        if self._primary is None:
            from core.llm import create_llm
            self._primary = create_llm()
        return self._primary

    def backup(self):
        """备用模型：优先使用显式备用 Key，否则复用已配置的百炼 Key。

        注意：未配置备用 Key 时**不缓存** None——运维补上 Key 后不应该还要重启进程。
        """
        from core.secrets import resolve
        backup_key = resolve(
            settings.BACKUP_LLM_API_KEY
            or settings.DASHSCOPE_API_KEY
            or ""
        )
        if not backup_key:
            return None
        if self._backup is None:
            self._backup = ChatOpenAI(
                model=settings.BACKUP_LLM_MODEL or "qwen-plus",
                temperature=settings.LLM_TEMPERATURE,
                max_tokens=settings.LLM_MAX_TOKENS,
                api_key=backup_key,
                base_url=settings.BACKUP_LLM_BASE_URL or DEFAULT_BACKUP_BASE_URL,
            )
            provider = settings.BACKUP_LLM_PROVIDER or (
                "dashscope" if settings.DASHSCOPE_API_KEY else "openai_compatible"
            )
            logger.info(
                "备用模型已启用: %s (%s)",
                settings.BACKUP_LLM_MODEL or "qwen-plus",
                provider,
            )
        return self._backup

    def record_failure(self):
        """记一次主模型失败；达到阈值且有备用模型时开启/续期降级窗口。

        计数与窗口都在共享状态里，所以多个 worker 的失败次数是累加的——
        否则每个 worker 各自要连挂 3 次才降级，等于把阈值放大了 N 倍。
        """
        count = llm_state.record_failure()
        if count >= llm_state.FAILURE_THRESHOLD and self.backup() is not None:
            llm_state.start_failover()
            logger.warning(
                "主模型连续失败 %s 次，临时切换到备用模型 %s 秒",
                count,
                llm_state.FAILOVER_SECONDS,
            )

    def record_success(self):
        """主模型成功一次。只清失败计数，不动手动指定，也不提前解除降级窗口。"""
        llm_state.record_success()

    def switch(self, model: str = "") -> bool:
        """手动切换：primary / backup / auto

        写共享状态、不带 TTL：运维点了"切到备用"，就得一直生效到再点回来，
        不能因为进程重启或者过了几分钟就悄悄回到主模型。
        """
        if model not in ("primary", "backup", "auto"):
            return False
        ok = llm_state.set_forced_model("" if model == "auto" else model)
        if ok:
            logger.info(
                "LLM 路由已手动切换为 %s（生效范围=%s，含全部 worker）",
                model,
                llm_state.backend_name(),
            )
        return ok

    def active_model(self) -> str:
        forced = llm_state.forced_model()
        if forced:
            # 手动指定优先于自动降级：运维说用主模型就用主模型，
            # 说用备用就一直用备用，不被自动窗口覆盖。
            return forced
        return "backup" if llm_state.failover_remaining() > 0 else "primary"

    def get(self):
        model = self.active_model()
        if model == "backup":
            return self.backup() or self.primary()
        return self.primary()

    def status(self) -> dict:
        return {
            "enabled": settings.LLM_ROUTER_ENABLED,
            "active": self.active_model(),
            "forced": llm_state.forced_model() or "auto",
            "failover_remaining_seconds": llm_state.failover_remaining(),
            "consecutive_failures": llm_state.failure_streak(),
            # 状态存在 redis 还是 memory：memory 意味着多 worker 下每进程各算各的。
            "state_backend": llm_state.backend_name(),
            "primary": settings.LLM_MODEL,
            "backup_configured": bool(
                settings.BACKUP_LLM_API_KEY or settings.DASHSCOPE_API_KEY
            ),
            "backup_provider": settings.BACKUP_LLM_PROVIDER
            or ("dashscope" if settings.DASHSCOPE_API_KEY else "未配置"),
            "backup_model": settings.BACKUP_LLM_MODEL or "",
        }


llm_router = LLMRouter()
