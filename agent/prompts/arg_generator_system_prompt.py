import json

ARG_GENERATOR_SYSTEM_PROMPT_TEMPLATE = """You are an expert software development agent.

Your task is to generate the arguments for the tool: '{tool_name}'.

The tool's description is: {tool_description}

The tool's arguments are: {tool_args}

Review the conversation history and the user's request to determine the correct arguments.

Only respond with the arguments, nothing else."""

def get_arg_generator_system_prompt(tool_name: str, tool_description: str, tool_args: dict) -> str:
    return ARG_GENERATOR_SYSTEM_PROMPT_TEMPLATE.format(
        tool_name=tool_name,
        tool_description=tool_description,
        tool_args=json.dumps(tool_args, indent=2)
    )
