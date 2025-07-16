import pytest
import json
from pydantic import BaseModel

from agent.executor.output_handlers import (
    get_output_handler,
    DefaultOutputHandler,
    RunShellOutputHandler,
    ApplyPatchOutputHandler,
)
from tools.shell_mcp_tools import RunShellOutput
from tools.patch_tools import ApplyPatchOutput

# --- Test Data Fixtures ---

@pytest.fixture
def run_shell_success():
    return RunShellOutput(ok=True, return_code=0, stdout="Success", stderr="", command_executed="echo success")

@pytest.fixture
def run_shell_failure():
    return RunShellOutput(ok=False, return_code=1, stdout="", stderr="Error", command_executed="ls non_existent_file")

@pytest.fixture
def apply_patch_success():
    return ApplyPatchOutput(ok=True, message="Patch applied")

@pytest.fixture
def apply_patch_failure():
    return ApplyPatchOutput(ok=False, message="Patch failed")

class UnknownOutputWithSuccess(BaseModel):
    success: bool
    data: str

class UnknownOutputWithOk(BaseModel):
    ok: bool
    info: str

class UnknownOutput(BaseModel):
    data: str

class SuccessAttributeOutput(BaseModel):
    success: bool
    info: str

class OkAttributeOutput(BaseModel):
    ok: bool
    data: str

class PlainOldObject:
    pass

# --- Handler Resolution Tests ---

def test_get_output_handler_resolves_correctly():
    """Verify that get_output_handler returns the correct handler for each type."""
    assert isinstance(get_output_handler(RunShellOutput(ok=True, return_code=0, stdout="", stderr="", command_executed="test")), RunShellOutputHandler)
    assert isinstance(get_output_handler(ApplyPatchOutput(ok=True, message="")), ApplyPatchOutputHandler)
    assert isinstance(get_output_handler("a string"), DefaultOutputHandler)
    assert isinstance(get_output_handler({"key": "value"}), DefaultOutputHandler)
    assert isinstance(get_output_handler(PlainOldObject()), DefaultOutputHandler)

# --- Handler Logic Tests ---

def test_run_shell_handler(run_shell_success, run_shell_failure):
    """Test the RunShellOutputHandler's success logic."""
    handler = RunShellOutputHandler()
    assert handler.is_successful(run_shell_success) is True
    assert handler.is_successful(run_shell_failure) is False

def test_apply_patch_handler(apply_patch_success, apply_patch_failure):
    """Test the ApplyPatchOutputHandler's success logic."""
    handler = ApplyPatchOutputHandler()
    assert handler.is_successful(apply_patch_success) is True
    assert handler.is_successful(apply_patch_failure) is False





# Test DefaultOutputHandler directly

@pytest.mark.parametrize(
    "output_obj, expected_success",
    [
        (UnknownOutputWithSuccess(success=True, data="y"), True),
        (UnknownOutputWithSuccess(success=False, data="n"), False),
        (UnknownOutputWithOk(ok=True, info="y"), True),
        (UnknownOutputWithOk(ok=False, info="n"), False),
        ("a string", True), # Simple types assumed successful by default
        (123, True),
        (True, True),
        (None, True),
        ([1, 2], True),
        ({"a": 1}, True),
        (UnknownOutput(data="unknown"), False), # Unknown complex object without success/ok
    ]
)
def test_default_handler_is_successful(output_obj, expected_success):
    handler = DefaultOutputHandler()
    assert handler.is_successful(output_obj) == expected_success

@pytest.mark.parametrize(
    "output_obj, expected_format_contains",
    [
        (SuccessAttributeOutput(success=True, info="yes"), '"success": true'),
        ("a string", "a string"),
        (123, "123"),
        (None, "None"),
        ([1, 2], json.dumps([1,2], indent=2)),
        ({"a": 1}, json.dumps({"a":1}, indent=2)),
        (UnknownOutput(data="unknown"), '"data": "unknown"'),
    ]
)
def test_default_handler_format_output(output_obj, expected_format_contains):
    handler = DefaultOutputHandler()
    formatted = handler.format_output(output_obj)
    assert expected_format_contains in formatted

def test_default_handler_format_output_non_json_serializable_dict():
    class NonJson: pass
    output_obj = {"key": NonJson()}
    handler = DefaultOutputHandler()
    formatted = handler.format_output(output_obj)
    assert "{'key': <" in formatted and ".NonJson object at " in formatted and ">}" in formatted # Fallback to str()
