## Autonomous, Tool‑Using AI Agent — Design Document (June 2025)

### 1 Strategic Introduction

Modern assistants outperform legacy “prompt graph” systems by giving a large‑language model **freedom to plan its own steps and call external tools on demand**.  A wide toolbelt—file I/O, semantic search, language‑server queries, shell commands, diff‑patch—lets the LLM iterate the way a senior developer would.  Deterministic helpers (lint auto‑fix, test gates, multi‑LLM cross‑checks) catch easy mistakes *without* hard‑coding the full sequence.  Research such as **Toolformer** shows that models can even teach themselves when and how to invoke these tools ([arxiv.org](https://arxiv.org/abs/2302.04761)).  Industry momentum backs the pattern: OpenAI’s new agent‑centric Responses API ([reuters.com](https://www.reuters.com/technology/artificial-intelligence/openai-launches-new-developer-tools-chinese-ai-startups-gain-ground-2025-03-11/)), GitHub’s Copilot Workspaces ([githubnext.com](https://githubnext.com/projects/copilot-workspace)), and Figma’s MCP server for design data ([theverge.com](https://www.theverge.com/news/679439/figma-dev-mode-mcp-server-beta-release)) all expose rich tool surfaces and rely on the model to drive them.

### 2 Executive Summary

* **Brain**: a Python **LangGraph** agent that plans tasks and calls tools. ([pypi.org](https://pypi.org/project/langgraph/))
* **UI**: a Next.js 14 (App Router) web app with a streaming chat log and a live preview iframe.
* **Toolbelt**: vector search (**Chroma** initially, using **OpenAI text-embedding-3-large**), compiler‑grade look‑ups (TypeScript LSP via pygls), diff‑patch (unidiff + GitPython), and execution/validation via **Model Context Protocol** shell tools ([modelcontextprotocol.io](https://modelcontextprotocol.io/docs/concepts/tools)).
* **Runtime**: everything runs in‑browser using **StackBlitz WebContainers** for instant Node+Next.js dev servers ([developer.stackblitz.com](https://developer.stackblitz.com/platform/api/webcontainer-api)).
* **Safety nets**: diagnostics from LSP, build/test exit codes, and lint auto‑fixes trigger automatic re‑planning rather than silent failure.

### 3 High‑Level Integration Diagram

```
┌─────────────  Next.js 14 UI  ───────────────┐
│ Chat (RSC)  ─▶  /api/agent  (fetch/ws)      │
└────────────────────────┬────────────────────┘
                         ▼
            ┌──────────────────────────────┐
            │  FastAPI‑WS Gateway (Py)     │
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
        Context mix   git apply  npm build/test
```

### 4 Node Reference & Implementation Cheat‑Sheet

| Node                       | Purpose                    | 2025‑Stable Package / Service                                                                                                                                 | Notes                                                                                                |
| -------------------------- | -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| **FastAPI‑WS Gateway**     | Duplex stream UI ⇄ agent   | `fastapi≥0.111`                                                                                                                                               | Streams JSON tokens to the browser.                                                                  |
| **LangGraph Agent**        | Planning + orchestration   | `langgraph==0.9.2`                                                                                                                                            | Observer pushes every LLM token to WS.                                                               |
| **Tool Router**            | Exposes Python `@tool` fns | `langchain.tools`                                                                                                                                             | All tools in `tools/` folder.                                                                        |
| **Vector DB**              | Breadth search             | `chromadb` (initially, e.g., `langchain.vectorstores.Chroma`); OpenAI `text-embedding-3-large` for embeddings.                                                | Easy swap to `qdrant‑client` later.                                                                  |
| **LSP Client**             | Depth / compiler oracle    | `pygls` → `typescript‑language‑server` ([github.com](https://github.com/openlawlibrary/pygls))                                                                 | One server per workspace.                                                                            |
| **Diff‑Patch**             | Precise writes             | `unidiff` + `GitPython` ([pypi.org](https://pypi.org/project/unidiff/))                                                                                        | Abort on patch failure.                                                                              |
| **Execution / Validation** | Build, test, lint          | `modelcontextprotocol` client → `mcp‑server‑commands` ([modelcontextprotocol.io](https://modelcontextprotocol.io/docs/concepts/tools))                         | Same schema adopted by Figma, VS Code, Claude, etc.                                                  |
| **Runtime Sandbox**        | Live dev server            | **StackBlitz WebContainers** API ([developer.stackblitz.com](https://developer.stackblitz.com/platform/api/webcontainer-api))                                  | Port‑forward 3000 → iframe.                                                                        |
| **Observability**          | Tracing & metrics          | **LangGraph Studio**, LangSmith                                                                                                                               | CI regression guard.                                                                                 |

\### 5 Implementation Map by Capability

| Capability         | Tool name                 | Python package        | Safety Net                    |
| ------------------ | ------------------------- | --------------------- | ----------------------------- |
| File ops           | `read_file`, `write_file` | MCP                   | `git status` diff preview     |
| Search (breadth)   | `vector_search`           | Chroma (via LangChain) | sim ≥ 0.20                    |
| Semantic look‑ups  | `lsp_definition`, `hover` | pygls                 | 50 ms timeout + retry         |
| Execute / validate | `run_shell`               | MCP shell             | non‑zero exit triggers repair |
| Write / edit       | `apply_patch`             | unidiff + GitPython   | patch‑fail ⇒ revert & re‑plan |

\### 6 End‑to‑End User Flow

1. **Prompt** → FastAPI forwards to LangGraph.
2. **Plan**: agent decides to initialize from template, install, run dev.
3. **Template Init**: Copy Next.js base template directory and configure as needed.
4. **Dev server**: `run_shell('npm run dev')`; WebContainer iframe streams preview.
5. **Diagnostics**: LSP `publishDiagnostics` arrive; agent patches via `apply_patch`.
6. **Tests**: `run_shell('npm test')`; failures feed back into plan.
7. **User tweak**: “Make header purple” → diff patch; preview refreshes.

\### 7 MVP‑First Roadmap (Python stack)

| Phase | Deliverable                      | Impact                  | Effort |
| ----- | -------------------------------- | ----------------------- | ------ |
| 0     | FastAPI skeleton (`/ws` echo)    | Unblocks UI             | 🟢 Low |
| 1     | Tool stubs (vector (Chroma), diff, shell) | Proves JSON contract    | 🟢 Low |
| 2     | Real MCP + LSP integration       | Self‑healing build loop | 🟠 Med |
| 3     | WebContainer preview             | UX wow moment           | 🟠 Med |
| 4     | LangGraph Studio CI              | Regression guard        | 🟢 Low |

---

**Take‑away**: Expose a rich toolbelt, let the Python LangGraph agent plan freely, and use deterministic guard‑rails (lint, tests, diagnostics) to *augment*—not constrain—the LLM.  This yields a flexible, end‑to‑end coding partner that can initialize from a predefined template, debug, and deploy a Next.js app with surprisingly little bespoke code.