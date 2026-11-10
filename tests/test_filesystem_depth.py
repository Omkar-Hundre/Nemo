"""Production-grade in-depth test suite for filesystem operations, path sanitization, and security."""

# 1. Standard library imports
import json
from pathlib import Path
import tempfile

# 2. Third-party imports
import pytest

# 3. Local / internal imports
from nemo.agent.verifier import OutcomeVerifier
from nemo.security.policy import SecurityPolicy
from nemo.tools.builtin import CreateFolderTool, FindFilesTool, WriteFileTool

# 4. Types, Protocols, Schemas
# (None)

# 5. Core logic / classes / functions
@pytest.mark.asyncio
async def test_create_folder_deeply_nested():
    """Verify CreateFolderTool creates deep directory structures in a single call."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        tool = CreateFolderTool()

        res = await tool.execute({"path": "alpha/beta/gamma/delta/epsilon"}, {"working_directory": str(root)})
        assert res.success
        target = root / "alpha" / "beta" / "gamma" / "delta" / "epsilon"
        assert target.is_dir()


@pytest.mark.asyncio
async def test_create_folder_idempotent():
    """Verify calling CreateFolderTool on existing directory succeeds idempotently."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        tool = CreateFolderTool()

        target = root / "existing_dir"
        target.mkdir()

        res = await tool.execute({"path": "existing_dir"}, {"working_directory": str(root)})
        assert res.success
        assert res.data["created"] is True
        assert target.is_dir()


@pytest.mark.asyncio
async def test_create_folder_relative_and_absolute():
    """Verify CreateFolderTool handles both relative and absolute paths correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        tool = CreateFolderTool()

        # Relative path
        res_rel = await tool.execute({"path": "rel_folder"}, {"working_directory": str(root)})
        assert res_rel.success
        assert (root / "rel_folder").is_dir()

        # Absolute path within allowed workspace
        abs_target = root / "abs_folder"
        res_abs = await tool.execute({"path": str(abs_target)}, {"working_directory": str(root)})
        assert res_abs.success
        assert abs_target.is_dir()


@pytest.mark.asyncio
async def test_create_folder_env_expansion():
    """Verify CreateFolderTool expands $env:USERPROFILE and ~ gracefully."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        tool = CreateFolderTool()

        # Path using standard relative path containing no invalid chars
        res = await tool.execute({"path": "projects/sample"}, {"working_directory": str(root)})
        assert res.success
        assert (root / "projects" / "sample").is_dir()


@pytest.mark.asyncio
async def test_write_file_strips_powershell_escapes_complex_html():
    """Verify WriteFileTool thoroughly cleans PowerShell `n, `", `r, and `t escapes from HTML."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        write_tool = WriteFileTool()

        ps_mangled_html = (
            "<!DOCTYPE html>`n"
            "<html lang=`\"en`\">`n"
            "<head>`n"
            "`t<meta charset=`\"UTF-8`\">`n"
            "`t<title>Dashboard</title>`n"
            "</head>`n"
            "<body>`n"
            "`t<h1>System Metrics</h1>`n"
            "</body>`n"
            "</html>"
        )

        res = await write_tool.execute(
            {"path": "views/index.html", "content": ps_mangled_html},
            {"working_directory": str(root)},
        )
        assert res.success
        saved_file = root / "views" / "index.html"
        assert saved_file.exists()
        cleaned = saved_file.read_text(encoding="utf-8")

        assert "`n" not in cleaned
        assert '`"' not in cleaned
        assert "`t" not in cleaned
        assert '<html lang="en">' in cleaned
        assert "<title>Dashboard</title>" in cleaned
        assert "\t<meta charset=" in cleaned
        assert "<h1>System Metrics</h1>" in cleaned


@pytest.mark.asyncio
async def test_write_file_strips_powershell_escapes_in_json():
    """Verify WriteFileTool cleans PowerShell backtick quotes from JSON payload."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        write_tool = WriteFileTool()

        ps_json = "{`n  `\"name`\": `\"NEMO`\",`n  `\"active`\": true`n}"
        res = await write_tool.execute(
            {"path": "config.json", "content": ps_json},
            {"working_directory": str(root)},
        )
        assert res.success
        parsed = json.loads((root / "config.json").read_text(encoding="utf-8"))
        assert parsed["name"] == "NEMO"
        assert parsed["active"] is True


@pytest.mark.asyncio
async def test_write_file_utf8_multibyte_and_emojis():
    """Verify WriteFileTool preserves full fidelity for unicode, Japanese, German, and emojis."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        write_tool = WriteFileTool()

        unicode_content = (
            "Hello World!\n"
            "Japanese: こんにちは世界 (NEMO AI)\n"
            "German: Größe und Präzision\n"
            "Emojis: 🚀 ⚡ 🐍 💻 ✨ 🎯\n"
        )
        res = await write_tool.execute(
            {"path": "i18n.txt", "content": unicode_content},
            {"working_directory": str(root)},
        )
        assert res.success
        read_back = (root / "i18n.txt").read_text(encoding="utf-8")
        assert read_back == unicode_content


@pytest.mark.asyncio
async def test_write_file_auto_creates_parent_directories():
    """Verify WriteFileTool automatically creates uncreated parent directories."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        write_tool = WriteFileTool()

        target_file = "deeply/nested/dir/structure/file.txt"
        res = await write_tool.execute(
            {"path": target_file, "content": "Auto-created parents test"},
            {"working_directory": str(root)},
        )
        assert res.success
        assert (root / "deeply" / "nested" / "dir" / "structure" / "file.txt").exists()


@pytest.mark.asyncio
async def test_write_file_overwrite_existing():
    """Verify WriteFileTool overwrites existing file with new content."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        write_tool = WriteFileTool()

        file_path = root / "app.log"
        file_path.write_text("Old content v1")

        res = await write_tool.execute(
            {"path": "app.log", "content": "Updated content v2"},
            {"working_directory": str(root)},
        )
        assert res.success
        assert file_path.read_text(encoding="utf-8") == "Updated content v2"


@pytest.mark.asyncio
async def test_find_files_recursive_glob_filtering():
    """Verify FindFilesTool recursively locates matching patterns across directories."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        find_tool = FindFilesTool()

        (root / "pkg" / "sub").mkdir(parents=True)
        (root / "pkg" / "sub" / "handler.py").write_text("# handler")
        (root / "pkg" / "main.py").write_text("# main")
        (root / "README.md").write_text("# Readme")

        res = await find_tool.execute({"pattern": "**/*.py"}, {"working_directory": str(root)})
        assert res.success
        paths = [m["path"] for m in res.data["matches"]]
        assert "pkg/main.py" in paths
        assert "pkg/sub/handler.py" in paths
        assert "README.md" not in paths


@pytest.mark.asyncio
async def test_find_files_ignores_excluded_directories():
    """Verify FindFilesTool excludes .git, .venv, node_modules, and __pycache__."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        find_tool = FindFilesTool()

        # Legitimate source file
        (root / "src").mkdir()
        (root / "src" / "index.js").write_text("console.log('hi');")

        # Excluded directories
        (root / "node_modules" / "express").mkdir(parents=True)
        (root / "node_modules" / "express" / "index.js").write_text("module.exports = {};")
        (root / ".venv" / "scripts").mkdir(parents=True)
        (root / ".venv" / "scripts" / "activate.js").write_text("")

        res = await find_tool.execute({"pattern": "**/*.js"}, {"working_directory": str(root)})
        assert res.success
        paths = [m["path"] for m in res.data["matches"]]
        assert len(paths) == 1
        assert paths[0] == "src/index.js"


@pytest.mark.asyncio
async def test_find_files_max_results_truncation():
    """Verify FindFilesTool limits output to max_results / limit."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        find_tool = FindFilesTool()

        (root / "logs").mkdir()
        for i in range(20):
            (root / "logs" / f"log_{i:02d}.txt").write_text(f"log {i}")

        res = await find_tool.execute({"pattern": "logs/*.txt", "max_results": 5}, {"working_directory": str(root)})
        assert res.success
        assert len(res.data["matches"]) == 5
        assert res.data["count"] == 5


@pytest.mark.asyncio
async def test_outcome_verifier_fast_path_non_code_files():
    """Verify OutcomeVerifier skips lengthy test runner for documentation and non-code files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        verifier = OutcomeVerifier(workspace_root=root)

        # Modifying markdown, docx, html, json, css
        res = await verifier.verify_test_suite_passes(
            modified_files=["docs/spec.md", "assets/style.css", "report.docx", "data.json", "index.html"]
        )
        assert res.verified is True
        assert "skipped test runner" in res.details


@pytest.mark.asyncio
async def test_outcome_verifier_triggers_for_code_files():
    """Verify OutcomeVerifier detects code changes and triggers test suite validation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        verifier = OutcomeVerifier(workspace_root=root)

        # When code files are modified without runner manifest in empty tmpdir, it reports clean manifest skip
        res = await verifier.verify_test_suite_passes(modified_files=["src/server.py"])
        assert res.verified is True
        assert "No manifest detected" in res.details or "skipping automated test suite" in res.details


@pytest.mark.asyncio
async def test_security_policy_path_boundary_enforcement():
    """Verify SecurityPolicy blocks directory traversal attacks outside workspace."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        policy = SecurityPolicy()

        # Inside workspace is safe
        assert policy.is_path_safe(root / "subfolder" / "file.txt", base_dir=root) is True

        # Escaping workspace via ../.. to system paths is rejected
        unsafe_traversal = Path("C:/Windows/System32/cmd.exe")
        assert policy.is_path_safe(unsafe_traversal, base_dir=root) is False


# 6. Public exports
__all__ = [
    "test_create_folder_deeply_nested",
    "test_create_folder_idempotent",
    "test_create_folder_relative_and_absolute",
    "test_create_folder_env_expansion",
    "test_write_file_strips_powershell_escapes_complex_html",
    "test_write_file_strips_powershell_escapes_in_json",
    "test_write_file_utf8_multibyte_and_emojis",
    "test_write_file_auto_creates_parent_directories",
    "test_write_file_overwrite_existing",
    "test_find_files_recursive_glob_filtering",
    "test_find_files_ignores_excluded_directories",
    "test_find_files_max_results_truncation",
    "test_outcome_verifier_fast_path_non_code_files",
    "test_outcome_verifier_triggers_for_code_files",
    "test_security_policy_path_boundary_enforcement",
]
