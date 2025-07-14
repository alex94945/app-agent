import asyncio
from uuid import UUID
import atexit
import logging
import os
import psutil
import ptyprocess
from typing import Dict, Optional, Callable, Awaitable, Any

# Define a type for the PTY callbacks for clarity
PTYCallbacks = Dict[str, Callable[[UUID, Any], Awaitable[None]]]
from uuid import uuid4, UUID

logger = logging.getLogger(__name__)

class PTYManager:
    """Manages pseudo-terminal (PTY) processes for long-running tasks."""

    def __init__(self):
        self._tasks: Dict[UUID, asyncio.Task] = {}
        self._completion_events: Dict[UUID, asyncio.Event] = {}
        self._procs: Dict[UUID, ptyprocess.PtyProcess] = {}
        self._callbacks: Optional[PTYCallbacks] = None
        atexit.register(self._cleanup_on_exit)

    def set_callbacks(self, callbacks: PTYCallbacks):
        """Sets the callbacks for the current session."""
        logger.info("Setting PTY callbacks for the current session.")
        self._callbacks = callbacks

    def get_callbacks(self) -> Optional[PTYCallbacks]:
        """Gets the callbacks for the current session."""
        return self._callbacks

    def clear_callbacks(self):
        """Clears the callbacks at the end of a session."""
        logger.info("Clearing PTY callbacks.")
        self._callbacks = None

    def _cleanup_on_exit(self):
        """Ensure all child processes are terminated when the application exits."""
        logger.info("Cleaning up PTY processes on exit...")
        for task_id, proc in self._procs.items():
            if proc.isalive():
                logger.warning(f"Terminating lingering PTY process for task {task_id} (PID: {proc.pid})")
                try:
                    parent = psutil.Process(proc.pid)
                    for child in parent.children(recursive=True):
                        child.terminate()
                    parent.terminate()
                    parent.wait(timeout=5)
                except psutil.NoSuchProcess:
                    pass # Process already finished
                except psutil.TimeoutExpired:
                    logger.error(f"Failed to terminate process {proc.pid} gracefully. Killing.")
                    parent.kill()

    async def spawn(
        self,
        command: list[str],
        cwd: str,
        task_name: str,
    ) -> UUID:
        """Spawns a new command in a PTY and starts streaming its output."""
        task_id = uuid4()
        self._completion_events[task_id] = asyncio.Event()

        try:
            proc = ptyprocess.PtyProcess.spawn(command, cwd=cwd, echo=False)
            self._procs[task_id] = proc
            logger.info(f"[PTYManager] Spawned PTY for task {task_id} (PID: {proc.pid}) with command: {' '.join(command)}")
            callbacks = self.get_callbacks()
            if not callbacks or not all(k in callbacks for k in ["on_started", "on_output", "on_complete"]):
                raise ValueError("PTY mode requires on_started, on_output, and on_complete callbacks to be set.")

            on_started = callbacks["on_started"]
            on_output = callbacks["on_output"]
            on_complete = callbacks["on_complete"]

            # Immediately call the on_started callback
            await on_started(task_id, task_name)
        except Exception as e:
            logger.error(f"[PTYManager] Failed to spawn PTY for command '{' '.join(command)}': {e}")
            await on_started(task_id, task_name) # Still inform the UI that the task was attempted
            await on_output(task_id, f"Error spawning process: {e}\n")
            await on_complete(task_id, -1) # Use -1 to indicate spawn failure
            self._completion_events[task_id].set()
            return task_id

        async def _stream_output():
            logger.info(f"[PTYManager] [Task {task_id}] Starting PTY output stream loop (PID: {proc.pid})")
            exit_code = -1 # Default to error
            try:
                while proc.isalive():
                    try:
                        output = await asyncio.to_thread(proc.read, 1024)
                        if output:
                            decoded = output.decode('utf-8', errors='replace')
                            logger.debug(f"[PTYManager] [Task {task_id}] PTY Output: {decoded.strip()}")
                            await on_output(task_id, decoded)
                    except EOFError:
                        logger.info(f"[PTYManager] [Task {task_id}] EOF reached on PTY (PID: {proc.pid})")
                        break
                    except Exception as e:
                        logger.error(f"[PTYManager] [Task {task_id}] Error reading from PTY: {e}")
                        break
                # Wait for the process to terminate and get the exit code
                await asyncio.to_thread(proc.wait)
                exit_code = proc.exitstatus if proc.exitstatus is not None else proc.signalstatus
            finally:
                logger.info(f"[PTYManager] [Task {task_id}] PTY stream finished. Exit code: {exit_code}")
                await on_complete(task_id, exit_code)
                self._completion_events[task_id].set()
                self._tasks.pop(task_id, None)
                self._procs.pop(task_id, None)

        self._tasks[task_id] = asyncio.create_task(_stream_output())
        return task_id

    async def wait_for_completion(self, task_id: UUID):
        """Waits until the specified PTY task has completed."""
        if task_id in self._completion_events:
            await self._completion_events[task_id].wait()
            self._completion_events.pop(task_id, None)

# Singleton instance
_manager: Optional[PTYManager] = None

def get_pty_manager() -> PTYManager:
    """Returns the singleton PTYManager instance."""
    global _manager
    if _manager is None:
        _manager = PTYManager()
    return _manager
