from typing import Any, Callable, Protocol, Type, Union, Optional, Dict
from pydantic import BaseModel
import json

# --- Tool Output Model Imports ---
from tools.shell_mcp_tools import RunShellOutput
from tools.patch_tools import ApplyPatchOutput

# --- Output Handler Protocol & Implementations ---

class OutputHandler(Protocol):
    """Defines the interface for handling a specific tool output type."""

    def is_successful(self, output: Any) -> bool:
        ...

    def format_output(self, output: Any) -> str:
        ...

class DefaultOutputHandler(OutputHandler):
    """Fallback handler for unknown or simple output types."""
    def is_successful(self, output: Any) -> bool:
        if hasattr(output, 'success'):
            return bool(output.success)
        if hasattr(output, 'ok'):
            return bool(output.ok)
        if isinstance(output, (str, int, float, bool, list, dict, type(None))):
            return True
        return False

    def format_output(self, output: Any) -> str:
        if isinstance(output, BaseModel):
            return output.model_dump_json(indent=2)
        elif isinstance(output, (list, dict)):
            try:
                return json.dumps(output, indent=2)
            except TypeError:
                return str(output)
        return str(output)




class RunShellOutputHandler(OutputHandler):
    def is_successful(self, output: RunShellOutput) -> bool:
        # The RunShellOutput model uses 'ok: bool' which is pre-calculated.
        # Alternatively, could use: return output.return_code == 0
        return output.ok

    def format_output(self, output: RunShellOutput) -> str:
        if output.ok:
            # Only include stdout if it's not empty, to keep messages concise for LLM
            stdout_msg = f"\nStdout:\n{output.stdout.strip()}" if output.stdout and output.stdout.strip() else ""
            return f"Command '{output.command_executed}' executed successfully.{stdout_msg}"
        else:
            # Include stderr if present and not empty
            stderr_msg = f"\nStderr:\n{output.stderr.strip()}" if output.stderr and output.stderr.strip() else ""
            stdout_msg = f"\nStdout:\n{output.stdout.strip()}" if output.stdout and output.stdout.strip() else ""
            return f"Command '{output.command_executed}' failed with return code {output.return_code}.{stderr_msg}{stdout_msg}"


class ApplyPatchOutputHandler(OutputHandler):
    def is_successful(self, output: ApplyPatchOutput) -> bool:
        # The ApplyPatchOutput model uses 'ok: bool'.
        return output.ok

    def format_output(self, output: ApplyPatchOutput) -> str:
        # The message field now contains all necessary success or failure info.
        return output.message


# --- Helper Functions ---

OUTPUT_HANDLERS: dict[Type, OutputHandler] = {
    RunShellOutput: RunShellOutputHandler(),
    ApplyPatchOutput: ApplyPatchOutputHandler(),
    # Add more handlers here as new tool output types are introduced
}

DEFAULT_HANDLER = DefaultOutputHandler()

def get_output_handler(output: Any) -> OutputHandler:
    """Gets the appropriate handler for a given tool output type."""
    output_type = type(output)
    return OUTPUT_HANDLERS.get(output_type, DEFAULT_HANDLER)

def is_tool_successful(tool_output: Any) -> bool:
    """Determines if a tool execution was successful based on its output."""
    handler = get_output_handler(tool_output)
    return handler.is_successful(tool_output)

def format_tool_output(tool_output: Any) -> str:
    """Formats the tool output into a string suitable for LLM consumption or logging."""
    handler = get_output_handler(tool_output)
    return handler.format_output(tool_output)
