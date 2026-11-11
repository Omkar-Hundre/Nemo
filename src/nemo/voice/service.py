"""Unified Voice Daemon and Floating Avatar Service for Nemo."""

# 1. Standard library imports
import asyncio
import logging
import threading
import time
from typing import Any

# 2. Third-party imports
# (None)

# 3. Local imports
from nemo.ui.avatar import NemoAvatarWindow
from nemo.voice.audio import AudioCaptureService
from nemo.voice.autostart import is_autostart_enabled, set_autostart
from nemo.voice.engine import WhisperVoiceEngine
from nemo.voice.queue import IdempotentTaskQueue

logger = logging.getLogger(__name__)


class NemoVoiceService:
    """Production operating layer coordinating local Whisper, task queue, and floating avatar."""

    def __init__(
        self,
        model_size: str = "base.en",
        enable_voice: bool = True,
        autostart: bool = False,
    ) -> None:
        self.enable_voice = enable_voice
        self.model_size = model_size

        if autostart:
            set_autostart(True)

        self._stop_event = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None
        self._speech_thread: threading.Thread | None = None

        self._wake_active_until = 0.0
        self.WAKE_WINDOW_SEC = 8.0

        # Avatar Window Controller
        self.avatar = NemoAvatarWindow(
            on_command=self._on_user_command,
            on_cancel=self._on_user_cancel,
            on_voice_toggle=self._on_voice_toggle,
        )

        # Priority Task Queue
        self.task_queue = IdempotentTaskQueue(
            on_state_change=self._on_queue_state_change,
            on_tasks_updated=self._on_queue_tasks_updated,
        )

        # Local Whisper Engine & Audio Capture
        self.engine: WhisperVoiceEngine | None = None
        self.audio: AudioCaptureService | None = None

        if self.enable_voice:
            try:
                self.engine = WhisperVoiceEngine(model_size=self.model_size)
                self.audio = AudioCaptureService()
            except Exception as e:
                logger.error("Failed to initialize voice components: %s", e)
                self.enable_voice = False

    def start(self, block: bool = True) -> None:
        """Launch all background workers and open desktop avatar window."""
        # 1. Start dedicated asyncio event loop thread for task executions
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self._loop_thread.start()

        # 2. Start task queue worker
        self.task_queue.start_worker(self._loop)

        # 3. Start audio capture and speech transcription loop
        if self.enable_voice and self.audio and self.engine:
            self.audio.start()
            self._speech_thread = threading.Thread(target=self._speech_worker_loop, daemon=True)
            self._speech_thread.start()

        # 4. Start avatar GUI on main thread
        self.avatar.start(block=block)

    def stop(self) -> None:
        """Terminate all background threads and close UI."""
        self._stop_event.set()
        if self.audio:
            self.audio.stop()
        self.task_queue.stop_worker()
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        self.avatar.close()

    def _run_async_loop(self) -> None:
        """Runs background asyncio loop indefinitely."""
        asyncio.set_event_loop(self._loop)
        if self._loop:
            self._loop.run_forever()

    def _speech_worker_loop(self) -> None:
        """Continuous background listener consuming speech chunks from microphone."""
        logger.info("Local Whisper listener loop active. Say 'Nemo' to trigger commands.")
        while not self._stop_event.is_set():
            if not self.enable_voice or not self.audio or not self.engine:
                time.sleep(0.2)
                continue

            chunk = self.audio.get_speech_chunk(timeout=0.1)
            if chunk is None:
                # Check if wake window expired
                now = time.time()
                if 0.0 < self._wake_active_until < now:
                    self._wake_active_until = 0.0
                    if not self.task_queue._current_task:
                        self.avatar.set_state("sleeping", "Nemo Resting")
                time.sleep(0.05)
                continue

            # Transcribe via faster-whisper
            try:
                text = self.engine.transcribe(chunk)
                if not text:
                    continue

                logger.info("Transcribed audio: '%s'", text)
                has_wake, command = self.engine.parse_wake_word(text)

                now = time.time()
                is_currently_awake = (now < self._wake_active_until)

                if has_wake:
                    self._wake_active_until = now + self.WAKE_WINDOW_SEC
                    self.avatar.set_state("listening", "Listening...")

                    if command:
                        logger.info("Executing voice command: '%s'", command)
                        self._wake_active_until = 0.0
                        self.task_queue.submit_command(command)
                elif is_currently_awake and text.strip():
                    logger.info("Executing follow-up voice command: '%s'", text)
                    self._wake_active_until = 0.0
                    self.task_queue.submit_command(text)

            except Exception as e:
                logger.error("Error transcribing speech chunk: %s", e)

    def _on_user_command(self, cmd_text: str) -> None:
        """Called when user types a command in GUI input box."""
        logger.info("Received user manual command: '%s'", cmd_text)
        self.task_queue.submit_command(cmd_text)

    def _on_user_cancel(self, task_id: str) -> None:
        """Called when user clicks stop button in GUI."""
        logger.info("Received cancel request for task #%s", task_id)
        self.task_queue.cancel_task(task_id)

    def _on_voice_toggle(self, enabled: bool) -> None:
        """Called when user toggles microphone button in GUI."""
        logger.info("Voice recognition toggled: %s", enabled)
        self.enable_voice = enabled
        if enabled:
            if self.audio:
                self.audio.start()
            self.avatar.set_state("sleeping", "Nemo Voice Active")
        else:
            if self.audio:
                self.audio.stop()
            self.avatar.set_state("sleeping", "Nemo (Voice Muted)")

    def _on_queue_state_change(self, state: str, message: str) -> None:
        """Relay task queue state updates to avatar."""
        self.avatar.set_state(state, message)

    def _on_queue_tasks_updated(self, tasks: list[dict[str, Any]]) -> None:
        """Relay task queue list updates to process manager GUI."""
        self.avatar.update_tasks(tasks)

