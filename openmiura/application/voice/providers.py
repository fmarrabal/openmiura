from __future__ import annotations

import base64
import io
import json
import math
import os
import struct
import time
import urllib.request
import wave
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class SpeechToTextResult:
    text: str
    confidence: float = 1.0
    language: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TextToSpeechResult:
    audio_bytes: bytes
    mime_type: str = "audio/wav"
    sample_rate_hz: int = 16000
    duration_ms: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


class LocalInlineSTTProvider:
    name = "local-inline-stt"

    def transcribe(self, audio_bytes: bytes, *, locale: str = "", metadata: dict[str, Any] | None = None) -> SpeechToTextResult:
        meta = dict(metadata or {})
        expected = str(meta.get("expected_transcript") or meta.get("transcript_text") or "").strip()
        text = expected
        if not text:
            for encoding in ("utf-8", "latin-1"):
                try:
                    decoded = audio_bytes.decode(encoding, errors="ignore").strip()
                except Exception:
                    decoded = ""
                if decoded:
                    text = decoded
                    break
        if not text:
            text = f"Audio turn captured ({len(audio_bytes)} bytes)."
        confidence = float(meta.get("confidence") or 0.91)
        return SpeechToTextResult(text=text[:1200], confidence=max(0.0, min(confidence, 1.0)), language=str(locale or meta.get("language") or ""), metadata={"provider": self.name, "mode": "inline-audio"})


class LocalWaveTTSProvider:
    name = "local-wave-tts"

    def synthesize(self, text: str, *, voice_name: str = "assistant", locale: str = "", metadata: dict[str, Any] | None = None) -> TextToSpeechResult:
        payload = str(text or "").strip() or "OpenMiura voice output"
        meta = dict(metadata or {})
        sample_rate = int(meta.get("sample_rate_hz") or 16000)
        duration_ms = max(250, min(4000, 220 + len(payload) * 18))
        frequency = 440 + (sum(payload.encode("utf-8")) % 180)
        frames = int(sample_rate * (duration_ms / 1000.0))
        amplitude = 11000
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            for i in range(frames):
                envelope = 0.6 if i < frames * 0.8 else max(0.05, (frames - i) / max(frames * 0.2, 1))
                value = int(amplitude * envelope * math.sin(2 * math.pi * frequency * (i / sample_rate)))
                wav.writeframesraw(struct.pack("<h", value))
        audio = buf.getvalue()
        return TextToSpeechResult(audio_bytes=audio, mime_type="audio/wav", sample_rate_hz=sample_rate, duration_ms=duration_ms, metadata={"provider": self.name, "voice_name": voice_name, "locale": locale})


class WebhookJsonSTTProvider:
    name = "webhook-stt"

    def __init__(self, url: str | None = None, timeout_s: float = 15.0) -> None:
        self.url = str(url or os.getenv("OPENMIURA_VOICE_STT_WEBHOOK_URL") or "").strip()
        self.timeout_s = float(timeout_s)

    def transcribe(self, audio_bytes: bytes, *, locale: str = "", metadata: dict[str, Any] | None = None) -> SpeechToTextResult:
        if not self.url:
            raise RuntimeError("OPENMIURA_VOICE_STT_WEBHOOK_URL is not configured")
        body = json.dumps({
            "audio_b64": base64.b64encode(audio_bytes).decode("ascii"),
            "locale": locale,
            "metadata": dict(metadata or {}),
        }, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(self.url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return SpeechToTextResult(
            text=str(payload.get("text") or "").strip(),
            confidence=float(payload.get("confidence") or 0.0),
            language=str(payload.get("language") or locale or ""),
            metadata={"provider": self.name, "response": payload},
        )


class WebhookJsonTTSProvider:
    name = "webhook-tts"

    def __init__(self, url: str | None = None, timeout_s: float = 15.0) -> None:
        self.url = str(url or os.getenv("OPENMIURA_VOICE_TTS_WEBHOOK_URL") or "").strip()
        self.timeout_s = float(timeout_s)

    def synthesize(self, text: str, *, voice_name: str = "assistant", locale: str = "", metadata: dict[str, Any] | None = None) -> TextToSpeechResult:
        if not self.url:
            raise RuntimeError("OPENMIURA_VOICE_TTS_WEBHOOK_URL is not configured")
        body = json.dumps({
            "text": str(text or ""),
            "voice_name": voice_name,
            "locale": locale,
            "metadata": dict(metadata or {}),
        }, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(self.url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
            payload = json.loads(response.read().decode("utf-8"))
        audio_b64 = str(payload.get("audio_b64") or "")
        if not audio_b64:
            raise RuntimeError("webhook tts provider did not return audio_b64")
        return TextToSpeechResult(
            audio_bytes=base64.b64decode(audio_b64),
            mime_type=str(payload.get("mime_type") or "audio/wav"),
            sample_rate_hz=int(payload.get("sample_rate_hz") or 16000),
            duration_ms=int(payload.get("duration_ms") or 0),
            metadata={"provider": self.name, "response": payload},
        )


def resolve_stt_provider(name: str | None):
    normalized = str(name or "local-inline-stt").strip().lower()
    if normalized in {"simulated-stt", "local-inline-stt", "inline-stt", "local-stt"}:
        return LocalInlineSTTProvider()
    if normalized in {"webhook-stt", "http-stt"}:
        return WebhookJsonSTTProvider()
    raise ValueError(f"Unsupported STT provider: {name}")


def resolve_tts_provider(name: str | None):
    normalized = str(name or "local-wave-tts").strip().lower()
    if normalized in {"simulated-tts", "local-wave-tts", "wave-tts", "local-tts"}:
        return LocalWaveTTSProvider()
    if normalized in {"webhook-tts", "http-tts"}:
        return WebhookJsonTTSProvider()
    raise ValueError(f"Unsupported TTS provider: {name}")
