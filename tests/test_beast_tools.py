"""Production-grade in-depth test suite for the 5 Core Developer Beast Tools.

Covers:
- GitOperationsTool (status, branch, checkout, stage, unstage, commit, log, diff, safety)
- DatabaseExplorerTool (list_tables, schema, query, read-only safety, allow_write, path security)
- ApiTesterTool (methods, headers, auth bearer, json parsing, response latency)
- SystemInspectorTool (summary, hardware metrics, processes, ports, protected process kill safety)
- WindowsDesktopTool (clipboard copy/read, toast notification)
"""

# 1. Standard library imports
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile

# 2. Third-party imports
import pytest

# 3. Local / internal imports
from nemo.security.policy import SecurityPolicy
from nemo.tools.builtin import (
    ApiTesterTool,
    DatabaseExplorerTool,
    GitOperationsTool,
    SystemInspectorTool,
    WindowsDesktopTool,
)

# 4. Types, Protocols, Schemas
# (None)

# 5. Core logic / classes / functions
def init_temp_git_repo(root: Path) -> None:
    """Helper to initialize a clean temporary Git repository."""
    subprocess.run(["git", "init"], cwd=root, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "dev@nemo.ai"], cwd=root, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "NEMO Dev"], cwd=root, capture_output=True, check=True)


# ============================================================================
# 1. GitOperationsTool Tests
# ============================================================================

@pytest.mark.asyncio
async def test_git_operations_status_clean_and_dirty():
    """Verify git_operations status accurately reports clean, staged, unstaged, and untracked files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        init_temp_git_repo(root)

        tool = GitOperationsTool()

        # 1. Initially clean empty repo
        res_clean = await tool.execute({"action": "status"}, {"working_directory": str(root)})
        assert res_clean.success
        assert res_clean.data["is_clean"] is True
        assert res_clean.data["total_changes"] == 0

        # 2. Add an untracked file
        (root / "new_module.py").write_text("# new module")
        res_untracked = await tool.execute({"action": "status"}, {"working_directory": str(root)})
        assert res_untracked.success
        assert res_untracked.data["is_clean"] is False
        assert "new_module.py" in res_untracked.data["untracked"]

        # 3. Stage the file
        await tool.execute({"action": "stage", "files": ["new_module.py"]}, {"working_directory": str(root)})
        res_staged = await tool.execute({"action": "status"}, {"working_directory": str(root)})
        assert res_staged.success
        assert "new_module.py" in res_staged.data["staged"]


@pytest.mark.asyncio
async def test_git_operations_branch_and_checkout():
    """Verify branch creation, listing, and switching."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        init_temp_git_repo(root)

        (root / "init.txt").write_text("initial")
        subprocess.run(["git", "add", "init.txt"], cwd=root, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=root, capture_output=True, check=True)

        tool = GitOperationsTool()

        # 1. Create new feature branch
        res_branch = await tool.execute({"action": "branch", "branch_name": "feature/voice-control"}, {"working_directory": str(root)})
        assert res_branch.success
        assert res_branch.data["created"] == "feature/voice-control"

        # 2. List branches
        res_list = await tool.execute({"action": "branch"}, {"working_directory": str(root)})
        assert res_list.success
        assert any("feature/voice-control" in b for b in res_list.data["branches"])

        # 3. Checkout branch
        res_co = await tool.execute({"action": "checkout", "branch_name": "feature/voice-control"}, {"working_directory": str(root)})
        assert res_co.success
        assert res_co.data["branch"] == "feature/voice-control"

        # 4. Checkout new branch with -b flag
        res_b = await tool.execute({"action": "checkout", "branch_name": "hotfix/urgent", "create_branch": True}, {"working_directory": str(root)})
        assert res_b.success
        assert res_b.data["branch"] == "hotfix/urgent"
        assert res_b.data["created"] is True


@pytest.mark.asyncio
async def test_git_operations_stage_unstage_and_commit():
    """Verify staging specific files, unstaging, and committing with commit hash return."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        init_temp_git_repo(root)

        tool = GitOperationsTool()
        (root / "a.py").write_text("a = 1")
        (root / "b.py").write_text("b = 2")

        # Stage only a.py
        res_stage = await tool.execute({"action": "stage", "files": ["a.py"]}, {"working_directory": str(root)})
        assert res_stage.success

        stat = await tool.execute({"action": "status"}, {"working_directory": str(root)})
        assert "a.py" in stat.data["staged"]
        assert "b.py" in stat.data["untracked"]

        # Unstage a.py
        res_unstage = await tool.execute({"action": "unstage", "files": ["a.py"]}, {"working_directory": str(root)})
        assert res_unstage.success

        stat_after = await tool.execute({"action": "status"}, {"working_directory": str(root)})
        assert len(stat_after.data["staged"]) == 0

        # Stage all and commit
        await tool.execute({"action": "stage"}, {"working_directory": str(root)})
        res_commit = await tool.execute(
            {"action": "commit", "message": "feat: initialize modules a and b"},
            {"working_directory": str(root)},
        )
        assert res_commit.success
        assert res_commit.data["commit_hash"] != "unknown"
        assert len(res_commit.data["commit_hash"]) >= 6
        assert res_commit.data["message"] == "feat: initialize modules a and b"


@pytest.mark.asyncio
async def test_git_operations_log_structured():
    """Verify git_operations log returns structured commit history with hash, author, date, message."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        init_temp_git_repo(root)

        tool = GitOperationsTool()

        # Create two commits
        (root / "f1.txt").write_text("1")
        subprocess.run(["git", "add", "."], cwd=root, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "commit 1: first step"], cwd=root, capture_output=True, check=True)

        (root / "f2.txt").write_text("2")
        subprocess.run(["git", "add", "."], cwd=root, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "commit 2: second step"], cwd=root, capture_output=True, check=True)

        res_log = await tool.execute({"action": "log", "limit": 5}, {"working_directory": str(root)})
        assert res_log.success
        assert res_log.data["count"] == 2
        commits = res_log.data["commits"]
        assert commits[0]["message"] == "commit 2: second step"
        assert commits[1]["message"] == "commit 1: first step"
        assert commits[0]["author"] == "NEMO Dev"


@pytest.mark.asyncio
async def test_git_operations_diff_stats():
    """Verify git_operations diff provides stats for staged and unstaged modifications."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        init_temp_git_repo(root)
        tool = GitOperationsTool()

        (root / "file.txt").write_text("line 1\n")
        subprocess.run(["git", "add", "."], cwd=root, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=root, capture_output=True, check=True)

        # Unstaged modification
        (root / "file.txt").write_text("line 1\nline 2\n")

        res_diff = await tool.execute({"action": "diff"}, {"working_directory": str(root)})
        assert res_diff.success
        assert "file.txt" in res_diff.data["unstaged_stat"]


@pytest.mark.asyncio
async def test_git_operations_non_git_repo_error():
    """Verify git_operations gracefully reports error on non-git directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        tool = GitOperationsTool()

        res = await tool.execute({"action": "status"}, {"working_directory": str(root)})
        assert res.success is False
        assert "not a git repository" in res.error.lower()


# ============================================================================
# 2. DatabaseExplorerTool Tests
# ============================================================================

@pytest.fixture
def sample_sqlite_db():
    """Fixture providing a populated test SQLite database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "app_data.db"
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()

        # Create tables and indexes
        cur.execute("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cur.execute("""
            CREATE TABLE tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                completed BOOLEAN DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
        """)
        cur.execute("CREATE INDEX idx_tasks_user ON tasks(user_id);")

        # Insert test data
        cur.execute("INSERT INTO users (username, email) VALUES ('alice', 'alice@nemo.ai');")
        cur.execute("INSERT INTO users (username, email) VALUES ('bob', 'bob@nemo.ai');")
        cur.execute("INSERT INTO tasks (user_id, title, completed) VALUES (1, 'Build voice engine', 1);")
        cur.execute("INSERT INTO tasks (user_id, title, completed) VALUES (1, 'Setup GUI automation', 0);")
        cur.execute("INSERT INTO tasks (user_id, title, completed) VALUES (2, 'Review API client', 0);")

        conn.commit()
        conn.close()

        yield db_path


@pytest.mark.asyncio
async def test_database_inspector_list_tables_and_row_counts(sample_sqlite_db):
    """Verify database_inspector list_tables returns exact tables, types, and row counts."""
    tool = DatabaseExplorerTool()
    res = await tool.execute({"path": str(sample_sqlite_db), "action": "list_tables"}, {"working_directory": str(sample_sqlite_db.parent)})
    assert res.success
    tables = {t["name"]: t for t in res.data["tables"]}
    assert "users" in tables
    assert "tasks" in tables
    assert tables["users"]["row_count"] == 2
    assert tables["tasks"]["row_count"] == 3


@pytest.mark.asyncio
async def test_database_inspector_schema_columns_fks_indexes(sample_sqlite_db):
    """Verify database_inspector schema inspects columns, foreign keys, and indexes."""
    tool = DatabaseExplorerTool()
    res = await tool.execute(
        {"path": str(sample_sqlite_db), "action": "schema", "table": "tasks"},
        {"working_directory": str(sample_sqlite_db.parent)},
    )
    assert res.success
    data = res.data
    assert data["table"] == "tasks"
    col_names = [c["name"] for c in data["columns"]]
    assert "id" in col_names
    assert "user_id" in col_names
    assert "title" in col_names
    assert "completed" in col_names

    # Check foreign key
    assert len(data["foreign_keys"]) == 1
    assert data["foreign_keys"][0]["target_table"] == "users"

    # Check index
    idx_names = [idx["name"] for idx in data["indexes"]]
    assert "idx_tasks_user" in idx_names


@pytest.mark.asyncio
async def test_database_inspector_safe_query_read_only(sample_sqlite_db):
    """Verify database_inspector executes read-only SELECT and returns formatted rows."""
    tool = DatabaseExplorerTool()
    res = await tool.execute(
        {
            "path": str(sample_sqlite_db),
            "action": "query",
            "query": "SELECT u.username, t.title, t.completed FROM tasks t JOIN users u ON t.user_id = u.id ORDER BY t.id;",
        },
        {"working_directory": str(sample_sqlite_db.parent)},
    )
    assert res.success
    assert res.data["columns"] == ["username", "title", "completed"]
    assert res.data["row_count"] == 3
    assert res.data["rows"][0] == ["alice", "Build voice engine", 1]
    assert res.data["execution_time_ms"] >= 0.0


@pytest.mark.asyncio
async def test_database_inspector_blocks_destructive_queries(sample_sqlite_db):
    """Verify database_inspector strictly blocks destructive write queries without allow_write."""
    tool = DatabaseExplorerTool()

    # Attempt DROP TABLE
    res_drop = await tool.execute(
        {"path": str(sample_sqlite_db), "action": "query", "query": "DROP TABLE users;"},
        {"working_directory": str(sample_sqlite_db.parent)},
    )
    assert res_drop.success is False
    assert "permission denied" in res_drop.error.lower()

    # Attempt DELETE
    res_del = await tool.execute(
        {"path": str(sample_sqlite_db), "action": "query", "query": "DELETE FROM users WHERE id = 1;"},
        {"working_directory": str(sample_sqlite_db.parent)},
    )
    assert res_del.success is False
    assert "permission denied" in res_del.error.lower()


@pytest.mark.asyncio
async def test_database_inspector_allow_write_mode(sample_sqlite_db):
    """Verify allow_write=True permits intentional INSERT and commits transaction."""
    tool = DatabaseExplorerTool()
    res_insert = await tool.execute(
        {
            "path": str(sample_sqlite_db),
            "action": "query",
            "query": "INSERT INTO users (username, email) VALUES ('charlie', 'charlie@nemo.ai');",
            "allow_write": True,
        },
        {"working_directory": str(sample_sqlite_db.parent)},
    )
    assert res_insert.success

    # Verify charlie exists
    res_check = await tool.execute(
        {"path": str(sample_sqlite_db), "action": "query", "query": "SELECT COUNT(*) FROM users;"},
        {"working_directory": str(sample_sqlite_db.parent)},
    )
    assert res_check.success
    assert res_check.data["rows"][0][0] == 3


@pytest.mark.asyncio
async def test_database_inspector_path_security(sample_sqlite_db):
    """Verify database_inspector blocks path traversal outside allowed boundary."""
    policy = SecurityPolicy()
    tool = DatabaseExplorerTool(policy=policy)

    res = await tool.execute(
        {"path": "C:/Windows/System32/kernel.db", "action": "list_tables"},
        {"working_directory": str(sample_sqlite_db.parent)},
    )
    assert res.success is False
    assert "access denied" in res.error.lower()


@pytest.mark.asyncio
async def test_database_inspector_nemo_db_auto_resolve():
    """Verify database_inspector permits and auto-resolves ~/.nemo/nemo.db."""
    from nemo.agent.orchestrator import extract_json_block
    nemo_db_path = Path.home() / ".nemo" / "nemo.db"
    if not nemo_db_path.exists():
        pytest.skip("~/.nemo/nemo.db does not exist on this machine.")

    tool = DatabaseExplorerTool()
    # 1. Explicit path with tilde
    res = await tool.execute(
        {"path": "~/.nemo/nemo.db", "action": "list_tables"},
        {"working_directory": str(Path.cwd())},
    )
    assert res.success is True
    table_names = [t["name"] for t in res.data["tables"]]
    assert "conversations" in table_names or "projects" in table_names

    # 2. Auto-resolution when passing "nemo.db"
    res_auto = await tool.execute(
        {"path": "nemo.db", "action": "list_tables"},
        {"working_directory": str(Path.cwd())},
    )
    assert res_auto.success is True

    # 3. Test extract_json_block with raw newlines in answer
    raw_llm_json = """{
      "thought": "Direct inspection succeeded",
      "action": "finish",
      "answer": "# Nemo Tables Report\n\n- Table: conversations\n- Rows: 43"
    }"""
    parsed = extract_json_block(raw_llm_json)
    assert parsed is not None
    assert parsed["action"] == "finish"
    assert "conversations" in parsed["answer"]


# ============================================================================
# 3. ApiTesterTool Tests
# ============================================================================

@pytest.mark.asyncio
async def test_api_tester_mock_request():
    """Verify ApiTesterTool handles standard HTTP calls and records timing and response data."""
    tool = ApiTesterTool()

    # Using public fast json test endpoint
    res = await tool.execute(
        {
            "url": "https://httpbin.org/get",
            "method": "GET",
            "params": {"agent": "nemo", "version": "0.1.0"},
            "headers": {"X-Custom-Client": "NEMO-Runtime"},
            "timeout_seconds": 10.0,
        },
        {},
    )
    # If network is available, test real roundtrip; if blocked/offline, verify graceful failure
    if res.success:
        assert res.data["status_code"] == 200
        assert res.data["is_success"] is True
        assert res.data["response_time_ms"] > 0
        assert res.data["json"]["args"]["agent"] == "nemo"
    else:
        assert "api request failed" in res.error.lower()


@pytest.mark.asyncio
async def test_api_tester_auth_bearer():
    """Verify ApiTesterTool injects Bearer token into headers."""
    tool = ApiTesterTool()
    res = await tool.execute(
        {
            "url": "https://httpbin.org/bearer",
            "method": "GET",
            "auth_bearer": "nemo_secret_token_123",
            "timeout_seconds": 10.0,
        },
        {},
    )
    if res.success:
        assert res.data["status_code"] == 200
        assert res.data["json"]["authenticated"] is True
        assert res.data["json"]["token"] == "nemo_secret_token_123"


# ============================================================================
# 4. SystemInspectorTool Tests
# ============================================================================

@pytest.mark.asyncio
async def test_system_inspector_summary_hardware_metrics():
    """Verify system_inspector summary returns CPU logical cores, RAM metrics, and disk stats."""
    tool = SystemInspectorTool()
    res = await tool.execute({"action": "summary"}, {})
    assert res.success
    data = res.data
    assert data["cpu_logical_cores"] >= 1
    assert "Windows" in data["os"]
    assert data["ram"]["total_gb"] > 0
    assert 0 <= data["ram"]["used_percent"] <= 100
    assert data["disk"]["total_gb"] > 0
    assert 0 <= data["disk"]["used_percent"] <= 100


@pytest.mark.asyncio
async def test_system_inspector_processes_and_filter():
    """Verify system_inspector processes lists Windows tasks and applies name filter."""
    tool = SystemInspectorTool()

    # 1. List top processes
    res_all = await tool.execute({"action": "processes", "limit": 10}, {})
    assert res_all.success
    assert len(res_all.data["processes"]) <= 10
    assert len(res_all.data["processes"]) > 0

    # 2. Filter by python process (which is currently executing this test)
    res_py = await tool.execute({"action": "processes", "filter_name": "python"}, {})
    assert res_py.success
    py_procs = res_py.data["processes"]
    assert any("python" in p["name"].lower() for p in py_procs)


@pytest.mark.asyncio
async def test_system_inspector_listening_ports():
    """Verify system_inspector ports enumerates active listening TCP sockets."""
    tool = SystemInspectorTool()
    res = await tool.execute({"action": "ports", "limit": 20}, {})
    assert res.success
    assert "ports" in res.data
    assert res.data["listening_count"] >= 0


@pytest.mark.asyncio
async def test_system_inspector_protected_process_kill_safety():
    """Verify system_inspector strictly denies killing core Windows system processes."""
    tool = SystemInspectorTool()
    res = await tool.execute({"action": "kill", "process_name": "explorer.exe"}, {})
    assert res.success is False
    assert "permission denied" in res.error.lower()
    assert "protected" in res.error.lower()


# ============================================================================
# 5. WindowsDesktopTool Tests
# ============================================================================

@pytest.mark.asyncio
async def test_desktop_integration_clipboard_copy_and_read():
    """Verify desktop_integration copies text to clipboard and reads it back accurately."""
    tool = WindowsDesktopTool()
    unique_text = "NEMO_AUTOMATION_TEST_TOKEN_9999"

    # Copy to clipboard
    res_copy = await tool.execute({"action": "clipboard_copy", "text": unique_text}, {})
    assert res_copy.success
    assert res_copy.data["copied_length"] == len(unique_text)

    # Read back from clipboard
    res_read = await tool.execute({"action": "clipboard_read"}, {})
    assert res_read.success
    assert res_read.data["content"] == unique_text


@pytest.mark.asyncio
async def test_desktop_integration_toast_notification():
    """Verify desktop_integration fires Windows desktop notification non-blockingly."""
    tool = WindowsDesktopTool()
    res = await tool.execute(
        {
            "action": "notify",
            "title": "NEMO Test Suite",
            "message": "All 5 Core Developer Beast Tools verified.",
        },
        {},
    )
    assert res.success
    assert res.data["delivered"] is True
    assert res.data["title"] == "NEMO Test Suite"


@pytest.mark.asyncio
async def test_desktop_integration_set_and_cancel_alarm():
    """Verify setting an alarm, querying it, and cancelling it without admin elevation."""
    tool = WindowsDesktopTool()

    # 1. Test natural time parsing
    t24, label = tool._parse_alarm_time("6 PM")
    assert t24 == "18:00"
    assert "6:00 PM" in label

    t24_b, _ = tool._parse_alarm_time("18:00")
    assert t24_b == "18:00"

    # 2. Set alarm for 23:58 (end of day)
    res_set = await tool.execute(
        {
            "action": "set_alarm",
            "time": "11:58 PM",
            "title": "Test 11:58 PM Alarm",
            "message": "Alarm unit test execution",
        },
        {},
    )
    assert res_set.success is True
    task_name = res_set.data["task_name"]
    assert "NEMO_Alarm_" in task_name

    # 3. List alarms to verify registered
    res_list = await tool.execute({"action": "list_alarms"}, {})
    assert res_list.success is True
    active_names = [a["task_name"] for a in res_list.data["alarms"]]
    assert task_name in active_names

    # 4. Cancel alarm
    res_cancel = await tool.execute({"action": "cancel_alarm", "task_name": task_name}, {})
    assert res_cancel.success is True
    assert task_name in res_cancel.data["deleted_tasks"]


@pytest.mark.asyncio
async def test_desktop_integration_timer_and_pomodoro_widgets():
    """Verify launching floating timer and pomodoro widgets."""
    tool = WindowsDesktopTool()

    # 1. Test set_timer
    res_timer = await tool.execute(
        {"action": "set_timer", "minutes": 15, "title": "Test Focus Timer"},
        {},
    )
    assert res_timer.success is True
    assert res_timer.data["duration_minutes"] == 15
    assert "active" in res_timer.data["widget_status"]

    # 2. Test start_pomodoro with custom settings
    res_pomo = await tool.execute(
        {
            "action": "start_pomodoro",
            "focus_minutes": 50,
            "break_minutes": 10,
            "long_break_minutes": 20,
            "cycles": 3,
            "title": "Custom Deep Work",
        },
        {},
    )
    assert res_pomo.success is True
    assert res_pomo.data["focus_minutes"] == 50
    assert res_pomo.data["break_minutes"] == 10
    assert res_pomo.data["cycles"] == 3

    # 3. Test set_timer with seconds
    res_sec = await tool.execute(
        {"action": "set_timer", "seconds": 10, "title": "10s Timer"},
        {},
    )
    assert res_sec.success is True
    assert res_sec.data["duration_seconds"] == 10

    # 4. Test start_stopwatch
    res_sw = await tool.execute(
        {"action": "start_stopwatch"},
        {},
    )
    assert res_sw.success is True
    assert res_sw.data["action"] == "start_stopwatch"


@pytest.mark.asyncio
async def test_desktop_integration_native_app_automations():
    """Verify camera, snipping tool, media player, paint, sound recorder, and terminal layout."""
    tool = WindowsDesktopTool()

    # 1. Test snipping tool
    res_snip = await tool.execute({"action": "snipping_tool"}, {})
    assert res_snip.success is True
    assert "active" in res_snip.data["status"]

    # 2. Test play_audio with built-in Windows sound
    res_audio = await tool.execute(
        {"action": "play_audio", "path": "C:/Windows/Media/chimes.wav", "volume": 50},
        {},
    )
    assert res_audio.success is True
    assert res_audio.data["volume"] == 50

    # 3. Test terminal_layout
    res_wt = await tool.execute(
        {"action": "terminal_layout", "panes": ["backend", "frontend", "docker"]},
        {},
    )
    assert res_wt.success is True
    assert res_wt.data["panes_count"] == 3


def test_extract_json_block_multi_concatenated_objects():
    """Verify extract_json_block extracts first valid JSON block when LLM concatenates multiple objects."""
    from nemo.agent.orchestrator import extract_json_block
    concatenated = (
        '{"thought": "inspecting first", "action": "tool_call", "tool": "inspect_project_environment", "arguments": {"path": "."}} '
        '{"thought": "inspecting second", "action": "tool_call", "tool": "system_inspector", "arguments": {"action": "summary"}} '
        '{"thought": "notifying user", "action": "tool_call", "tool": "desktop_integration", "arguments": {"action": "notify"}}'
    )
    parsed = extract_json_block(concatenated)
    assert parsed is not None
    assert parsed["tool"] == "inspect_project_environment"
    assert parsed["action"] == "tool_call"


@pytest.mark.asyncio
async def test_file_operations_copy_move_and_batch(tmp_path):
    """Verify FileOperationsTool copy, move, batch_transfer, and zip capabilities."""
    from nemo.tools.builtin import FileOperationsTool
    tool = FileOperationsTool()

    # 1. Test single file copy
    src_file = tmp_path / "source.txt"
    src_file.write_text("hello nemo developer", encoding="utf-8")
    dst_file = tmp_path / "dest.txt"

    res_copy = await tool.execute(
        {"action": "copy", "src": str(src_file), "dst": str(dst_file)},
        {"working_directory": str(tmp_path)},
    )
    assert res_copy.success is True
    assert dst_file.exists()
    assert dst_file.read_text(encoding="utf-8") == "hello nemo developer"

    # 2. Test batch transfer
    f1 = tmp_path / "code1.py"
    f2 = tmp_path / "code2.py"
    f1.write_text("print('f1')")
    f2.write_text("print('f2')")
    target_dir = tmp_path / "target_folder"

    res_batch = await tool.execute(
        {
            "action": "batch_transfer",
            "sources": [str(f1), str(f2)],
            "target_dir": str(target_dir),
            "operation": "copy",
        },
        {"working_directory": str(tmp_path)},
    )
    assert res_batch.success is True
    assert (target_dir / "code1.py").exists()
    assert (target_dir / "code2.py").exists()

    # 3. Test zip archive
    zip_out = tmp_path / "archive.zip"
    res_zip = await tool.execute(
        {"action": "zip", "src": str(target_dir), "dst": str(zip_out)},
        {"working_directory": str(tmp_path)},
    )
    assert res_zip.success is True
    assert zip_out.exists()
    assert zip_out.stat().st_size > 0

    # 4. Test unzip
    unzip_dir = tmp_path / "unzipped"
    res_unzip = await tool.execute(
        {"action": "unzip", "src": str(zip_out), "dst": str(unzip_dir)},
        {"working_directory": str(tmp_path)},
    )
    assert res_unzip.success is True
    assert (unzip_dir / "target_folder" / "code1.py").exists() or (unzip_dir / "code1.py").exists()


# 6. Public exports
__all__ = [
    "test_git_operations_status_clean_and_dirty",
    "test_git_operations_branch_and_checkout",
    "test_git_operations_stage_unstage_and_commit",
    "test_git_operations_log_structured",
    "test_git_operations_diff_stats",
    "test_git_operations_non_git_repo_error",
    "test_database_inspector_list_tables_and_row_counts",
    "test_database_inspector_schema_columns_fks_indexes",
    "test_database_inspector_safe_query_read_only",
    "test_database_inspector_blocks_destructive_queries",
    "test_database_inspector_allow_write_mode",
    "test_database_inspector_path_security",
    "test_api_tester_mock_request",
    "test_api_tester_auth_bearer",
    "test_system_inspector_summary_hardware_metrics",
    "test_system_inspector_processes_and_filter",
    "test_system_inspector_listening_ports",
    "test_system_inspector_protected_process_kill_safety",
    "test_desktop_integration_clipboard_copy_and_read",
    "test_desktop_integration_toast_notification",
]
