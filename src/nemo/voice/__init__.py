"""Voice processing, local Whisper STT, and voice-native service layer for Nemo."""

from nemo.voice.audio import AudioCaptureService
from nemo.voice.autostart import is_autostart_enabled, set_autostart
from nemo.voice.engine import WhisperVoiceEngine
from nemo.voice.queue import IdempotentTaskQueue, NemoTask
from nemo.voice.service import NemoVoiceService

__all__ = [
    "AudioCaptureService",
    "WhisperVoiceEngine",
    "IdempotentTaskQueue",
    "NemoTask",
    "NemoVoiceService",
    "is_autostart_enabled",
    "set_autostart",
]
