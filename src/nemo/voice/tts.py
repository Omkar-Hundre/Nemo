"""Native, offline, asynchronous Text-To-Speech (TTS) engine for Nemo."""

# 1. Standard library imports
import logging
import re
import threading

# 2. Third-party imports
# (None)

# 3. Local imports
# (None)

logger = logging.getLogger(__name__)

# SAPI Speech Voice Flags
SVSF_DEFAULT = 0
SVS_FLAGS_ASYNC = 1
SVS_PURGE_BEFORE_SPEAK = 2


class NemoTtsEngine:
    """Asynchronous, offline Windows speech synthesizer using native SAPI."""

    def __init__(self, rate: int = 1, volume: int = 100) -> None:
        self.rate = rate
        self.volume = volume
        self._voice = None
        self._lock = threading.Lock()
        self._init_voice()

    def _init_voice(self) -> None:
        try:
            import win32com.client
            self._voice = win32com.client.Dispatch("SAPI.SpVoice")
            self._voice.Rate = self.rate
            self._voice.Volume = self.volume
            logger.info("Windows SAPI TTS engine ready.")
        except Exception as e:
            logger.warning("Could not initialize SAPI TTS: %s", e)
            self._voice = None

    def speak(self, text: str, interrupt: bool = True) -> None:
        """Speak message asynchronously without blocking execution."""
        clean_text = self._clean_for_speech(text)
        if not clean_text:
            return

        if not self._voice:
            self._init_voice()

        if self._voice:
            try:
                flags = SVS_FLAGS_ASYNC
                if interrupt:
                    flags |= SVS_PURGE_BEFORE_SPEAK
                self._voice.Speak(clean_text, flags)
            except Exception as e:
                logger.debug("TTS speak error: %s", e)

    def stop(self) -> None:
        """Immediately stop currently playing audio."""
        if self._voice:
            try:
                self._voice.Speak("", SVS_PURGE_BEFORE_SPEAK)
            except Exception:
                pass

    @staticmethod
    def _clean_for_speech(text: str) -> str:
        """Strip markdown syntax, code fences, and long URLs for natural conversation."""
        if not text:
            return ""

        # Remove fenced code blocks ```...```
        t = re.sub(r"```[\s\S]*?```", " [code omitted] ", text)
        # Remove inline code `...`
        t = re.sub(r"`([^`]+)`", r"\1", t)
        # Remove Markdown links [text](url) -> text
        t = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", t)
        # Remove markdown headers and bullets
        t = re.sub(r"^#{1,6}\s+", "", t, flags=re.MULTILINE)
        t = re.sub(r"^\s*[\*\-\+]\s+", "", t, flags=re.MULTILINE)
        # Remove bold/italic markers
        t = re.sub(r"[*_]{1,3}", "", t)
        # Remove extra whitespace
        t = re.sub(r"\s+", " ", t).strip()

        # If text is extremely verbose, summarize to first 2 sentences or 250 characters
        if len(t) > 300:
            sentences = re.split(r"(?<=[.!?])\s+", t)
            shortened = " ".join(sentences[:2])
            if len(shortened) > 280:
                shortened = shortened[:270] + "..."
            return shortened

        return t
