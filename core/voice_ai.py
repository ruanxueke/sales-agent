"""实时语音对话框架：ASR/TTS/情绪检测占位（外部语音服务未配置时自动降级）"""
from __future__ import annotations
import logging

from config.settings import settings
from pathlib import Path

logger = logging.getLogger(__name__)


class VoiceAI:
    def __init__(self):
        self._tts_dir = Path(settings.PROJECT_ROOT) / "static" / "voice_tts"
        try:
            self._tts_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.warning("TTS 输出目录不可用，语音播报将全部失败: %s", e)

    def configured(self) -> bool:
        return bool(settings.VOICE_PROVIDER and settings.VOICE_API_KEY)

    def status(self) -> dict:
        return {
            "configured": self.configured(),
            "provider": settings.VOICE_PROVIDER or "unconfigured",
            "model": settings.VOICE_MODEL or "",
            "realtime_dialogue": False,
            "emotion_detection": True,
            "note": "已启用百炼 qwen-tts 语音合成；实时通话仍为占位接口",
        }

    def synthesize(self, text: str) -> dict:
        """百炼 qwen-tts 语音合成：返回本地音频文件路径与公开 URL"""
        try:
            from dashscope.audio.qwen_tts import SpeechSynthesizer
        except Exception as e:
            return {"ok": False, "mode": "degraded", "audio_url": "", "file_path": "", "text": text, "error": f"dashscope SDK 未安装: {e}"}
        if not self.configured():
            return {"ok": False, "mode": "degraded", "audio_url": "", "file_path": "", "text": text, "error": "语音服务未配置"}
        try:
            response = SpeechSynthesizer.call(
                model=settings.VOICE_MODEL or "qwen3-tts-flash",
                api_key=settings.VOICE_API_KEY,
                text=text,
                voice=settings.VOICE_TTS_VOICE or "Cherry",
            )
            if getattr(response, "status_code", None) != 200:
                return {"ok": False, "mode": "error", "audio_url": "", "file_path": "", "text": text, "error": str(response)[:200]}
            output = getattr(response, "output", None) or {}
            audio = output.get("audio") or {}
            audio_url = audio.get("url") or ""
            if not audio_url:
                return {"ok": False, "mode": "error", "audio_url": "", "file_path": "", "text": text, "error": "音频 URL 为空"}
            import hashlib
            import requests as http
            name = hashlib.md5(text.encode("utf-8")).hexdigest()[:16] + ".wav"
            file_path = self._tts_dir / name
            if not file_path.exists():
                r = http.get(audio_url, timeout=60)
                if r.status_code != 200:
                    return {"ok": False, "mode": "error", "audio_url": "", "file_path": "", "text": text, "error": f"音频下载失败 HTTP {r.status_code}"}
                file_path.write_bytes(r.content)
            public_url = "/static/voice_tts/" + name
            return {"ok": True, "mode": "provider", "audio_url": public_url, "file_path": str(file_path), "text": text, "model": settings.VOICE_MODEL}
        except Exception as e:
            logger.warning("语音合成失败: %s", e)
            return {"ok": False, "mode": "error", "audio_url": "", "file_path": "", "text": text, "error": str(e)[:200]}

    def emotion(self, transcript: str) -> dict:
        """情绪检测：基于关键词与否定词的简单判定"""
        positive = ("满意", "好", "可以", "要", "感兴趣", "太棒了", "不错", "愿意")
        negative = ("太贵", "算了", "不要", "骗人", "垃圾", "投诉", "差评", "退钱")
        score = 0
        for w in positive:
            if w in transcript:
                score += 1
        for w in negative:
            if w in transcript:
                score -= 2
        level = "positive" if score > 0 else "negative" if score < 0 else "neutral"
        return {"ok": True, "mode": "rule", "emotion": level, "score": score}


voice_ai = VoiceAI()
