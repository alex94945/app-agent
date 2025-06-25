# tests/live_e2e/test_live_e2e.py

# By being in a separate directory `live_e2e`, this test avoids loading
# the mock fixtures from `tests/integration/conftest.py`.

import pytest
import logging
from pathlib import Path
import shutil
import sys
import subprocess
import json
import os
import re
import unicodedata
import hashlib
from typing import Optional, Dict, Any

# --- Add project root to sys.path to allow imports ---
# Assumes tests/live_e2e/test_live_e2e.py
project_root = Path(__file__).parent.parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from common.config import get_settings
from langchain_core.messages import HumanMessage
from langchain_core.tools import Tool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


@pytest.fixture(scope="function")
def live_e2e_repo_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """
    Provides a clean, temporary git repository for the live E2E test to run in.
    This fixture ensures the agent operates in an isolated environment.
    """
    settings = get_settings()
    if settings.E2E_OUTPUT_DIR:
        repo_dir = settings.E2E_OUTPUT_DIR.resolve()
        logger.info(f"Using persistent directory for E2E test output: {repo_dir}")
        if repo_dir.exists():
            shutil.rmtree(repo_dir)
        repo_dir.mkdir(parents=True, exist_ok=True)
    else:
        repo_dir = tmp_path / "live_e2e_repo"
        repo_dir.mkdir()
        logger.info(f"Using temporary directory for E2E test output: {repo_dir}")

    # Initialize a git repository, as the agent's patch tool requires it.
    subprocess.run(["git", "init"], cwd=repo_dir, check=True)

    monkeypatch.setattr(get_settings(), 'REPO_DIR', repo_dir)
    logger.info(f"Live E2E test running in: {repo_dir}")
    
    yield repo_dir
    
    logger.info(f"Live E2E test finished in: {repo_dir}")


@pytest.mark.e2e_live
@pytest.mark.timeout(900)  # 15-minute timeout
@pytest.mark.asyncio
async def test_live_full_e2e(agent_graph_fixture, live_e2e_repo_dir: Path, prompt: str):
    """
    Tests the full, unmocked agent pipeline on a simple scaffolding and
    editing task. This test uses REAL implementations of all tools.
    It is VERY SLOW and should be run selectively.
    It is parametrized by the 'prompt' fixture, which is populated by the
    --prompts CLI argument.
    """
    logger.info(f"--- Starting LIVE End-to-End Test for prompt: '{prompt}' ---")
    
    # --- Real Tool Implementations ---
    class RunShellArgs(BaseModel):
        command: str = Field(..., description="The command to run.")
        working_directory_relative_to_repo: Optional[str] = Field(None, description="Subdirectory within the repo to run the command from.")

    async def real_run_shell(command: str, working_directory_relative_to_repo: Optional[str] = None) -> Dict[str, Any]:
        cwd = live_e2e_repo_dir
        if working_directory_relative_to_repo:
            cwd = live_e2e_repo_dir / working_directory_relative_to_repo
        
        logger.info(f"Executing real shell command: '{command}' in '{cwd}'")
        try:
            # Using shell=True is necessary for complex commands like those with pipes or redirects
            # that the LLM might generate. It's acceptable in this controlled test environment.
            process = subprocess.run(
                command, shell=True, check=True, capture_output=True, text=True, cwd=cwd
            )
            return {"return_code": process.returncode, "stdout": process.stdout, "stderr": process.stderr}
        except subprocess.CalledProcessError as e:
            # This is not an exception in the test, but a valid outcome of the tool.
            return {"return_code": e.returncode, "stdout": e.stdout, "stderr": e.stderr}

    class FileArgs(BaseModel):
        path_in_repo: str = Field(..., description="Path to the file relative to the repo root.")

    class WriteFileArgs(FileArgs):
        content: str = Field(..., description="Content to write.")

    async def real_read_file(path_in_repo: str) -> str:
        file_path = live_e2e_repo_dir / path_in_repo
        logger.info(f"Reading real file: {file_path}")
        try:
            return file_path.read_text()
        except Exception as e:
            return f"Error reading file: {e}"

    async def real_write_file(path_in_repo: str, content: str) -> str:
        file_path = live_e2e_repo_dir / path_in_repo
        logger.info(f"Writing to real file: {file_path}")
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content)
            return f"Successfully wrote to {path_in_repo}."
        except Exception as e:
            return f"Error writing file: {e}"

    class ApplyPatchArgs(BaseModel):
        file_path_in_repo: str = Field(description="A representative file path for the patch, used for logging. The patch content itself determines which files are modified.")
        diff_content: str = Field(..., description="The content of the diff/patch to apply, in unidiff format.")

    async def real_apply_patch(file_path_in_repo: str, diff_content: str) -> str:
        logger.info(f"Applying real patch for file hint: {file_path_in_repo}")
        if not diff_content.endswith("\n"):
            diff_content += "\n"
        # This regex was in the original test, keeping it for robustness.
        diff_content = re.sub(r"^index .*$\n", "", diff_content, flags=re.MULTILINE)
        
        try:
            # Stage all current changes before applying the patch
            subprocess.run(["git", "add", "-A"], cwd=live_e2e_repo_dir, check=True)
            # Apply the patch from stdin
            process = subprocess.run(
                ["git", "apply", "--verbose", "-"],
                input=diff_content, text=True, capture_output=True, check=True, cwd=live_e2e_repo_dir
            )
            return f"Patch applied successfully.\nSTDOUT:\n{process.stdout}\nSTDERR:\n{process.stderr}"
        except subprocess.CalledProcessError as e:
            return f"Failed to apply patch.\nSTDOUT:\n{e.stdout}\nSTDERR:\n{e.stderr}"

    # --- Tool Injection ---
    # We need to create new Tool objects because the original ones in agent_graph.py
    # might have different schemas or be bound to different logic.
    from agent.agent_graph import all_tools_list
    real_tools_map = {
        "run_shell": Tool(name="run_shell", func=real_run_shell, description="Runs a shell command.", args_schema=RunShellArgs),
        "read_file": Tool(name="read_file", func=real_read_file, description="Reads a file.", args_schema=FileArgs),
        "write_file": Tool(name="write_file", func=real_write_file, description="Writes a file.", args_schema=WriteFileArgs),
        "apply_patch": Tool(name="apply_patch", func=real_apply_patch, description="Applies a patch.", args_schema=ApplyPatchArgs),
    }
    # Create a list of tools for the graph, using real ones where we have them, and originals for the rest (lsp, etc)
    final_tools_list = [real_tools_map.get(tool.name, tool) for tool in all_tools_list]

    # Rebuild the agent graph with our real, live tools
    agent_graph = agent_graph_fixture(tools=final_tools_list)

    try:
        thread_id = f"live-e2e-test-{os.getpid()}"
        initial_state = {"messages": [HumanMessage(content=prompt)]}
        config = {"configurable": {"thread_id": thread_id}}

        logger.info(f"Invoking agent for prompt: '{prompt}'")
        final_state = await agent_graph.ainvoke(initial_state, config)
        logger.info("Agent invocation complete.")

        app_slug = final_state.get("project_subdirectory")
        assert app_slug, "Agent did not set project_subdirectory in its final state."

        logger.info("--- Verifying Assertions ---")

        assert final_state is not None, "Agent run did not complete."
        last_message = final_state.get("messages", [])[-1]
        assert "error" not in last_message.content.lower(), f"Agent run ended with an error: {last_message.content}"
        final_text = last_message.content.lower()
        assert "hello" in final_text and "world" in final_text, "Agent's final message did not confirm the change."

        project_path = live_e2e_repo_dir / app_slug
        page_tsx_path = project_path / "src" / "app" / "page.tsx"
        assert project_path.is_dir(), f"Project directory '{project_path}' was not created."
        assert page_tsx_path.is_file(), f"Page component '{page_tsx_path}' was not created."
        logger.info("✅ Assertion Passed: Project directory and page.tsx exist.")

        page_content = page_tsx_path.read_text().lower()
        assert "hello, world!" in page_content, "The text 'Hello, World!' was not found in page.tsx."
        logger.info("✅ Assertion Passed: page.tsx content is correct.")

        package_json_path = project_path / "package.json"
        assert package_json_path.is_file(), "package.json was not created."
        package_data = json.loads(package_json_path.read_text())
        dependencies = package_data.get("dependencies", {})
        assert "next" in dependencies, "'next' not found in package.json dependencies"
        assert "react" in dependencies, "'react' not found in package.json dependencies"
        logger.info("✅ Assertion Passed: package.json dependencies are correct.")

        logger.info(f"Performing final verification by running 'npm run build' in {project_path}...")
        build_tool = real_tools_map["run_shell"]
        build_result = await build_tool.ainvoke({
            "command": "npm run build",
            "working_directory_relative_to_repo": app_slug,
        })

        assert build_result["return_code"] == 0, f"Final verification failed. 'npm run build' did not pass.\nSTDOUT:\n{build_result['stdout']}\nSTDERR:\n{build_result['stderr']}"
        logger.info("✅ Assertion Passed: `npm run build` completed successfully.")

        logger.info(f"--- LIVE End-to-End Test for prompt '{prompt}' Passed Successfully! ---")

    finally:
        if sys.exc_info()[0]:
            logger.error(f"--- LIVE E2E Test FAILED for prompt '{prompt}'. Dumping state for debugging. ---")
            tree_process = subprocess.run(["ls", "-R"], cwd=live_e2e_repo_dir, capture_output=True, text=True)
            logger.info(f"File tree in {live_e2e_repo_dir}:\n{tree_process.stdout}")