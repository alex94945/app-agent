## Implementation Plan: Autonomous, Tool-Using AI Agent (Revised v2)

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

-   [ ] **2. Basic Self-Healing Loop in Agent:**
    -   [ ] Action: Implement self-healing logic.
    -   [ ] File: `agent/agent_graph.py`
    -   [ ] Details:
        -   [ ] **Lint/Build Failure:** Agent uses `run_shell` (MCP) for `npm run lint` / `npm run build`. On failure: agent gets error, LLM plans fix (diff), agent calls `apply_patch`, retries shell command.
        -   [ ] **LSP Diagnostics:** After `write_file`/`apply_patch`, agent calls `get_diagnostics`. If errors: LLM plans fix, `apply_patch`.
    -   [ ] Testing: Scenario for lint error fix. Scenario for type error fix via LSP.

-   [ ] **3. CLI Smoke Test (`scripts/e2e_smoke.py`):**
    -   [ ] Action: Create the E2E smoke test script.
    -   [ ] File: `scripts/e2e_smoke.py`
    -   [ ] Details:
        -   [ ] Script initializes agent, sets `REPO_DIR` to a temp dir.
        -   [ ] Instructs agent: "Create a new Next.js application."
        -   [ ] The test will **verify that the agent's first tool call is `run_shell` with the `npx create-next-app...` command.**
        -   [ ] The test will then assert that the `REPO_DIR/my-app/package.json` file exists after the agent run is complete.
    -   [ ] Testing: Run `python scripts/e2e_smoke.py`.

---

### **Phase 3: UI, WebContainer Preview & Streaming**

**(Corresponds to Design Doc MVP Phase 3)**

-   [ ] **1. Next.js UI - Basic Structure:**
    -   [ ] Action: Set up Next.js UI.
    -   [ ] Directory: `ui/`
    -   [ ] Details: `npx create-next-app@latest`. Basic layout, chat input, log display, iframe placeholder.
    -   [ ] Testing: `npm run dev` in `ui/`.

-   [ ] **2. Next.js UI - WebSocket Connection to FastAPI (with New Schema):**
    -   [ ] Action: Implement client-side JS for WebSocket, using 1-byte prefix schema.
    -   [ ] File: `ui/app/components/ChatInterface.tsx`, `common/ws_messages.ts`.
    -   [ ] Details: Connect, send input, handle incoming messages based on `t` field.
    -   [ ] Testing: Start gateway & UI. Send messages, verify `FinalMessage` displayed.

-   [ ] **3. FastAPI Gateway & Agent - Full Streaming:**
    -   [ ] Action: Implement full streaming of LLM tokens and tool events.
    -   [ ] Files: `gateway/main.py`, `agent/agent_graph.py`.
    -   [ ] Details:
        -   [ ] LangGraph agent uses `astream_events`, observer/callback captures events.
        -   [ ] Events formatted to 1-byte prefix schema.
        -   [ ] FastAPI iterates agent stream, sends messages over WebSocket.
    -   [ ] Testing: Inspect WebSocket traffic. UI chat log updates dynamically.

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