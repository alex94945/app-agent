# tests/integration/test_self_healing.py

import pytest
import asyncio
import uuid
import os
import shutil
import subprocess
import sys
import json
import logging

from pathlib import Path
from unittest.mock import patch
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, BaseMessage

# Adjust the import path based on your project structure
# This assumes 'agent_graph' is accessible from the 'agent' package
from agent.agent_graph import agent_graph, AgentState


@pytest.mark.asyncio
async def test_fix_typescript_type_error(tmp_path: Path):
    """
    Tests the agent's ability to detect a TypeScript type error using tsc (or diagnose),
    apply a patch, and verify the fix.
    """
    # 1. Setup: Create a temporary project with a TypeScript file containing a type error
    mock_repo_dir = tmp_path / "mock_repo"
    project_subdir_name = "ts_type_error_project"
    project_path = mock_repo_dir / project_subdir_name
    project_path.mkdir(parents=True, exist_ok=True)

    # Create tsconfig.json
    tsconfig_content = {
        "compilerOptions": {
            "target": "es2016",
            "module": "commonjs",
            "strict": True,
            "esModuleInterop": True,
            "skipLibCheck": True,
            "forceConsistentCasingInFileNames": True,
            "noEmit": True
        },
        "include": ["**/*.ts"]
    }
    (project_path / "tsconfig.json").write_text(json.dumps(tsconfig_content, indent=2))

    source_file_name = "broken_code.ts"
    source_file_path_in_project = project_path / source_file_name
    
    original_code_content = (
        "let myValue: string = 123; // Type error: number assigned to string\n"
        "console.log(myValue);\n"
    )
    source_file_path_in_project.write_text(original_code_content)

    # Initialize a git repository and install dependencies
    subprocess.run(["git", "init"], cwd=mock_repo_dir, check=True, capture_output=True)
    subprocess.run(["npm", "install", "typescript"], cwd=str(project_path), check=True, capture_output=True, text=True)

    # 2. Define the agent's task
    user_input = (
        f"Please run 'tsc --noEmit --project tsconfig.json' in the '{project_subdir_name}' directory to check the file '{source_file_name}'. "
        f"If there are any type errors, fix them and verify the fix by running the same command again."
    )

    thread_id = f"test_type_error_fix_{uuid.uuid4()}"

    with patch("common.config.settings.REPO_DIR", mock_repo_dir):
        initial_state: AgentState = {
            "input": user_input,
            "messages": [HumanMessage(content=user_input)],
            "iteration_count": 0,
            "project_subdirectory": project_subdir_name,
            "fix_attempts": 0,
            "failing_tool_run": None,
            "needs_verification": False,
        }

        # 3. Run the agent
        final_state_events = []
        async for event in agent_graph.astream_events(initial_state, config={"configurable": {"thread_id": thread_id}}, version="v1"):
            if event["event"] == "on_chain_end" and event["name"] == "LangGraph":
                final_state_events.append(event['data']['output'])
                break

        assert final_state_events, "Agent did not produce a final state."
        final_agent_state = final_state_events[0]
        assert isinstance(final_agent_state, dict), f"Expected final state to be a dict, but it is a {type(final_agent_state)}"
        final_messages: list[BaseMessage] = final_agent_state.get("messages", [])

        # The following section is commented out to reduce log verbosity.
        # logging.debug("--- TS Agent Messages (truncated) ---")
        # for msg in final_messages[-10:]:
        #     logging.debug("Type=%s, Content=%s", type(msg).__name__, msg.content[:200])
        #     if isinstance(msg, AIMessage) and msg.tool_calls:
        #         logging.debug("  Tool Calls: %s", msg.tool_calls)
        #     if isinstance(msg, ToolMessage):
        #         logging.debug("  Tool Call ID: %s", msg.tool_call_id)
        # logging.debug("--- End TS Agent Messages ---")

        # 4. Assertions
        # Check if tsc eventually passed by looking for the verify_node's output
        tool_messages_by_id = {
            msg.tool_call_id: msg
            for msg in final_messages
            if isinstance(msg, ToolMessage)
        }

        # Find the initial failing tsc call to get its ID for verification tracking
        initial_tsc_tool_call_id = None
        for msg in final_messages: # Iterate through all messages to find the first relevant AIMessage
            if isinstance(msg, AIMessage) and msg.tool_calls:
                for tc in msg.tool_calls:
                    if (
                        tc.get("name") == "run_shell" and 
                        isinstance(tc.get("args"), dict) and 
                        "tsc" in tc.get("args", {}).get("command", "") # Check for 'tsc'
                    ):
                        initial_tsc_tool_call_id = tc.get("id")
                        logging.debug(f"Found initial tsc call with ID: {initial_tsc_tool_call_id}")
                        break 
            if initial_tsc_tool_call_id:
                break
        
        assert initial_tsc_tool_call_id is not None, "Initial failing tsc tool call not found in agent messages."

        expected_verify_tool_call_id = initial_tsc_tool_call_id + "_verify"
        logging.debug(f"Looking for tsc verification tool message with ID: {expected_verify_tool_call_id}")

        verification_message = tool_messages_by_id.get(expected_verify_tool_call_id)
        assert verification_message is not None, f"Verification ToolMessage from verify_node (for tsc) with ID '{expected_verify_tool_call_id}' not found."

        successful_tsc_run_found = False
        if verification_message and isinstance(verification_message.content, str) and verification_message.content.startswith("{"):
            try:
                output_data = json.loads(verification_message.content)
                # For tsc, a successful run (even with --noEmit) usually means returncode 0.
                # stdout/stderr might not be empty if there are informational messages,
                # but the key is the return code.
                if output_data.get("returncode") == 0:
                    successful_tsc_run_found = True
                    logging.info("Successful tsc verification run confirmed via verify_node's ToolMessage.")
                else:
                    logging.warning(f"Verification tsc run failed. Return Code: {output_data.get('returncode')}, stdout: '{output_data.get('stdout')}', stderr: '{output_data.get('stderr')}'")
            except json.JSONDecodeError as e:
                logging.error(f"Failed to parse tsc verification message content: {e}. Content: {verification_message.content}")
        else:
            logging.warning(f"TSC Verification message content was not as expected: {verification_message.content if verification_message else 'None'}")
        
        assert successful_tsc_run_found, "Verification node did not confirm a successful 'tsc --noEmit' run after fixes (expected returncode 0)."

        fixed_code_content = source_file_path_in_project.read_text()
        logging.debug("Fixed TS Code Content after patch:\n%s", fixed_code_content)
        
        # Agent could fix it by changing type to number, or value to string
        fixed_by_changing_type = "let myValue: number = 123;" in fixed_code_content
        fixed_by_changing_value = 'let myValue: string = "123";' in fixed_code_content
        assert fixed_by_changing_type or fixed_by_changing_value, "TypeScript type error was not fixed correctly."

        final_ai_message = next((msg for msg in reversed(final_messages) if isinstance(msg, AIMessage) and not msg.tool_calls), None)
        assert final_ai_message is not None, "Agent did not provide a final response."
        assert ("type check" in final_ai_message.content.lower() or "tsc" in final_ai_message.content.lower()) and \
               ("successful" in final_ai_message.content.lower() or "resolved" in final_ai_message.content.lower() or "passed" in final_ai_message.content.lower() or "no errors" in final_ai_message.content.lower()), \
               f"Final AI message did not confirm successful type checking. Got: {final_ai_message.content}"
