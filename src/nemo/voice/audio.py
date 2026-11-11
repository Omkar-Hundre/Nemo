"""Audio capture and Voice Activity Detection (VAD) via sounddevice."""

# 1. Standard library imports
from collections import deque
import logging
import threading
import time
from typing import Any, Generator

# 2. Third-party imports
import numpy as np
import sounddevice as sd

# 3. Local imports
# (None)

logger = logging.getLogger(__name__)


class AudioCaptureService:
    """Continuous low-latency audio capture with RMS-based Voice Activity Detection (VAD)."""

    def __init__(
        self,
        sample_rate: int = 16000,
        chunk_duration_ms: int = 30,
        silence_timeout_sec: float = 0.8,
        pre_roll_sec: float = 0.4,
        energy_threshold: float = 0.015,
    ) -> None:
        self.sample_rate = sample_rate
        self.chunk_size = int(sample_rate * (chunk_duration_ms / 1000.0))
        self.silence_timeout = silence_timeout_sec
        self.pre_roll_chunks = int(pre_roll_sec / (chunk_duration_ms / 1000.0))
        self.energy_threshold = energy_threshold

        self._running = False
        self._stream: sd.InputStream | None = None
        self._pre_roll_buffer: deque[np.ndarray] = deque(maxlen=self.pre_roll_chunks)
        self._speech_buffer: list[np.ndarray] = []
        self._is_speaking = False
        self._last_speech_time = 0.0
        self._audio_queue: deque[np.ndarray] = deque()
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start streaming microphone frames."""
        if self._running:
            return
        self._running = True
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            blocksize=self.chunk_size,
            callback=self._audio_callback,
        )
        self._stream.start()
        logger.info("Audio capture started at %d Hz", self.sample_rate)

    def stop(self) -> None:
        """Stop microphone stream."""
        self._running = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        logger.info("Audio capture stopped")

    def _audio_callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info: Any,
        status: sd.CallbackFlags,
    ) -> None:
        """Audio stream callback running in high-priority audio thread."""
        if not self._running:
            return

        # indata is shape (frames, 1) float32
        chunk = indata[:, 0].copy()
        rms = float(np.sqrt(np.mean(chunk**2)))

        now = time.time()

        if rms > self.energy_threshold:
            if not self._is_speaking:
                # Speech onset
                self._is_speaking = True
                self._speech_buffer = list(self._pre_roll_buffer)
            self._is_speaking = True
            self._last_speech_time = now
            self._speech_buffer.append(chunk)
        elif self._is_speaking:
            # Trailing audio during speech
            self._speech_buffer.append(chunk)
            if (now - self._last_speech_time) > self.silence_timeout:
                # Speech ended
                self._is_speaking = False
                full_speech = np.concatenate(self._speech_buffer)
                self._speech_buffer = []
                with self._lock:
                    self._audio_queue.append(full_speech)
        else:
            # Pre-speech ring buffer
            self._pre_roll_buffer.append(chunk)

    def get_speech_chunk(self, timeout: float = 0.1) -> np.ndarray | None:
        """Retrieve complete recorded speech chunk if available."""
        with self._lock:
            if self._audio_queue:
                return self._audio_queue.popleft()
        return None
