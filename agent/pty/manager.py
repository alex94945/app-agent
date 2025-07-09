import asyncio
import atexit
import logging
import os
import psutil
import ptyprocess
from typing import Dict, Optional, Callable, Awaitable
from uuid import uuid4, UUID

logger = logging.getLogger(__name__)

class PTYManager:
    """Manages pseudo-terminal (PTY) processes for long-running tasks."""

    def __init__(self):
        self._tasks: Dict[UUID, asyncio.Task] = {}
        self._completion_events: Dict[UUID, asyncio.Event] = {}
        self._procs: Dict[UUID, ptyprocess.PtyProcess] = {}
        atexit.register(self._cleanup_on_exit)

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
        on_output: Callable[[UUID, str], Awaitable[None]],
        on_complete: Callable[[UUID], Awaitable[None]],
    ) -> UUID:
        """Spawns a new command in a PTY and starts streaming its output."""
        task_id = uuid4()
        self._completion_events[task_id] = asyncio.Event()

        try:
            proc = ptyprocess.PtyProcess.spawn(command, cwd=cwd, echo=False)
            self._procs[task_id] = proc
        except Exception as e:
            logger.error(f"Failed to spawn PTY for command '{' '.join(command)}': {e}")
            # Immediately signal completion on spawn failure
            await on_output(task_id, f"Error spawning process: {e}")
            await on_complete(task_id)
            self._completion_events[task_id].set()
            return task_id

        logger.info(f"Spawned PTY for task {task_id} (PID: {proc.pid}) with command: {' '.join(command)}")

        async def _stream_output():
            try:
                while proc.isalive():
                    try:
                        # Use a small timeout to prevent blocking indefinitely
                        output = await asyncio.to_thread(proc.read, 1024)
                        if output:
                            await on_output(task_id, output.decode('utf-8', errors='replace'))
                    except EOFError:
                        break
                    except Exception as e:
                        logger.error(f"Error reading from PTY for task {task_id}: {e}")
                        break
            finally:
                logger.info(f"PTY stream finished for task {task_id}. Process alive: {proc.isalive()}")
                await on_complete(task_id)
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
