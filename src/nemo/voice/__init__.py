"""Voice processing, local Whisper STT, SAPI TTS, and voice-native service layer for Nemo."""

from nemo.voice.audio import AudioCaptureService
from nemo.voice.autostart import is_autostart_enabled, set_autostart
from nemo.voice.engine import WhisperVoiceEngine
from nemo.voice.panel import ActionPanelPill
from nemo.voice.queue import IdempotentTaskQueue, NemoTask
from nemo.voice.service import NemoVoiceService
from nemo.voice.tts import NemoTtsEngine

__all__ = [
    "ActionPanelPill",
    "AudioCaptureService",
    "WhisperVoiceEngine",
    "NemoTtsEngine",
    "IdempotentTaskQueue",
    "NemoTask",
    "NemoVoiceService",
    "is_autostart_enabled",
    "set_autostart",
]
