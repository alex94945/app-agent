import pytest
import json
from pydantic import BaseModel

from agent.executor.output_handlers import (
    is_tool_successful,
    format_tool_output,
    get_handler,
    DefaultOutputHandler,
    RunShellOutputHandler,
    WriteFileOutputHandler,
    ApplyPatchOutputHandler,
    OUTPUT_HANDLERS
)
from tools.shell_mcp_tools import RunShellOutput
from tools.file_io_mcp_tools import WriteFileOutput
from tools.patch_tools import ApplyPatchOutput


# --- Test Data ---

@pytest.fixture
def mock_run_shell_output_success():
    return RunShellOutput(
        ok=True,
        return_code=0,
        stdout="Command output",
        stderr="",
        command_executed="ls -l"
    )

@pytest.fixture
def mock_run_shell_output_failure():
    return RunShellOutput(
        ok=False,
        return_code=1,
        stdout="",
        stderr="Error occurred",
        command_executed="bad_command"
    )

@pytest.fixture
def mock_write_file_output_success():
    return WriteFileOutput(
        ok=True,
        path="/path/to/file.txt",
        message="File written successfully."
    )

@pytest.fixture
def mock_write_file_output_failure():
    return WriteFileOutput(
        ok=False,
        path="/path/to/file.txt",
        message="Failed to write file."
    )

@pytest.fixture
def mock_apply_patch_output_success():
    return ApplyPatchOutput(
        ok=True,
        file_path_hint="file.py",
        message="Patch applied successfully.",
        details=None
    )

@pytest.fixture
def mock_apply_patch_output_failure():
    return ApplyPatchOutput(
        ok=False,
        message="Patch application failed."
    )

class UnknownOutput(BaseModel):
    data: str

class SuccessAttributeOutput(BaseModel):
    success: bool
    info: str

class OkAttributeOutput(BaseModel):
    ok: bool
    info: str

# --- Test Cases ---

# Test get_handler
def test_get_handler_specific_types():
    assert isinstance(get_handler(RunShellOutput(ok=True, return_code=0, stdout="", stderr="", command_executed="")), RunShellOutputHandler)
    assert isinstance(get_handler(WriteFileOutput(ok=True, path="", message="")), WriteFileOutputHandler)
    assert isinstance(get_handler(ApplyPatchOutput(ok=True, file_path_hint="", message="")), ApplyPatchOutputHandler)

def test_get_handler_default():
    assert isinstance(get_handler("just a string"), DefaultOutputHandler)
    assert isinstance(get_handler(UnknownOutput(data="test")), DefaultOutputHandler)

# Test is_tool_successful

def test_is_tool_successful_run_shell(mock_run_shell_output_success, mock_run_shell_output_failure):
    assert is_tool_successful(mock_run_shell_output_success) is True
    assert is_tool_successful(mock_run_shell_output_failure) is False

def test_is_tool_successful_write_file(mock_write_file_output_success, mock_write_file_output_failure):
    assert is_tool_successful(mock_write_file_output_success) is True
    assert is_tool_successful(mock_write_file_output_failure) is False

def test_is_tool_successful_apply_patch(mock_apply_patch_output_success, mock_apply_patch_output_failure):
    assert is_tool_successful(mock_apply_patch_output_success) is True
    assert is_tool_successful(mock_apply_patch_output_failure) is False

# Test format_tool_output

def test_format_tool_output_run_shell_success(mock_run_shell_output_success):
    formatted = format_tool_output(mock_run_shell_output_success)
    assert "Command 'ls -l' executed successfully." in formatted
    assert "Stdout:\nCommand output" in formatted
    assert "Stderr:" not in formatted # No stderr for success

def test_format_tool_output_run_shell_success_no_stdout():
    output = RunShellOutput(ok=True, return_code=0, stdout="  ", stderr="", command_executed="echo 'hello'")
    formatted = format_tool_output(output)
    assert "Command 'echo 'hello'' executed successfully." == formatted # No stdout if it's blank

def test_format_tool_output_run_shell_failure(mock_run_shell_output_failure):
    formatted = format_tool_output(mock_run_shell_output_failure)
    assert "Command 'bad_command' failed with return code 1." in formatted
    assert "Stderr:\nError occurred" in formatted
    assert "Stdout:" not in formatted # No stdout for this failure case

def test_format_tool_output_write_file(mock_write_file_output_success, mock_write_file_output_failure):
    assert format_tool_output(mock_write_file_output_success) == "File written successfully."
    assert format_tool_output(mock_write_file_output_failure) == "Failed to write file."

def test_format_tool_output_apply_patch_success(mock_apply_patch_output_success):
    assert format_tool_output(mock_apply_patch_output_success) == "Patch applied successfully."

def test_format_tool_output_apply_patch_failure(mock_apply_patch_output_failure):
    formatted = format_tool_output(mock_apply_patch_output_failure)
    assert "Patch application failed." in formatted
    assert "Error details:\nGit apply error" in formatted

def test_format_tool_output_apply_patch_failure_no_details_stderr(mock_apply_patch_output_failure):
    mock_apply_patch_output_failure.details.stderr = "  " # Blank stderr
    formatted = format_tool_output(mock_apply_patch_output_failure)
    assert format_tool_output(mock_apply_patch_output_failure) == "Patch application failed."

# Test DefaultOutputHandler directly

@pytest.mark.parametrize(
    "output_obj, expected_success",
    [
        (SuccessAttributeOutput(success=True, info="yes"), True),
        (SuccessAttributeOutput(success=False, info="no"), False),
        (OkAttributeOutput(ok=True, info="yes"), True),
        (OkAttributeOutput(ok=False, info="no"), False),
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
