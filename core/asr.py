"""语音转文字（ASR）模块：微信 SILK / 通用音频 → 16k WAV → Vosk 本地识别"""
from __future__ import annotations
import json
import logging
import os
import subprocess
import tempfile
import wave

from config.settings import settings
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_MODEL_NAME = "vosk-model-small-cn-0.22"
SILK_EXTENSIONS = {".sil", ".silk"}


def _default_model_path() -> str:
    if settings.VOSK_MODEL_PATH:
        return settings.VOSK_MODEL_PATH
    return str(settings.PROJECT_ROOT / "models" / DEFAULT_MODEL_NAME)


def _to_wav(src_path: str, dst_path: str) -> None:
    import imageio_ffmpeg
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [ffmpeg, "-y", "-i", src_path, "-ar", "16000", "-ac", "1", "-f", "wav", dst_path]
    proc = subprocess.run(cmd, capture_output=True, timeout=120)
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"音频转换失败: {detail}")


class SpeechToText:
    """基于 Vosk 中文小模型的本地语音识别器"""

    def __init__(self, model_path: str | None = None):
        self._model_path = model_path or _default_model_path()
        self._model = None

    def _get_model(self):
        if self._model is None:
            from vosk import Model
            if not os.path.isdir(self._model_path):
                raise FileNotFoundError(f"语音识别模型不存在: {self._model_path}")
            logger.info("正在加载语音识别模型: %s", self._model_path)
            self._model = Model(self._model_path)
        return self._model

    def transcribe_file(self, file_path: str) -> str:
        # 优先使用阿里百炼云端语音识别（配置 VOICE_PROVIDER=dashscope 时）
        try:
            if settings.VOICE_PROVIDER == "dashscope" and settings.VOICE_API_KEY:
                return self._transcribe_dashscope(file_path)
        except Exception as e:
            logger.warning("百炼语音识别失败，尝试本地 Vosk: %s", e)
        wav_path = None
        try:
            fd, wav_path = tempfile.mkstemp(suffix=".wav")
            os.close(fd)
            suffix = os.path.splitext(file_path)[1].lower()
            if suffix in SILK_EXTENSIONS:
                import pilk
                pilk.silk_to_wav(file_path, wav_path, rate=16000)
            else:
                _to_wav(file_path, wav_path)
            return self._transcribe_wav(wav_path)
        finally:
            if wav_path:
                try:
                    os.unlink(wav_path)
                except OSError as e:
                    logger.debug("SpeechToText.transcribe_file 异常已忽略: %s", e)

    def _transcribe_dashscope(self, file_path: str) -> str:
        """百炼 paraformer 文件转写：先转 wav 并放入公网 static 目录，再调云端识别"""
        import hashlib
        import requests as http
        import dashscope
        from dashscope.audio.asr import Transcription

        dashscope.api_key = settings.VOICE_API_KEY
        tmp_wav = None
        try:
            suffix = os.path.splitext(file_path)[1].lower()
            if suffix in SILK_EXTENSIONS:
                import pilk
                fd, tmp_wav = tempfile.mkstemp(suffix=".wav")
                os.close(fd)
                pilk.silk_to_wav(file_path, tmp_wav, rate=16000)
                upload_path = tmp_wav
            else:
                upload_path = file_path
            # 复制到 static 目录，生成公网 URL（nginx /static 已代理）
            name = hashlib.md5(str(os.path.getsize(upload_path)).encode()).hexdigest()[:12] + ".wav"
            static_dir = Path(settings.PROJECT_ROOT) / "static" / "voice_tts"
            static_dir.mkdir(parents=True, exist_ok=True)
            target = static_dir / name
            import shutil
            shutil.copyfile(upload_path, target)
            base = (settings.PUBLIC_BASE_URL or "http://127.0.0.1:5010").rstrip("/")
            file_url = f"{base}/static/voice_tts/{name}"
            task = Transcription.async_call(
                model=settings.VOICE_ASR_MODEL or "paraformer-v2",
                file_urls=[file_url],
                api_key=settings.VOICE_API_KEY,
            )
            task_id = getattr(getattr(task, "output", None), "task_id", "") or ""
            if not task_id:
                raise RuntimeError(f"百炼 ASR 任务创建失败: {task}")
            import time as _time
            result = None
            for _ in range(20):  # 最多约 40 秒，避免任务长期 RUNNING 卡死服务
                _time.sleep(2)
                result = Transcription.fetch(task_id, api_key=settings.VOICE_API_KEY)
                status = getattr(getattr(result, "output", None), "task_status", "")
                if status in ("SUCCEEDED", "FAILED", "CANCELED"):
                    break
            if not result or getattr(getattr(result, "output", None), "task_status", "") != "SUCCEEDED":
                raise RuntimeError("百炼 ASR 任务超时或失败")
            # 递归查找 transcription_url 并下载转写 JSON
            transcription_url = self._find_transcription_url(result.output)
            if not transcription_url:
                raise RuntimeError("百炼 ASR 未返回转写地址")
            r = http.get(transcription_url, timeout=60)
            if r.status_code != 200:
                raise RuntimeError(f"转写结果下载失败 HTTP {r.status_code}")
            data = r.json()
            return self._extract_transcript(data)
        finally:
            if tmp_wav:
                try:
                    os.unlink(tmp_wav)
                except OSError as e:
                    logger.debug("SpeechToText._transcribe_dashscope 异常已忽略: %s", e)

    def _find_transcription_url(self, obj) -> str:
        if isinstance(obj, dict):
            if obj.get("transcription_url"):
                return obj["transcription_url"]
            for v in obj.values():
                found = self._find_transcription_url(v)
                if found:
                    return found
        elif isinstance(obj, list):
            for v in obj:
                found = self._find_transcription_url(v)
                if found:
                    return found
        return ""

    def _extract_transcript(self, data) -> str:
        parts = []
        if isinstance(data, dict):
            for key in ("transcriptions", "transcripts", "results", "sentences"):
                val = data.get(key)
                if isinstance(val, list):
                    for item in val:
                        if isinstance(item, dict):
                            t = item.get("text") or item.get("transcription") or ""
                            if isinstance(t, dict):
                                t = t.get("text") or ""
                            if t:
                                parts.append(str(t))
        return "".join(parts).strip()

    def _transcribe_wav(self, wav_path: str) -> str:
        from vosk import KaldiRecognizer
        model = self._get_model()
        rec = KaldiRecognizer(model, 16000)
        parts = []
        with wave.open(wav_path, "rb") as wf:
            if wf.getframerate() != 16000 or wf.getnchannels() != 1:
                raise ValueError("音频必须是 16kHz 单声道 WAV")
            while True:
                data = wf.readframes(4000)
                if not data:
                    break
                if rec.AcceptWaveform(data):
                    result = json.loads(rec.Result())
                    if result.get("text"):
                        parts.append(result["text"])
        final = json.loads(rec.FinalResult())
        if final.get("text"):
            parts.append(final["text"])
        return "".join(parts).strip()


speech_to_text = SpeechToText()
