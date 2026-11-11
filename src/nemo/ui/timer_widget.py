"""Always-on-top, configurable floating Desktop Timer & Pomodoro Widget."""

# 1. Standard library imports
import argparse
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import font as tkfont
import winsound

# 2. Third-party imports
# (None - pure standard library for instant zero-dependency execution)

# Constants & Palette
BG_COLOR = "#18181b"       # Zinc-900 dark obsidian
CARD_BG = "#27272a"        # Zinc-800
TEXT_MAIN = "#fafafa"      # Pure white
TEXT_MUTED = "#a1a1aa"     # Zinc-400
ACCENT_FOCUS = "#06b6d4"   # Neon Cyan
ACCENT_BREAK = "#10b981"   # Emerald Green
ACCENT_ALARM = "#ef4444"   # Vivid Red
ACCENT_PAUSE = "#f59e0b"   # Amber
ALARM_SOUND_PATH = r"C:\Windows\Media\Alarm01.wav"


class FloatingTimerWidget:
    """Always-on-top floating desktop widget supporting standard timers and configurable Pomodoro cycles."""

    def __init__(
        self,
        mode: str = "timer",
        minutes: float = 25.0,
        focus_minutes: float = 25.0,
        break_minutes: float = 5.0,
        long_break_minutes: float = 15.0,
        cycles: int = 4,
        title: str = "Timer",
    ) -> None:
        self.mode = mode.lower().strip()
        self.initial_timer_seconds = int(max(1.0, minutes) * 60)
        self.focus_seconds = int(max(1.0, focus_minutes) * 60)
        self.break_seconds = int(max(1.0, break_minutes) * 60)
        self.long_break_seconds = int(max(1.0, long_break_minutes) * 60)
        self.total_cycles = max(1, cycles)
        self.current_cycle = 1
        self.custom_title = title

        # Internal state
        self.is_running = True
        self.is_paused = False
        self.is_alarm_ringing = False
        self.current_phase = "FOCUS" if self.mode == "pomodoro" else "TIMER"
        self.remaining_seconds = (
            self.focus_seconds if self.mode == "pomodoro" else self.initial_timer_seconds
        )

        # Drag tracking
        self._drag_start_x = 0
        self._drag_start_y = 0

        # Build UI
        self._build_ui()

    def _build_ui(self) -> None:
        self.root = tk.Tk()
        self.root.title(f"NEMO - {self.custom_title}")
        self.root.geometry("320x210")
        self.root.configure(bg=BG_COLOR)
        self.root.attributes("-topmost", True)
        self.root.resizable(False, False)

        # Position at bottom-right of screen by default
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        pos_x = max(20, screen_w - 360)
        pos_y = max(40, screen_h - 300)
        self.root.geometry(f"320x210+{pos_x}+{pos_y}")

        # Enable dragging by clicking anywhere on the background
        self.root.bind("<ButtonPress-1>", self._on_drag_start)
        self.root.bind("<B1-Motion>", self._on_drag_motion)

        # Main container card
        self.card = tk.Frame(self.root, bg=BG_COLOR, padx=16, pady=12)
        self.card.pack(fill=tk.BOTH, expand=True)

        # Top Bar: Phase badge & cycle counter
        self.top_bar = tk.Frame(self.card, bg=BG_COLOR)
        self.top_bar.pack(fill=tk.X, pady=(0, 6))

        self.phase_badge = tk.Label(
            self.top_bar,
            text=self._get_badge_text(),
            font=("Segoe UI", 10, "bold"),
            bg=CARD_BG,
            fg=ACCENT_FOCUS,
            padx=8,
            pady=2,
        )
        self.phase_badge.pack(side=tk.LEFT)

        self.close_btn = tk.Button(
            self.top_bar,
            text="✕",
            font=("Segoe UI", 10, "bold"),
            bg=BG_COLOR,
            fg=TEXT_MUTED,
            bd=0,
            activebackground=ACCENT_ALARM,
            activeforeground=TEXT_MAIN,
            cursor="hand2",
            command=self._on_close,
        )
        self.close_btn.pack(side=tk.RIGHT)

        # Main Digital Countdown
        self.time_label = tk.Label(
            self.card,
            text=self._format_time(self.remaining_seconds),
            font=("Consolas", 38, "bold"),
            bg=BG_COLOR,
            fg=TEXT_MAIN,
        )
        self.time_label.pack(pady=(4, 8))

        # Controls Row
        self.btn_frame = tk.Frame(self.card, bg=BG_COLOR)
        self.btn_frame.pack(fill=tk.X, pady=(4, 0))

        self.main_btn = tk.Button(
            self.btn_frame,
            text="Pause",
            font=("Segoe UI", 10, "bold"),
            bg=CARD_BG,
            fg=ACCENT_FOCUS,
            bd=0,
            padx=12,
            pady=6,
            cursor="hand2",
            command=self._toggle_pause,
        )
        self.main_btn.pack(side=tk.LEFT, padx=(0, 4), expand=True, fill=tk.X)

        self.reset_btn = tk.Button(
            self.btn_frame,
            text="Reset",
            font=("Segoe UI", 10),
            bg=CARD_BG,
            fg=TEXT_MUTED,
            bd=0,
            padx=10,
            pady=6,
            cursor="hand2",
            command=self._reset,
        )
        self.reset_btn.pack(side=tk.LEFT, padx=4, expand=True, fill=tk.X)

        if self.mode == "pomodoro":
            self.skip_btn = tk.Button(
                self.btn_frame,
                text="Skip ⏭",
                font=("Segoe UI", 10),
                bg=CARD_BG,
                fg=TEXT_MUTED,
                bd=0,
                padx=8,
                pady=6,
                cursor="hand2",
                command=self._skip_phase,
            )
            self.skip_btn.pack(side=tk.LEFT, padx=(4, 0), expand=True, fill=tk.X)
        else:
            self.plus_btn = tk.Button(
                self.btn_frame,
                text="+1m",
                font=("Segoe UI", 10),
                bg=CARD_BG,
                fg=TEXT_MUTED,
                bd=0,
                padx=8,
                pady=6,
                cursor="hand2",
                command=lambda: self._adjust_time(60),
            )
            self.plus_btn.pack(side=tk.LEFT, padx=(4, 0), expand=True, fill=tk.X)

        # Kickoff timer loop
        self.root.after(1000, self._timer_tick)

    def _on_drag_start(self, event: tk.Event) -> None:
        self._drag_start_x = event.x
        self._drag_start_y = event.y

    def _on_drag_motion(self, event: tk.Event) -> None:
        delta_x = event.x - self._drag_start_x
        delta_y = event.y - self._drag_start_y
        new_x = self.root.winfo_x() + delta_x
        new_y = self.root.winfo_y() + delta_y
        self.root.geometry(f"+{new_x}+{new_y}")

    def _format_time(self, seconds: int) -> str:
        mins, secs = divmod(max(0, seconds), 60)
        hours, mins = divmod(mins, 60)
        if hours > 0:
            return f"{hours:02d}:{mins:02d}:{secs:02d}"
        return f"{mins:02d}:{secs:02d}"

    def _get_badge_text(self) -> str:
        if self.is_alarm_ringing:
            return "⏰ TIME'S UP!"
        if self.mode == "pomodoro":
            phase_name = "FOCUS" if self.current_phase == "FOCUS" else "BREAK"
            return f"{phase_name} • {self.current_cycle}/{self.total_cycles}"
        return f"TIMER • {self.custom_title}"

    def _timer_tick(self) -> None:
        if self.is_running and not self.is_paused and not self.is_alarm_ringing:
            self.remaining_seconds -= 1
            self.time_label.config(text=self._format_time(self.remaining_seconds))

            if self.remaining_seconds <= 0:
                self._trigger_alarm()

        # Schedule next tick in 1 second
        if self.is_running:
            self.root.after(1000, self._timer_tick)

    def _trigger_alarm(self) -> None:
        """Trigger hard ringing alarm and visual alert."""
        self.is_alarm_ringing = True
        self.root.attributes("-topmost", True)
        self.root.lift()

        # Update visuals
        self.time_label.config(text="00:00", fg=ACCENT_ALARM)
        self.phase_badge.config(text="⏰ TIME'S UP!", bg=ACCENT_ALARM, fg=TEXT_MAIN)
        self.main_btn.config(
            text="STOP ALARM",
            bg=ACCENT_ALARM,
            fg=TEXT_MAIN,
            font=("Segoe UI", 11, "bold"),
        )

        # Start continuous looping alarm sound in background thread
        threading.Thread(target=self._play_alarm_sound_loop, daemon=True).start()

    def _play_alarm_sound_loop(self) -> None:
        """Play continuous loud alarm sound until dismissed."""
        sound_file = ALARM_SOUND_PATH if Path(ALARM_SOUND_PATH).exists() else None
        while self.is_alarm_ringing:
            try:
                if sound_file:
                    winsound.PlaySound(sound_file, winsound.SND_FILENAME)
                else:
                    winsound.Beep(1200, 400)
                    time.sleep(0.1)
                    winsound.Beep(1600, 400)
                    time.sleep(0.3)
            except Exception:
                time.sleep(1)

    def _stop_alarm(self) -> None:
        """Silence alarm sound and advance to next phase."""
        self.is_alarm_ringing = False
        try:
            winsound.PlaySound(None, winsound.SND_PURGE)
        except Exception:
            pass

        if self.mode == "pomodoro":
            self._advance_pomodoro()
        else:
            self.remaining_seconds = self.initial_timer_seconds
            self.is_paused = True
            self._update_display_state()

    def _advance_pomodoro(self) -> None:
        """Transition Pomodoro state machine (Focus -> Break -> Next Cycle)."""
        if self.current_phase == "FOCUS":
            # Focus ended -> check if long break or short break
            if self.current_cycle >= self.total_cycles:
                self.current_phase = "LONG_BREAK"
                self.remaining_seconds = self.long_break_seconds
            else:
                self.current_phase = "SHORT_BREAK"
                self.remaining_seconds = self.break_seconds
        else:
            # Break ended -> back to Focus of next cycle
            if self.current_phase == "LONG_BREAK":
                self.current_cycle = 1
            else:
                self.current_cycle += 1
            self.current_phase = "FOCUS"
            self.remaining_seconds = self.focus_seconds

        self.is_paused = False
        self._update_display_state()

    def _update_display_state(self) -> None:
        """Refresh colors, badge, and labels based on current state."""
        color = ACCENT_FOCUS if self.current_phase == "FOCUS" else ACCENT_BREAK
        if self.is_paused:
            color = ACCENT_PAUSE

        self.phase_badge.config(text=self._get_badge_text(), bg=CARD_BG, fg=color)
        self.time_label.config(text=self._format_time(self.remaining_seconds), fg=TEXT_MAIN)
        self.main_btn.config(
            text="Resume" if self.is_paused else "Pause",
            bg=CARD_BG,
            fg=color,
            font=("Segoe UI", 10, "bold"),
        )

    def _toggle_pause(self) -> None:
        if self.is_alarm_ringing:
            self._stop_alarm()
            return

        self.is_paused = not self.is_paused
        self._update_display_state()

    def _reset(self) -> None:
        if self.is_alarm_ringing:
            self._stop_alarm()

        if self.mode == "pomodoro":
            self.remaining_seconds = (
                self.focus_seconds if self.current_phase == "FOCUS" else self.break_seconds
            )
        else:
            self.remaining_seconds = self.initial_timer_seconds

        self.is_paused = True
        self._update_display_state()

    def _adjust_time(self, seconds_delta: int) -> None:
        if not self.is_alarm_ringing:
            self.remaining_seconds = max(10, self.remaining_seconds + seconds_delta)
            self.time_label.config(text=self._format_time(self.remaining_seconds))

    def _skip_phase(self) -> None:
        if self.is_alarm_ringing:
            self._stop_alarm()
        self._advance_pomodoro()

    def _on_close(self) -> None:
        self.is_running = False
        self.is_alarm_ringing = False
        try:
            winsound.PlaySound(None, winsound.SND_PURGE)
        except Exception:
            pass
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def launch_timer_widget_process(
    mode: str = "timer",
    minutes: float = 25.0,
    focus: float = 25.0,
    break_min: float = 5.0,
    long_break: float = 15.0,
    cycles: int = 4,
    title: str = "Timer",
) -> subprocess.Popen:
    """Launch the floating timer widget in an independent detached process."""
    cmd = [
        sys.executable,
        "-m",
        "nemo.ui.timer_widget",
        "--mode",
        mode,
        "--minutes",
        str(minutes),
        "--focus",
        str(focus),
        "--break-min",
        str(break_min),
        "--long-break",
        str(long_break),
        "--cycles",
        str(cycles),
        "--title",
        title,
    ]
    # On Windows, DETACHED_PROCESS flag allows it to run completely independently
    creation_flags = 0x00000008 if sys.platform == "win32" else 0
    proc = subprocess.Popen(
        cmd,
        creationflags=creation_flags,
        close_fds=True,
    )
    return proc


def main() -> None:
    parser = argparse.ArgumentParser(description="NEMO Floating Desktop Timer & Pomodoro Widget")
    parser.add_argument("--mode", default="timer", choices=["timer", "pomodoro"], help="Widget mode")
    parser.add_argument("--minutes", type=float, default=25.0, help="Timer duration in minutes")
    parser.add_argument("--focus", type=float, default=25.0, help="Pomodoro focus duration in minutes")
    parser.add_argument("--break-min", type=float, default=5.0, help="Pomodoro short break duration in minutes")
    parser.add_argument("--long-break", type=float, default=15.0, help="Pomodoro long break duration in minutes")
    parser.add_argument("--cycles", type=int, default=4, help="Pomodoro cycles before long break")
    parser.add_argument("--title", default="Timer", help="Custom title label")

    args = parser.parse_args()

    widget = FloatingTimerWidget(
        mode=args.mode,
        minutes=args.minutes,
        focus_minutes=args.focus,
        break_minutes=args.break_min,
        long_break_minutes=args.long_break,
        cycles=args.cycles,
        title=args.title,
    )
    widget.run()


if __name__ == "__main__":
    main()
