"""Unified Voice Service and Taskbar Action Panel for Nemo."""

# 1. Standard library imports
import asyncio
import logging
import threading
import time
from typing import Any

# 2. Third-party imports
from rich.console import Console

# 3. Local imports
from nemo.voice.audio import AudioCaptureService
from nemo.voice.autostart import set_autostart
from nemo.voice.engine import WhisperVoiceEngine
from nemo.voice.panel import ActionPanelPill
from nemo.voice.queue import IdempotentTaskQueue

logger = logging.getLogger(__name__)
console = Console()


class NemoVoiceService:
    """Production voice operating layer coordinating local Whisper, task queue, and taskbar pill."""

    def __init__(
        self,
        model_size: str = "base.en",
        enable_voice: bool = True,
        show_panel: bool = True,
        autostart: bool = False,
    ) -> None:
        self.enable_voice = enable_voice
        self.model_size = model_size
        self.show_panel = show_panel

        if autostart:
            set_autostart(True)

        self._stop_event = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None
        self._speech_thread: threading.Thread | None = None

        self._wake_active_until = 0.0
        self.WAKE_WINDOW_SEC = 8.0

        # Action Panel Pill (bottom-right taskbar area)
        self.panel: ActionPanelPill | None = None
        if self.show_panel:
            self.panel = ActionPanelPill(on_cancel=self.stop)

        # Priority Task Queue
        self.task_queue = IdempotentTaskQueue(
            on_state_change=self._on_queue_state_change,
        )

        # Local Whisper Engine & Audio Capture
        self.engine: WhisperVoiceEngine | None = None
        self.audio: AudioCaptureService | None = None

        if self.enable_voice:
            try:
                self.engine = WhisperVoiceEngine(model_size=self.model_size)
                self.audio = AudioCaptureService()
            except Exception as e:
                console.print(f"[bold red]Failed to initialize voice components: {e}[/bold red]")
                self.enable_voice = False

    def start(self, block: bool = True) -> None:
        """Launch background workers and show the taskbar action pill."""
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
            console.print("[bold green]Voice Listener Online.[/bold green] Say [bold cyan]'Nemo'[/bold cyan] to issue commands.")

        # 4. Show minimal bottom-right Action Panel pill
        if self.panel:
            self.panel.start(block=block)
        elif block:
            try:
                while not self._stop_event.is_set():
                    time.sleep(0.5)
            except KeyboardInterrupt:
                self.stop()

    def stop(self) -> None:
        """Terminate all background threads and close UI."""
        self._stop_event.set()
        if self.audio:
            self.audio.stop()
        self.task_queue.stop_worker()
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self.panel:
            self.panel.stop()

    def _run_async_loop(self) -> None:
        """Runs background asyncio loop indefinitely."""
        asyncio.set_event_loop(self._loop)
        if self._loop:
            self._loop.run_forever()

    def _speech_worker_loop(self) -> None:
        """Continuous background listener consuming speech chunks from microphone."""
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
                        if self.panel:
                            self.panel.update_status("idle", "Nemo Listening")
                time.sleep(0.05)
                continue

            # Transcribe via local faster-whisper
            try:
                text = self.engine.transcribe(chunk)
                if not text:
                    continue

                has_wake, command = self.engine.parse_wake_word(text)
                now = time.time()
                is_currently_awake = (now < self._wake_active_until)

                if has_wake:
                    self._wake_active_until = now + self.WAKE_WINDOW_SEC
                    console.print(f"[bold cyan][HEARD][/bold cyan] Wake word detected: '{text}'")
                    if self.panel:
                        self.panel.update_status("listening", "Hearing command...")

                    if command:
                        console.print(f"[bold green][VOICE TASK][/bold green] Executing: '{command}'")
                        self._wake_active_until = 0.0
                        self.task_queue.submit_command(command)
                elif is_currently_awake and text.strip():
                    console.print(f"[bold green][VOICE TASK][/bold green] Follow-up command: '{text}'")
                    self._wake_active_until = 0.0
                    self.task_queue.submit_command(text)

            except Exception as e:
                logger.error("Error transcribing speech chunk: %s", e)

    def _on_queue_state_change(self, state: str, message: str) -> None:
        """Relay task queue state updates to taskbar action pill and console."""
        pill_state = "idle"
        if state == "working":
            pill_state = "working"
            console.print(f"[bold yellow]→ {message}[/bold yellow]")
        elif "Complete" in message:
            pill_state = "completed"
            console.print(f"[bold green]✓ {message}[/bold green]")
        elif state == "listening":
            pill_state = "listening"

        if self.panel:
            self.panel.update_status(pill_state, message)
