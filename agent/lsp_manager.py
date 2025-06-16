# /agent/lsp_manager.py

import asyncio
import logging
import os
import shutil
from typing import List, Optional, Dict
from pathlib import Path

from pygls.lsp.client import BaseLanguageClient
from pygls.protocol import LanguageServerProtocol
from lsprotocol import types as lsp_types

logger = logging.getLogger(__name__)

class LspManager:
    """Manages a single Language Server Protocol (LSP) client instance for the workspace."""

    def __init__(self, workspace_path: str, server_command: Optional[List[str]] = None):
        self.workspace_path = workspace_path
        self.client = None
        self._process = None
        self._diagnostics = {}

        if server_command is None:
            self.server_command = ['typescript-language-server', '--stdio']
        else:
            self.server_command = server_command

        if not self.server_command or not self.server_command[0]:
            raise ValueError("server_command must be a non-empty list with the executable as the first element.")

        executable_path = shutil.which(self.server_command[0])
        if not executable_path:
            raise FileNotFoundError(
                f"LSP server executable '{self.server_command[0]}' not found in PATH. "
                f"Please ensure it is installed and accessible."
            )
        # Use the absolute path found by shutil.which
        self.server_command[0] = executable_path
        self._diagnostics_lock = asyncio.Lock()
        self._stderr_drain_task: Optional[asyncio.Task] = None
        self._io_task: Optional[asyncio.Task] = None
        self._tsconfig_path: Optional[Path] = None
        self._tsconfig_mtime: Optional[float] = None

    async def start(self):
        """Starts the language server process and initializes the client."""
        if self.client and self.client.is_running:
            logger.info("LSP client is already running.")
            return

        logger.info("Starting typescript-language-server...")
        self._process = await asyncio.create_subprocess_exec(
            *self.server_command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        self.client = BaseLanguageClient(
            name="app-agent-client",
            version="0.1.0",
            protocol_cls=LanguageServerProtocol,
            # The following converters are needed to handle some non-standard responses
            # from the typescript-language-server.
        )

        # Register the diagnostics handler
        @self.client.feature('textDocument/publishDiagnostics')
        async def _publish_diagnostics(params):
            uri = params.uri
            diagnostics = params.diagnostics
            async with self._diagnostics_lock:
                self._diagnostics[uri] = diagnostics
            logger.info(f"Received diagnostics for {uri}: {len(diagnostics)} items")

        # Start the main IO loop for the protocol
        # self.client.protocol is the LanguageServerProtocol instance
        # self._process.stdout is the reader, self._process.stdin is the writer for the server
        await self.client.start_io(self._process.stdout, self._process.stdin)

        # Initialize the server
        root_uri = f'file://{self.workspace_path}'
        params = lsp_types.InitializeParams(
            process_id=self._process.pid,
            root_uri=root_uri,
            capabilities=lsp_types.ClientCapabilities()  # Basic capabilities
        )
        await self.client.initialize(params)
        logger.info(f"LSP client initialized for workspace: {root_uri}")

        if self._process.stderr:
            self._stderr_drain_task = asyncio.create_task(self._drain_stream(self._process.stderr, logging.ERROR))
        else:
            logger.warning("LSP server process has no stderr stream to drain.")

        self._update_tsconfig_mtime() # Initial check and store of tsconfig mtime

    async def stop(self):
        """Stops the language server client and process."""
        # No separate IO task after start_io; ensure client.stop() later
        if False and self._io_task:
            logger.info("Cancelling LSP IO task...")
            self._io_task.cancel()
            try:
                await self._io_task
            except asyncio.CancelledError:
                logger.info("LSP IO task cancelled successfully.")
            except Exception as e:
                logger.error(f"Error during LSP IO task cancellation: {e}")
        self._io_task = None  # kept for backward compatibility

        if self._stderr_drain_task and not self._stderr_drain_task.done():
            logger.info("Cancelling LSP stderr drain task...")
            self._stderr_drain_task.cancel()
            try:
                await self._stderr_drain_task
            except asyncio.CancelledError:
                logger.info("LSP stderr drain task cancelled successfully.")
            except Exception as e:
                logger.error(f"Error during LSP stderr drain task cancellation: {e}")
        self._stderr_drain_task = None

        if self.client and self.client.is_running:
            logger.info("Stopping LSP client (sending shutdown/exit)...")
            try:
                if self.client.protocol.initialized:
                    await self.client.shutdown()
                await self.client.exit()
            except Exception as e:
                logger.error(f"Error during LSP client shutdown/exit: {e}")
            await self.client.stop()
        self.client = None # Clear the client

        if self._process and self._process.returncode is None:
            logger.info("Terminating LSP server process...")
            logger.info(f"Attempting to terminate LSP server process (PID: {self._process.pid})...")
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
                logger.info(f"LSP server process (PID: {self._process.pid}) terminated gracefully.")
            except asyncio.TimeoutError:
                logger.warning(
                    f"LSP server process (PID: {self._process.pid}) did not terminate within 5 seconds. Attempting to kill..."
                )
                self._process.kill()
                try:
                    await asyncio.wait_for(self._process.wait(), timeout=2.0) # Wait for kill to complete
                    logger.info(f"LSP server process (PID: {self._process.pid}) killed successfully.")
                except asyncio.TimeoutError:
                    logger.error(f"LSP server process (PID: {self._process.pid}) did not stop even after kill. It might be orphaned.")
            except Exception as e:
                logger.error(f"Error during LSP server process termination: {e}")
            finally:
                self._process = None
        if self._stderr_drain_task and not self._stderr_drain_task.done():
            self._stderr_drain_task.cancel()
            try:
                await self._stderr_drain_task
            except asyncio.CancelledError:
                logger.info("Stderr drain task cancelled.")
        logger.info("LSP client and server stopped.")

    async def restart(self):
        """Restarts the language server."""
        logger.info("Restarting LSP server...")
        await self.stop()
        await self.start()

    async def get_definition(self, file_path: str, line: int, character: int):
        """Requests a go-to-definition for a symbol at a given location."""
        if not self.client or not self.client.is_running:
            raise ConnectionError("LSP client is not running.")

        uri = f'file://{file_path}'
        params = {'textDocument': {'uri': uri}, 'position': {'line': line, 'character': character}}
        return await self.client.lsp.send_request('textDocument/definition', params)

    async def get_hover(self, file_path: str, line: int, character: int):
        """Requests hover information for a symbol at a given location."""
        if not self.client or not self.client.is_running:
            raise ConnectionError("LSP client is not running.")

        uri = f'file://{file_path}'
        params = {'textDocument': {'uri': uri}, 'position': {'line': line, 'character': character}}
        return await self.client.lsp.send_request('textDocument/hover', params)

    async def get_diagnostics(self, file_path: str) -> list:
        """Retrieves diagnostic information (errors, warnings) for a file."""
        uri = f'file://{file_path}'
        async with self._diagnostics_lock:
            return self._diagnostics.get(uri, [])

    async def get_all_diagnostics(self) -> list:
        """Retrieves all diagnostic information stored in the manager, flattened into a single list."""
        all_diags = []
        async with self._diagnostics_lock:
            for diags in self._diagnostics.values():
                all_diags.extend(diags)
        return all_diags

    def _update_tsconfig_mtime(self):
        """Updates the stored modification time of tsconfig.json if it exists."""
        if not self._tsconfig_path:
            self._tsconfig_path = Path(self.workspace_path) / "tsconfig.json"
        
        if self._tsconfig_path.exists() and self._tsconfig_path.is_file():
            try:
                self._tsconfig_mtime = self._tsconfig_path.stat().st_mtime
                logger.info(f"Updated tsconfig.json mtime: {self._tsconfig_mtime} for {self._tsconfig_path}")
            except OSError as e:
                logger.warning(f"Could not stat {self._tsconfig_path}: {e}")
                self._tsconfig_mtime = None # Reset if error
        else:
            self._tsconfig_mtime = None # tsconfig.json does not exist
            logger.info(f"No tsconfig.json found at {self._tsconfig_path}, mtime check skipped.")

    async def check_and_restart_on_tsconfig_update(self):
        """Checks if tsconfig.json has been modified and restarts the LSP server if so."""
        if not self._tsconfig_path: # Ensure path is initialized
            self._tsconfig_path = Path(self.workspace_path) / "tsconfig.json"

        if not self._tsconfig_path.exists() or not self._tsconfig_path.is_file():
            logger.debug(f"No tsconfig.json found at {self._tsconfig_path}. No restart needed based on it.")
            # If tsconfig was present and now deleted, we might want to restart or clear mtime.
            # For now, if it's gone, we consider the 'no tsconfig' state as current.
            if self._tsconfig_mtime is not None:
                logger.info(f"tsconfig.json at {self._tsconfig_path} was present but now deleted. Clearing stored mtime.")
                self._tsconfig_mtime = None
            return

        try:
            current_mtime = self._tsconfig_path.stat().st_mtime
        except OSError as e:
            logger.warning(f"Could not stat {self._tsconfig_path} for mtime check: {e}. Skipping restart check.")
            return

        if self._tsconfig_mtime is None:
            # This is the first time we're seeing tsconfig.json (e.g., it was just created)
            # or it's the first check after manager start/restart.
            logger.info(f"Initial mtime for {self._tsconfig_path}: {current_mtime}. Storing it.")
            self._tsconfig_mtime = current_mtime
            # Potentially restart here if it was just created and we want the LSP to pick it up immediately.
            # For now, we'll assume the next explicit call or a natural restart will handle it.
            # Or, if we want to be proactive:
            # logger.info(f"tsconfig.json appeared or first check. Restarting LSP to ensure it's loaded.")
            # await self.restart() # This would call _update_tsconfig_mtime again.
            return

        if current_mtime != self._tsconfig_mtime:
            logger.info(f"Detected change in {self._tsconfig_path} (old_mtime: {self._tsconfig_mtime}, new_mtime: {current_mtime}). Restarting LSP server.")
            await self.restart() # self.restart() will call _update_tsconfig_mtime() after successful start
        else:
            logger.debug(f"{self._tsconfig_path} mtime ({current_mtime}) unchanged. No restart needed.")

    async def _drain_stream(self, stream: asyncio.StreamReader, log_level: int):
        """Reads lines from a stream and logs them."""
        while True:
            try:
                line = await stream.readline()
                if not line:
                    logger.info(f"Stream {stream} closed.")
                    break
                logger.log(log_level, f"LSP Server STDERR: {line.decode().strip()}")
            except Exception as e:
                logger.error(f"Error draining stream {stream}: {e}")
                break

# Registry for LspManager instances, keyed by workspace path
_lsp_managers_registry: Dict[Path, LspManager] = {}
_registry_lock = asyncio.Lock()

async def get_lsp_manager(workspace_path: str, server_command: Optional[List[str]] = None) -> LspManager:
    """Factory function to get an LspManager instance for a given workspace path."""
    resolved_workspace_path = Path(workspace_path).resolve()

    async with _registry_lock:
        if resolved_workspace_path not in _lsp_managers_registry:
            logger.info(f"Creating new LspManager for workspace: {resolved_workspace_path}")
            manager = LspManager(str(resolved_workspace_path), server_command=server_command)
            # We might want to defer the start() call to the consumer
            # await manager.start() # Or not start it here automatically
            _lsp_managers_registry[resolved_workspace_path] = manager
        else:
            logger.info(f"Reusing existing LspManager for workspace: {resolved_workspace_path}")
        return _lsp_managers_registry[resolved_workspace_path]
