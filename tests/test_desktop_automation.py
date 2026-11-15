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
             patch.object(tool, "_is_whatsapp_preview_active", return_value=False), \
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
        from nemo.ai.schemas import LLMResponse
        queue = IdempotentTaskQueue()
        test_file = tmp_path / "final_report.pdf"
        test_file.write_text("Report data")

        task = NemoTask(id="vf2", name="send this file to Rohan on whatsapp at 1:00 PM", status="queued")

        mock_resp = LLMResponse(
            content='```json\n{\n  "thought": "Schedule send file to Rohan on WhatsApp at 1:00 PM",\n  "action": "tool_call",\n  "tool": "messaging_dispatch",\n  "arguments": {"platform": "whatsapp", "recipient": "Rohan", "file_path": "active", "schedule_time": "1:00 PM"}\n}\n```',
            model="test",
        )
        finish_resp = LLMResponse(
            content='```json\n{\n  "thought": "Scheduled",\n  "action": "finish",\n  "answer": "Scheduled to send final_report.pdf to Rohan via WhatsApp."\n}\n```',
            model="test",
        )

        with patch.object(ActiveFileInspectorTool, "get_selected_files", return_value=[str(test_file)]), \
             patch("threading.Timer") as mock_timer, \
             patch("nemo.ai.providers.nvidia.NvidiaNimProvider.generate", side_effect=[mock_resp, finish_resp]), \
             patch("nemo.ai.providers.nvidia.NvidiaNimProvider.stream", side_effect=Exception("no stream")):
            await queue._run_task_worker(task)
            assert task.status == "completed"
            assert "Rohan" in task.result

    @pytest.mark.asyncio
    async def test_voice_queue_followup_sends_video_with_inferred_recipient(self, tmp_path: Path):
        from nemo.ai.schemas import LLMResponse
        queue = IdempotentTaskQueue()
        test_video = tmp_path / "presentation.mp4"
        test_video.write_text("fake video bytes")

        followup = NemoTask(id="vf_followup", name="Can we just send this video?", status="queued")

        mock_resp = LLMResponse(
            content='```json\n{\n  "thought": "Send active video to Bund via WhatsApp",\n  "action": "tool_call",\n  "tool": "messaging_dispatch",\n  "arguments": {"platform": "whatsapp", "recipient": "bund", "file_path": "active"}\n}\n```',
            model="test",
        )
        finish_resp = LLMResponse(
            content='```json\n{\n  "thought": "Sent",\n  "action": "finish",\n  "answer": "Sent presentation.mp4 to Bund via WhatsApp."\n}\n```',
            model="test",
        )

        with patch.object(ActiveFileInspectorTool, "get_selected_files", return_value=[str(test_video)]), \
             patch.object(MessagingDispatchTool, "_send_whatsapp", return_value={"success": True, "delivered": True, "method": "whatsapp_ui"}) as mock_wa, \
             patch("nemo.ai.providers.nvidia.NvidiaNimProvider.generate", side_effect=[mock_resp, finish_resp]), \
             patch("nemo.ai.providers.nvidia.NvidiaNimProvider.stream", side_effect=Exception("no stream")):
            await queue._run_task_worker(followup)
            assert followup.status == "completed"
            mock_wa.assert_called_once()
            args = mock_wa.call_args[0]
            assert args[0] == "bund"
            assert args[2] == test_video

    @pytest.mark.asyncio
    async def test_voice_queue_opens_whatsapp_chat_without_file_demands(self):
        from nemo.ai.schemas import LLMResponse
        queue = IdempotentTaskQueue()
        task = NemoTask(id="vq_open_gotham", name="Can you open WhatsApp and like show me Gotham?", status="queued")

        mock_resp = LLMResponse(
            content='```json\n{\n  "thought": "Open WhatsApp and view Gotham\'s chat",\n  "action": "tool_call",\n  "tool": "messaging_dispatch",\n  "arguments": {"platform": "whatsapp", "recipient": "Gotham", "message": "", "file_path": null}\n}\n```',
            model="test",
        )
        finish_resp = LLMResponse(
            content='```json\n{\n  "thought": "Opened",\n  "action": "finish",\n  "answer": "Opened WhatsApp chat with Gotham."\n}\n```',
            model="test",
        )

        with patch.object(ActiveFileInspectorTool, "get_selected_files", return_value=[]), \
             patch.object(ActiveFileInspectorTool, "get_hovered_file", return_value=None), \
             patch.object(MessagingDispatchTool, "_send_whatsapp", return_value={"success": True, "delivered": True, "method": "whatsapp_ui_search", "summary": "Opened WhatsApp chat with Gotham."}) as mock_wa, \
             patch("nemo.ai.providers.nvidia.NvidiaNimProvider.generate", side_effect=[mock_resp, finish_resp]), \
             patch("nemo.ai.providers.nvidia.NvidiaNimProvider.stream", side_effect=Exception("no stream")):
            await queue._run_task_worker(task)
            assert task.status == "completed"
            assert "Gotham" in task.result
            mock_wa.assert_called_once()
            args = mock_wa.call_args[0]
            assert args[0] == "Gotham"
            assert args[1] == ""
            assert args[2] is None

    @pytest.mark.asyncio
    async def test_voice_queue_opens_whatsapp_and_messages_contact(self):
        from nemo.ai.schemas import LLMResponse
        queue = IdempotentTaskQueue()
        task = NemoTask(id="vq_msg_bund", name="can you open whatsapp and find bund account and message him bye", status="queued")

        mock_resp = LLMResponse(
            content='```json\n{\n  "thought": "Open WhatsApp and send bye to bund",\n  "action": "tool_call",\n  "tool": "messaging_dispatch",\n  "arguments": {"platform": "whatsapp", "recipient": "bund", "message": "bye", "file_path": null}\n}\n```',
            model="test",
        )
        finish_resp = LLMResponse(
            content='```json\n{\n  "thought": "Done",\n  "action": "finish",\n  "answer": "Sent message to bund via WhatsApp."\n}\n```',
            model="test",
        )

        with patch.object(ActiveFileInspectorTool, "get_selected_files", return_value=[]), \
             patch.object(MessagingDispatchTool, "_send_whatsapp", return_value={"success": True, "delivered": True, "method": "whatsapp_ui_search", "summary": "Sent message to bund via Whatsapp successfully."}) as mock_wa, \
             patch("nemo.ai.providers.nvidia.NvidiaNimProvider.generate", side_effect=[mock_resp, finish_resp]), \
             patch("nemo.ai.providers.nvidia.NvidiaNimProvider.stream", side_effect=Exception("no stream")):
            await queue._run_task_worker(task)
            assert task.status == "completed"
            mock_wa.assert_called_once()
            args = mock_wa.call_args[0]
            assert args[0] == "bund"
            assert args[1] == "bye"
            assert args[2] is None

    @pytest.mark.asyncio
    async def test_gui_automation_launch_whatsapp(self):
        from nemo.tools.builtin import WindowsGuiTool
        tool = WindowsGuiTool()
        with patch("subprocess.Popen") as mock_popen:
            res = await tool.execute({"action": "launch", "target": "WhatsApp"}, context={})
            assert res.success is True
            mock_popen.assert_called_once()
            cmd = mock_popen.call_args[0][0]
            assert "whatsapp:" in cmd


class TestProjectDiscovery:
    @pytest.mark.asyncio
    async def test_project_discovery_phonetic_chloe_matches_clovi(self, tmp_path: Path):
        from nemo.tools.builtin import ProjectDiscoveryTool

        # Setup mock project directory for Clovi with win-unpacked build
        clovi_dir = tmp_path / "Clovi"
        clovi_dir.mkdir()
        (clovi_dir / "package.json").write_text('{"name": "clovi", "description": "Clovi — Windows Floating Overlay Assistant with Gemini Vision"}')
        unpacked_dir = clovi_dir / "release" / "win-unpacked"
        unpacked_dir.mkdir(parents=True)
        exe_file = unpacked_dir / "Clovi.exe"
        exe_file.write_text("dummy exe")

        tool = ProjectDiscoveryTool()
        res = await tool.execute({
            "query": "Chloe Kerken GUI tool which helps me find answers of questions",
            "action": "search",
            "search_roots": [str(tmp_path)],
        }, context={})

        assert res.success is True
        top = res.data["top_match"]
        assert top["name"] == "Clovi"
        assert top["score"] >= 0.70
        assert "win-unpacked" in top["unpacked_exe"]
        assert "Clovi" in res.data["summary"]

    @pytest.mark.asyncio
    async def test_project_discovery_win_unpacked_launch(self, tmp_path: Path):
        from nemo.tools.builtin import ProjectDiscoveryTool

        clovi_dir = tmp_path / "Clovi"
        clovi_dir.mkdir()
        unpacked_dir = clovi_dir / "release" / "win-unpacked"
        unpacked_dir.mkdir(parents=True)
        exe_file = unpacked_dir / "Clovi.exe"
        exe_file.write_text("dummy exe")

        tool = ProjectDiscoveryTool()
        with patch("subprocess.Popen") as mock_popen:
            res = await tool.execute({
                "query": "Can you just like open Win Unpacked version of Chloe?",
                "action": "launch",
                "search_roots": [str(tmp_path)],
            }, context={})

            assert res.success is True
            assert res.data["action"] == "launch"
            assert res.data["project"] == "Clovi"
            assert "Clovi.exe" in res.data["executable"]
            mock_popen.assert_called_once()
            cmd_called = mock_popen.call_args[0][0]
            assert "Clovi.exe" in cmd_called

    @pytest.mark.asyncio
    async def test_voice_queue_opens_win_unpacked_clovi(self, tmp_path: Path):
        from nemo.tools.builtin import ProjectDiscoveryTool

        clovi_dir = tmp_path / "Clovi"
        clovi_dir.mkdir()
        unpacked_dir = clovi_dir / "release" / "win-unpacked"
        unpacked_dir.mkdir(parents=True)
        exe_file = unpacked_dir / "Clovi.exe"
        exe_file.write_text("dummy exe")

        queue = IdempotentTaskQueue()
        task = NemoTask(id="pd_task", name="Can you just like open Win Unpacked version of Chloe?", status="queued")

        from nemo.ai.schemas import LLMResponse
        mock_resp = LLMResponse(
            content='```json\n{\n  "thought": "Launch unpacked build of Clovi",\n  "action": "tool_call",\n  "tool": "project_discovery",\n  "arguments": {"query": "Chloe", "action": "launch", "target": "unpacked"}\n}\n```',
            model="test",
        )
        finish_resp = LLMResponse(
            content='```json\n{\n  "thought": "Launched Clovi",\n  "action": "finish",\n  "answer": "Successfully launched Clovi from release/win-unpacked."\n}\n```',
            model="test",
        )

        with patch.object(ProjectDiscoveryTool, "discover_candidates") as mock_disc, \
             patch("subprocess.Popen") as mock_popen, \
             patch("nemo.ai.providers.nvidia.NvidiaNimProvider.generate", side_effect=[mock_resp, finish_resp]), \
             patch("nemo.ai.providers.nvidia.NvidiaNimProvider.stream", side_effect=Exception("no stream")):
            mock_disc.return_value = [{
                "name": "Clovi",
                "path": str(clovi_dir),
                "score": 0.95,
                "phonetic_match": True,
                "description": "Clovi Overlay Assistant",
                "unpacked_exe": str(exe_file),
                "executables": [str(exe_file)],
            }]
            await queue._run_task_worker(task)
            assert task.status == "completed"
            assert "Clovi" in task.result
            mock_popen.assert_called_once()
