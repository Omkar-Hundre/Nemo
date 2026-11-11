"""Unit tests for Voice Daemon, Local Whisper Engine, and Floating Avatar UI."""

# 1. Standard library imports
import asyncio
from unittest.mock import MagicMock, patch

# 2. Third-party imports
import pytest

# 3. Local imports
from nemo.voice.audio import AudioCaptureService
from nemo.voice.autostart import is_autostart_enabled, set_autostart
from nemo.voice.engine import WhisperVoiceEngine
from nemo.voice.queue import IdempotentTaskQueue, NemoTask
from nemo.ui.avatar import NemoAvatarWindow, NemoJsApi


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
        tasks_mock = MagicMock()
        queue = IdempotentTaskQueue(on_state_change=state_mock, on_tasks_updated=tasks_mock)

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
        # Test enabling and disabling auto-start
        assert set_autostart(False) is True
        assert is_autostart_enabled() is False

        assert set_autostart(True) is True
        assert is_autostart_enabled() is True

        # Clean up
        set_autostart(False)
        assert is_autostart_enabled() is False


class TestAvatarWindowApi:
    def test_js_api_delegation(self):
        on_cmd = MagicMock()
        on_cancel = MagicMock()
        on_voice = MagicMock()

        avatar_mock = MagicMock()
        api = NemoJsApi(
            avatar_window=avatar_mock,
            on_command=on_cmd,
            on_cancel=on_cancel,
            on_voice_toggle=on_voice,
        )

        api.expand_window()
        avatar_mock.expand.assert_called_once()

        api.collapse_window()
        avatar_mock.collapse.assert_called_once()

        api.execute_command("take a webcam snapshot")
        on_cmd.assert_called_with("take a webcam snapshot")

        api.cancel_task("task-123")
        on_cancel.assert_called_with("task-123")

        api.toggle_voice(True)
        on_voice.assert_called_with(True)
