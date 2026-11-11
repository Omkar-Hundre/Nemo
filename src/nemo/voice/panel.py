"""Minimal, non-intrusive bottom-right Action Panel Pill for Nemo Voice Assistant."""

# 1. Standard library imports
import logging
import threading
import tkinter as tk
from typing import Any, Callable

# 2. Third-party imports
# (None - pure standard library)

logger = logging.getLogger(__name__)


class ActionPanelPill:
    """Lightweight, zero-bloat status pill anchored to the Windows taskbar / action panel area."""

    WIDTH = 280
    HEIGHT = 46

    COLORS = {
        "idle": {"dot": "#64748b", "text": "#94a3b8", "bg": "#0f172a"},
        "listening": {"dot": "#ff6f00", "text": "#ffedd5", "bg": "#1e1b18"},
        "working": {"dot": "#00e5ff", "text": "#e0f2fe", "bg": "#0c1e28"},
        "completed": {"dot": "#00e676", "text": "#dcfce7", "bg": "#0a2318"},
    }

    def __init__(self, on_cancel: Callable[[], Any] | None = None) -> None:
        self.on_cancel = on_cancel
        self.root: tk.Tk | None = None
        self._dot_canvas: tk.Canvas | None = None
        self._label: tk.Label | None = None
        self._current_state = "idle"
        self._current_message = "Nemo Active"
        self._ready_event = threading.Event()

    def start(self, block: bool = True) -> None:
        """Create and launch the bottom-right taskbar pill."""
        self.root = tk.Tk()
        self.root.title("NEMO Action Pill")

        # Borderless and always on top
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg="#334155")  # Border color

        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()

        # Place right above Windows taskbar / Action Center in bottom right
        x = max(10, screen_w - self.WIDTH - 24)
        y = max(10, screen_h - self.HEIGHT - 55)
        self.root.geometry(f"{self.WIDTH}x{self.HEIGHT}+{x}+{y}")

        # Main inner frame
        inner = tk.Frame(self.root, bg="#0f172a", highlightthickness=0)
        inner.pack(fill="both", expand=True, padx=1, pady=1)

        # Dot indicator
        self._dot_canvas = tk.Canvas(inner, width=16, height=16, bg="#0f172a", highlightthickness=0)
        self._dot_canvas.pack(side="left", padx=(12, 6))
        self._draw_dot(self.COLORS["idle"]["dot"])

        # Text label
        self._label = tk.Label(
            inner,
            text=self._current_message,
            fg="#94a3b8",
            bg="#0f172a",
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        )
        self._label.pack(side="left", fill="x", expand=True)

        # Small close / dismiss button
        close_btn = tk.Label(
            inner,
            text="✕",
            fg="#64748b",
            bg="#0f172a",
            font=("Segoe UI", 9),
            cursor="hand2",
            padx=8,
        )
        close_btn.pack(side="right")
        close_btn.bind("<Button-1>", lambda e: self._handle_close())

        self._ready_event.set()

        if block:
            try:
                self.root.mainloop()
            except KeyboardInterrupt:
                self.stop()

    def update_status(self, state: str, message: str) -> None:
        """Thread-safe update of pill status and colors."""
        if not self.root:
            return

        def _do_update():
            if not self.root or not self._label:
                return
            config = self.COLORS.get(state, self.COLORS["idle"])
            self._current_state = state
            self._current_message = message

            # Truncate text cleanly if too long
            disp_text = message if len(message) <= 28 else message[:25] + "..."
            self._label.config(text=disp_text, fg=config["text"])
            self._draw_dot(config["dot"])

        try:
            self.root.after(0, _do_update)
        except Exception as e:
            logger.debug("Pill UI update skipped: %s", e)

    def stop(self) -> None:
        """Close the pill window."""
        if self.root:
            try:
                self.root.quit()
                self.root.destroy()
            except Exception:
                pass
            self.root = None

    def _draw_dot(self, color: str) -> None:
        if not self._dot_canvas:
            return
        self._dot_canvas.delete("all")
        self._dot_canvas.create_oval(3, 3, 13, 13, fill=color, outline="")

    def _handle_close(self) -> None:
        if self.on_cancel:
            self.on_cancel()
        self.stop()
