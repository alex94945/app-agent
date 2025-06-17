from typing import Any, Callable, Protocol, Type, Union, Optional
from pydantic import BaseModel

# --- Tool Output Model Imports ---
# Importing actual Pydantic models from their respective tool definition files.

from tools.shell_mcp_tools import RunShellOutput
from tools.file_io_mcp_tools import WriteFileOutput
from tools.patch_tools import ApplyPatchOutput, ShellRunResult # ShellRunResult holds the details for ApplyPatchOutput

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
        # By default, assume success if no specific handler exists.
        # This might need adjustment based on how 'success' is typically indicated.
        if hasattr(output, 'success'):
            return bool(output.success)
        if hasattr(output, 'ok'): # Another common pattern
            return bool(output.ok)
        # If it's a simple type or no success attribute, assume success.
        # This is a basic fallback; specific handlers are preferred.
        if isinstance(output, (str, int, float, bool, list, dict, type(None))):
            return True 
        return False # For unknown complex objects without a success flag

    def format_output(self, output: Any) -> str:
        if isinstance(output, BaseModel):
            return output.model_dump_json(indent=2)
        elif isinstance(output, (list, dict)):
            import json
            try:
                return json.dumps(output, indent=2)
            except TypeError:
                return str(output) # Fallback for non-serializable dicts/lists
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


class WriteFileOutputHandler(OutputHandler):
    def is_successful(self, output: WriteFileOutput) -> bool:
        # The WriteFileOutput model uses 'ok: bool'.
        return output.ok

    def format_output(self, output: WriteFileOutput) -> str:
        # The message field already contains a descriptive success/failure message.
        return output.message


class ApplyPatchOutputHandler(OutputHandler):
    def is_successful(self, output: ApplyPatchOutput) -> bool:
        # The ApplyPatchOutput model uses 'ok: bool'.
        return output.ok

    def format_output(self, output: ApplyPatchOutput) -> str:
        # The message field contains a summary. If not ok and details exist, append stderr.
        if not output.ok and output.details and output.details.stderr and output.details.stderr.strip():
            return f"{output.message}\nError details:\n{output.details.stderr.strip()}"
        return output.message


# --- Registry & Helper Functions ---

OUTPUT_HANDLERS: dict[Type, OutputHandler] = {
    RunShellOutput: RunShellOutputHandler(),
    WriteFileOutput: WriteFileOutputHandler(),
    ApplyPatchOutput: ApplyPatchOutputHandler(),
    # Add more handlers here as new tool output types are introduced
}

_default_handler = DefaultOutputHandler()

def get_handler(output: Any) -> OutputHandler:
    """Retrieves the appropriate handler for the given tool output type."""
    return OUTPUT_HANDLERS.get(type(output), _default_handler)

def is_tool_successful(tool_output: Any) -> bool:
    """Determines if a tool execution was successful based on its output."""
    handler = get_handler(tool_output)
    return handler.is_successful(tool_output)

def format_tool_output(tool_output: Any) -> str:
    """Formats the tool output into a string suitable for LLM consumption or logging."""
    handler = get_handler(tool_output)
    return handler.format_output(tool_output)
