# App-Agent

App-Agent is an agent-centric, LLM-powered codebase designed for automated code modification, diagnostics, and self-healing workflows. It leverages the MCP (Machine Control Protocol) ecosystem, FastMCP in-memory servers for robust tool testing, and a modular agent architecture to support advanced developer-assist and code-repair scenarios.

## Features

- **Agent-Centric Architecture**: Central planner LLM coordinates tool usage for code analysis, modification, and diagnostics.
- **Self-Healing Workflows**: Automated detection and repair of code issues, including TypeScript and Python errors.
- **MCP Tool Integration**: Tools for file I/O, shell execution, diagnostics, and patching, all tested via in-memory FastMCP servers.
- **LSP (Language Server Protocol) Integration**: Supports diagnostics and code actions via language servers.
- **Extensive Test Suite**: Tests for agent flows, tool behaviors, and integration scenarios using modern pytest and FastMCP fixtures.
- **Modern Python Stack**: Async-first design, pydantic models, and clear separation of concerns.

## Directory Structure

```
agent/                  # Core agent logic, graph, state, and LSP manager
common/                 # Shared utilities (config, MCP session helpers)
tools/                  # MCP tool implementations (file I/O, shell, patch, diagnostics)
tests/                  # Unit and integration tests (with FastMCP fixtures)
project-docs/           # Architecture, design, and implementation plans
```

## Quick Start

### Prerequisites

- Python 3.10+
- Node.js (for TypeScript integration tests)
- (Recommended) Create a virtual environment

### Installation

```bash
pip install -r requirements.txt
```

### Running Tests

```bash
pytest
```

All tool tests use in-memory FastMCP servers for speed and reliability.

### Example: Running the Agent

The agent is modular and typically invoked via a script or API. See `agent/agent_graph.py` for entry points and orchestration logic.

## Key Components

- **agent/agent_graph.py**: Main orchestration logic for agent flows.
- **agent/lsp_manager.py**: Manages language server processes and diagnostics.
- **tools/**: Implements MCP tools (file I/O, patching, shell, diagnostics).
- **tests/tools/**: Test suites for each tool, using FastMCP in-memory servers.
- **tests/integration/**: End-to-end tests for self-healing and multi-tool flows.
- **project-docs/architecture.md**: Up-to-date system architecture overview.
- **project-docs/implementation_plan.md**: Step-by-step implementation checklist.

## Development Workflow

- Follow the implementation plan in `project-docs/implementation_plan.md`.
- All new tool tests should use FastMCP in-memory servers (see `conftest.py` for fixtures).
- Keep `architecture.md` and `design_doc.md` up to date with major changes.

## Contributing

1. Fork the repo and create a feature branch.
2. Write tests for new features or bug fixes.
3. Run the full test suite before submitting a PR.
4. Update documentation as needed.

## References

- [FastMCP Documentation](https://gofastmcp.com)
- [MCP Protocol Spec](https://github.com/mcp-protocol/spec)
- See `project-docs/` for internal design docs.
