"""Unified Voice Service, SAPI TTS Synthesizer, and Taskbar Action Panel for Nemo."""

# 1. Standard library imports
import asyncio
import logging
import threading
import time
from typing import Any

# 2. Third-party imports
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

# 3. Local imports
from nemo.voice.audio import AudioCaptureService
from nemo.voice.autostart import set_autostart
from nemo.voice.engine import WhisperVoiceEngine
from nemo.voice.panel import ActionPanelPill
from nemo.voice.queue import IdempotentTaskQueue
from nemo.voice.tts import NemoTtsEngine

logger = logging.getLogger(__name__)
console = Console()


class NemoVoiceService:
    """Production voice operating layer with live thinking streaming, SAPI TTS, and taskbar pill."""

    def __init__(
        self,
        model_size: str = "base.en",
        enable_voice: bool = True,
        enable_tts: bool = True,
        show_panel: bool = True,
        autostart: bool = False,
        enable_proactive: bool = True,
    ) -> None:
        self.enable_voice = enable_voice
        self.enable_tts = enable_tts
        self.enable_proactive = enable_proactive
        self.model_size = model_size
        self.show_panel = show_panel

        if autostart:
            set_autostart(True)

        self._stop_event = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None
        self._speech_thread: threading.Thread | None = None
        self._proactive_thread: threading.Thread | None = None
        self._stdin_thread: threading.Thread | None = None

        self._wake_active_until = 0.0
        self.WAKE_WINDOW_SEC = 8.0
        self._proactive_silenced_until = 0.0
        self._last_proactive_checkin = time.time()

        # Text-To-Speech Synthesizer
        self.tts = NemoTtsEngine() if self.enable_tts else None

        # Action Panel Pill (bottom-right taskbar area)
        self.panel: ActionPanelPill | None = None
        if self.show_panel:
            self.panel = ActionPanelPill(on_cancel=self.stop)

        # Priority Task Queue with step callbacks
        self.task_queue = IdempotentTaskQueue(
            on_state_change=self._on_queue_state_change,
            on_step=self._on_agent_step,
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
            if self.tts:
                self.tts.speak("Nemo voice assistant is active and listening.")

        # 4. Start Proactive Companion Worker
        if self.enable_proactive and self.tts:
            self._proactive_thread = threading.Thread(target=self._proactive_worker_loop, daemon=True)
            self._proactive_thread.start()

        # 5. Start Terminal STDIN listener (allows typing commands or questions anytime)
        self._stdin_thread = threading.Thread(target=self._stdin_worker_loop, daemon=True)
        self._stdin_thread.start()

        # 6. Show minimal bottom-right Action Panel pill
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
        if self.tts:
            self.tts.stop()
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

                cmd_text = (command or text).strip().lower().rstrip(".!?,")
                DISMISSAL_PHRASES = (
                    "not now", "not now nemo", "later nemo", "later",
                    "quiet", "keep quiet", "shut up", "leave me alone",
                    "stop talking", "be quiet", "pause",
                )
                if any(cmd_text == dp or cmd_text.startswith(dp) for dp in DISMISSAL_PHRASES):
                    self._proactive_silenced_until = now + 1800.0
                    self._wake_active_until = 0.0
                    console.print("[dim]Polite Boundary: Nemo proactive speaking silenced for 30m.[/dim]")
                    if self.panel:
                        self.panel.update_status("sleeping", "Nemo: Kept Quiet (Paused)")
                    if self.tts:
                        self.tts.speak("Sorry! I'll keep quiet. Let me know when you need me.")
                    continue

                if has_wake:
                    self._wake_active_until = now + self.WAKE_WINDOW_SEC
                    console.print(f"[bold cyan][HEARD][/bold cyan] Wake word detected: '{text}'")
                    if self.panel:
                        self.panel.update_status("listening", "Hearing command...")

                    if command:
                        console.print(f"\n[bold green][VOICE TASK][/bold green] Executing: '[bold]{command}[/bold]'")
                        self._wake_active_until = 0.0
                        self.task_queue.submit_command(command)
                elif is_currently_awake and text.strip():
                    console.print(f"\n[bold green][VOICE TASK][/bold green] Follow-up command: '[bold]{text}[/bold]'")
                    self._wake_active_until = 0.0
                    self.task_queue.submit_command(text)
                else:
                    disp = text if len(text) <= 60 else text[:57] + "..."
                    console.print(f"[dim]🎤 [Mic Heard]: \"{disp}\" [italic](Say 'Nemo, ...' or type below)[/italic][/dim]")
                    if self.panel:
                        short_disp = text if len(text) <= 22 else text[:19] + "..."
                        self.panel.update_status("idle", f"Heard: {short_disp}")

            except Exception as e:
                logger.error("Error transcribing speech chunk: %s", e)

    def _stdin_worker_loop(self) -> None:
        """Allow typing commands directly into the terminal while voice is active."""
        import sys
        console.print("[dim]⌨️  Interactive Mode: You can speak [bold cyan]'Nemo ...'[/bold cyan] or type commands directly into this terminal.[/dim]\n")
        while not self._stop_event.is_set():
            try:
                line = sys.stdin.readline()
                if not line:
                    time.sleep(0.2)
                    continue
                cmd = line.strip()
                if cmd:
                    console.print(f"\n[bold green][TERMINAL COMMAND][/bold green] Executing: '[bold]{cmd}[/bold]'")
                    self.task_queue.submit_command(cmd)
            except Exception as ex:
                logger.debug("Terminal input ended: %s", ex)
                break

    def _proactive_worker_loop(self) -> None:
        """Periodic background companion that checks for knowledge gaps and deepens memory."""
        inquiry_questions = [
            "Hey Omkar, quick question for my memory graph — which test runner do you prefer for our Python tests?",
            "Hey Omkar, would you like me to keep automatic project backups on D: drive?",
            "Hey Omkar, are you planning to deploy our landing page to Netlify or host it locally?",
            "Hey Omkar, should I keep terminal status outputs minimal or verbose?",
        ]
        q_idx = 0
        while not self._stop_event.is_set():
            time.sleep(10.0)
            now = time.time()
            if not self.enable_proactive or not self.tts:
                continue

            # Respect polite boundary cooldown
            if now < self._proactive_silenced_until:
                continue

            # Check if idle for at least 120s
            is_idle = (
                not self.task_queue.tasks or 
                all(t.status in ("completed", "cancelled", "failed") for t in self.task_queue.tasks)
            )
            if is_idle and (now - self._last_proactive_checkin) > 120.0:
                self._last_proactive_checkin = now
                question = inquiry_questions[q_idx % len(inquiry_questions)]
                q_idx += 1
                console.print(f"\n[bold cyan][NEMO INQUIRY][/bold cyan] {question}")
                if self.panel:
                    self.panel.update_status("listening", "Nemo: Inquiring...")
                self.tts.speak(question)
                self._wake_active_until = now + 15.0

    def _on_agent_step(self, event: dict[str, Any]) -> None:
        """Handle real-time step streaming, thoughts, and outcomes from AgentOrchestrator."""
        etype = event.get("type")

        if etype == "thought":
            thought_text = event.get("content", "").strip()
            if thought_text:
                console.print(f"[dim italic]🤔 Thinking: {thought_text}[/dim italic]")

        elif etype == "tool_start":
            tool_name = event.get("tool", "")
            args_str = str(event.get("arguments", {}))
            console.print(f"[bold yellow]⚡ Action:[/bold yellow] [bold cyan]{tool_name}[/bold cyan] [dim]{args_str}[/dim]")
            if self.panel:
                self.panel.update_status("working", f"Tool: {tool_name}")

        elif etype == "tool_end":
            success = event.get("success", True)
            icon = "[bold green]✓[/bold green]" if success else "[bold red]✗[/bold red]"
            data = event.get("data")
            err = event.get("error")
            note = ""
            if isinstance(data, dict) and "note" in data:
                note = data["note"]
            elif data:
                note = str(data)[:90]
            elif err:
                note = str(err)[:90]
            console.print(f" {icon} [dim]{note}[/dim]")

        elif etype == "finish":
            answer = event.get("answer", "Task complete.")
            console.print(Panel(Markdown(answer), title="[bold cyan]💬 NEMO[/bold cyan]", border_style="cyan"))
            if self.panel:
                self.panel.update_status("completed", "Done ✓")
            if self.tts:
                self.tts.speak(answer)

    def _on_queue_state_change(self, state: str, message: str) -> None:
        """Relay task queue state updates to taskbar action pill and console."""
        pill_state = "idle"
        if state == "working":
            pill_state = "working"
        elif "Complete" in message:
            pill_state = "completed"
            console.print(f"[bold green]✓ {message}[/bold green]")
        elif state == "listening":
            pill_state = "listening"

        if self.panel:
            self.panel.update_status(pill_state, message)
