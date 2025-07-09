# Design Doc — PTY‑Streaming for Real‑Time Scaffolding Progress

---

## Executive summary

Moving long‑running scaffold commands (e.g., `npx create-next-app`) into a pseudo‑terminal (PTY) and streaming its output to both the UI and the agent removes race conditions and aligns us with SOTA agentic IDEs. This revision keeps the **Gateway** as a pure message bus and maintains backward compatibility in `run_shell`.

---

## 1 Problem statement

Current background execution lets the agent proceed before scaffolding finishes, causing directory‑not‑found errors and leaving the user blind to progress.

---

## 2 Goals / Non‑goals

| Goal                                                | Non‑goal                              |
| --------------------------------------------------- | ------------------------------------- |
| Live log stream to UI & agent (raw PTY bytes)       | Semantic milestone parsing (post‑MVP) |
| Deterministic agent control via awaitable Task      | Swapping WebSockets for SSE           |
| Zero breaking change for existing `run_shell` calls | Log retention/persistence (post‑MVP)  |

---

## 3 Solution overview

### 3.1 Solution components

* **Agent‑local await**. `tool_executor_step` now awaits an `asyncio.Event` provided by **PTYManager** instead of relying on the Gateway to inject synthetic messages.
* **Backward‑compatible ****************************************`run_shell`****************************************.** `pty` defaults to `False`; when `True` it returns a `TaskHandle` (`{taskId, status: "started"}`).
* **Dedicated PTYManager module** (`agent/pty/manager.py`) owning spawn, stream, Task registry, cleanup.
* **Semantic log parsing deferred**; the MVP streams raw log chunks only.

### 3.2 SOTA reference implementations

Below are illustrative examples of how leading AI‑coding tools surface long‑running task output, reinforcing the choice of PTY streaming:

* **GitHub Copilot Workspace** – integrated terminal view; “terminal assist” fixes errors in real time.
* **Copilot Agent Mode** – watches terminal output and iterates until tests pass.
* **Cursor – YOLO / Auto‑run** – streams each command so agent and user watch simultaneously.
* **Replit Workflows** – runs every task inside a Rust PTY (`pid2`) and exposes a headless terminal shared by humans and AI.
* **Nx task runner** – replays cached terminal output via JSON‑RPC.
* \*\*Aider \*\***`/run`** – injects stdout/stderr directly into the chat for both agent and human consumption.

### 3.3 Sequence diagram

```
Agent Executor ─┬─ run_shell(cmd, pty=True) ──▶ PTYManager
               │                           ├─ spawn PTY, return {taskId}
               │◀──────────────────────────┘
               │
               │  awaits TaskEvent[taskId]
PTYManager ────┤  (set when PTY closes)
               │
               └─ continues next agent step
Gateway ═ message relay only (task_started, task_log, task_finished)
UI      ═ renders log stream & final status
```

---

## 4 Backend design

| Component           | Behaviour                                                                                                                                                                                                                             |                                                                                                                                                          |       |                                                                           |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- | ----- | ------------------------------------------------------------------------- |
| **`run_shell`**     | Signature \`run\_shell(cmd\:str, pty\:bool=False, timeout\:int=300, task\_name\:str                                                                                                                                                   | None=None)`.<br>  *When `pty=False`(default):* same synchronous return as today.<br>  *When`pty=True`:* delegates to PTYManager → returns `TaskHandle\`. |       |                                                                           |
| **PTYManager**      | • Singleton (`get_pty_manager()`).• `spawn(cmd, task_name)` → `taskId`, registers `asyncio.Event`.• Async task reads PTY, emits `task_log` WS msgs, sets cleanup timer.• On EOF, records exitCode, sets Event, emits `task_finished`. |                                                                                                                                                          |       |                                                                           |
| **Task object**     | \`{id, name, state(running                                                                                                                                                                                                            | success                                                                                                                                                  | error | timeout), pid, startedAt, finishedAt, exitCode}\` stored in manager dict. |
| **Process cleanup** | `atexit` hook kills lingering tasks via `psutil`.                                                                                                                                                                                     |                                                                                                                                                          |       |                                                                           |

Dependencies added: `ptyprocess~=0.7`, `psutil~=7.0` (both CPython 3.13 wheels).

---

## 5 Agent flow changes

```python
handle = run_shell(cmd="npx create-next-app", pty=True, task_name="scaffold")
await PTY_MANAGER.wait_for_completion(handle["taskId"])
# proceed with directory exploration
```

No polling, no extra LLM turns.

---

## 6 API / WebSocket events

| Event           | Payload                                |
| --------------- | -------------------------------------- |
| `task_started`  | `{taskId, name, startedAt}`            |
| `task_log`      | `{taskId, chunk}` (UTF‑8 bytes)        |
| `task_finished` | `{taskId, state, exitCode, durationMs` |

---

## 9 Open points&#x20;

* Evaluate `ruspty` vs `ptyprocess` after load testing.
* Define regex milestone catalogue when semantic parsing is prioritized.
* Decide retention policy for build logs (S3 vs Chroma).

---