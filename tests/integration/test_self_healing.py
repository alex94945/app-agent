# tests/integration/test_self_healing.py

import pytest
import asyncio
import uuid
import os
import shutil
from pathlib import Path
from unittest.mock import patch
import json
import logging

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, BaseMessage

# Adjust the import path based on your project structure
# This assumes 'agent_graph' is accessible from the 'agent' package
from agent.agent_graph import agent_graph, AgentState, MAX_FIX_ATTEMPTS


@pytest.mark.asyncio
async def test_fix_python_lint_error(tmp_path: Path):
    """
    Tests the agent's ability to detect a Python linting error using flake8,
    diagnose it (implicitly or explicitly), apply a patch, and verify the fix.
    """
    # 1. Setup: Create a temporary project with a Python file containing a lint error
    mock_repo_dir = tmp_path / "mock_repo"
    project_subdir_name = "python_linter_test_project"
    project_path = mock_repo_dir / project_subdir_name
    project_path.mkdir(parents=True, exist_ok=True)

    source_file_name = "broken_code.py"
    source_file_path_in_project = project_path / source_file_name
    
    # Code with lint errors (unused import, unused variable)
    original_code_content = (
        "import os  # Unused import\n"
        "import sys\n\n"
        "def my_func():\n"
        "    unused_var = 10  # Unused variable\n"
        "    print(sys.version)\n\n"
        "my_func()\n"
    )
    source_file_path_in_project.write_text(original_code_content)

    # 2. Define the agent's task
    user_input = (
        f"The Python file '{source_file_name}' in the project '{project_subdir_name}' "
        "might have linting errors. Please run 'flake8 {source_file_name}' within the project directory. "
        "If there are errors, diagnose them, apply a patch to fix them, and then run "
        "'flake8 {source_file_name}' again to confirm they are resolved. "
        "Tell me the final status of the lint check."
    )

    thread_id = f"test_lint_fix_{uuid.uuid4()}"
    
    # Patch REPO_DIR for the duration of this test
    # The agent's tools (like run_shell) will use this as their base
    with patch.dict(os.environ, {"REPO_DIR": str(mock_repo_dir)}):
        
        initial_state: AgentState = {
            "input": user_input,
            "messages": [HumanMessage(content=user_input)],
            "iteration_count": 0,
            "project_subdirectory": project_subdir_name, # Crucial for context
            "fix_attempts": 0,
            "failing_tool_run": None,
        }

        # 3. Run the agent
        final_state_events = []
        async for event in agent_graph.astream_events(initial_state, config={"configurable": {"thread_id": thread_id}}, version="v1"):
            # print(f"EVENT: {event['event']}, Name: {event.get('name')}, Data: {event.get('data')}") # Debug
            if event["event"] == "on_chain_end" and event["name"] == "LangGraph":
                final_state_events.append(event['data']['output'])
                break # Stop after the graph finishes

        assert final_state_events, "Agent did not produce a final state."
        final_agent_state = final_state_events[-1] # Get the actual final state dict

        # 4. Assertions
        final_messages: list[BaseMessage] = final_agent_state.get("messages", [])
        
        # Debug output (only if pytest -s or logging level DEBUG)
        logging.debug("--- Agent Messages (truncated) ---")
        for msg in final_messages[-10:]:  # show only last 10 messages for brevity
            logging.debug("Type=%s, Content=%s", type(msg).__name__, msg.content[:200])
            if isinstance(msg, AIMessage) and msg.tool_calls:
                logging.debug("  Tool Calls: %s", msg.tool_calls)
            if isinstance(msg, ToolMessage):
                logging.debug("  Tool Call ID: %s", msg.tool_call_id)
        logging.debug("--- End Agent Messages ---")

        # Check if flake8 eventually passed by looking for the verify_node's output
        tool_messages_by_id = {
            msg.tool_call_id: msg
            for msg in final_messages
            if isinstance(msg, ToolMessage)
        }

        # Find the initial failing flake8 call to get its ID for verification tracking
        initial_flake8_tool_call_id = None
        for msg in final_messages: # Iterate through all messages to find the first relevant AIMessage
            if isinstance(msg, AIMessage) and msg.tool_calls:
                for tc in msg.tool_calls:
                    if (
                        tc.get("name") == "run_shell" and 
                        isinstance(tc.get("args"), dict) and 
                        "flake8" in tc.get("args", {}).get("command", "")
                    ):
                        # This will capture the first flake8 call, which is expected to fail
                        # and whose ID is used as a base for the _verify call ID.
                        initial_flake8_tool_call_id = tc.get("id")
                        logging.debug(f"Found initial flake8 call with ID: {initial_flake8_tool_call_id}")
                        break # Found the tool call
            if initial_flake8_tool_call_id:
                break # Found the ID, no need to search further
        
        # Temporary debugging: Log all run_shell commands
        all_run_shell_commands = []
        for msg in final_messages:
            if isinstance(msg, AIMessage) and msg.tool_calls:
                for tc in msg.tool_calls:
                    if tc.get("name") == "run_shell" and isinstance(tc.get("args"), dict):
                        command = tc.get("args", {}).get("command", "")
                        all_run_shell_commands.append(command)
                        logging.warning(f"AGENT ATTEMPTED run_shell: {command} (ID: {tc.get('id')})")
        
        logging.warning(f"All run_shell commands by agent: {all_run_shell_commands}")
        assert initial_flake8_tool_call_id is not None, f"Initial failing flake8 tool call not found. Agent run_shell commands: {all_run_shell_commands}"

        # The verify_node appends '_verify' to the original tool_call_id
        # (This suffix is defined in agent_graph.py, in the verify_node)
        expected_verify_tool_call_id = initial_flake8_tool_call_id + "_verify"
        logging.debug(f"Looking for verification tool message with ID: {expected_verify_tool_call_id}")

        verification_message = tool_messages_by_id.get(expected_verify_tool_call_id)
        assert verification_message is not None, f"Verification ToolMessage from verify_node with ID '{expected_verify_tool_call_id}' not found."

        successful_flake8_run_found = False
        if verification_message and isinstance(verification_message.content, str) and verification_message.content.startswith("{"):
            try:
                output_data = json.loads(verification_message.content)
                if (output_data.get("returncode") == 0 and
                    output_data.get("stdout", "").strip() == "" and # Flake8 success means no stdout
                    output_data.get("stderr", "").strip() == ""): # And no stderr
                    successful_flake8_run_found = True
                    logging.info("Successful flake8 verification run confirmed via verify_node's ToolMessage.")
                else:
                    logging.warning(f"Verification flake8 run failed or had output. Return Code: {output_data.get('returncode')}, stdout: '{output_data.get('stdout')}', stderr: '{output_data.get('stderr')}'")
            except json.JSONDecodeError as e:
                logging.error(f"Failed to parse verification message content from verify_node: {e}. Content: {verification_message.content}")
        else:
            logging.warning(f"Verification message content was not as expected: {verification_message.content if verification_message else 'None'}")
        
        assert successful_flake8_run_found, "Verification node did not confirm a successful flake8 run after fixes (expected returncode 0, empty stdout/stderr)."

        # Check the file content
        fixed_code_content = source_file_path_in_project.read_text()
        logging.debug("Fixed Code Content after patch:\n%s", fixed_code_content)
        
        assert "import os" not in fixed_code_content, "Unused 'import os' should have been removed."
        assert "unused_var =" not in fixed_code_content, "Unused 'unused_var' should have been removed."
        assert "import sys" in fixed_code_content, "'import sys' should remain as it's used."

        # Optional: Check for AIMessage indicating success
        final_ai_message = next((msg for msg in reversed(final_messages) if isinstance(msg, AIMessage) and not msg.tool_calls), None)
        assert final_ai_message is not None, "Agent did not provide a final response."
        assert "lint check" in final_ai_message.content.lower() and \
               ("successful" in final_ai_message.content.lower() or "resolved" in final_ai_message.content.lower() or "passed" in final_ai_message.content.lower()), \
               f"Final AI message did not confirm successful linting. Got: {final_ai_message.content}"


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

    # 2. Define the agent's task
    user_input = (
        f"The TypeScript file '{source_file_name}' in project '{project_subdir_name}' has a type error. "
        f"Please use 'tsc --noEmit --project tsconfig.json' or the diagnose tool to find it. "
        f"Then, fix the error by changing the type or the value, apply the patch, and verify with 'tsc --noEmit' again. "
        f"Report the final status."
    )

    thread_id = f"test_type_error_fix_{uuid.uuid4()}"
    
    with patch.dict(os.environ, {"REPO_DIR": str(mock_repo_dir)}):
        initial_state: AgentState = {
            "input": user_input,
            "messages": [HumanMessage(content=user_input)],
            "iteration_count": 0,
            "project_subdirectory": project_subdir_name,
            "fix_attempts": 0,
            "failing_tool_run": None,
        }

        # 3. Run the agent
        final_state_events = []
        async for event in agent_graph.astream_events(initial_state, config={"configurable": {"thread_id": thread_id}}, version="v1"):
            if event["event"] == "on_chain_end" and event["name"] == "LangGraph":
                final_state_events.append(event['data']['output'])
                break

        assert final_state_events, "Agent did not produce a final state."
        final_agent_state = final_state_events[-1]
        final_messages: list[BaseMessage] = final_agent_state.get("messages", [])

        logging.debug("--- TS Agent Messages (truncated) ---")
        for msg in final_messages[-10:]:
            logging.debug("Type=%s, Content=%s", type(msg).__name__, msg.content[:200])
            if isinstance(msg, AIMessage) and msg.tool_calls:
                logging.debug("  Tool Calls: %s", msg.tool_calls)
            if isinstance(msg, ToolMessage):
                logging.debug("  Tool Call ID: %s", msg.tool_call_id)
        logging.debug("--- End TS Agent Messages ---")

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
