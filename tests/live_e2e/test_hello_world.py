# tests/live_e2e/test_hello_world.py

# By being in a separate directory `live_e2e`, this test avoids loading
# the mock fixtures from `tests/integration/conftest.py`.
pytest_plugins = []

import pytest
import logging
from pathlib import Path
import sys
import subprocess
import json
import os
import re
from typing import Optional, Dict, Any

# --- Add project root to sys.path to allow imports ---
# Assumes tests/live_e2e/test_hello_world.py
project_root = Path(__file__).parent.parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from common.config import get_settings
from langchain_core.messages import HumanMessage
from langchain_core.tools import Tool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

@pytest.fixture(scope="function")
def live_repo(tmp_path: Path, monkeypatch) -> Path:
    """
    Provides a clean, temporary git repository for the live E2E test to run in.
    This fixture ensures the agent operates in an isolated environment.
    """
    repo_dir = tmp_path / "live_e2e_repo"
    repo_dir.mkdir()

    # Initialize a git repository, as the agent's patch tool requires it.
    subprocess.run(["git", "init"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir, check=True)

    monkeypatch.setattr(get_settings(), 'REPO_DIR', repo_dir)
    logger.info(f"Live E2E test running in: {repo_dir}")
    
    yield repo_dir
    
    logger.info(f"Live E2E test finished in: {repo_dir}")


@pytest.mark.e2e_live
@pytest.mark.timeout(900)  # 15-minute timeout
@pytest.mark.asyncio
async def test_hello_world(agent_graph_fixture, live_repo: Path):
    """
    Tests the full, unmocked agent pipeline on a simple scaffolding and
    editing task. This test uses REAL implementations of all tools.
    It is VERY SLOW and should be run selectively.
    """
    logger.info("--- Starting LIVE End-to-End Test: Hello World ---")
    
    # --- Real Tool Implementations ---
    class RunShellArgs(BaseModel):
        command: str = Field(..., description="The command to run.")
        working_directory: Optional[str] = Field(None, description="Subdirectory within the repo to run the command from.")

    async def real_run_shell(command: str, working_directory: Optional[str] = None) -> Dict[str, Any]:
        cwd = live_repo
        if working_directory:
            cwd = live_repo / working_directory
        
        logger.info(f"Executing real shell command: '{command}' in '{cwd}'")
        try:
            process = subprocess.run(
                command, shell=True, check=True, capture_output=True, text=True, cwd=cwd
            )
            return {"returncode": process.returncode, "stdout": process.stdout, "stderr": process.stderr}
        except subprocess.CalledProcessError as e:
            return {"returncode": e.returncode, "stdout": e.stdout, "stderr": e.stderr}

    class FileArgs(BaseModel):
        path_in_repo: str = Field(..., description="Path to the file relative to the repo root.")

    class WriteFileArgs(FileArgs):
        content: str = Field(..., description="Content to write.")

    async def real_read_file(path_in_repo: str) -> str:
        file_path = live_repo / path_in_repo
        logger.info(f"Reading real file: {file_path}")
        try:
            return file_path.read_text()
        except Exception as e:
            return f"Error reading file: {e}"

    async def real_write_file(path_in_repo: str, content: str) -> str:
        file_path = live_repo / path_in_repo
        logger.info(f"Writing to real file: {file_path}")
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content)
            return f"Successfully wrote to {path_in_repo}."
        except Exception as e:
            return f"Error writing file: {e}"

    class ApplyPatchArgs(BaseModel):
        diff_content: str = Field(..., description="The diff content to apply.")

    async def real_apply_patch(diff_content: str) -> str:
        logger.info(f"Applying real patch.")
        if not diff_content.endswith("\n"):
            diff_content += "\n"
        diff_content = re.sub(r"^index .*$\n", "", diff_content, flags=re.MULTILINE)
        
        try:
            subprocess.run(["git", "add", "-A"], cwd=live_repo, check=True)
            process = subprocess.run(
                ["git", "apply", "--verbose", "-"],
                input=diff_content, text=True, capture_output=True, check=True, cwd=live_repo
            )
            return f"Patch applied successfully.\nSTDOUT:\n{process.stdout}\nSTDERR:\n{process.stderr}"
        except subprocess.CalledProcessError as e:
            return f"Failed to apply patch.\nSTDOUT:\n{e.stdout}\nSTDERR:\n{e.stderr}"

    # --- Tool Injection ---
    real_tools = {
        "run_shell": Tool(name="run_shell", func=real_run_shell, description="Runs a shell command.", args_schema=RunShellArgs),
        "read_file": Tool(name="read_file", func=real_read_file, description="Reads a file.", args_schema=FileArgs),
        "write_file": Tool(name="write_file", func=real_write_file, description="Writes a file.", args_schema=WriteFileArgs),
        "apply_patch": Tool(name="apply_patch", func=real_apply_patch, description="Applies a patch.", args_schema=ApplyPatchArgs),
    }

    agent_graph = agent_graph_fixture(tools=list(real_tools.values()))

    try:
        prompt = (
            "Create a new Next.js application called 'hello-world-app' using create-next-app. "
            "After it's created, modify the home page (src/app/page.tsx) to display the text 'Hello, World!' instead of the default content."
        )
        thread_id = f"live-e2e-hello-world-{os.getpid()}"
        initial_state = {"messages": [HumanMessage(content=prompt)]}
        config = {"configurable": {"thread_id": thread_id}}

        logger.info(f"Invoking agent for prompt: '{prompt}'")
        final_state = await agent_graph.ainvoke(initial_state, config)
        logger.info("Agent invocation complete.")

        logger.info("--- Verifying Assertions ---")

        assert final_state is not None, "Agent run did not complete."
        last_message = final_state.get("messages", [])[-1]
        assert "error" not in last_message.content.lower(), f"Agent run ended with an error: {last_message.content}"
        assert "hello, world" in last_message.content.lower(), "Agent's final message did not confirm the change."

        project_path = live_repo / "hello-world-app"
        page_tsx_path = project_path / "src" / "app" / "page.tsx"
        assert project_path.is_dir(), f"Project directory '{project_path}' was not created."
        assert page_tsx_path.is_file(), f"Page component '{page_tsx_path}' was not created."
        logger.info("✅ Assertion Passed: Project directory and page.tsx exist.")

        page_content = page_tsx_path.read_text()
        assert "Hello, World!" in page_content, "The text 'Hello, World!' was not found in page.tsx."
        logger.info("✅ Assertion Passed: page.tsx content is correct.")

        package_json_path = project_path / "package.json"
        assert package_json_path.is_file(), "package.json was not created."
        package_data = json.loads(package_json_path.read_text())
        dependencies = package_data.get("dependencies", {})
        assert "next" in dependencies, "'next' not found in package.json dependencies"
        assert "react" in dependencies, "'react' not found in package.json dependencies"
        logger.info("✅ Assertion Passed: package.json dependencies are correct.")

        logger.info(f"Performing final verification by running 'npm run build' in {project_path}...")
        build_tool = real_tools["run_shell"]
        build_result = await build_tool.ainvoke({
            "command": "npm run build",
            "working_directory": "hello-world-app",
        })

        assert build_result["returncode"] == 0, f"Final verification failed. 'npm run build' did not pass.\nSTDOUT:\n{build_result['stdout']}\nSTDERR:\n{build_result['stderr']}"
        logger.info("✅ Assertion Passed: `npm run build` completed successfully.")

        logger.info("--- LIVE End-to-End Test Passed Successfully! ---")

    finally:
        if sys.exc_info()[0]:
            logger.error("--- LIVE E2E Test FAILED. Dumping state for debugging. ---")
            tree_process = subprocess.run(["ls", "-R"], cwd=live_repo, capture_output=True, text=True)
            logger.info(f"File tree in {live_repo}:\n{tree_process.stdout}")
