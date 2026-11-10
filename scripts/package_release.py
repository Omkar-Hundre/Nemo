"""Package NEMO codebase into a clean, standalone distributable ZIP archive for friends and release."""

# 1. Standard library imports
from pathlib import Path
import zipfile

# 2. Third-party imports
# (None)

# 3. Local / internal imports
# (None)

# 4. Types, Protocols, Schemas
EXCLUDED_NAMES = {
    ".git",
    ".venv",
    ".pytest_cache",
    "__pycache__",
    "dist",
    "build",
    ".coverage",
    ".env",  # Exclude private developer API keys
}

# 5. Core logic / classes / functions
def package_nemo(output_dir: Path | str = "dist") -> Path:
    """Create clean release zip containing codebase, installer, and docs."""
    root = Path(__file__).resolve().parent.parent
    dist_dir = (root / output_dir).resolve()
    dist_dir.mkdir(parents=True, exist_ok=True)
    zip_path = dist_dir / "Nemo-Windows-Installer.zip"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for file_path in root.rglob("*"):
            if file_path.is_dir():
                continue
            # Check exclusions
            rel = file_path.relative_to(root)
            if any(part in EXCLUDED_NAMES for part in rel.parts):
                continue
            if file_path.suffix == ".pyc":
                continue

            zipf.write(file_path, arcname=str(rel))

    print(f"[OK] Release archive packaged successfully: {zip_path}")
    print(f"     Archive size: {zip_path.stat().st_size / (1024 * 1024):.2f} MB")
    return zip_path


# 6. Public exports
__all__ = ["package_nemo"]

if __name__ == "__main__":
    package_nemo()

