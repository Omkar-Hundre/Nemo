"""Unit tests for Voice Daemon, Local Whisper Engine, SAPI TTS, and Paint Drawing."""

# 1. Standard library imports
import asyncio
from unittest.mock import MagicMock, patch

# 2. Third-party imports
import pytest

# 3. Local imports
from nemo.tools.builtin import WindowsDesktopTool
from nemo.voice.audio import AudioCaptureService
from nemo.voice.autostart import is_autostart_enabled, set_autostart
from nemo.voice.engine import WhisperVoiceEngine
from nemo.voice.panel import ActionPanelPill
from nemo.voice.queue import IdempotentTaskQueue, NemoTask
from nemo.voice.tts import NemoTtsEngine


class TestVoiceEngine:
    def test_wake_word_parsing(self):
        engine = WhisperVoiceEngine.__new__(WhisperVoiceEngine)
        engine.WAKE_WORDS = ["nemo", "hey nemo", "ok nemo", "hi nemo", "namo", "nemu"]

        # Exact prefix match
        has_wake, cmd = engine.parse_wake_word("nemo set a timer of 10 seconds")
        assert has_wake is True
        assert cmd == "set a timer of 10 seconds"

        # Hey Nemo variant
        has_wake, cmd = engine.parse_wake_word("hey nemo, take a webcam snapshot!")
        assert has_wake is True
        assert cmd == "take a webcam snapshot"

        # Namo variant (phonetic support requested by user)
        has_wake, cmd = engine.parse_wake_word("namo stop")
        assert has_wake is True
        assert cmd == "stop"

        # No wake word
        has_wake, cmd = engine.parse_wake_word("what is the weather today")
        assert has_wake is False
        assert cmd == "what is the weather today"


class TestIdempotentTaskQueue:
    def test_tier1_cancel_keywords(self):
        state_mock = MagicMock()
        queue = IdempotentTaskQueue(on_state_change=state_mock)

        result = queue.submit_command("stop")
        assert result is None
        state_mock.assert_called_with("sleeping", "Tasks Cancelled")

        result2 = queue.submit_command("cancel")
        assert result2 is None

    def test_tier2_status_keywords(self):
        state_mock = MagicMock()
        queue = IdempotentTaskQueue(on_state_change=state_mock)

        result = queue.submit_command("what is running")
        assert result is None
        state_mock.assert_called_with("sleeping", "All tasks idle")

    def test_tier3_deduplication(self):
        queue = IdempotentTaskQueue()

        task1 = queue.submit_command("set a timer of 10 seconds")
        assert task1 is not None
        assert task1.name == "set a timer of 10 seconds"

        # Duplicate command within 15 seconds should be rejected
        task2 = queue.submit_command("set a timer of 10 seconds")
        assert task2 is None

    def test_task_cancellation(self):
        queue = IdempotentTaskQueue()
        task = queue.submit_command("play some music in my system")
        assert task is not None
        assert task.status == "queued"

        cancelled = queue.cancel_task(task.id)
        assert cancelled is True
        assert task.status == "cancelled"


class TestAutostart:
    def test_autostart_toggle(self):
        assert set_autostart(False) is True
        assert is_autostart_enabled() is False

        assert set_autostart(True) is True
        assert is_autostart_enabled() is True

        # Clean up
        set_autostart(False)
        assert is_autostart_enabled() is False


class TestActionPanelPill:
    def test_panel_initialization_and_colors(self):
        pill = ActionPanelPill()
        assert "idle" in pill.COLORS
        assert "listening" in pill.COLORS
        assert "working" in pill.COLORS
        assert "completed" in pill.COLORS
        assert pill.WIDTH == 280
        assert pill.HEIGHT == 46


class TestTtsEngine:
    def test_clean_for_speech(self):
        raw = "```python\nprint('hello')\n```\nHere is your **solution** at [website](https://example.com)!"
        cleaned = NemoTtsEngine._clean_for_speech(raw)
        assert "```" not in cleaned
        assert "**" not in cleaned
        assert "solution" in cleaned
        assert "https://" not in cleaned

    def test_verbose_truncation(self):
        verbose = "Sentence one. " * 30
        cleaned = NemoTtsEngine._clean_for_speech(verbose)
        assert len(cleaned) <= 300


class TestPaintDrawTool:
    @pytest.mark.asyncio
    async def test_paint_draw_square(self):
        tool = WindowsDesktopTool()
        with patch("subprocess.Popen") as mock_popen, \
             patch("win32gui.EnumWindows"), \
             patch("win32api.SetCursorPos"), \
             patch("win32api.mouse_event"):
            mock_proc = MagicMock()
            mock_proc.pid = 9999
            mock_popen.return_value = mock_proc

            res = await tool.execute({"action": "paint_draw", "shape": "square", "size": 180}, {})
            assert res.success is True
            assert res.data["action"] == "paint_draw"
            assert res.data["shape"] == "square"
            assert "Square" in res.data["note"]

    @pytest.mark.asyncio
    async def test_paint_draw_hut_and_triangle_over(self):
        tool = WindowsDesktopTool()
        with patch("subprocess.Popen"), \
             patch("win32gui.EnumWindows"), \
             patch("win32api.SetCursorPos"), \
             patch("win32api.mouse_event"):
            res_hut = await tool.execute({"action": "paint_draw", "shape": "hut", "size": 200}, {})
            assert res_hut.success is True
            assert "hut" in res_hut.data["note"].lower()

            res_tri = await tool.execute({"action": "paint_draw", "shape": "triangle_over", "size": 200}, {})
            assert res_tri.success is True
            assert res_tri.data["shape"] == "triangle_over"

            res_heart = await tool.execute({"action": "paint_draw", "shape": "heart", "size": 200}, {})
            assert res_heart.success is True
            assert res_heart.data["shape"] == "heart"

    @pytest.mark.asyncio
    async def test_paint_svg_rasterize_and_open(self, tmp_path):
        tool = WindowsDesktopTool()
        svg_file = tmp_path / "art.svg"
        svg_file.write_text("<svg><rect width='10' height='10'/></svg>")
        with patch.object(WindowsDesktopTool, "_rasterize_svg_to_png") as mock_rast, \
             patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.pid = 4321
            mock_popen.return_value = mock_proc
            mock_rast.return_value = tmp_path / "art.png"

            res = await tool.execute({"action": "open_in_paint", "path": str(svg_file)}, {"working_directory": tmp_path})
            assert res.success is True
            assert mock_rast.called
            assert "art.png" in res.data["image_path"]

    @pytest.mark.asyncio
    async def test_open_youtube_autoplay(self):
        tool = WindowsDesktopTool()
        with patch("subprocess.Popen") as mock_popen, \
             patch("webbrowser.open") as mock_wb, \
             patch("urllib.request.urlopen") as mock_urlopen:
            mock_proc = MagicMock()
            mock_proc.pid = 1234
            mock_popen.return_value = mock_proc

            mock_resp = MagicMock()
            mock_resp.read.return_value = b'{"videoId":"dQw4w9WgXcQ"}'
            mock_resp.__enter__.return_value = mock_resp
            mock_urlopen.return_value = mock_resp

            res = await tool.execute({"action": "open_youtube", "query": "rickroll"}, {})
            assert res.success is True
            assert "watch?v=dQw4w9WgXcQ&autoplay=1" in res.data["url"]
            assert res.data["status"] == "playing"
