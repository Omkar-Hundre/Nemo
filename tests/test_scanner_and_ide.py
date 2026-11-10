"""Self-check verification test for Phase 6 scanner and Phase 7 IDE registry."""

# 1. Standard library imports
import asyncio
from pathlib import Path
import tempfile

# 2. Third-party imports
# (None)

# 3. Local / internal imports
from nemo.intelligence.indexer import ProjectIndexer
from nemo.intelligence.scanner import ProjectScanner
from nemo.integrations.ide.registry import IDERegistry

# 4. Types, Protocols, Schemas
# (None)

# 5. Core logic / classes / functions
def test_project_scanner_and_incremental_indexer():
    """Verify scanner filtering, language detection, and incremental cache skips."""
    with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as cachedir:
        root = Path(tmpdir)
        cache_dir = Path(cachedir)

        # Create files
        (root / "main.py").write_text("print('hello')", encoding="utf-8")
        (root / "types.ts").write_text("export type User = { id: string };", encoding="utf-8")

        # Create ignored folder and file
        venv_dir = root / ".venv"
        venv_dir.mkdir()
        (venv_dir / "ignored.py").write_text("secret", encoding="utf-8")

        # Create .env file (should be ignored by default)
        (root / ".env").write_text("SECRET=123", encoding="utf-8")

        # 1. Test Scanner
        scanner = ProjectScanner(root)
        scanned = scanner.scan()
        rel_paths = [f.relative_path for f in scanned]

        assert "main.py" in rel_paths
        assert "types.ts" in rel_paths
        assert not any(".venv" in p for p in rel_paths)
        assert not any(".env" in p for p in rel_paths)

        # 2. Test Incremental Indexer
        indexer = ProjectIndexer(root, cache_dir=cache_dir)
        report1 = indexer.run_index()
        assert report1.total_files == 2
        assert report1.indexed_files == 2
        assert report1.skipped_files == 0
        assert "python" in report1.languages
        assert "typescript" in report1.languages

        # Second run without changes -> both files should be skipped!
        report2 = indexer.run_index()
        assert report2.total_files == 2
        assert report2.indexed_files == 0
        assert report2.skipped_files == 2


async def async_test_ide_registry():
    """Verify IDE adapter detection."""
    registry = IDERegistry()
    available = await registry.list_available()
    names = [a["name"] for a in available]
    assert "antigravity" in names
    assert "vscode" in names

    # On this development machine, at least one is installed
    assert any(a["detected"] for a in available), "Expected Antigravity or VS Code to be detected"


def main():
    print("Running Phase 6 scanner and Phase 7 IDE verification...")
    test_project_scanner_and_incremental_indexer()
    print("✓ Project scanner and incremental indexer checks passed!")
    asyncio.run(async_test_ide_registry())
    print("✓ IDE registry detection checks passed!")


if __name__ == "__main__":
    main()

# 6. Public exports
__all__ = ["test_project_scanner_and_incremental_indexer", "async_test_ide_registry"]
