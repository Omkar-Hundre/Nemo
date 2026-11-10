"""Production-grade in-depth test suite for advanced operating, document, and network tools."""

# 1. Standard library imports
import asyncio
from pathlib import Path
import socket
import tempfile

# 2. Third-party imports
import pytest

# 3. Local / internal imports
from nemo.tools.builtin import (
    CreateFolderTool,
    DeployAnalysisTool,
    DocumentGeneratorTool,
    DocumentReaderTool,
    EnvConfigInspectorTool,
    FindFilesTool,
    HttpProbeTool,
    PortManagerTool,
    PresentationGeneratorTool,
    ScaffoldProjectTool,
    WriteFileTool,
)

# 4. Types, Protocols, Schemas
# (None)

# 5. Core logic / classes / functions
@pytest.mark.asyncio
async def test_find_files_recursive_with_exclusions():
    """Verify recursive glob search excludes .venv, node_modules, and returns correct files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "src" / "components").mkdir(parents=True)
        (root / "src" / "components" / "Button.tsx").write_text("// Button component")
        (root / "src" / "App.tsx").write_text("// App component")
        (root / "package.json").write_text('{"name": "test"}')

        # Create excluded directory structure
        (root / ".venv" / "Lib").mkdir(parents=True)
        (root / ".venv" / "Lib" / "config.json").write_text("{}")
        (root / "node_modules" / "pkg").mkdir(parents=True)
        (root / "node_modules" / "pkg" / "package.json").write_text("{}")

        tool = FindFilesTool()
        res = await tool.execute({"pattern": "**/*.tsx"}, {"working_directory": str(root)})
        assert res.success
        paths = [m["path"] for m in res.data["matches"]]
        assert "src/components/Button.tsx" in paths
        assert "src/App.tsx" in paths
        assert not any(".venv" in p for p in paths)
        assert not any("node_modules" in p for p in paths)

        # Glob for package.json
        res_json = await tool.execute({"pattern": "**/package.json"}, {"working_directory": str(root)})
        assert res_json.success
        assert len(res_json.data["matches"]) == 1
        assert res_json.data["matches"][0]["path"] == "package.json"


@pytest.mark.asyncio
async def test_port_manager_free_and_bound_port():
    """Verify PortManagerTool identifies free ports and detects active listening sockets."""
    tool = PortManagerTool()

    # 1. Inspect guaranteed free port
    free_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    free_sock.bind(("127.0.0.1", 0))
    free_port = free_sock.getsockname()[1]
    free_sock.close()

    res_free = await tool.execute({"action": "inspect", "port": free_port}, {})
    assert res_free.success
    assert res_free.data["in_use"] is False

    # 2. Bind port and inspect while listening
    srv_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv_sock.bind(("127.0.0.1", free_port))
    srv_sock.listen(1)

    try:
        res_busy = await tool.execute({"action": "inspect", "port": free_port}, {})
        assert res_busy.success
        assert res_busy.data["in_use"] is True
        assert res_busy.data["port"] == free_port
        assert "pid" in res_busy.data
    finally:
        srv_sock.close()


@pytest.mark.asyncio
async def test_http_probe_connection_refused():
    """Verify HttpProbeTool detects connection refused gracefully."""
    tool = HttpProbeTool()
    # Find unused port
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    dead_port = s.getsockname()[1]
    s.close()

    res = await tool.execute({"url": f"http://127.0.0.1:{dead_port}", "timeout_seconds": 1.0}, {})
    assert res.success is False
    assert "connection refused" in res.error.lower() or "timed out" in res.error.lower()


@pytest.mark.asyncio
async def test_env_config_inspector():
    """Verify EnvConfigInspectorTool detects missing and unpopulated placeholder keys."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / ".env.example").write_text(
            "PORT=3000\nDATABASE_URL=postgresql://localhost:5432/db\nAPI_KEY=replace_me\nSECRET_KEY=todo\n"
        )
        (root / ".env").write_text(
            "PORT=8080\nAPI_KEY=YOUR_API_KEY\n"
        )

        tool = EnvConfigInspectorTool()
        res = await tool.execute({}, {"working_directory": str(root)})
        assert res.success
        data = res.data
        assert data["target_file_exists"] is True
        assert data["example_file_exists"] is True
        assert "DATABASE_URL" in data["missing_keys"]
        assert "SECRET_KEY" in data["missing_keys"]
        assert "API_KEY" in data["unpopulated_keys"]
        assert data["is_healthy"] is False


@pytest.mark.asyncio
async def test_document_generator_and_reader_docx_and_csv():
    """Verify DOCX and CSV generation and structured extraction."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)

        # 1. Generate DOCX
        gen_tool = DocumentGeneratorTool()
        docx_path = root / "Architecture_Report.docx"
        res_gen = await gen_tool.execute(
            {
                "path": str(docx_path),
                "title": "NEMO System Architecture",
                "format": "docx",
                "sections": [
                    {
                        "heading": "Core Operating Components",
                        "body": "NEMO coordinates development environments natively on Windows.",
                        "bullets": ["Session Manager", "NVIDIA AI Core", "Intelligent Memory Engine"],
                    }
                ],
            },
            {"working_directory": str(root)},
        )
        assert res_gen.success
        assert docx_path.exists()
        assert docx_path.stat().st_size > 0

        # 2. Read DOCX back
        read_tool = DocumentReaderTool()
        res_read = await read_tool.execute({"path": str(docx_path)}, {"working_directory": str(root)})
        assert res_read.success
        assert res_read.data["format"] == "docx"
        assert "NEMO System Architecture" in res_read.data["content"]
        assert "Core Operating Components" in res_read.data["content"]
        assert "Session Manager" in res_read.data["content"]

        # 3. Read CSV
        csv_path = root / "metrics.csv"
        csv_path.write_text("model,accuracy,latency_ms\nNemotron-120B,98.5,120\nEmbed-1B,99.1,15\n")
        res_csv = await read_tool.execute({"path": str(csv_path)}, {"working_directory": str(root)})
        assert res_csv.success
        assert res_csv.data["format"] == "csv"
        assert res_csv.data["headers"] == ["model", "accuracy", "latency_ms"]
        assert len(res_csv.data["rows"]) == 3


@pytest.mark.asyncio
async def test_presentation_generator_standalone_html():
    """Verify interactive HTML presentation generation with keyboard navigation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        pres_tool = PresentationGeneratorTool()
        html_path = root / "deck.html"

        res = await pres_tool.execute(
            {
                "path": str(html_path),
                "title": "NEMO Developer Environment",
                "subtitle": "AI-Native Operating System for Windows",
                "theme": "dark",
                "slides": [
                    {
                        "title": "Architecture Overview",
                        "content": "A high-performance operating layer for developers.",
                        "bullets": ["Native Windows Subprocess", "NVIDIA NIM Nemotron", "Persistent Memory"],
                    },
                    {
                        "title": "Sample Execution",
                        "code": "nemo task 'inspect codebase architecture'",
                    },
                ],
            },
            {"working_directory": str(root)},
        )
        assert res.success
        assert html_path.exists()
        content = html_path.read_text(encoding="utf-8")
        assert "NEMO Developer Environment" in content
        assert "Architecture Overview" in content
        assert "showSlide(current + 1)" in content
        assert "ArrowRight" in content
        assert res.data["slide_count"] == 3  # 1 title slide + 2 body slides


@pytest.mark.asyncio
async def test_scaffold_project_fastapi():
    """Verify non-interactive FastAPI project scaffolding without prompts."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        scaffold_tool = ScaffoldProjectTool()

        res = await scaffold_tool.execute(
            {
                "template": "fastapi",
                "project_name": "backend_service",
                "install_dependencies": False,
            },
            {"working_directory": str(root)},
        )
        assert res.success
        target = root / "backend_service"
        assert (target / "pyproject.toml").exists()
        assert (target / "main.py").exists()
        assert "FastAPI" in (target / "main.py").read_text(encoding="utf-8")
        assert res.data["dev_command"] == "uvicorn main:app --reload --port 8000"


@pytest.mark.asyncio
async def test_create_folder_and_sanitized_write_file():
    """Verify CreateFolderTool creates directories and WriteFileTool strips PowerShell backticks."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        folder_tool = CreateFolderTool()
        write_tool = WriteFileTool()

        # 1. Create nested directory
        res_dir = await folder_tool.execute({"path": "downloads/omkarisgreat"}, {"working_directory": str(root)})
        assert res_dir.success
        target_dir = root / "downloads" / "omkarisgreat"
        assert target_dir.is_dir()

        # 2. Write file containing accidental PowerShell escape sequences (`n and `")
        ps_escaped_html = "<!DOCTYPE html>`n<html lang=`\"en`\">`n<head>`n<title>Hello</title>`n</head>`n<body>`n<h1>Hello Omkar</h1>`n</body>`n</html>"
        res_file = await write_tool.execute(
            {"path": "downloads/omkarisgreat/test.html", "content": ps_escaped_html},
            {"working_directory": str(root)},
        )
        assert res_file.success
        html_file = target_dir / "test.html"
        assert html_file.exists()
        cleaned_content = html_file.read_text(encoding="utf-8")

        # Verify no backticks remain; standard HTML tags and newlines are preserved
        assert "`n" not in cleaned_content
        assert '`"' not in cleaned_content
        assert '<html lang="en">' in cleaned_content
        assert "\n" in cleaned_content
        assert "<h1>Hello Omkar</h1>" in cleaned_content


@pytest.mark.asyncio
async def test_deploy_analysis_tool_secret_leak_and_platform_detection():
    """Verify DeployAnalysisTool flags unignored .env files as critical blockers."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        deploy_tool = DeployAnalysisTool()

        # Scenario A: .env exists without .gitignore -> blocker
        (root / ".env").write_text("DATABASE_URL=postgres://user:pass@localhost/db")
        res_blocked = await deploy_tool.execute({"path": "."}, {"working_directory": str(root)})
        assert res_blocked.success
        assert res_blocked.data["safe_to_push"] is False
        assert any("Secret file '.env' exists but is NOT covered in .gitignore" in b for b in res_blocked.data["blockers"])

        # Scenario B: Add .gitignore and package.json with build script
        (root / ".gitignore").write_text(".env\nnode_modules\ndist\n")
        (root / "package.json").write_text('{"name": "my-app", "scripts": {"build": "vite build"}}')
        (root / "dist").mkdir()
        (root / "dist" / "index.html").write_text("<h1>App</h1>")

        res_ready = await deploy_tool.execute({"path": "."}, {"working_directory": str(root)})
        assert res_ready.success
        # Blockers resolved
        assert len(res_ready.data["blockers"]) == 0
        assert res_ready.data["safe_to_deploy"] is True
        assert "dist" in res_ready.data["details"]["detected_publish_dirs"]
        assert any("netlify" in rec.lower() for rec in res_ready.data["recommendations"])


@pytest.mark.asyncio
async def test_outcome_verifier_skips_test_runner_for_content():
    """Verify OutcomeVerifier skips lengthy test suites for non-code files."""
    from nemo.agent.verifier import OutcomeVerifier
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        verifier = OutcomeVerifier(workspace_root=root)

        # Modifying only HTML/markdown should bypass test runner
        res = await verifier.verify_test_suite_passes(modified_files=["index.html", "README.md"])
        assert res.verified
        assert "skipped test runner" in res.details


# 6. Public exports
__all__ = [
    "test_find_files_recursive_with_exclusions",
    "test_port_manager_free_and_bound_port",
    "test_http_probe_connection_refused",
    "test_env_config_inspector",
    "test_document_generator_and_reader_docx_and_csv",
    "test_presentation_generator_standalone_html",
    "test_scaffold_project_fastapi",
    "test_create_folder_and_sanitized_write_file",
    "test_deploy_analysis_tool_secret_leak_and_platform_detection",
    "test_outcome_verifier_skips_test_runner_for_content",
]
