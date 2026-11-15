"""Production-grade unit tests for Active File Detection, Smart Messaging, and Windows GUI Automation."""

# 1. Standard library imports
import asyncio
import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

# 2. Third-party imports
import pytest

# 3. Local imports
from nemo.tools.builtin import (
    ActiveFileInspectorTool,
    MessagingDispatchTool,
    WindowsGuiTool,
)
from nemo.voice.queue import IdempotentTaskQueue, NemoTask


class TestActiveFileInspector:
    @pytest.mark.asyncio
    async def test_active_file_inspector_structure(self, tmp_path: Path):
        tool = ActiveFileInspectorTool()
        test_file = tmp_path / "test_doc.pdf"
        test_file.write_text("dummy content")

        with patch.object(ActiveFileInspectorTool, "get_selected_files", return_value=[str(test_file)]):
            res = await tool.execute({"action": "get_selected"}, context={})
            assert res.success is True
            assert res.data["count"] == 1
            assert res.data["primary_file"] == str(test_file)
            assert res.data["details"][0]["name"] == "test_doc.pdf"
            assert res.data["detection_method"] == "explorer_selection"

    @pytest.mark.asyncio
    async def test_active_file_empty_selection(self):
        tool = ActiveFileInspectorTool()
        with patch.object(ActiveFileInspectorTool, "get_selected_files", return_value=[]):
            res = await tool.execute({"action": "get_selected"}, context={})
            assert res.success is True
            assert res.data["count"] == 0
            assert res.data["primary_file"] is None


class TestMessagingDispatchTool:
    def test_schedule_delay_parsing(self):
        tool = MessagingDispatchTool()

        # Relative minutes
        delay_min = tool._parse_schedule_delay("in 15 minutes")
        assert delay_min == 15 * 60.0

        delay_min_short = tool._parse_schedule_delay("in 30m")
        assert delay_min_short == 30 * 60.0

        # Relative hours
        delay_hr = tool._parse_schedule_delay("in 2 hours")
        assert delay_hr == 2 * 3600.0

        # Absolute time
        now = datetime.datetime.now()
        target_h = (now.hour + 1) % 24
        delay_abs = tool._parse_schedule_delay(f"{target_h:02d}:00")
        assert delay_abs is not None
        assert 0 < delay_abs <= 86400

    @pytest.mark.asyncio
    async def test_whatsapp_phone_number_dispatch(self, tmp_path: Path):
        tool = MessagingDispatchTool()
        dummy_file = tmp_path / "quotation.pdf"
        dummy_file.write_text("PDF body")

        with patch("subprocess.Popen") as mock_popen, \
             patch.object(tool, "_focus_app_window", return_value=12345), \
             patch.object(tool, "_copy_file_to_clipboard", return_value=True), \
             patch("pywinauto.keyboard.send_keys") as mock_keys:
            res = await tool.execute({
                "platform": "whatsapp",
                "recipient": "+919876543210",
                "message": "Here is the quotation",
                "file_path": str(dummy_file),
            }, context={})

            assert res.success is True
            assert res.data["delivered"] is True
            assert res.data["platform"] == "whatsapp"
            mock_popen.assert_called()
            # Verify whatsapp://send URI was opened
            called_cmd = mock_popen.call_args[0][0]
            assert "whatsapp://send?phone=919876543210" in called_cmd

    @pytest.mark.asyncio
    async def test_whatsapp_name_search_dispatch(self, tmp_path: Path):
        tool = MessagingDispatchTool()
        dummy_file = tmp_path / "invoice.pdf"
        dummy_file.write_text("Invoice body")

        with patch("subprocess.Popen") as mock_popen, \
             patch.object(tool, "_focus_app_window", return_value=12345), \
             patch("win32gui.GetForegroundWindow", return_value=12345), \
             patch("win32gui.GetWindowText", return_value="WhatsApp"), \
             patch("win32gui.GetClassName", return_value="WinUIDesktopWin32WindowClass"), \
             patch.object(tool, "_copy_file_to_clipboard", return_value=True), \
             patch("pywinauto.keyboard.send_keys") as mock_keys:
            res = await tool.execute({
                "platform": "whatsapp",
                "recipient": "Rohan",
                "message": "Hello Rohan",
                "file_path": str(dummy_file),
            }, context={})

            assert res.success is True
            assert res.data["delivered"] is True
            mock_popen.assert_called()
            # Verify Ctrl+F and contact name were dispatched
            keys_calls = [c[0][0] for c in mock_keys.call_args_list]
            assert "^f" in keys_calls
            assert any("Rohan" in k for k in keys_calls)

    @pytest.mark.asyncio
    async def test_whatsapp_aborts_when_not_focused(self):
        tool = MessagingDispatchTool()
        with patch("subprocess.Popen"), \
             patch.object(tool, "_focus_app_window", return_value=None), \
             patch("pywinauto.keyboard.send_keys") as mock_keys:
            res = await tool.execute({
                "platform": "whatsapp",
                "recipient": "Rohan",
                "message": "Hello Rohan",
            }, context={})

            assert res.success is False
            assert "could not be brought to the foreground" in res.error
            mock_keys.assert_not_called()

    @pytest.mark.asyncio
    async def test_whatsapp_strict_foreground_guard(self):
        tool = MessagingDispatchTool()
        with patch("subprocess.Popen"), \
             patch.object(tool, "_focus_app_window", return_value=12345), \
             patch("win32gui.GetForegroundWindow", return_value=99999), \
             patch("win32gui.GetWindowText", return_value="Visual Studio Code - Antigravity"), \
             patch("win32gui.GetClassName", return_value="Chrome_WidgetWin_1"), \
             patch("pywinauto.keyboard.send_keys") as mock_keys:
            res = await tool.execute({
                "platform": "whatsapp",
                "recipient": "Rohan",
                "message": "Hello Rohan",
            }, context={})

            assert res.success is False
            assert "Focus check failed" in res.error
            assert "visual studio code" in res.error.lower()
            mock_keys.assert_not_called()

    @pytest.mark.asyncio
    async def test_messaging_dispatch_omitted_file_no_attachment(self):
        tool = MessagingDispatchTool()
        with patch("subprocess.Popen"), \
             patch.object(ActiveFileInspectorTool, "get_selected_files", return_value=["C:\\docs\\secret.pdf"]), \
             patch.object(tool, "_send_whatsapp", return_value={"success": True, "method": "uri"}) as mock_send:
            res = await tool.execute({
                "platform": "whatsapp",
                "recipient": "+1234567890",
                "message": "Just a text message",
            }, context={})

            assert res.success is True
            # Verify file_path was NOT passed as an attachment
            mock_send.assert_called_once_with("+1234567890", "Just a text message", None)
            assert res.data.get("file_path") is None

    @pytest.mark.asyncio
    async def test_scheduled_delayed_dispatch(self, tmp_path: Path):
        tool = MessagingDispatchTool()
        dummy_file = tmp_path / "doc.txt"
        dummy_file.write_text("Doc text")

        with patch("threading.Timer") as mock_timer:
            res = await tool.execute({
                "platform": "whatsapp",
                "recipient": "Rohan",
                "file_path": str(dummy_file),
                "schedule_time": "in 15m",
            }, context={})

            assert res.success is True
            assert res.data["scheduled"] is True
            assert res.data["delay_seconds"] == 900.0
            mock_timer.assert_called_once()


class TestWindowsGuiToolExtensions:
    @pytest.mark.asyncio
    async def test_click_coords_and_hotkey(self):
        tool = WindowsGuiTool()

        with patch("ctypes.windll.user32.SetCursorPos") as mock_cursor, \
             patch("ctypes.windll.user32.mouse_event") as mock_mouse:
            res_click = await tool.execute({"action": "click_coords", "x": 100, "y": 200}, context={})
            assert res_click.success is True
            assert res_click.data["x"] == 100
            assert res_click.data["y"] == 200
            mock_cursor.assert_called_with(100, 200)

        with patch("pywinauto.keyboard.send_keys") as mock_keys:
            res_hk = await tool.execute({"action": "press_hotkey", "hotkey": "^s"}, context={})
            assert res_hk.success is True
            mock_keys.assert_called_with("^s")


class TestVoiceQueueActiveFileAndDispatch:
    @pytest.mark.asyncio
    async def test_voice_active_file_query(self, tmp_path: Path):
        queue = IdempotentTaskQueue()
        test_file = tmp_path / "report.docx"
        test_file.write_text("Report data")

        task = NemoTask(id="vf1", name="what file is selected", status="queued")

        with patch.object(ActiveFileInspectorTool, "get_selected_files", return_value=[str(test_file)]):
            await queue._run_task_worker(task)
            assert task.status == "completed"
            assert "report.docx" in task.result

    @pytest.mark.asyncio
    async def test_voice_send_file_dispatch(self, tmp_path: Path):
        queue = IdempotentTaskQueue()
        test_file = tmp_path / "final_report.pdf"
        test_file.write_text("Report data")

        task = NemoTask(id="vf2", name="send this file to Rohan on whatsapp at 1:00 PM", status="queued")

        with patch.object(ActiveFileInspectorTool, "get_selected_files", return_value=[str(test_file)]), \
             patch("threading.Timer") as mock_timer:
            await queue._run_task_worker(task)
            assert task.status == "completed"
            assert "Scheduled to send" in task.result
            assert "Rohan" in task.result
