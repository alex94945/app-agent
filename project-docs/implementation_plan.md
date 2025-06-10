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
        -   [x] The "planner_llm_step" node will:
            -   [x] Take the input prompt from the state.
            -   [x] Make a **simple, real LLM call** (OpenAI). Prompt: "User said: {input}. What is your response or next tool call?".
            -   [x] Update state with the LLM's response.
    -   [x] Testing: Unit test: invoke graph, check output state.

-   [ ] **2. Integrate Agent with FastAPI Gateway (Initial - Final Output):**
    -   [ ] Action: Modify FastAPI to pass messages to LangGraph and send back the agent's *final* response using the new WebSocket schema.
    -   [ ] Files: `gateway/main.py`, `agent/agent_graph.py`.
    -   [ ] Details:
        -   [ ] Gateway invokes agent.
        -   [ ] Agent runs until it reaches a "final response" state.
        -   [ ] Gateway sends this back as a `FinalMessage`.
    -   [ ] Testing: WebSocket client sends prompt, verifies a `FinalMessage` from the agent's planner is received.

-   [ ] **3. Tool Definition & Initial Implementations (`tools/` directory):**
    -   [ ] General: Add `langchain-community`, `openai`, `chromadb`, `unidiff`, `GitPython`, `modelcontextprotocol`, `python-multipart` to `requirements.txt`.
    -   [ ] Workspace Setup: All tools operate assuming files are within `os.environ['REPO_DIR']`.
    -   [ ] **File: `tools/file_io_mcp_tools.py`**
        -   [ ] Tools: `read_file(path_in_repo: str) -> str`, `write_file(path_in_repo: str, content: str) -> str`
        -   [ ] Implementation: **Implement for real.** Wrappers around MCP client calls. Paths are relative to `REPO_DIR`.
    -   [ ] **File: `tools/shell_mcp_tools.py`**
        -   [ ] Tool: `run_shell(command: str, working_directory_relative_to_repo: Optional[str] = None) -> Dict[str, Any]`
        -   [ ] Implementation: **Implement for real.** Calls MCP `execute_command`.
    -   [ ] **File: `tools/patch_tools.py`**
        -   [ ] Tool: `apply_patch(file_path_in_repo: str, diff_content: str) -> Dict[str, Any]`
        -   [ ] Implementation: **Implement for real.** Uses `run_shell` tool for `git apply`.
        -   [ ] TODO: Add note for future diff-normalization.
    -   [ ] **File: `tools/vector_store_tools.py`**
        -   [ ] Adapter Class: `VectorStoreAdapter` (internal to module or common).
        -   [ ] Tool: `vector_search(query: str, k: int = 3) -> List[Dict[str, Any]]`
        -   [ ] Implementation: **Implement basic adapter and tool.**
            -   [ ] Adapter uses `get_embedding_model()`.
            -   [ ] In-memory Chroma store.
            -   [ ] Implement simple disk cache for embeddings.
    -   [ ] **File: `tools/lsp_tools.py`**
        -   [ ] Tools: `lsp_definition(file_path_in_repo: str, line: int, character: int) -> Dict`, `lsp_hover(file_path_in_repo: str, line: int, character: int) -> Dict`
        -   [ ] Implementation: **Stub first.** Return mock JSON.
    -   [ ] **File: `tools/diagnostics_tools.py`** (or combine with `lsp_tools.py`)
        -   [ ] Tool: `get_diagnostics(file_path_in_repo: Optional[str] = None) -> List[Dict]`
        -   [ ] Implementation: **Stub first.** Return `[]`.
    -   [ ] Testing: Unit tests for each tool.

-   [ ] **4. LangGraph Agent - Tool Routing & Execution:**
    -   [ ] Action: Enhance LangGraph agent for tool calling.
    -   [ ] File: `agent/agent_graph.py`
    -   [ ] Details:
        -   [ ] "planner_llm_step" LLM identifies needed tool.
        -   [ ] Conditional edge to "tool_executor_step".
        -   [ ] "tool_executor_step" parses, dispatches, executes tool, stores output in `AgentState`.
        -   [ ] Edge back to "planner_llm_step" (or "process_tool_result_llm_step").
        -   [ ] If no tool call, graph to `END`.
    -   [ ] Testing: Integration tests for `read_file`, `run_shell`, `vector_search` stub flows.

---

### **Phase 2: Real LSP, Self-Healing & CLI Smoke Test**

**(Corresponds to Design Doc MVP Phase 2, with enhancements)**

-   [ ] **1. LSP Integration (TypeScript Language Server):**
    -   [ ] Action: Replace LSP stubs with real `pygls` client calls.
    -   [ ] File: `tools/lsp_tools.py`, `tools/diagnostics_tools.py`, `agent/lsp_manager.py` (new).
    -   [ ] Details:
        -   [ ] Add `pygls` to `requirements.txt`. Install `typescript-language-server`.
        -   [ ] **`agent/lsp_manager.py`:** Manages single `pygls.LanguageServer` for `REPO_DIR`. Handles spin-up, requests, diagnostics. Restarts LSP on `tsconfig.json` write.
        -   [ ] LSP tools call `LspManager` methods.
    -   [ ] Testing: Agent uses `write_file` for TS project in `REPO_DIR`. Test `lsp_definition`, `lsp_hover`. Introduce error, test `get_diagnostics`.

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
        -   [ ] Instructs agent: "Initialize a new npm project and install 'lodash'."
        -   [ ] Agent calls `run_shell("npm init -y")`, then `run_shell("npm install lodash")`.
        -   [ ] Script asserts `package.json` and `node_modules/lodash` exist in `REPO_DIR`.
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
    -   [ ] Testing: Minimal Next.js app boots in iframe.

-   [ ] **5. End-to-End Flow for Preview:**
    -   [ ] Action: Connect agent's file operations (MCP tools on `REPO_DIR`) to WebContainer.
    -   [ ] Details:
        -   [ ] Agent uses `write_file` or `apply_patch`.
        -   [ ] Agent sends `{"t": "file_updated", "d": {"path": "path/in/repo", "content": "..."}}` message.
        -   [ ] UI receives `file_updated`, uses `wc.fs.writeFile()`. HMR updates iframe.
        -   [ ] Initial Scaffolding (MVP): Agent uses `run_shell("npm init -y")`, `run_shell("npm install next...")`, then `write_file` for minimal configs and `app/page.tsx`.
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
*   Full `npx create-next-app` Scaffolding (efficiently into WebContainer)
*   State Management in Agent (for workspace understanding)
*   Security Hardening