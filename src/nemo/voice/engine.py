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

    WAKE_WORDS = [
        "hey nemo", "ok nemo", "hi nemo", "hello nemo", "and nemo",
        "listen nemo", "yo nemo", "hey nimo", "hi nimo",
        "nemo", "nimo", "namo", "nemu", "nimu", "neemo", "kneemo",
        "niemo", "nimmo", "memo", "meemo", "demo", "neymo", "naymo",
        "emo", "mimo", "mino",
    ]

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
            beam_size=1,
            language="en",
            initial_prompt="Nemo, Hey Nemo, Nemo assistant, Clovi, Omkar, WhatsApp, Bundu, Goutam, Gautam, Patil, placements, COSEM, DLMS, Python, Antigravity, FastAPI, Brave, GitHub, pytest, Windows, terminal",
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
        words = clean.split()
        if not words:
            return False, ""

        # 1. Exact match on multi-word or single-word wake phrases
        for wake in self.WAKE_WORDS:
            wake_words = wake.split()
            # Prefix check
            if len(words) >= len(wake_words) and words[:len(wake_words)] == wake_words:
                cmd = " ".join(words[len(wake_words):]).strip()
                return True, cmd

            # Mid-sentence check
            match = re.search(r"\b" + re.escape(wake) + r"\b\s*(.*)", clean)
            if match:
                cmd = match.group(1).strip()
                return True, cmd

        # 2. Phonetic / fuzzy fallback for first word if within edit distance 1 of 'nemo'
        first = words[0]
        if len(first) in (3, 4, 5):
            diffs = sum(1 for a, b in zip(first, "nemo") if a != b) + abs(len(first) - 4)
            if diffs <= 1:
                return True, " ".join(words[1:]).strip()

        return False, clean

