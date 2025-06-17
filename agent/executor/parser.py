# agent/executor/parser.py
import logging
from langchain_core.messages import AIMessage, ToolCall

logger = logging.getLogger(__name__)

def _is_valid_tool_call(obj) -> bool:
    """Checks if an object is a well-formed tool call (Pydantic model or dict)."""
    # Pydantic model path (“dot” attributes exist)
    if hasattr(obj, "name") and hasattr(obj, "id") and hasattr(obj, "args"):
        return True
    # Plain dict / TypedDict path
    if isinstance(obj, dict) and "name" in obj and "id" in obj and (
        "args" in obj or "arguments" in obj
    ):
        return True
    return False

def parse_tool_calls(last_message: AIMessage) -> list[ToolCall]:
    """
    Parses tool calls from the last AIMessage, ensuring they are valid ToolCall objects.
    """
    if not isinstance(last_message, AIMessage) or not last_message.tool_calls:
        logger.warning("No tool calls found in the last AIMessage or last_message is not AIMessage.")
        return []

    raw_tool_calls_from_message = last_message.tool_calls
    parsed_tool_calls: list[ToolCall] = []

    if raw_tool_calls_from_message:
        for item in raw_tool_calls_from_message:
            if isinstance(item, dict):
                try:
                    # Prefer Pydantic parsing for robustness if it's a dict from LLM
                    tool_call_obj = ToolCall.parse_obj(item)
                except Exception:
                    # Fallback manual handling for other dicts (e.g., already normalized)
                    args_data = item.get('args') or item.get('arguments')
                    if args_data is None:
                        logger.error(f"Dictionary item in tool_calls missing 'args'/'arguments': {item}")
                        continue
                    tool_call_obj = ToolCall(name=item['name'], args=args_data, id=item['id'])
                parsed_tool_calls.append(tool_call_obj)
            elif isinstance(item, ToolCall):
                parsed_tool_calls.append(item)
            else:
                logger.warning(f"Unexpected type in tool_calls list: {type(item)}, item: {item}")
    
    valid_tool_calls = [tc for tc in parsed_tool_calls if _is_valid_tool_call(tc)]
    
    if not valid_tool_calls and parsed_tool_calls: # Some calls were parsed but none were valid
        logger.warning("No valid ToolCall objects to execute after parsing raw tool_calls.")
    
    return valid_tool_calls
