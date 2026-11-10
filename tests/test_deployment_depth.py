"""Production-grade in-depth test suite for deployment safety, secret leak auditing, and CI/CD validation."""

# 1. Standard library imports
from pathlib import Path
import subprocess
import tempfile

# 2. Third-party imports
import pytest

# 3. Local / internal imports
from nemo.tools.builtin import DeployAnalysisTool

# 4. Types, Protocols, Schemas
# (None)

# 5. Core logic / classes / functions
def init_temp_git_repo(root: Path) -> None:
    """Helper to initialize a real Git repository in temp directory."""
    subprocess.run(["git", "init"], cwd=root, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "dev@nemo.ai"], cwd=root, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Nemo Developer"], cwd=root, capture_output=True, check=True)


@pytest.mark.asyncio
async def test_deploy_non_git_repo_warning():
    """Verify non-git workspace produces clear warning and safe_to_push=False."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        tool = DeployAnalysisTool()

        res = await tool.execute({"path": "."}, {"working_directory": str(root)})
        assert res.success
        assert res.data["safe_to_push"] is False
        assert any("not a Git repository" in w for w in res.data["warnings"])


@pytest.mark.asyncio
async def test_deploy_clean_git_repo_with_remote():
    """Verify a clean git repository with remote configured passes all push checks."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        init_temp_git_repo(root)

        # Add initial commit
        (root / "README.md").write_text("# Hello Nemo")
        subprocess.run(["git", "add", "README.md"], cwd=root, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=root, capture_output=True, check=True)

        # Add mock remote
        subprocess.run(["git", "remote", "add", "origin", "https://github.com/nemo/test-app.git"], cwd=root, capture_output=True, check=True)

        tool = DeployAnalysisTool()
        res = await tool.execute({"path": "."}, {"working_directory": str(root)})
        assert res.success
        assert res.data["safe_to_push"] is True
        assert res.data["safe_to_deploy"] is True
        assert len(res.data["blockers"]) == 0
        assert res.data["details"]["is_git_repo"] is True
        assert len(res.data["details"]["remotes"]) > 0


@pytest.mark.asyncio
async def test_deploy_dirty_working_tree_warning():
    """Verify uncommitted/untracked files trigger dirty working tree warning."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        init_temp_git_repo(root)

        # Create untracked file
        (root / "draft.txt").write_text("uncommitted work")

        tool = DeployAnalysisTool()
        res = await tool.execute({"path": "."}, {"working_directory": str(root)})
        assert res.success
        assert any("uncommitted or untracked changes" in w for w in res.data["warnings"])
        assert res.data["details"]["uncommitted_changes_count"] == 1


@pytest.mark.asyncio
async def test_deploy_no_remotes_warning():
    """Verify missing remote produces actionable setup recommendation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        init_temp_git_repo(root)

        tool = DeployAnalysisTool()
        res = await tool.execute({"path": "."}, {"working_directory": str(root)})
        assert res.success
        assert any("No Git remotes configured" in w for w in res.data["warnings"])


@pytest.mark.asyncio
async def test_deploy_secret_leak_unignored_env():
    """Verify .env without .gitignore triggers critical deployment blocker."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        init_temp_git_repo(root)

        (root / ".env").write_text("OPENAI_API_KEY=sk-12345")

        tool = DeployAnalysisTool()
        res = await tool.execute({"path": "."}, {"working_directory": str(root)})
        assert res.success
        assert res.data["safe_to_push"] is False
        assert res.data["safe_to_deploy"] is False
        assert any("CRITICAL: Secret file '.env' exists but is NOT covered in .gitignore" in b for b in res.data["blockers"])


@pytest.mark.asyncio
async def test_deploy_secret_leak_unignored_env_local():
    """Verify .env.local without explicit coverage in .gitignore is flagged."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        init_temp_git_repo(root)

        (root / ".gitignore").write_text(".env\n")
        (root / ".env.local").write_text("DATABASE_PASSWORD=supersecret")

        tool = DeployAnalysisTool()
        res = await tool.execute({"path": "."}, {"working_directory": str(root)})
        assert res.success
        assert any("CRITICAL: Secret file '.env.local'" in b for b in res.data["blockers"])


@pytest.mark.asyncio
async def test_deploy_secret_leak_wildcard_env_ignored():
    """Verify .gitignore containing .env* wildcard properly covers all .env variations."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        init_temp_git_repo(root)

        (root / ".gitignore").write_text(".env*\nnode_modules\n")
        (root / ".env").write_text("SECRET=1")
        (root / ".env.development").write_text("SECRET=2")
        (root / ".env.production").write_text("SECRET=3")

        tool = DeployAnalysisTool()
        res = await tool.execute({"path": "."}, {"working_directory": str(root)})
        assert res.success
        # None of the .env files should trigger unignored blocker
        env_blockers = [b for b in res.data["blockers"] if "NOT covered in .gitignore" in b]
        assert len(env_blockers) == 0


@pytest.mark.asyncio
async def test_deploy_secret_actively_tracked_in_git():
    """Verify .env tracked in Git index triggers critical removal blocker."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        init_temp_git_repo(root)

        (root / ".env").write_text("DB_PASS=123456")
        subprocess.run(["git", "add", ".env"], cwd=root, capture_output=True, check=True)

        tool = DeployAnalysisTool()
        res = await tool.execute({"path": "."}, {"working_directory": str(root)})
        assert res.success
        assert any("Secret file(s) are actively tracked in Git" in b for b in res.data["blockers"])


@pytest.mark.asyncio
async def test_deploy_hardcoded_github_token_in_diff():
    """Verify hardcoded GitHub Personal Access Token in git diff triggers blocker."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        init_temp_git_repo(root)

        # Baseline commit
        code_file = root / "client.py"
        code_file.write_text("# client")
        subprocess.run(["git", "add", "client.py"], cwd=root, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=root, capture_output=True, check=True)

        # Introduce GitHub token: ghp_ + 36 alphanumeric
        ghp_token = "ghp_" + ("a" * 36)
        code_file.write_text(f"GITHUB_TOKEN = '{ghp_token}'\n")

        tool = DeployAnalysisTool()
        res = await tool.execute({"path": "."}, {"working_directory": str(root)})
        assert res.success
        assert any("Hardcoded API secret/token detected in pending git diff" in b for b in res.data["blockers"])


@pytest.mark.asyncio
async def test_deploy_hardcoded_nvidia_token_in_diff():
    """Verify hardcoded NVIDIA NIM API key in git diff triggers blocker."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        init_temp_git_repo(root)

        code_file = root / "ai_model.py"
        code_file.write_text("# model")
        subprocess.run(["git", "add", "ai_model.py"], cwd=root, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=root, capture_output=True, check=True)

        nv_token = "nvapi-" + ("x" * 42)
        code_file.write_text(f"API_KEY = '{nv_token}'\n")

        tool = DeployAnalysisTool()
        res = await tool.execute({"path": "."}, {"working_directory": str(root)})
        assert res.success
        assert any("Hardcoded API secret/token detected" in b for b in res.data["blockers"])


@pytest.mark.asyncio
async def test_deploy_hardcoded_openai_token_in_diff():
    """Verify hardcoded OpenAI sk- token in git diff triggers blocker."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        init_temp_git_repo(root)

        code_file = root / "llm.py"
        code_file.write_text("# llm")
        subprocess.run(["git", "add", "llm.py"], cwd=root, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=root, capture_output=True, check=True)

        sk_token = "sk-" + ("k" * 34)
        code_file.write_text(f"KEY = '{sk_token}'\n")

        tool = DeployAnalysisTool()
        res = await tool.execute({"path": "."}, {"working_directory": str(root)})
        assert res.success
        assert any("Hardcoded API secret/token detected" in b for b in res.data["blockers"])


@pytest.mark.asyncio
async def test_deploy_hardcoded_aws_key_in_diff():
    """Verify hardcoded AWS AKIA access key in git diff triggers blocker."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        init_temp_git_repo(root)

        code_file = root / "s3.py"
        code_file.write_text("# s3")
        subprocess.run(["git", "add", "s3.py"], cwd=root, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=root, capture_output=True, check=True)

        aws_key = "AKIA" + ("Z" * 16)
        code_file.write_text(f"AWS_KEY = '{aws_key}'\n")

        tool = DeployAnalysisTool()
        res = await tool.execute({"path": "."}, {"working_directory": str(root)})
        assert res.success
        assert any("Hardcoded API secret/token detected" in b for b in res.data["blockers"])


@pytest.mark.asyncio
async def test_deploy_build_script_and_publish_dir_detection():
    """Verify detection of npm build scripts and publish output directories (dist/build/out)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "package.json").write_text('{"name": "app", "scripts": {"build": "next build"}}')
        (root / "dist").mkdir()
        (root / "dist" / "index.html").write_text("<html/>")

        tool = DeployAnalysisTool()
        res = await tool.execute({"path": "."}, {"working_directory": str(root)})
        assert res.success
        details = res.data["details"]
        assert details["has_package_json"] is True
        assert details["build_command"] == "npm run build"
        assert "dist" in details["detected_publish_dirs"]


@pytest.mark.asyncio
async def test_deploy_platform_filter_netlify():
    """Verify filtering by 'netlify' evaluates netlify.toml and provides Netlify-specific guidance."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        tool = DeployAnalysisTool()

        res_no_toml = await tool.execute({"path": ".", "target_platform": "netlify"}, {"working_directory": str(root)})
        assert res_no_toml.success
        assert any("No netlify.toml found" in w for w in res_no_toml.data["warnings"])
        # Should not mention vercel
        assert not any("vercel" in rec.lower() for rec in res_no_toml.data["recommendations"])

        (root / "netlify.toml").write_text("[build]\npublish = 'dist'\ncommand = 'npm run build'\n")
        res_with_toml = await tool.execute({"path": ".", "target_platform": "netlify"}, {"working_directory": str(root)})
        assert res_with_toml.success
        assert not any("No netlify.toml found" in w for w in res_with_toml.data["warnings"])
        assert any("netlify" in rec.lower() for rec in res_with_toml.data["recommendations"])


@pytest.mark.asyncio
async def test_deploy_platform_filter_vercel():
    """Verify filtering by 'vercel' inspects vercel.json and provides Vercel guidance."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        tool = DeployAnalysisTool()

        (root / "vercel.json").write_text('{"cleanUrls": true}')
        res = await tool.execute({"path": ".", "target_platform": "vercel"}, {"working_directory": str(root)})
        assert res.success
        assert res.data["details"]["has_vercel_json"] is True
        assert any("vercel" in rec.lower() for rec in res.data["recommendations"])
        # Should not mention netlify
        assert not any("netlify" in rec.lower() for rec in res.data["recommendations"])


@pytest.mark.asyncio
async def test_deploy_github_workflows_detection():
    """Verify detection of GitHub Actions CI/CD workflow YAML files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        tool = DeployAnalysisTool()

        # Without workflow
        res_none = await tool.execute({"path": ".", "target_platform": "github"}, {"working_directory": str(root)})
        assert any("No GitHub Actions workflows found" in w for w in res_none.data["warnings"])

        # With workflow
        wf_dir = root / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("name: CI\non: [push]\n")

        res_wf = await tool.execute({"path": ".", "target_platform": "github"}, {"working_directory": str(root)})
        assert res_wf.success
        assert "ci.yml" in res_wf.data["details"]["github_workflows"]
        assert any("GitHub Actions CI/CD workflows detected" in rec for rec in res_wf.data["recommendations"])


# 6. Public exports
__all__ = [
    "test_deploy_non_git_repo_warning",
    "test_deploy_clean_git_repo_with_remote",
    "test_deploy_dirty_working_tree_warning",
    "test_deploy_no_remotes_warning",
    "test_deploy_secret_leak_unignored_env",
    "test_deploy_secret_leak_unignored_env_local",
    "test_deploy_secret_leak_wildcard_env_ignored",
    "test_deploy_secret_actively_tracked_in_git",
    "test_deploy_hardcoded_github_token_in_diff",
    "test_deploy_hardcoded_nvidia_token_in_diff",
    "test_deploy_hardcoded_openai_token_in_diff",
    "test_deploy_hardcoded_aws_key_in_diff",
    "test_deploy_build_script_and_publish_dir_detection",
    "test_deploy_platform_filter_netlify",
    "test_deploy_platform_filter_vercel",
    "test_deploy_github_workflows_detection",
]
