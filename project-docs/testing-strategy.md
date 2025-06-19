# Agent Testing Strategy

**Version:** 1.0
**Date:** June 19, 2025

## 1. Guiding Philosophy

The agent is a complex system combining a non-deterministic LLM, deterministic state logic (LangGraph), and external tools that interact with a filesystem (via MCP). A single testing approach is insufficient. Our strategy is to use two primary types of tests to gain high confidence in the agent's behavior while maintaining a fast and reliable CI/CD pipeline.

1.  **Integration Tests:** Verify the agent's internal logic, state transitions, and tool-handling capabilities in a controlled, deterministic environment.
2.  **Smoke Tests:** Verify the live integration between our prompt engineering and the real LLM for the most critical user flows.

## 2. Test Implementations

### 2.1. Integration Tests (e.g., `tests/integration/test_self_healing.py`)

These are the workhorses of our test suite, designed to be fast, reliable, and hermetic.

*   **Goal:** To prove that if the LLM produces a specific, expected output, our agent's graph logic will correctly route to the right tools, manage state, and handle tool outputs to proceed. **We are testing our code, not the LLM.**

*   **Implementation Strategy:**
    *   **Mock the LLM:** The LLM is replaced with a mock. We use a `side_effect` list to provide a "golden path" of pre-defined `AIMessage` responses. This makes the test deterministic and repeatable.
    *   **Use Real Tools with an In-Memory Backend:** The test invokes the agent's *real* tool functions (`run_shell`, `apply_patch`, etc.). However, these tools are patched to communicate with a fast, in-memory `FastMCP` server (`patch_client` fixture) instead of a real network service. This provides excellent coverage of our tool code without network flakiness.
    *   **Create a Pristine, Hermetic Environment:** Each test run gets a fresh, temporary directory. Crucially, for tests involving Node.js tooling, we programmatically create the project files (`package.json`, etc.) and run `npm install` *inside the test fixture*. This is slow but 100% reliable, as it avoids all pathing and symlink issues caused by copying pre-built `node_modules`.
    *   **Perform Definitive Verification:** The test does not just trust the agent's final message. It concludes by independently running the initial failing command (e.g., `npx eslint ...`) to prove that the agent's fix was effective and the environment is now clean.

### 2.2. E2E Smoke Tests (e.g., `scripts/e2e_smoke.py`)

These are narrow, targeted tests for our most critical, user-facing workflows.

*   **Goal:** To prove that our system prompts and prompt engineering are still effective with the **live, real LLM**. It answers the question: "Given a common user request, does the real AI plan the correct first step?"

*   **Implementation Strategy:**
    *   **Use the Real LLM:** This is the key distinction. The test makes a real network call to the LLM provider (e.g., OpenAI) to get a plan.
    *   **Mock the Tool's *Effect*:** We do not mock the agent's code. We let the agent run its full logic, call the real `run_shell` tool, which then connects to our in-memory MCP server. The mock is at the lowest possible level: the MCP server's implementation of the `shell.run` tool simulates the *side effect* of the slow command (e.g., creating a `package.json` file) and returns a success message.
    *   **Rationale:** This approach keeps the test extremely fast (no real `npx create-next-app`) while still verifying the most important and unpredictable part of the chain: the live LLM's response to our prompt.

## 3. Core Testing Paradigms: A Summary

This table summarizes the best practices we have established. All new integration and smoke tests should adhere to these patterns.

| Paradigm | Purpose & Benefit | Example Implementation |
| :--- | :--- | :--- |
| **Hermetic Project Setup** | Guarantees a clean, isolated, and correct environment for each test run, eliminating flakiness from shared state or broken paths. | The `ts_project_with_error` fixture creates a temp dir and runs `npm install` inside it. |
| **Declarative LLM "Golden Path"** | Makes integration tests deterministic, fast, and focused on our code's logic rather than the LLM's non-determinism. | Using `mock_llm_client.invoke.side_effect = [response1, response2, ...]` in tests. |
| **Real Tools + In-Memory MCP** | Provides high-fidelity testing of our tool code and its interaction with the MCP protocol, without network dependencies. | The `patch_client` fixture from `conftest.py` and patching `open_mcp_session` in tool modules. |
| **Definitive End-to-End Verification** | Provides absolute confidence that the agent's task was successfully completed by checking the final state of the system, not just the agent's belief. | Calling `run_shell` at the end of a test to assert that `npm run build` now passes with exit code 0. |
| **Targeted, Multi-Module Patching** | Ensures mocks are applied correctly regardless of how functions are imported, preventing subtle test failures. | Using `with patch('module1.func'), patch('module2.func'):` to cover all points of use. |
| **Session-Scoped Fixtures** | Improves test suite performance by running expensive, read-only setup operations (like compiling the agent graph) only once per session. | `@pytest.fixture(scope="session")` for the `agent_graph_fixture`. |

By adhering to this strategy, we ensure our test suite remains a powerful asset that enables us to build and refactor with confidence.