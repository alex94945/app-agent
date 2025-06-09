## Autonomous, Tool‑Using AI Agent — Design Document (June 2025) - v2

### 1 Strategic Introduction

Modern assistants outperform legacy “prompt graph” systems by giving a large‑language model **freedom to plan its own steps and call external tools on demand**.  A wide toolbelt—file I/O, semantic search, language‑server queries, shell commands, diff‑patch—lets the LLM iterate the way a senior developer would.  Deterministic helpers (lint auto‑fix, test gates, multi‑LLM cross‑checks) catch easy mistakes *without* hard‑coding the full sequence.  Research such as **Toolformer** shows that models can even teach themselves when and how to invoke these tools ([arxiv.org](https://arxiv.org/abs/2302.04761)).  Industry momentum backs the pattern: OpenAI’s new agent‑centric Responses API ([reuters.com](https://www.reuters.com/technology/artificial-intelligence/openai-launches-new-developer-tools-chinese-ai-startups-gain-ground-2025-03-11/)), GitHub’s Copilot Workspaces ([githubnext.com](https://githubnext.com/projects/copilot-workspace)), and Figma’s MCP server for design data ([theverge.com](https://www.theverge.com/news/679439/figma-dev-mode-mcp-server-beta-release)) all expose rich tool surfaces and rely on the model to drive them.

### 2 Executive Summary

* **Brain**: a Python **LangGraph** agent that plans tasks and calls tools. ([pypi.org](https://pypi.org/project/langgraph/))
* **UI**: a Next.js 14 (App Router) web app with a streaming chat log and a live preview iframe.
* **Toolbelt**: vector search (**Chroma** initially, using **OpenAI text-embedding-3-large** via a configurable `EMBED_PROVIDER`), compiler‑grade look‑ups (TypeScript LSP via pygls), diff‑patch (`git apply` via MCP shell), and execution/validation via **Model Context Protocol** shell tools ([modelcontextprotocol.io](https://modelcontextprotocol.io/docs/concepts/tools)).
* **Runtime**: everything runs in‑browser using **StackBlitz WebContainers** for instant Node+Next.js dev servers ([developer.stackblitz.com](https://developer.stackblitz.com/platform/api/webcontainer-api)).
* **Workspace Convention**: All tools (MCP, LSP, Git) operate on a unified workspace defined by an environment variable (e.g., `REPO_DIR`), which is also the basis for the WebContainer's file system.
* **Safety nets**: diagnostics from LSP, build/test exit codes, and lint auto‑fixes trigger automatic re‑planning rather than silent failure.

### 3 High‑Level Integration Diagram

```
┌─────────────  Next.js 14 UI  ───────────────┐
│ Chat (RSC)  ─▶  /api/agent  (fetch/ws)      │
└────────────────────────┬────────────────────┘
                         ▼
            ┌──────────────────────────────┐
            │  FastAPI‑WS Gateway (Py)     │ # Handles 1-byte prefix msg schema
            └──────────────┬───────────────┘
                           ▼
         ┌──────────────────────────────────┐
         │   LangGraph Agent  (Python)      │
         │  • Planner + Tool Router         │
         └────┬────────┬────────┬───────────┘
              │        │        │
  vector‑db   │   LSP  │  diff  │  MCP shell
 (Chroma)     │ client │ engine │  server
              ▼        ▼        ▼
        Context mix  git apply   npm build/test
                     (via MCP)
```

### 4 Node Reference & Implementation Cheat‑Sheet

| Node                       | Purpose                    | 2025‑Stable Package / Service                                                                                                                                 | Notes                                                                                                                                                              |
| -------------------------- | -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **FastAPI‑WS Gateway**     | Duplex stream UI ⇄ agent   | `fastapi≥0.111`                                                                                                                                               | Streams JSON tokens to browser using a 1-byte type prefix schema (e.g., `{"t": "tok", "d": "..."}`).                                                               |
| **LangGraph Agent**        | Planning + orchestration   | `langgraph==0.9.2`                                                                                                                                            | Observer pushes every LLM token to WS.                                                                                                                             |
| **Tool Router**            | Exposes Python `@tool` fns | `langchain.tools`                                                                                                                                             | All tools in `tools/` folder. Operates on `os.environ['REPO_DIR']`.                                                                                                |
| **Vector DB**              | Breadth search             | `chromadb` (via `VectorStoreAdapter`); Embeddings via `EMBED_PROVIDER` (default OpenAI `text-embedding-3-large`).                                               | Adapter allows easy swap to Qdrant. Disk cache for embeddings during dev.                                                                                          |
| **LSP Client**             | Depth / compiler oracle    | `pygls` → `typescript‑language‑server` ([github.com](https://github.com/openlawlibrary/pygls))                                                                 | Single LSP server per `REPO_DIR`. Restarts on `tsconfig.json` write.                                                                                               |
| **Diff‑Patch**             | Precise writes             | MCP `run_shell` tool to call `git apply --cached`.                                                                                                            | `git` must be in MCP environment. Abort on patch failure (non-zero exit from `git apply`). TODO: Better diff normalization before applying.                     |
| **Execution / Validation** | Build, test, lint          | `modelcontextprotocol` client → `mcp‑server‑commands` ([modelcontextprotocol.io](https://modelcontextprotocol.io/docs/concepts/tools))                         | Tools operate within `REPO_DIR`.                                                                                                                                   |
| **Runtime Sandbox**        | Live dev server            | **StackBlitz WebContainers** API ([developer.stackblitz.com](https://developer.stackblitz.com/platform/api/webcontainer-api))                                  | Port‑forward 3000 → iframe. File system mirrors `REPO_DIR`.                                                                                                      |
| **Observability**          | Tracing & metrics          | **LangGraph Studio**, LangSmith                                                                                                                               | CI regression guard includes CLI smoke tests (e.g., `npm init -y` via agent).                                                                                      |

\### 5 Implementation Map by Capability

| Capability         | Tool name                 | Python package / Method       | Safety Net                    |
| ------------------ | ------------------------- | ----------------------------- | ----------------------------- |
| File ops           | `read_file`, `write_file` | MCP client                    | `git status` diff preview     |
| Search (breadth)   | `vector_search`           | `VectorStoreAdapter` (Chroma) | sim ≥ 0.20                    |
| Semantic look‑ups  | `lsp_definition`, `hover` | `pygls` client to LSP         | 50 ms timeout + retry         |
| Diagnostics        | `get_diagnostics`         | `pygls` client (from LSP push)| Agent re-plans on errors      |
| Execute / validate | `run_shell`               | MCP client `execute_command`  | non‑zero exit triggers repair |
| Write / edit       | `apply_patch`             | `run_shell` (`git apply ...`) | patch‑fail ⇒ revert & re‑plan |

\### 6 End‑to‑End User Flow

1. **Prompt** → FastAPI forwards to LangGraph.
2. **Plan**: agent decides to scaffold (e.g., `npm init -y`, write basic files), install, run dev.
3. **Scaffold**: `run_shell('npm init -y')`, then agent uses `write_file` for `package.json` (add scripts), `next.config.js`, `app/page.tsx`.
4. **Dev server**: `run_shell('npm run dev')`; WebContainer (mirroring `REPO_DIR`) iframe streams preview.
5. **Diagnostics**: LSP (watching `REPO_DIR`) `publishDiagnostics` arrive via `get_diagnostics` tool; agent patches via `apply_patch` tool.
6. **Tests**: `run_shell('npm test')`; failures feed back into plan.
7. **User tweak**: “Make header purple” → LLM generates diff → `apply_patch` tool; preview refreshes.

\### 7 MVP‑First Roadmap (Python stack)

| Phase | Deliverable                                     | Impact                  | Effort |
| ----- | ----------------------------------------------- | ----------------------- | ------ |
| 0     | FastAPI skeleton (`/ws` echo, 1-byte schema)    | Unblocks UI             | 🟢 Low |
| 1     | Tool impls (MCP file/shell, basic Chroma adapter, basic patch, LSP stubs) | Proves JSON contract    | 🟢 Low |
| 2     | Real MCP + LSP integration; CLI smoke test      | Self‑healing build loop | 🟠 Med |
| 3     | WebContainer preview                            | UX wow moment           | 🟠 Med |
| 4     | LangGraph Studio CI                             | Regression guard        | 🟢 Low |

---

**Take‑away**: Expose a rich toolbelt, let the Python LangGraph agent plan freely, and use deterministic guard‑rails (lint, tests, diagnostics) to *augment*—not constrain—the LLM.  This yields a flexible, end‑to‑end coding partner that can scaffold, debug, and deploy a Next.js app with surprisingly little bespoke code.