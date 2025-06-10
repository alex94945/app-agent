# tests/common/test_config_and_embeddings.py

import os
from pathlib import Path
import importlib

import pytest
from pydantic import ValidationError
from langchain_openai import OpenAIEmbeddings

# We need to test the modules, so we import them.
from common import config, embeddings

def test_settings_load_defaults():
    """
    Tests that settings load correctly with default values when no .env file is present.
    """
    # Temporarily remove .env path to ensure defaults are used
    # We use monkeypatch, a pytest fixture to safely modify environment/modules for a test
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(config, 'PROJECT_ROOT', Path('/tmp/non_existent_dir'))
    
    # Reload the module to re-trigger the Settings instantiation
    importlib.reload(config)
    
    # Check default values
    assert config.settings.LOG_LEVEL == "INFO"
    assert config.settings.EMBED_PROVIDER == "openai"
    assert "workspace_dev" in str(config.settings.REPO_DIR)
    assert config.settings.OPENAI_API_KEY == "YOUR_OPENAI_API_KEY"

def test_settings_load_from_env_file(tmp_path):
    """
    Tests that settings are correctly overridden by a .env file.
    tmp_path is a pytest fixture that provides a temporary directory.
    """
    # 1. Create a dummy .env file in the temporary directory
    env_content = """
    REPO_DIR=./custom_workspace
    OPENAI_API_KEY=sk-from-env-file
    LOG_LEVEL=DEBUG
    EMBED_PROVIDER=custom_provider_for_test
    """
    env_file = tmp_path / ".env"
    env_file.write_text(env_content)

    # 2. Patch the PROJECT_ROOT in the config module to point to our temp dir
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(config, 'PROJECT_ROOT', tmp_path)

    # 3. Reload the config module to make it read from the new .env path
    importlib.reload(config)

    # 4. Assert that the settings have been loaded from the .env file
    assert config.settings.LOG_LEVEL == "DEBUG"
    assert config.settings.EMBED_PROVIDER == "custom_provider_for_test"
    assert config.settings.OPENAI_API_KEY == "sk-from-env-file"
    # Check that REPO_DIR is resolved correctly relative to the temp path
    assert config.settings.REPO_DIR == (tmp_path / "custom_workspace").resolve()

def test_embedding_factory_openai_success():
    """
    Tests that the embedding factory returns an OpenAIEmbeddings instance correctly.
    """
    monkeypatch = pytest.MonkeyPatch()
    # Ensure the settings reflect the desired provider for this test
    monkeypatch.setattr(config.settings, 'EMBED_PROVIDER', 'openai')
    monkeypatch.setattr(config.settings, 'OPENAI_API_KEY', 'sk-test-key')

    # Reload embeddings module to make sure it sees the patched config
    importlib.reload(embeddings)
    
    embedding_model = embeddings.get_embedding_model()
    
    assert isinstance(embedding_model, OpenAIEmbeddings)
    # The key is correctly passed to the client instance
    assert embedding_model.openai_api_key == 'sk-test-key'

def test_embedding_factory_unsupported_provider_fails():
    """
    Tests that the embedding factory raises a ValueError for an unsupported provider.
    """
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(config.settings, 'EMBED_PROVIDER', 'unsupported_provider')
    
    # Reload embeddings module to see the patched config
    importlib.reload(embeddings)

    with pytest.raises(ValueError, match="Unsupported embedding provider configured"):
        embeddings.get_embedding_model()
