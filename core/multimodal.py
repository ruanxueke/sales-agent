"""多模态理解：图片/语音/文件识别框架（外部视觉模型未配置时自动降级为文字）"""
from __future__ import annotations
import logging
from pathlib import Path

from config.settings import settings

logger = logging.getLogger(__name__)


class MultimodalEngine:
    def configured(self) -> bool:
        return bool(settings.MULTIMODAL_API_KEY and settings.MULTIMODAL_MODEL and settings.MULTIMODAL_BASE_URL)

    def status(self) -> dict:
        return {
            "configured": self.configured(),
            "provider": settings.MULTIMODAL_PROVIDER or "unconfigured",
            "model": settings.MULTIMODAL_MODEL or "",
            "base_url": settings.MULTIMODAL_BASE_URL or "",
            "note": "未配置时，图片消息按原文降级处理",
        }

    def describe_image(self, image_path: str | Path) -> dict:
        """调用 OpenAI 兼容视觉模型（MIMO 等）识别图片，返回中文描述。"""
        if not self.configured():
            return {"ok": False, "mode": "degraded", "transcript": "", "error": "视觉模型未配置，请配置 MULTIMODAL_PROVIDER/MULTIMODAL_MODEL/MULTIMODAL_API_KEY/MULTIMODAL_BASE_URL"}
        import base64
        import requests
        try:
            data = Path(image_path).read_bytes()
            mime = "image/png" if Path(image_path).suffix.lower() == ".png" else "image/jpeg"
            b64 = base64.b64encode(data).decode("utf-8")
            url = (settings.MULTIMODAL_BASE_URL.rstrip("/")) + "/chat/completions"
            payload = {
                "model": settings.MULTIMODAL_MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": settings.MULTIMODAL_PROMPT},
                            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                        ],
                    }
                ],
                "temperature": 0.2,
            }
            headers = {
                "Authorization": "Bearer " + (settings.MULTIMODAL_API_KEY or ""),
                "Content-Type": "application/json",
            }
            resp = requests.post(url, json=payload, headers=headers, timeout=60)
            if resp.status_code != 200:
                return {"ok": False, "mode": "error", "transcript": "", "error": f"视觉模型 HTTP {resp.status_code}: {resp.text[:200]}"}
            data = resp.json()
            content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
            if not content:
                return {"ok": False, "mode": "error", "transcript": "", "error": "视觉模型返回为空"}
            return {"ok": True, "mode": "provider", "transcript": str(content).strip(), "provider": settings.MULTIMODAL_PROVIDER, "model": settings.MULTIMODAL_MODEL}
        except Exception as e:
            logger.warning("视觉模型调用失败: %s", e)
            return {"ok": False, "mode": "error", "transcript": "", "error": str(e)[:200]}

    def handle_attachment(self, file_path: str | Path, mime: str = "") -> dict:
        ext = Path(file_path).suffix.lower() if file_path else ""
        if mime.startswith("image/") or ext in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
            return self.describe_image(file_path)
        if mime.startswith("audio/") or ext in (".sil", ".mp3", ".wav", ".amr"):
            return {"ok": False, "mode": "voice", "transcript": "", "error": "语音已走 ASR 链路，此处仅记录"}
        return {"ok": False, "mode": "file", "transcript": "", "error": "暂不支持的附件类型"}


multimodal = MultimodalEngine()
