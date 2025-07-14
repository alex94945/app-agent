import logging
from typing import Any, Optional, Union
from pydantic import BaseModel # Added import

from langchain_core.tools import ToolException
from mcp.shared.exceptions import McpError

from agent.state import AgentState
from agent.executor.utils import maybe_inject_subdir
from agent.pty.manager import get_pty_manager

# Import all necessary tools directly
from tools.file_io_mcp_tools import read_file, write_file
from tools.scaffold_tool import scaffold_project
from tools.shell_mcp_tools import run_shell, PTYTask
from tools.patch_tools import apply_patch
from tools.vector_store_tools import vector_search
from tools.lsp_tools import lsp_definition, lsp_hover
from tools.diagnostics_tools import get_diagnostics, diagnose

# List of all tools for the executor
# This list should ideally be consistent with the one used by the planner
ALL_TOOLS_LIST = [
    read_file,
    write_file,
    scaffold_project,
    run_shell,
    apply_patch,
    vector_search,
    lsp_definition,
    lsp_hover,
    get_diagnostics,
    diagnose,
]

# Mapping tool names to their callable functions for the executor
tool_map = {tool.name: tool for tool in ALL_TOOLS_LIST}

logger = logging.getLogger(__name__)

class ToolExecutionError(Exception):
    """Structured error output for when a tool fails during execution."""
    def __init__(self, error_type: str, tool_name: str, message: str, details: Optional[str] = None):
        self.error_type = error_type
        self.tool_name = tool_name
        self.message = message
        self.details = details
        super().__init__(f"[{error_type}] Error in tool '{tool_name}': {message}")

async def run_single_tool(
    tool_name: str,
    tool_args: dict[str, Any],
    state: AgentState,
    # fix_tracker: Optional[FixCycleTracker] = None, # Will be used by the orchestrator, not directly here yet
) -> Union[Any, ToolExecutionError]:
    """
    Runs a single tool, handles argument injection, and catches common exceptions.

    Args:
        tool_name: The name of the tool to run.
        tool_args: The arguments for the tool.
        state: The current AgentState, used for context like project_subdirectory.
        # fix_tracker: An optional FixCycleTracker instance (not used in this function directly).

    Returns:
        The raw output from the tool, or a ToolExecutionError instance if an error occurs.
    """
    logger.info(f"Attempting to run tool '{tool_name}' with args: {tool_args}")

    tool_to_run = tool_map.get(tool_name)
    if not tool_to_run:
        logger.error(f"Tool '{tool_name}' not found in tool_map.")
        return ToolExecutionError(
            error_type="ToolNotFound",
            tool_name=tool_name,
            message=f"Tool '{tool_name}' is not available."
        )

    try:
        # Inject project_subdirectory if applicable
        # This helper function was previously named maybe_inject_subdir_to_tool_args
        # Renaming it to 'maybe_inject_subdir' for consistency with plan if it's not already done.
        # Assuming it's in agent.executor.utils as per Step 1 of the plan.
        processed_args = maybe_inject_subdir(tool_args, tool_name, state)
        logger.debug(f"Processed args for '{tool_name}': {processed_args}")

        # Add state to args for tools that need it (like run_shell in pty mode)
        if 'state' not in processed_args:
            processed_args['state'] = state

        # Most tools are async, so use ainvoke
        tool_output = await tool_to_run.ainvoke(processed_args)
        logger.info(f"Tool '{tool_name}' executed. Raw output type: {type(tool_output)}")

        if isinstance(tool_output, PTYTask):
            logger.info(f"Tool '{tool_name}' returned a PTY task ({tool_output.task_id}). Awaiting completion...")
            pty_manager = get_pty_manager()
            await pty_manager.wait_for_completion(tool_output.task_id)
            logger.info(f"PTY task {tool_output.task_id} completed.")
            # The output stream was handled by callbacks. Return a simple success message for the agent graph.
            return f"PTY task '{tool_args.get('task_name', 'Unnamed Task')}' completed successfully."

        return tool_output

    except ToolException as e:
        logger.error(f"ToolException while running tool '{tool_name}': {e}")
        return ToolExecutionError(
            error_type="ToolException",
            tool_name=tool_name,
            message=str(e),
            details=getattr(e, 'description', None) # Some ToolExceptions might have descriptions
        )
    except McpError as e:
        logger.error(f"McpError while running tool '{tool_name}': {e}")
        return ToolExecutionError(
            error_type="McpError",
            tool_name=tool_name,
            message=str(e), # This is e.error.message as per McpError.__init__
            details=str(e.error) if hasattr(e, 'error') and e.error else None # e.error is the ErrorData instance
        )
    except Exception as e:
        logger.error(f"Generic exception while running tool '{tool_name}': {e}", exc_info=True)
        return ToolExecutionError(
            error_type="GenericException",
            tool_name=tool_name,
            message=str(e)
        )
