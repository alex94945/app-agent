import logging
from typing import Dict

from langchain_core.messages import ToolMessage

from agent.executor.fix_cycle import FixCycleTracker
from agent.executor.output_handlers import get_output_handler
from agent.executor.runner import run_single_tool
from agent.state import AgentState

logger = logging.getLogger(__name__)


async def tool_executor_step(state: AgentState) -> Dict:
    """This step executes the chosen tool, manages failure/fix cycles, and returns the result."""
    tool_call = state.messages[-1].tool_calls[0]
    tool_name = tool_call["name"]
    tool_args = tool_call["args"]
    logger.info(f"[ToolExecutor] Executing tool '{tool_name}' with args: {tool_args}")

    # --- Initialize FixCycleTracker from state ---
    fix_tracker = FixCycleTracker.from_state(state.fix_cycle_tracker_state)

    # --- Run the tool ---
    tool_output = await run_single_tool(tool_call, state)

    # --- Handle output and update fix cycle state ---
    handler = get_output_handler(tool_output)
    is_success = handler.is_successful(tool_output)
    output_str = handler.format_output(tool_output)

    fix_tracker.record_result(tool_call, is_success, output_str)

    logger.info(f"[ToolExecutor] Tool '{tool_name}' output: {output_str}")

    return {
        "messages": [ToolMessage(content=output_str, tool_call_id=tool_call["id"])],
        "fix_cycle_tracker_state": fix_tracker.to_state(),
    }
