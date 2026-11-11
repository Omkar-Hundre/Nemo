"""Local Whisper speech-to-text and wake-word parsing engine."""

# 1. Standard library imports
import logging
import re
from typing import Tuple

# 2. Third-party imports
from faster_whisper import WhisperModel
import numpy as np

# 3. Local imports
# (None)

logger = logging.getLogger(__name__)


class WhisperVoiceEngine:
    """Local, offline speech recognition using faster-whisper INT8."""

    WAKE_WORDS = ["nemo", "hey nemo", "ok nemo", "hi nemo", "namo", "nemu"]

    def __init__(self, model_size: str = "base.en", device: str = "cpu", compute_type: str = "int8") -> None:
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        logger.info("Initializing faster-whisper (%s, %s, %s)...", model_size, device, compute_type)
        self.model = WhisperModel(model_size, device=device, compute_type=compute_type)
        logger.info("faster-whisper model ready.")

    def transcribe(self, audio: np.ndarray) -> str:
        """Transcribe a 16kHz float32 audio array to text."""
        if audio is None or len(audio) < 1600:  # < 0.1s
            return ""

        # Normalize audio amplitude
        max_val = np.max(np.abs(audio))
        if max_val > 0:
            audio = audio / max_val

        segments, _ = self.model.transcribe(
            audio,
            beam_size=3,
            language="en",
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=400),
        )

        text_parts = [s.text.strip() for s in segments]
        transcription = " ".join(text_parts).strip()
        return transcription

    def parse_wake_word(self, raw_text: str) -> Tuple[bool, str]:
        """Detect wake word and extract target command.
        
        Returns:
            (has_wake_word, clean_command)
        """
        if not raw_text:
            return False, ""

        clean = re.sub(r"[^\w\s]", "", raw_text.lower()).strip()

        for wake in self.WAKE_WORDS:
            # Check prefix e.g. "hey nemo set a timer" or "nemo set a timer"
            if clean.startswith(wake):
                cmd = clean[len(wake):].strip()
                return True, cmd
            # Check mid-sentence e.g. "could you please nemo set a timer"
            match = re.search(r"\b" + re.escape(wake) + r"\b\s*(.*)", clean)
            if match:
                cmd = match.group(1).strip()
                return True, cmd

        return False, clean

