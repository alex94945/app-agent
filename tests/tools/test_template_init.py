"""Tests for the template_init tool."""

import pytest
import shutil
from pathlib import Path

from tools.template_init import template_init


@pytest.fixture
def setup_test_environment(tmp_path: Path, monkeypatch):
    """Create a temporary workspace and template directory for testing."""
    test_workspace = tmp_path / "workspace"
    test_templates = tmp_path / "templates"
    test_workspace.mkdir()
    test_templates.mkdir()

    # Patch the constants in the module where they are used
    monkeypatch.setattr('tools.template_init.WORKSPACE_ROOT', test_workspace)
    monkeypatch.setattr('tools.template_init.TEMPLATES_ROOT', test_templates)

    # Create a dummy template
    (test_templates / "nextjs-base").mkdir()
    (test_templates / "nextjs-base" / "index.js").write_text("console.log('hello');")

    yield test_workspace, test_templates


def test_template_init_success(setup_test_environment):
    """Test that the template is copied successfully."""
    test_workspace, _ = setup_test_environment
    project_name = "my-new-app"

    result_path = template_init.invoke({"project_name": project_name})

    assert Path(result_path).name == project_name
    assert (test_workspace / project_name).is_dir()
    assert (test_workspace / project_name / "index.js").exists()


def test_template_init_missing_template(setup_test_environment):
    """Test that a FileNotFoundError is raised for a missing template."""
    with pytest.raises(FileNotFoundError):
        template_init.invoke({"project_name": "my-app", "template_name": "non-existent-template"})


def test_template_init_project_exists(setup_test_environment):
    """Test that a FileExistsError is raised if the project directory already exists."""
    test_workspace, _ = setup_test_environment
    project_name = "my-existing-app"
    (test_workspace / project_name).mkdir()

    with pytest.raises(FileExistsError):
        template_init.invoke({"project_name": project_name})
