import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from pydantic import BaseModel

from agent.state import AgentState
from agent.executor.runner import run_single_tool, ToolExecutionError
from langchain_core.tools import ToolException
from mcp.shared.exceptions import McpError, ErrorData

# --- Mock Tool Definitions ---

class MockToolInput(BaseModel):
    param: str

async def mock_successful_tool_func(args_dict: dict):
    parsed_args = MockToolInput.model_validate(args_dict)
    return f"Success: {parsed_args.param}"

async def mock_tool_exception_func(args_dict: dict):
    parsed_args = MockToolInput.model_validate(args_dict)
    raise ToolException(f"Tool failed: {parsed_args.param}")

async def mock_mcp_error_func(args_dict: dict):
    parsed_args = MockToolInput.model_validate(args_dict)
    # The main message for the test will be in ErrorData.message
    error_data_instance = ErrorData(
        code=-32000,  # Standard JSON-RPC error code for server error
        message=f"MCP error: {parsed_args.param}",
        data={"type": "mcp_test_error_type", "title": "MCP Test Error Title"} # Additional structured data
    )
    raise McpError(error_data_instance)

async def mock_generic_exception_func(args_dict: dict):
    parsed_args = MockToolInput.model_validate(args_dict)
    raise ValueError(f"Generic error: {parsed_args.param}")

successful_tool = AsyncMock(spec=["ainvoke", "name", "args_schema"])
successful_tool.name = "successful_tool"
successful_tool.ainvoke = AsyncMock(side_effect=mock_successful_tool_func)
successful_tool.args_schema = MockToolInput

tool_exception_tool = AsyncMock(spec=["ainvoke", "name", "args_schema"])
tool_exception_tool.name = "tool_exception_tool"
tool_exception_tool.ainvoke = AsyncMock(side_effect=mock_tool_exception_func)
tool_exception_tool.args_schema = MockToolInput

mcp_error_tool = AsyncMock(spec=["ainvoke", "name", "args_schema"])
mcp_error_tool.name = "mcp_error_tool"
mcp_error_tool.ainvoke = AsyncMock(side_effect=mock_mcp_error_func)
mcp_error_tool.args_schema = MockToolInput

generic_exception_tool = AsyncMock(spec=["ainvoke", "name", "args_schema"])
generic_exception_tool.name = "generic_exception_tool"
generic_exception_tool.ainvoke = AsyncMock(side_effect=mock_generic_exception_func)
generic_exception_tool.args_schema = MockToolInput


# --- Fixtures ---

@pytest.fixture
def mock_agent_state_no_subdir():
    state = MagicMock(spec=AgentState)
    state.project_subdirectory = None
    return state

@pytest.fixture
def mock_agent_state_with_subdir():
    state = MagicMock(spec=AgentState)
    state.project_subdirectory = "my_app"
    return state

@pytest.fixture(autouse=True)
def mock_all_tools_and_utils():
    mock_tools_list = [
        successful_tool,
        tool_exception_tool,
        mcp_error_tool,
        generic_exception_tool
    ]
    # Reset mocks before each test
    for tool_mock in mock_tools_list:
        tool_mock.ainvoke.reset_mock()

    with patch('agent.executor.runner.ALL_TOOLS_LIST', mock_tools_list):  # Changed ALL_TOOLS to ALL_TOOLS_LIST
        with patch('agent.executor.runner.tool_map', {tool.name: tool for tool in mock_tools_list}):
            with patch('agent.executor.runner.maybe_inject_subdir', side_effect=lambda args, tn, st: args) as mock_injector:
                yield mock_injector

# --- Test Cases ---

@pytest.mark.asyncio
async def test_run_single_tool_success(mock_agent_state_no_subdir, mock_all_tools_and_utils):
    tool_args = {"param": "test_value"}
    result = await run_single_tool("successful_tool", tool_args, mock_agent_state_no_subdir)
    assert result == "Success: test_value"
    successful_tool.ainvoke.assert_called_once_with(tool_args)
    mock_all_tools_and_utils.assert_called_once_with(tool_args, "successful_tool", mock_agent_state_no_subdir)

@pytest.mark.asyncio
async def test_run_single_tool_not_found(mock_agent_state_no_subdir):
    result = await run_single_tool("non_existent_tool", {}, mock_agent_state_no_subdir)
    assert isinstance(result, ToolExecutionError)
    assert result.error_type == "ToolNotFound"
    assert result.tool_name == "non_existent_tool"
    assert "not available" in result.message

@pytest.mark.asyncio
async def test_run_single_tool_tool_exception(mock_agent_state_no_subdir):
    tool_args = {"param": "fail_me"}
    result = await run_single_tool("tool_exception_tool", tool_args, mock_agent_state_no_subdir)
    assert isinstance(result, ToolExecutionError)
    assert result.error_type == "ToolException"
    assert result.tool_name == "tool_exception_tool"
    assert "Tool failed: fail_me" in result.message
    tool_exception_tool.ainvoke.assert_called_once_with(tool_args)

@pytest.mark.asyncio
async def test_run_single_tool_mcp_error(mock_agent_state_no_subdir):
    tool_args = {"param": "mcp_fail"}
    result = await run_single_tool("mcp_error_tool", tool_args, mock_agent_state_no_subdir)
    assert isinstance(result, ToolExecutionError)
    assert result.error_type == "McpError"
    assert result.tool_name == "mcp_error_tool"
    assert "MCP error: mcp_fail" in result.message
    assert result.details is not None
    # McpError.data is an ErrorData object, its string representation will be in details
    assert "mcp_test_error_type" in result.details # Check for the type in ErrorData.data
    assert "-32000" in result.details # Check for the code in ErrorData
    assert "MCP Test Error Title" in result.details # Check for title in ErrorData.data
    mcp_error_tool.ainvoke.assert_called_once_with(tool_args)

@pytest.mark.asyncio
async def test_run_single_tool_generic_exception(mock_agent_state_no_subdir):
    tool_args = {"param": "generic_fail"}
    result = await run_single_tool("generic_exception_tool", tool_args, mock_agent_state_no_subdir)
    assert isinstance(result, ToolExecutionError)
    assert result.error_type == "GenericException"
    assert result.tool_name == "generic_exception_tool"
    assert "Generic error: generic_fail" in result.message
    generic_exception_tool.ainvoke.assert_called_once_with(tool_args)

@pytest.mark.asyncio
async def test_run_single_tool_uses_maybe_inject_subdir(mock_agent_state_with_subdir, mock_all_tools_and_utils):
    tool_args = {"param": "test_value"}
    # Reconfigure mock_injector for this specific test to return modified args
    modified_args = {"param": "test_value", "cwd": "my_app"}
    mock_all_tools_and_utils.side_effect = lambda args, tn, st: modified_args if tn == "successful_tool" else args

    await run_single_tool("successful_tool", tool_args, mock_agent_state_with_subdir)
    
    mock_all_tools_and_utils.assert_called_once_with(tool_args, "successful_tool", mock_agent_state_with_subdir)
    successful_tool.ainvoke.assert_called_once_with(modified_args)
