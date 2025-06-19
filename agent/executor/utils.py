# agent/executor/utils.py
import logging
from agent.state import AgentState # Assuming AgentState is accessible

logger = logging.getLogger(__name__)

# Define LSP tool names here or pass them in. For now, defining them here.
# This should ideally be sourced from the same place as in agent_graph.py
LSP_TOOL_NAMES = {"lsp_definition", "lsp_hover", "get_diagnostics", "diagnose"} # Example names

def maybe_inject_subdir(tool_args: dict | None, tool_name: str, state: AgentState) -> dict:
    """
    Injects 'project_subdirectory' into tool arguments if the tool is an LSP tool
    and 'project_subdirectory' is present in the agent state.
    """
    args_to_invoke = dict(tool_args) if tool_args else {}

    if tool_name in LSP_TOOL_NAMES:
        current_project_subdirectory = state.get("project_subdirectory")
        if current_project_subdirectory:
            # Ensure tool_args is a mutable dictionary
            if not isinstance(args_to_invoke, dict):
                logger.warning(
                    f"Tool args for {tool_name} is not a dict: {type(args_to_invoke)}. "
                    f"Attempting to proceed but this might indicate an issue."
                )
                # Attempt to convert if it's a known model type, or raise error if unsafe
                # For now, we assume it's either a dict or this warning is sufficient.
            
            args_to_invoke["project_subdirectory"] = current_project_subdirectory
            logger.debug(
                f"Injected project_subdirectory='{current_project_subdirectory}' "
                f"into args for LSP tool '{tool_name}'. New args: {args_to_invoke}"
            )
    return args_to_invoke
