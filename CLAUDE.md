# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Testing
- `python -m pytest` - Run all tests
- `python -m pytest tests/agent/` - Run agent tests only
- `python -m pytest tests/tools/` - Run tool tests only
- `python -m pytest tests/integration/` - Run integration tests
- `python -m pytest -k "test_name"` - Run specific test
- `python -m pytest --tb=short` - Run tests with shorter traceback

### Code Quality
- `python -m black .` - Format code with Black
- `python -m ruff check .` - Lint code with Ruff
- `python -m ruff check --fix .` - Auto-fix linting issues
- `python -m mypy .` - Run type checking

### Running the Application
- `python -m uvicorn gateway.main:app --reload` - Start FastAPI gateway with auto-reload
- `python -m uvicorn gateway.main:app --host 0.0.0.0 --port 8000` - Start on specific host/port

## Architecture Overview

This is an autonomous AI web application co-pilot built with:

### Core Components
- **FastAPI Gateway** (`gateway/main.py`) - WebSocket-based API gateway that streams events between UI and agent
- **LangGraph Agent** (`agent/agent_graph.py`) - The main AI brain using LangGraph for planning and tool orchestration
- **Toolbelt** (`tools/`) - Collection of specialized tools for file I/O, shell commands, LSP integration, etc.
- **LSP Manager** (`agent/lsp_manager.py`) - Manages Language Server Protocol instances for code intelligence

### Key Patterns
- **Tool-Centric Design**: Agent capabilities are extended through well-defined tools in the `tools/` directory
- **Streaming Architecture**: Real-time communication via WebSockets with structured message types
- **Self-Healing**: Agent interprets diagnostics and build errors to attempt automatic fixes
- **State Management**: LangGraph maintains conversation history and tool results in `AgentState`

### Tool Categories
- **File I/O**: `file_io_mcp_tools.py` - Read/write files in workspace
- **Shell Operations**: `shell_mcp_tools.py` - Execute shell commands via MCP
- **Code Intelligence**: `lsp_tools.py` + `diagnostics_tools.py` - LSP-based code analysis
- **Patch Management**: `patch_tools.py` - Apply git-style diff patches
- **Semantic Search**: `vector_store_tools.py` - Vector-based code search using Chroma

## Configuration

### Environment Setup
- Configuration in `common/config.py` using Pydantic settings
- Workspace directory: `REPO_DIR` (defaults to `workspace_dev/`)
- OpenAI API key required: `OPENAI_API_KEY`
- Optional: `TOGETHER_API_KEY`, `GOOGLE_API_KEY`

### Project Structure
```
agent/          # LangGraph agent implementation
├── agent_graph.py      # Main agent orchestration
├── lsp_manager.py      # LSP lifecycle management
├── state.py           # Agent state definitions
└── prompts/           # Agent prompt templates

tools/          # Tool implementations
├── file_io_mcp_tools.py    # File operations
├── shell_mcp_tools.py      # Shell execution
├── lsp_tools.py           # LSP queries
├── diagnostics_tools.py   # Error diagnostics
├── patch_tools.py         # Git patch application
└── vector_store_tools.py  # Semantic search

common/         # Shared utilities
├── config.py          # Application settings
├── llm.py            # LLM client setup
└── embeddings.py     # Vector embedding utilities

gateway/        # FastAPI web gateway
└── main.py           # WebSocket server

tests/          # Test suite
├── agent/            # Agent tests
├── tools/            # Tool tests
└── integration/      # Integration tests
```

## Development Guidelines

### Testing Strategy
- Unit tests for each tool in `tests/tools/`
- Agent behavior tests in `tests/agent/`
- Integration tests in `tests/integration/`
- LSP integration tests use `pytest-lsp` for client/server testing

### Code Quality Requirements
- All code must pass Black formatting
- Ruff linting must pass (no errors)
- Type hints required for all public functions
- Tests required for new tools and agent functionality

### Adding New Tools
1. Create tool function in appropriate `tools/*.py` file
2. Add to `all_tools_list` in `agent/agent_graph.py`
3. Write comprehensive tests in `tests/tools/`
4. Update tool documentation in docstrings

### Agent Behavior Limits
- Max iterations: 10 (configurable via `MAX_ITERATIONS`)
- Max fix attempts per tool call: 3 (configurable via `MAX_FIX_ATTEMPTS`)
- Agent automatically attempts self-healing when tools fail