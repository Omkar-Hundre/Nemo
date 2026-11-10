"""Configuration module for NEMO."""

# 1. Standard library imports
from pathlib import Path

# 2. Third-party imports
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# 3. Local / internal imports
# (None)

# 4. Types, Protocols, Schemas
class Settings(BaseSettings):
    """Global application settings loaded from environment and .env file."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # AI Provider Settings
    nvidia_api_key: str = Field(default="", alias="NVIDIA_API_KEY")
    nvidia_base_url: str = Field(
        default="https://integrate.api.nvidia.com/v1",
        alias="NVIDIA_BASE_URL"
    )
    nvidia_model: str = Field(
        default="nvidia/nemotron-3.5-super-vl-120b-a12b",
        alias="NVIDIA_MODEL"
    )

    # Runtime Settings
    default_shell: str = Field(default="powershell", alias="NEMO_SHELL")
    default_ide: str = Field(default="antigravity", alias="NEMO_IDE")
    workspace_root: Path = Field(default_factory=Path.cwd, alias="NEMO_WORKSPACE")
    debug: bool = Field(default=False, alias="NEMO_DEBUG")

# 5. Core logic / classes / functions
_settings: Settings | None = None

def get_settings() -> Settings:
    """Return cached global settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings

# 6. Public exports
__all__ = ["Settings", "get_settings"]
