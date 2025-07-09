## Implementation Plan
: Autonomous, Tool-Using AI Agent (Revised v2)

**Guiding Principles for this Implementation:**

*   **MVP First (as per Design Doc):** Focus on delivering the core, end-to-end flow with initial tool implementations as specified, then enhance.
*   **Tool-Centric Development:** Each new capability should ideally be encapsulated as a tool that the LangGraph agent can call.
*   **Clear Interfaces:** Define clear JSON contracts for communication between the UI, FastAPI gateway, and the Agent, and for tool inputs/outputs.
*   **Incremental Testing:** Test each component and integration point as it's developed.
*   **Configuration Management:** Plan for how API keys, server URLs, etc., will be managed.
*   **Workspace Root Convention:** A single `REPO_DIR` environment variable will define the root for MCP, LSP, Git operations, and be passed to WebContainer.

---

### **Phase 0: Project Setup, Configuration & FastAPI Gateway Skeleton**

**(Corresponds to Design Doc MVP Phase 0, with enhancements)**

-   [x] **1. Project Initialization (New Codebase):**
    -   [x] Action: Create a new Git repository.
    -   [x] Structure:
        -   [x] `agent/` (for LangGraph agent and related logic)
        -   [x] `tools/` (for all tool implementations)
        -   [x] `gateway/` (for FastAPI application)
        -   [x] `ui/` (for Next.js frontend application)
        -   [x] `common/` (for shared Pydantic models, constants, WebSocket message schemas)
        -   [x] `scripts/` (For CLI tests like `e2e_smoke.py`)
        -   [x] `tests/` (Unit/integration tests)
        -   [x] `.env.example`, `requirements.txt`, `.gitignore`, `README.md`
    -   [x] Details: Initialize Python virtual environment. Populate `.gitignore`. Create `.env.example` with `REPO_DIR`, `EMBED_PROVIDER`, `OPENAI_API_KEY`, etc.

-   [x] **2. Configuration & Environment:**
    -   [x] Action: Implement basic configuration loading.
    -   [x] File: `common/config.py` (or similar)
    -   [x] Details:
        -   [x] Load environment variables from `.env` file (using `python-dotenv`).
        -   [x] Define `REPO_DIR`: This will be the primary workspace root. For local dev, it can be a subdirectory in the project (e.g., `./workspace_dev`). MCP, LSP, Git tools will operate relative to this.
        -   [x] Define `EMBED_PROVIDER` (default to "openai").
        -   [x] Implement a simple factory function `get_embedding_model()` in `common/embeddings.py` that returns an embedding client (e.g., `OpenAIEmbeddings`) based on `EMBED_PROVIDER`.
    -   [x] Testing: Basic check that environment variables are loaded.

-   [x] **3. FastAPI Gateway - Basic Setup:**
    -   [x] Action: Implement the initial FastAPI application.
    -   [x] File: `gateway/main.py`
    -   [x] Details: 
        -   [x] Add `fastapi`, `uvicorn`, `websockets`, `python-dotenv` to `requirements.txt`.
        -   [x] Create a basic FastAPI app instance.
        -   [x] Implement a health check endpoint (e.g., `/health`).
    -   [x] Testing: Run `uvicorn gateway.main:app --reload` and verify `/health`.

-   [x] **4. FastAPI Gateway - WebSocket Echo Endpoint (with New Schema):**
    -   [x] Action: Implement the `/api/agent` WebSocket endpoint.
    -   [x] File: `gateway/main.py` (or `gateway/agent_router.py`), `common/ws_messages.py` (for schema definitions).
    -   [x] Details:
        -   [x] Define Pydantic models or TypedDicts in `common/ws_messages.py` for the 1-byte prefix WebSocket message schema:
            -   [x] `TokenMessage(t: Literal["tok"], d: str)`
            -   [x] `ToolCallMessage(t: Literal["tool_call"], d: Dict[str, Any])`
            -   [x] `ToolResultMessage(t: Literal["tool_result"], d: Dict[str, Any])`
            -   [x] `FinalMessage(t: Literal["final"], d: str)`
            -   [x] `ErrorMessage(t: Literal["error"], d: str)`
        -   [x] The WebSocket endpoint should accept incoming messages (likely a simple JSON string from UI initially, e.g., `{"prompt": "user input"}`).
        -   [x] For now, it echoes back a `FinalMessage` with the received prompt.
        -   [x] Log received and sent messages, including their type prefix.
    -   [x] Testing: Use a WebSocket client. Send a JSON prompt. Verify a `FinalMessage` (e.g., `{"t": "final", "d": "Echo: user input"}`) is received.

---

### **Phase 1: LangGraph Agent Core & Initial Tool Implementations**

**(Corresponds to Design Doc MVP Phase 1, with enhancements)**

-   [x] **1. LangGraph Agent - Initial Setup:**
    -   [x] Action: Create the basic structure for the LangGraph agent.
    -   [x] Directory: `agent/`
    -   [x] Files: `agent/agent_graph.py`, `agent/state.py`.
    -   [x] Details:
        -   [x] Add `langgraph`, `langchain-core`, `langchain-openai` to `requirements.txt`.
        -   [x] Define `AgentState` (e.g., input prompt, conversation history list, current tool call request, tool results list).
        -   [x] Create a LangGraph `StateGraph` with a "planner_llm_step" node.
        -   [x] **(Revised)** The "planner_llm_step" node will:
            -   [x] Take the input prompt.
            -   [x] Make a **simple, real LLM call** (OpenAI). Prompt will guide the LLM to recognize this is a new project and that the first step should be to call a shell command to set it up.
            -   [x] The LLM's first response should be a tool call to `run_shell` with the `npx create-next-app...` command.
    -   [x] Testing: Unit test: invoke graph, check output state.

-   [x] **2. Integrate Agent with FastAPI Gateway (Initial - Final Output):**
    -   [x] Action: Modify FastAPI to pass messages to LangGraph and send back the agent's *final* response using the new WebSocket schema.
    -   [x] Files: `gateway/main.py`, `agent/agent_graph.py`.
    -   [x] Details:
        -   [x] Gateway invokes agent.
        -   [x] Agent runs until it reaches a "final response" state.
        -   [x] Gateway sends this back as a `FinalMessage`.
        -   [x] Testing: WebSocket client sends prompt, verifies a `FinalMessage` from the agent's planner is received.
        -   [x] Stabilize WebSocket integration tests (using TestClient, regressions fixed).

-   [x] **3. Tool Definition & Initial Implementations (`tools/` directory):**
    -   [x] General: Add `langchain-community`, `openai`, `chromadb`, `unidiff`, `GitPython`, `modelcontextprotocol`, `python-multipart` to `requirements.txt`.
    -   [x] Workspace Setup: All tools operate assuming files are within `os.environ['REPO_DIR']`.
    -   [x] **File: `tools/file_io_mcp_tools.py`**
        -   [x] Tools: `read_file(path_in_repo: str) -> str`, `write_file(path_in_repo: str, content: str) -> str`
        -   [x] Implementation: **Implement for real.** Wrappers around MCP client calls. Paths are relative to `REPO_DIR`.
    -   [x] **File: `tools/shell_mcp_tools.py`**
        -   [x] Tool: `run_shell(command: str, working_directory_relative_to_repo: Optional[str] = None) -> Dict[str, Any]`
        -   [x] Implementation: **Implement for real.** Calls MCP `execute_command`.
        -   [x] Testing: Unit tests for `run_shell` migrated to in-memory FastMCP server, ensuring robust and accurate testing.
    -   [x] **File: `tools/patch_tools.py`**
        -   [x] Tool: `apply_patch(file_path_in_repo: str, diff_content: str) -> Dict[str, Any]`
        -   [x] Implementation: **Implement for real.** Uses `run_shell` tool for `git apply`.
        -   [x] TODO: Add note for future diff-normalization.
    -   [x] **File: `tools/vector_store_tools.py`**
        -   [x] Adapter Class: `VectorStoreAdapter` (internal to module or common).
        -   [x] Tool: `vector_search(query: str, k: int = 3) -> List[Dict[str, Any]]`
        -   [x] Implementation: **Implement basic adapter and tool.**
            -   [x] Adapter uses `get_embedding_model()`.
            -   [x] In-memory Chroma store.
            -   [x] Implement simple disk cache for embeddings.
    -   [x] **File: `tools/lsp_tools.py`**
        -   [x] Tools: `lsp_definition(file_path_in_repo: str, line: int, character: int) -> Dict`, `lsp_hover(file_path_in_repo: str, line: int, character: int) -> Dict`
        -   [x] Implementation: **Stub first.** Return mock JSON.
    -   [x] **File: `tools/diagnostics_tools.py`** (or combine with `lsp_tools.py`)
        -   [x] Tool: `get_diagnostics(file_path_in_repo: Optional[str] = None) -> List[Dict]`
        -   [x] Implementation: **Stub first.** Return `[]`.
    -   [x] Testing: Unit tests for each tool.

-   [x] **4. LangGraph Agent - Tool Routing & Execution:**
    -   [x] Action: Enhance LangGraph agent for tool calling.
    -   [x] File: `agent/agent_graph.py` (Primary file for these enhancements)
    -   [x] Details:
        -   [x] "planner_llm_step" mock / "idealized" LLM identifies needed tool.
        -   [x] Conditional edge to "tool_executor_step".
        -   [x] "tool_executor_step" parses, dispatches, executes tool, stores output in `AgentState`.
        -   [x] Edge back to "planner_llm_step" (or "process_tool_result_llm_step").
        -   [x] If no tool call, graph to `END`.
        -   [x] Agent must handle the output of the first `run_shell` call (`create-next-app`).
        -   [x] Agent's next planned step should be to discover the new file structure (e.g., by calling `run_shell` with `ls -R`).
        -   [x] Agent must then proceed with the modification loop (read/plan-change/patch/validate) to fulfill the user's prompt.
        -   [x] Agent's internal context must be updated to treat `REPO_DIR/my-app` as the new root for subsequent file operations.
    -   [x] Testing: Integration tests for `read_file`, `run_shell`, `vector_search` tool flows.

---

### **Phase 2: Real LSP, Self-Healing & CLI Smoke Test**

**(Corresponds to Design Doc MVP Phase 2, with enhancements)**

-   [x] **0. Cleanup & Refactoring:**
    -   [x] Action: Abstract prompts into their own folder.
    -   [x] Files: `agent/agent_graph.py`, `agent/prompts/initial_scaffold.py`, `agent/prompts/__init__.py`

-   [x] **1. LSP Integration (TypeScript Language Server):**
    -   [x] Action: Replace LSP stubs with real `pygls` client calls.
    -   [x] File: `tools/lsp_tools.py`, `tools/diagnostics_tools.py`, `agent/lsp_manager.py` (new).
    -   [x] Details:
        -   [x] Add `pygls` to `requirements.txt`. Install `typescript-language-server`.
        -   [x] **`agent/lsp_manager.py`:** Manages `pygls.LanguageServer` instances per workspace. Handles spin-up, requests, diagnostics. Restarts LSP on `tsconfig.json` write (via explicit tool call).
        -   [x] LSP tools call `LspManager` methods.
    -   [x] Testing: A comprehensive integration test (`test_lsp_integration.py`) has been created to verify diagnostics, hover, and definition functionality directly.
    -   [ ] Testing (Agent E2E): An end-to-end test is needed to verify the agent can use the LSP tools in a realistic workflow. This will be covered under the "Self-Healing" phase.
    -   [x] **1.1. Refactor `agent/lsp_manager.py` (based on feedback):**
        -   [x] **Startup**: Accept `server_command: list[str]` in `__init__` (defaulting to `["typescript-language-server", "--stdio"]`), validate with `shutil.which`.
        -   [x] **Handshake**: Use typed `lsprotocol.types.InitializeParams` for `client.initialize()`.
        -   [x] **Diagnostics cache**: Protect `_diagnostics` with `asyncio.Lock()`.
        -   [x] **Process stderr**: Create an `asyncio.create_task` to drain and log `self._process.stderr`.
        -   [x] **Singleton/Concurrency**: Replace global `lsp_manager` with a keyed registry (e.g., `managers: dict[Path, LspManager]`) for workspace-specific instances to ensure thread-safety and support parallel operations.
        -   [x] **Resource cleanup**: Implement `kill()` fallback after `terminate()` and `wait()` timeout (e.g., `asyncio.TimeoutError` on `self._process.wait(timeout=5)`).

-   [x] **2. Basic Self-Healing Loop in Agent:**
    -   [x] Action: Implement self-healing logic.
    -   [x] File: `agent/agent_graph.py`
    -   [x] Details:
        -   [x] **Lint/Build Failure:** Agent uses `run_shell` (MCP) for `npm run lint` / `npm run build`. On failure: agent gets error, LLM plans fix (diff), agent calls `apply_patch`, retries shell command.
        -   [x] **LSP Diagnostics:** After `write_file`/`apply_patch`, agent calls `get_diagnostics`. If errors: LLM plans fix, `apply_patch`.
            -   Current debugging efforts for `apply_patch` (used in both lint/build and LSP-driven self-healing) involve ensuring robust error handling for async MCP calls, correct path/CWD management for `git apply`. The goal is to ensure `apply_patch` reliably functions within integration tests.
    -   [x] Testing:
        -   [x] **E2E Self-Healing Test: Linting Error**
            -   [x] Action: Create an integration test that verifies the agent can fix a TypeScript linting error.
            -   [x] File: `tests/integration/test_self_healing.py`
            -   [x] Details:
                -   [x] Setup a minimal TS project with `eslint` and a file with an unused variable.
                -   [x] Prompt the agent to run `npm run lint`.
                -   [x] Assert that the agent correctly identifies the failure, uses `diagnose` and `apply_patch` to fix the code, and successfully verifies the fix by re-running `npm run lint`.
        -   [x] **E2E Self-Healing Test: Next.js Build Error**
            -   [x] Action: Create an integration test that verifies the agent can fix a Next.js build error.
            -   [x] File: `tests/integration/test_self_healing.py`
            -   [x] Details:
                -   [x] Setup a minimal `create-next-app` project fixture with pre-installed dependencies.
                -   [x] Programmatically edit a `.tsx` file to introduce a TypeScript type error.
                -   [x] Prompt the agent to run `npm run build`.
                -   [x] Assert that the agent correctly identifies the build failure, uses `diagnose` and `apply_patch` to fix the type error, and successfully verifies the fix by re-running `npm run build`.

-   [x] **3. CLI Smoke Test (`tests/integration/test_e2e_smoke.py`):**
    -   [x] Action: Create the E2E smoke test script.
    -   [x] File: `tests/integration/test_e2e_smoke.py`
    -   [x] Details:
        -   [x] Script initializes agent, sets `REPO_DIR` to a temp dir.
        -   [x] Instructs agent: "Create a new Next.js application."
        -   [x] The test will verify that the agent's first tool call is `run_shell` with the `npx create-next-app...` command.
        -   [x] The test will assert that the `REPO_DIR/my-app/package.json` file exists after the agent run is complete.
    -   [x] Testing: Run `pytest tests/integration/test_e2e_smoke.py`.

---

### **Phase 2.5: Refactor `tool_executor_step` in `agent/agent_graph.py`**

- [x] **Refactor `tool_executor_step` for clarity, testability, and maintainability.**
    - [x] Step 1: Extract pure helper functions:
        - [x] `parse_tool_calls(message: AIMessage) -> list[ToolCall]`
        - [x] `maybe_inject_subdir(args: dict, tool_name: str, state: AgentState) -> dict`
    - [x] Step 2: Introduce `FixCycleTracker` dataclass:
        - [x] Define `FixCycleTracker` in `agent/executor/fix_cycle.py`.
        - [x] Implement `record_result` and `needs_verification` methods.
        - [x] Write comprehensive unit tests for `FixCycleTracker` mirroring current edge-cases (increment vs. reset logic for attempts, conditions for needing verification).
    - [x] Step 3: Replace output handling ladder with an `OUTPUT_HANDLERS` registry:
        - [x] Create `agent/executor/output_handlers.py`.
        - [x] Define `is_tool_successful(tool_output: Any) -> bool` using a registry.
        - [x] Define `format_tool_output(tool_output: Any) -> str` using a similar registry or integrate into the success handlers.
        - [x] Start with handlers for `RunShellOutput`, `WriteFileOutput`, `ApplyPatchOutput`, and a fallback.
    - [x] Step 4: Rewrite main `tool_executor_step` loop:
        - [x] Create `agent/executor/runner.py` for `async def run_single_tool(call: ToolCall, state: AgentState, tool_map: dict) -> Any`.
        - [x] Create `agent/executor/executor.py` for the new `async def tool_executor_step(state: AgentState) -> dict`.
        -   [x] The new `tool_executor_step` will use `parse_tool_calls`, `FixCycleTracker`, `run_single_tool`, `is_tool_successful`, and `format_tool_output`.
        -   [x] Keep the old `tool_executor_step` in `agent/agent_graph.py` alongside the new one (e.g., `_tool_executor_step_legacy`), selectable via a temporary flag or by commenting out, until all tests pass with the new implementation.
        -   [x] Update `agent_graph.py` to import and use the new `tool_executor_step` from `agent.executor.executor`.
    - [x] Step 5: Clean up and finalize:
        - [x] Delete dead logs and duplicate assignments identified in the original `tool_executor_step`.
        - [x] Once the new implementation is stable and all tests pass, remove the legacy `_tool_executor_step_legacy`.
        - [x] Ensure all relevant imports are updated and old ones removed.
    - [x] Update `architecture.md` to reflect the new `agent/executor/` module structure.

---

### **Phase 3: PTY Streaming for Real-Time Scaffolding**

**(Corresponds to Design Doc v2: PTY-Streaming)**

-   [x] **1. Backend: PTY Manager & `run_shell` Enhancement**
    -   [x] Action: Create a `PTYManager` for handling pseudo-terminal processes and update the `run_shell` tool.
    -   [x] Files: `agent/pty/manager.py` (new), `tools/shell_mcp_tools.py`, `requirements.txt`.
    -   [x] Details:
        -   [x] Add `ptyprocess~=0.7` and `psutil~=7.0` to `requirements.txt`.
        -   [x] Implement `PTYManager` as a singleton to spawn, stream, and manage PTY processes.
        -   [x] Modify `run_shell` to accept `pty: bool = False`. If `True`, it delegates to `PTYManager` and returns a `TaskHandle`. If `False`, it maintains the existing synchronous behavior for backward compatibility.
        -   [x] The `PTYManager` is responsible for emitting `task_started`, `task_log`, and `task_finished` events via callbacks.
    -   [x] Testing: Unit tests for `PTYManager` (spawning, cleanup). Unit tests for `run_shell`'s dual sync/async behavior.

-   [x] **2. Agent: Await PTY Task Completion**
    -   [x] Action: Update the agent executor to handle and await asynchronous PTY tasks.
    -   [x] Files: `agent/executor/runner.py`, `agent/state.py`.
    -   [x] Details:
        -   [x] When `run_shell` returns a `PTYTask`, the `run_single_tool` function in the runner awaits its completion using `PTYManager.wait_for_completion(taskId)`.
        -   [x] This deterministically blocks the agent's execution graph until the long-running PTY process is complete.
        -   [x] The `AgentState` was updated to include `pty_callbacks` to pass handlers from the gateway to the tool.
    -   [x] Testing: Integration test where the agent calls `run_shell(pty=True)` and correctly waits for completion before proceeding to the next step.

-   [x] **3. Gateway: Relay PTY Events via WebSocket**
    -   [x] Action: Modify the WebSocket handler to stream all agent and PTY events.
    -   [x] File: `gateway/main.py`, `common/ws_messages.py`.
    -   [x] Details:
        -   [x] The WebSocket handler now defines PTY callbacks (`on_started`, `on_output`, `on_complete`) and injects them into the `AgentState`.
        -   [x] The handler was switched from `ainvoke` to `astream_events` to process the full event stream from LangGraph.
        -   [x] It now relays tool calls, tool results, and PTY task messages (`task_started`, `task_log`, `task_finished`) to the UI.
        -   [x] Added PTY message schemas to `common/ws_messages.py`.
    -   [x] Testing: WebSocket client test that initiates a PTY task and asserts that `task_started`, `task_log`, and `task_finished` events are received correctly.

-   [ ] **4. UI: Implement Tabbed Terminal and Preview Panel**
    -   [ ] Action: Refactor the UI to support a tabbed view for real-time PTY logs and the application preview, separating them from the chat.
    -   [ ] Files:
        -   `ui/src/app/page.tsx` (main layout)
        -   `ui/src/app/components/MainPanel.tsx` (new: for tab switching)
        -   `ui/src/app/components/TerminalView.tsx` (new: for rendering logs)
        -   `ui/src/app/components/ChatInterface.tsx` (refactored)
        -   `ui/src/types/ws_messages.ts` (new: for frontend type definitions)
    -   [ ] Details:
        -   [ ] **State Management:** Lift WebSocket connection logic and message state from `ChatInterface` up to `page.tsx`.
        -   [ ] **Layout:** Modify `page.tsx` to use a new `MainPanel` component that will contain the tabbed interface for the "Terminal" and "Live Preview".
        -   [ ] **Terminal View:** Create `TerminalView.tsx` to receive log data as props and render it, handling auto-scrolling.
        -   [ ] **Message Handling:** Update the main page's WebSocket handler to process `task_started`, `task_log`, and `task_finished` messages. On `task_started`, switch to the "Terminal" tab. On `task_finished` and subsequent agent messages, switch to the "Live App Preview" tab.
        -   [ ] **Chat Interface:** Simplify `ChatInterface.tsx` to be a presentational component, receiving messages and sending user input via props.
    -   [ ] Testing: Manual E2E test: run the full stack, issue a command like "create a ciao world app," watch the UI switch to the terminal tab and stream logs, then switch to the preview when done.

-   [ ] **4. StackBlitz WebContainer Integration (Proof of Concept):**
    -   [ ] Action: Integrate WebContainer API into Next.js UI.
    -   [ ] File: `ui/app/components/PreviewFrame.tsx`
    -   [ ] Details:
        -   [ ] UI receives minimal Next.js app files from agent.
        -   [ ] Use `wc.mount()` to write files.
        -   [ ] Run `npm install`, `npm run dev` via WebContainer API.
        -   [ ] Embed preview URL in iframe.
        -   [ ] Pass `REPO_DIR` concept to WebContainer (mount files from agent as if `REPO_DIR` is root).
    -   [ ] Testing: Minimal Next.js app boots in iframe.`

-   [ ] **5. End-to-End Flow for Preview:**
    -   [ ] Action: Connect agent's file operations (MCP tools on `REPO_DIR`) to WebContainer.
    -   [ ] Details:
        -   [ ] Agent uses `write_file` or `apply_patch`.
        -   [ ] Agent sends `{"t": "file_updated", "d": {"path": "path/in/repo", "content": "..."}}` message.
        -   [ ] UI receives `file_updated`, uses `wc.fs.writeFile()`. HMR updates iframe.
        -   [ ] Initial Scaffolding (MVP): Agent uses `run_shell("npx create-next-app ...")`. The agent must then discover the created files (e.g., via `run_shell('ls -R')`) and send them to the UI for mounting in the WebContainer.
    -   [ ] Testing: Agent creates `app/page.tsx` -> appears in iframe. Agent patches `app/page.tsx` -> iframe updates.

---

### **Phase 4: Observability & CI**

**(Corresponds to Design Doc MVP Phase 4)**

-   [ ] **1. LangGraph Studio / LangSmith Integration:**
    -   [ ] Action: Configure LangGraph agent for LangSmith traces.
    -   [ ] File: `agent/agent_graph.py`.
    -   [ ] Details: Set up API key/project env vars. Enable tracing.
    -   [ ] Testing: Run agent, verify traces in LangSmith.

-   [ ] **2. Basic CI Regression Guard:**
    -   [ ] Action: Set up basic CI pipeline (e.g., GitHub Actions).
    -   [ ] Details: Setup Python, install deps, run linters, `pytest tests/`, run `scripts/e2e_smoke.py`.
    -   [ ] Testing: Push change, verify CI passes. Check LangSmith for CI run trace.

---

**Post-MVP Enhancements (Beyond Initial Roadmap):**

*   Real Vector Search Implementation
*   Advanced LSP Tooling
*   Sophisticated Agent Planning
*   Error Recovery & Re-planning
*   State Management in Agent (for workspace understanding)
*   Security Hardening

**Future-proofing Note:**
> To ensure reliable imports for all contributors and CI, plan to migrate the codebase to a `src/` layout (placing all source code in a `src/` directory) or support editable installs (`pip install -e .`). This will eliminate the need for contributors to set `PYTHONPATH` manually and is considered best practice for modern Python projects.