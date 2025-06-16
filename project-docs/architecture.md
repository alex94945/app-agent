# System Architecture

**Version:** 1.0
**Date:** June 13, 2025

## 1. Overview

This document outlines the architecture of the Autonomous AI Web Application Co-Pilot. The system is designed as a modular, tool-using AI agent capable of understanding natural language prompts to scaffold, build, and iteratively develop web applications. The architecture is composed of several key components that work in concert to provide a seamless conversational development experience, from initial idea to a live, in-browser preview.

The core principles guiding this architecture are:

*   **Modularity:** Each component has a well-defined responsibility, allowing for independent development, testing, and enhancement.
*   **Tool-Centric Design:** The agent's capabilities are extended through a collection of well-defined tools, making it easy to add new functionalities.
*   **Clear Interfaces:** Communication between components relies on clear, schema-defined contracts, primarily over WebSockets.
*   **Real-Time Feedback:** The system is designed to provide continuous, real-time feedback to the user, including the agent's thought process, actions, and a live preview of the application.

---

## 2. Architectural Diagram

```mermaid
graph TD
    subgraph "User's Browser"
        UI[Next.js UI]
        Preview[Live Preview (WebContainer)]
    end

    subgraph "Backend Infrastructure (Python)"
        Gateway[FastAPI Gateway]
        Agent[LangGraph Agent]
        Tools[Toolbelt]
        LSP[LSP Manager]
    end

    subgraph "Development Workspace"
        Workspace[REPO_DIR Filesystem]
    end

    UI -- WebSocket --> Gateway
    Gateway -- Invokes --> Agent
    Agent -- Uses --> Tools
    Tools -- Interact with --> Workspace
    Tools -- Interact with --> LSP
    Agent -- Streams updates --> Gateway
    Gateway -- Streams updates --> UI
    UI -- Updates --> Preview

    classDef component fill:#f9f,stroke:#333,stroke-width:2px;
    class UI,Preview,Gateway,Agent,Tools,LSP,Workspace component;
```

---

## 3. Core Components

### 3.1. Frontend (UI)

*   **Technology:** Next.js, TypeScript, React
*   **Responsibilities:**
    *   Provides the primary user interface, including a chat window for sending prompts to the agent.
    *   Establishes and manages a WebSocket connection to the FastAPI Gateway.
    *   Receives and displays a real-time stream of messages from the agent (e.g., thoughts, tool calls, results, errors).
    *   Hosts the StackBlitz WebContainer iframe for the live preview.
    *   Receives file system updates from the agent and forwards them to the WebContainer to keep the preview synchronized.

### 3.2. FastAPI Gateway

*   **Technology:** FastAPI, Python, WebSockets
*   **Responsibilities:**
    *   Acts as the central communication hub between the frontend and the agent.
    *   Manages WebSocket connections from clients.
    *   Receives user prompts and initiates the LangGraph agent execution.
    *   Streams events (LLM tokens, tool calls, etc.) from the running agent back to the UI using a defined message schema.
    *   Provides a basic health check endpoint.

### 3.3. LangGraph Agent

*   **Technology:** LangGraph, LangChain, Python
*   **Responsibilities:**
    *   The "brain" of the system.
    *   Maintains the state of the development task, including conversation history and tool results.
    *   Interprets user prompts using a large language model (LLM) to form a plan.
    *   Executes the plan by making decisions on which tool to use from the `Toolbelt`.
    *   Processes the output from tools to inform its next steps.
    *   Implements self-healing logic by interpreting diagnostics and build errors to attempt fixes.

### 3.4. Toolbelt

*   **Technology:** Python
*   **Responsibilities:**
    *   A collection of functions that the agent can invoke to interact with the development environment. Each tool is a wrapper around a specific capability.
    *   **`file_io_tools`:** Read from and write to the `REPO_DIR` workspace.
    *   **`shell_tools`:** Execute shell commands (e.g., `npm install`, `npx create-next-app`, `ls -R`) within the workspace.
    *   **`patch_tools`:** Apply `diff` patches to files, enabling precise code modifications.
    *   **`lsp_tools`:** Interact with the Language Server Protocol (LSP) for code intelligence (e.g., getting definitions, hover information).
    *   **`diagnostics_tools`:** Fetch diagnostics (errors, warnings) from the LSP.
    *   **`vector_store_tools`:** Perform semantic search over the codebase for context retrieval.

### 3.5. LSP Manager

*   **Technology:** `pygls`, Python
*   **Responsibilities:**
    *   Manages the lifecycle of Language Server Protocol instances (e.g., `typescript-language-server`).
    *   Maintains a registry of LSP instances, keyed by workspace path, to handle multiple projects or subdirectories.
    *   Provides a clean, asynchronous interface for the LSP tools to send requests (e.g., `textDocument/definition`) and receive responses.
    *   Caches diagnostics reported by the language server.

### 3.6. Live Preview (WebContainer)

*   **Technology:** StackBlitz WebContainers
*   **Responsibilities:**
    *   Runs a full, in-browser Node.js development server.
    *   Maintains a virtual file system that is kept in sync with the agent's `REPO_DIR` workspace via messages from the UI.
    *   Executes commands like `npm install` and `npm run dev` within the container.
    *   Renders the running Next.js application in an iframe, providing an instant, interactive preview with Hot Module Replacement (HMR).

---

## 4. Data Flow & Communication

1.  **User Interaction:** The user sends a prompt through the **UI**.
2.  **Request:** The prompt is sent over a WebSocket to the **FastAPI Gateway**.
3.  **Agent Invocation:** The Gateway invokes the **LangGraph Agent** with the prompt.
4.  **Planning & Execution:** The Agent plans its steps and calls a function from the **Toolbelt**.
5.  **Action:** The tool performs an action, such as writing a file to the **Workspace** or querying the **LSP Manager**.
6.  **Streaming Feedback:** As the agent executes, it streams events (LLM tokens, tool calls, file updates) back through the **Gateway** to the **UI**.
7.  **Preview Update:** When the UI receives a file update event, it updates the file system in the **WebContainer**, which triggers a refresh of the **Live Preview**.
8.  **Iteration:** The user sees the result in the preview and the agent's logs, and provides the next prompt, continuing the cycle.

---

## 5. Document Maintenance

This architecture document should be considered a living document. It must be updated whenever significant changes are made to the core components, their responsibilities, or the communication flow between them. This ensures it remains an accurate and valuable resource for all team members.
