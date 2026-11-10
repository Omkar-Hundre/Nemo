"""Package management intelligence detecting ecosystems, manifests, and lockfiles."""

# 1. Standard library imports
import json
from pathlib import Path
from typing import Any

# 2. Third-party imports
from pydantic import BaseModel, Field

# 3. Local / internal imports
# (None)

# 4. Types, Protocols, Schemas
class ProjectEcosystem(BaseModel):
    """Detected development ecosystem and package manager details."""
    ecosystem: str  # "python" | "nodejs" | "rust" | "go" | "dotnet"
    package_manager: str  # "uv" | "pip" | "pnpm" | "npm" | "yarn" | "bun" | "cargo" | "go"
    manifest_file: str
    lock_file: str | None = None
    install_command: str
    validate_command: str
    installed: bool = False
    dev_command: str | None = None
    default_url: str | None = None
    dependencies: list[str] = Field(default_factory=list)

# 5. Core logic / classes / functions
class PackageManagerDetector:
    """Inspects workspace manifests to infer correct package managers and lockfiles."""

    @staticmethod
    def detect(root_path: Path | str) -> list[ProjectEcosystem]:
        root = Path(root_path).resolve()
        detected: list[ProjectEcosystem] = []

        # 1. Python ecosystem
        pyproject = root / "pyproject.toml"
        reqs = root / "requirements.txt"
        uv_lock = root / "uv.lock"

        if pyproject.exists() or reqs.exists():
            pkg_mgr = "uv" if uv_lock.exists() or pyproject.exists() else "pip"
            inst_cmd = "uv pip install -e ." if pkg_mgr == "uv" else "pip install -r requirements.txt"
            manifest = "pyproject.toml" if pyproject.exists() else "requirements.txt"
            lock = "uv.lock" if uv_lock.exists() else None

            deps: list[str] = []
            if reqs.exists():
                try:
                    deps = [
                        line.strip() for line in reqs.read_text(encoding="utf-8").splitlines()
                        if line.strip() and not line.startswith("#")
                    ]
                except Exception:
                    pass

            venv_python = root / ".venv" / "Scripts" / "python.exe"
            val_cmd = f'& "{venv_python}" -m pytest' if venv_python.exists() else "pytest"
            is_installed = venv_python.exists()

            py_dev_cmd = None
            if (root / "manage.py").exists():
                py_dev_cmd = "python manage.py runserver"
            elif (root / "app.py").exists():
                py_dev_cmd = "python app.py"
            elif (root / "main.py").exists():
                py_dev_cmd = "python main.py"

            py_url = "http://127.0.0.1:8000" if py_dev_cmd else None

            detected.append(ProjectEcosystem(
                ecosystem="python",
                package_manager=pkg_mgr,
                manifest_file=manifest,
                lock_file=lock,
                install_command=inst_cmd,
                validate_command=val_cmd,
                installed=is_installed,
                dev_command=py_dev_cmd,
                default_url=py_url,
                dependencies=deps[:20],
            ))

        # 2. Node.js ecosystem
        pkg_json = root / "package.json"
        if pkg_json.exists():
            pnpm_lock = root / "pnpm-lock.yaml"
            yarn_lock = root / "yarn.lock"
            bun_lock = root / "bun.lockb"
            npm_lock = root / "package-lock.json"

            if pnpm_lock.exists():
                pm = "pnpm"
                lock_name = "pnpm-lock.yaml"
            elif yarn_lock.exists():
                pm = "yarn"
                lock_name = "yarn.lock"
            elif bun_lock.exists():
                pm = "bun"
                lock_name = "bun.lockb"
            else:
                pm = "npm"
                lock_name = "package-lock.json" if npm_lock.exists() else None

            deps = []
            scripts: dict[str, Any] = {}
            dev_deps: dict[str, Any] = {}
            try:
                data = json.loads(pkg_json.read_text(encoding="utf-8"))
                deps = list(data.get("dependencies", {}).keys()) + list(data.get("devDependencies", {}).keys())
                scripts = data.get("scripts", {})
                dev_deps = data.get("devDependencies", {})
            except Exception:
                pass

            node_modules = root / "node_modules"
            is_node_installed = False
            if node_modules.is_dir():
                try:
                    is_node_installed = any(node_modules.iterdir())
                except Exception:
                    is_node_installed = True

            node_dev_cmd = None
            if "dev" in scripts:
                node_dev_cmd = f"{pm} run dev"
            elif "start" in scripts:
                node_dev_cmd = f"{pm} start"
            elif "serve" in scripts:
                node_dev_cmd = f"{pm} run serve"

            node_url = "http://localhost:3000"
            if "vite" in str(scripts.get("dev", "")) or "vite" in dev_deps or "vite" in deps:
                node_url = "http://localhost:5173"

            detected.append(ProjectEcosystem(
                ecosystem="nodejs",
                package_manager=pm,
                manifest_file="package.json",
                lock_file=lock_name,
                install_command=f"{pm} install",
                validate_command=f"{pm} test",
                installed=is_node_installed,
                dev_command=node_dev_cmd,
                default_url=node_url,
                dependencies=deps[:20],
            ))

        # 3. Rust ecosystem
        cargo_toml = root / "Cargo.toml"
        if cargo_toml.exists():
            cargo_lock = root / "Cargo.lock"
            is_rust_installed = cargo_lock.exists() or (root / "target").is_dir()
            detected.append(ProjectEcosystem(
                ecosystem="rust",
                package_manager="cargo",
                manifest_file="Cargo.toml",
                lock_file="Cargo.lock" if cargo_lock.exists() else None,
                install_command="cargo build",
                validate_command="cargo test",
                installed=is_rust_installed,
                dev_command="cargo run",
            ))

        # 4. Go ecosystem
        go_mod = root / "go.mod"
        if go_mod.exists():
            go_sum = root / "go.sum"
            detected.append(ProjectEcosystem(
                ecosystem="go",
                package_manager="go",
                manifest_file="go.mod",
                lock_file="go.sum" if go_sum.exists() else None,
                install_command="go mod download",
                validate_command="go test ./...",
                installed=go_sum.exists(),
                dev_command="go run .",
            ))

        return detected

# 6. Public exports
__all__ = ["ProjectEcosystem", "PackageManagerDetector"]
