# common/config.py

import os
from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# Determine the project root directory (assuming this file is in project_root/common/)
# This allows .env to be loaded from the project root.
PROJECT_ROOT = Path(__file__).parent.parent.resolve()

class Settings(BaseSettings):
    """
    Defines and loads all application settings from environment variables
    and/or a .env file.
    """
    # --- Workspace Configuration ---
    # Base directory for all agent operations (file I/O, LSP, Git, etc.).
    # All tools will operate relative to this path.
    # It's resolved to an absolute path to prevent ambiguity.
    REPO_DIR: Path = PROJECT_ROOT / "workspace_dev"

    # --- API Keys ---
    # Required for the agent's core planning/reasoning LLM.
    OPENAI_API_KEY: str = "YOUR_OPENAI_API_KEY"

    # Optional, for future flexibility or specific tools.
    TOGETHER_API_KEY: str | None = None
    GOOGLE_API_KEY: str | None = None

    # --- AI Model Configuration ---
    # Provider for text embeddings ('openai' is the default).
    EMBED_PROVIDER: str = "openai"

    # Model to use for OpenAI LLM calls.
    OPENAI_MODEL_NAME: str = "gpt-4.1-2025-04-14"

    # --- Tool & Service Configuration ---
    # URL for the running Model Context Protocol (MCP) server.
    MCP_SERVER_URL: str = "http://127.0.0.1:8080"

    # Command to execute the TypeScript Language Server.
    TS_LSP_CMD: str = "typescript-language-server --stdio"

    # Paths for data stores, relative to REPO_DIR.
    VECTOR_STORE_PATH: str = ".dev_data/chroma_db"
    EMBEDDING_CACHE_PATH: str = ".dev_data/embedding_cache"

    # --- System & Server Configuration ---
    # Logging level for the application (DEBUG, INFO, WARNING, ERROR, CRITICAL).
    LOG_LEVEL: str = "INFO"

    # --- Test-Specific Settings ---
    # If set, the full E2E test will write its output here instead of a temp dir.
    E2E_OUTPUT_DIR: Optional[Path] = None

    # Host and port for the FastAPI gateway.
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Pydantic Settings configuration
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding='utf-8',
        case_sensitive=False,
        extra='ignore' # Ignore extra fields from .env file
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Returns a cached instance of the application settings.

    The lru_cache decorator ensures that the Settings object is created only
    once, the first time this function is called. This allows test fixtures
    or other setup code to modify environment variables before the settings
    are loaded.
    """
    return Settings()


# For convenience, a global settings object is provided.
# However, for code that needs to be testable with different configurations
# (e.g., in integration tests), it's better to call get_settings()
# directly inside the function or method to ensure the latest,
# test-specific configuration is loaded.
settings = get_settings()