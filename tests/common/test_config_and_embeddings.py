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
    """Tests that the Settings class loads with default values."""
    # Instantiate the class directly, providing no env file.
    # Pydantic-settings will not find a .env file and use defaults.
    # This test is now independent of any .env file in the project root.
    settings_instance = config.Settings(_env_file=None)

    # Check default values
    assert settings_instance.LOG_LEVEL == "INFO"
    assert settings_instance.EMBED_PROVIDER == "openai"
    assert "workspace_dev" in str(settings_instance.REPO_DIR)
    assert settings_instance.OPENAI_API_KEY == "YOUR_OPENAI_API_KEY"

def test_settings_load_from_env_file(tmp_path, monkeypatch):
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

    # 2. Instantiate the Settings class, explicitly pointing to our temp .env file.
    # This forces it to load our test configuration and ignore any others.
    settings_instance = config.Settings(_env_file=env_file)

    # 3. Assert that the settings have been loaded from the .env file
    assert settings_instance.LOG_LEVEL == "DEBUG"
    assert settings_instance.EMBED_PROVIDER == "custom_provider_for_test"
    assert settings_instance.OPENAI_API_KEY == "sk-from-env-file"
    # The Settings class now correctly loads the relative path as-is.
    # The test should verify this behavior. Path resolution is handled by the app on startup.
    assert settings_instance.REPO_DIR == Path('./custom_workspace')

def test_embedding_factory_openai_success(monkeypatch):
    """
    Tests that the embedding factory returns an OpenAIEmbeddings instance correctly.
    """
    # We patch the 'settings' object specifically where it's imported and used.
    # This is more surgical than reloading the whole module.
    mock_settings = config.Settings(
        EMBED_PROVIDER='openai',
        OPENAI_API_KEY='sk-test-key',
        _env_file=None # Ensure no .env file is loaded
    )
    monkeypatch.setattr(embeddings, 'settings', mock_settings)

    embedding_model = embeddings.get_embedding_model()
    
    assert isinstance(embedding_model, OpenAIEmbeddings)
    # The key is correctly passed to the client instance
    # We must use .get_secret_value() to compare a Pydantic SecretStr
    assert embedding_model.openai_api_key.get_secret_value() == 'sk-test-key'

def test_embedding_factory_unsupported_provider_fails(monkeypatch):
    """
    Tests that the embedding factory raises a ValueError for an unsupported provider.
    """
    mock_settings = config.Settings(EMBED_PROVIDER='unsupported_provider', _env_file=None)
    monkeypatch.setattr(embeddings, 'settings', mock_settings)

    with pytest.raises(ValueError, match="Unsupported embedding provider configured"):
        embeddings.get_embedding_model()
