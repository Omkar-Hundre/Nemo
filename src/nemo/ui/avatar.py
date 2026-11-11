"""Floating Finding Nemo desktop avatar window and process controller GUI."""

# 1. Standard library imports
import json
import logging
from pathlib import Path
import subprocess
import threading
import time
from typing import Any, Callable

# 2. Third-party imports
import webview
import win32api
import win32con
import win32gui

# 3. Local imports
# (None)

logger = logging.getLogger(__name__)


class NemoJsApi:
    """RPC bridge between Webview JavaScript frontend and Python backend."""

    def __init__(
        self,
        avatar_window: "NemoAvatarWindow",
        on_command: Callable[[str], Any] | None = None,
        on_cancel: Callable[[str], Any] | None = None,
        on_voice_toggle: Callable[[bool], Any] | None = None,
    ) -> None:
        self.avatar_window = avatar_window
        self.on_command = on_command
        self.on_cancel = on_cancel
        self.on_voice_toggle = on_voice_toggle

    def expand_window(self) -> None:
        """Expand avatar to full Process Manager GUI."""
        self.avatar_window.expand()

    def collapse_window(self) -> None:
        """Collapse Process Manager back to floating avatar."""
        self.avatar_window.collapse()

    def execute_command(self, cmd_text: str) -> None:
        """Dispatch user typed command into task pipeline."""
        if self.on_command:
            self.on_command(cmd_text)

    def cancel_task(self, task_id: str) -> None:
        """Cancel active task."""
        if self.on_cancel:
            self.on_cancel(task_id)

    def open_terminal(self) -> None:
        """Launch Windows Terminal."""
        try:
            subprocess.Popen(["wt.exe"], shell=False)
        except Exception:
            subprocess.Popen(["powershell.exe"], shell=False)

    def toggle_voice(self, enabled: bool) -> None:
        """Toggle local voice recognition."""
        if self.on_voice_toggle:
            self.on_voice_toggle(enabled)


class NemoAvatarWindow:
    """Manages the borderless transparent always-on-top desktop avatar and modal GUI."""

    COMPACT_WIDTH = 340
    COMPACT_HEIGHT = 175
    EXPANDED_WIDTH = 640
    EXPANDED_HEIGHT = 460

    def __init__(
        self,
        on_command: Callable[[str], Any] | None = None,
        on_cancel: Callable[[str], Any] | None = None,
        on_voice_toggle: Callable[[bool], Any] | None = None,
    ) -> None:
        self.on_command = on_command
        self.on_cancel = on_cancel
        self.on_voice_toggle = on_voice_toggle
        self.window: webview.Window | None = None
        self.is_expanded = False
        self._auto_hidden_for_fullscreen = False
        self._stop_event = threading.Event()
        self._monitor_thread: threading.Thread | None = None

        # Resolve assets path
        self.assets_dir = Path(__file__).parent / "assets"
        self.index_html_path = self.assets_dir / "index.html"

    def start(self, block: bool = True) -> None:
        """Initialize and launch the pywebview transparent desktop window."""
        screen_w = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        screen_h = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)

        # Bottom right placement (above taskbar)
        initial_x = max(10, screen_w - self.COMPACT_WIDTH - 24)
        initial_y = max(10, screen_h - self.COMPACT_HEIGHT - 65)

        api = NemoJsApi(
            self,
            on_command=self.on_command,
            on_cancel=self.on_cancel,
            on_voice_toggle=self.on_voice_toggle,
        )

        self.window = webview.create_window(
            title="Nemo Desktop Avatar",
            url=str(self.index_html_path.resolve()),
            js_api=api,
            width=self.COMPACT_WIDTH,
            height=self.COMPACT_HEIGHT,
            x=initial_x,
            y=initial_y,
            frameless=True,
            transparent=True,
            on_top=True,
            resizable=False,
            easy_drag=True,
        )

        # Start background monitor for fullscreen apps (movies/games auto-hide)
        self._monitor_thread = threading.Thread(target=self._monitor_fullscreen_loop, daemon=True)
        self._monitor_thread.start()

        if block:
            webview.start(debug=False)

    def expand(self) -> None:
        """Resize and reposition for Process Manager GUI."""
        if not self.window:
            return
        self.is_expanded = True
        screen_w = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        screen_h = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
        new_x = max(10, screen_w - self.EXPANDED_WIDTH - 24)
        new_y = max(10, screen_h - self.EXPANDED_HEIGHT - 65)
        self.window.resize(self.EXPANDED_WIDTH, self.EXPANDED_HEIGHT)
        self.window.move(new_x, new_y)

    def collapse(self) -> None:
        """Resize and reposition back to compact avatar."""
        if not self.window:
            return
        self.is_expanded = False
        screen_w = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        screen_h = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
        new_x = max(10, screen_w - self.COMPACT_WIDTH - 24)
        new_y = max(10, screen_h - self.COMPACT_HEIGHT - 65)
        self.window.resize(self.COMPACT_WIDTH, self.COMPACT_HEIGHT)
        self.window.move(new_x, new_y)

    def set_state(self, state: str, message: str) -> None:
        """Update fish animation state and status pill text.
        
        Args:
            state: "sleeping", "listening", or "working".
            message: Text to display in status pill.
        """
        if not self.window:
            return
        safe_msg = message.replace("'", "\\'").replace("\n", " ")
        js = f"updateState('{state}', '{safe_msg}');"
        try:
            self.window.evaluate_js(js)
        except Exception as e:
            logger.debug("Failed to evaluate state JS: %s", e)

    def update_tasks(self, tasks: list[dict[str, Any]]) -> None:
        """Update active tasks list inside process controller GUI."""
        if not self.window:
            return
        tasks_json = json.dumps(tasks)
        js = f"renderTaskList({tasks_json});"
        try:
            self.window.evaluate_js(js)
        except Exception as e:
            logger.debug("Failed to evaluate tasks JS: %s", e)

    def close(self) -> None:
        """Destroy window and terminate monitor thread."""
        self._stop_event.set()
        if self.window:
            self.window.destroy()

    def _monitor_fullscreen_loop(self) -> None:
        """Detect fullscreen movies, YouTube, games, or presentation windows and auto-hide."""
        while not self._stop_event.is_set():
            time.sleep(1.0)
            if not self.window:
                continue

            try:
                hwnd = win32gui.GetForegroundWindow()
                if not hwnd or not win32gui.IsWindow(hwnd):
                    continue

                # Don't auto-hide if foreground is desktop, taskbar, or our own window
                classname = win32gui.GetClassName(hwnd)
                title = win32gui.GetWindowText(hwnd)
                if classname in ("WorkerW", "Progman", "Shell_TrayWnd") or "Nemo Desktop Avatar" in title:
                    continue

                screen_w = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
                screen_h = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
                rect = win32gui.GetWindowRect(hwnd)

                # Window covers full screen
                is_fullscreen = (
                    rect[0] <= 0
                    and rect[1] <= 0
                    and rect[2] >= screen_w
                    and rect[3] >= screen_h
                )

                if is_fullscreen:
                    if not self._auto_hidden_for_fullscreen:
                        self._auto_hidden_for_fullscreen = True
                        self.window.hide()
                else:
                    if self._auto_hidden_for_fullscreen:
                        self._auto_hidden_for_fullscreen = False
                        self.window.show()
            except Exception as e:
                logger.debug("Fullscreen check failed: %s", e)

