import asyncio
import logging
import shutil
from typing import List, Optional, Dict, Any
from pathlib import Path

from pygls.lsp.client import LanguageClient
from pygls.protocol import LanguageServerProtocol
from pygls import uris
from lsprotocol import types as lsp_types

logger = logging.getLogger(__name__)


def _norm(p: str | Path) -> str:
    """Return a canonical absolute path with symlinks resolved."""
    return str(Path(p).resolve())


class LspManager:
    """Manages a single Language Server Protocol (LSP) client instance for the workspace."""

    def __init__(self, workspace_path: str, server_command: Optional[List[str]] = None):
        self.workspace_path = workspace_path
        self._diagnostics: Dict[str, List[lsp_types.Diagnostic]] = {}
        self._diagnostics_lock = asyncio.Lock()
        self._diagnostics_events: Dict[str, asyncio.Event] = {}
        self._diagnostics_cache: Dict[str, List[lsp_types.Diagnostic]] = {}
        self._stderr_drain_task: Optional[asyncio.Task] = None
        self._tsconfig_path: Path = Path(self.workspace_path) / "tsconfig.json"
        self._tsconfig_mtime: Optional[float] = None

        # Respect server_command argument, default if None
        self.server_command = server_command or [
            "typescript-language-server",
            "--stdio",
        ]
        logger.info(f"Using server_command: {' '.join(self.server_command)}")

        if not self.server_command or not self.server_command[0]:
            raise ValueError(
                "server_command must be a non-empty list with the executable as the first element."
            )

        executable_path = shutil.which(self.server_command[0])
        if not executable_path:
            raise FileNotFoundError(
                f"LSP server executable '{self.server_command[0]}' not found in PATH. "
                f"Please ensure it is installed and accessible."
            )
        self.server_command[0] = executable_path  # Use absolute path

        self.client = LanguageClient(
            name="CascadeLspClient",
            version="0.1",
            protocol_cls=LanguageServerProtocol,  # Use imported LanguageServerProtocol from pygls.protocol
        )

        # Register the diagnostics handler once during initialization
        @self.client.feature(lsp_types.TEXT_DOCUMENT_PUBLISH_DIAGNOSTICS)
        async def _publish_diagnostics(params: lsp_types.PublishDiagnosticsParams):
            uri = params.uri
            fs_key = _norm(uris.to_fs_path(uri))
            logger.debug(
                f"Storing diags for URI {uri} under normalized path key: {fs_key} and URI key: {uri}"
            )
            raw_diagnostics = params.diagnostics
            logger.info(
                f"_diagnostics_handler: Received diagnostics for URI '{uri}', version {params.version}, {len(params.diagnostics)} items: {params.diagnostics}"
            )
            # Filter to ensure only actual Diagnostic objects are stored
            valid_diagnostics = [
                d for d in raw_diagnostics if isinstance(d, lsp_types.Diagnostic)
            ]
            if len(valid_diagnostics) < len(raw_diagnostics):
                invalid_items_count = len(raw_diagnostics) - len(valid_diagnostics)
                logger.warning(
                    f"Filtered out {invalid_items_count} non-Diagnostic items from "
                    f"textDocument/publishDiagnostics for {uri}. Original count: {len(raw_diagnostics)}"
                )
            async with self._diagnostics_lock:
                self._diagnostics[fs_key] = (
                    valid_diagnostics  # Store by normalized path
                )
                self._diagnostics[uri] = valid_diagnostics  # Also store by original URI
                self._diagnostics_cache[uri] = (
                    params.diagnostics
                )  # This cache is keyed by URI
            logger.info(
                f"Received and stored {len(valid_diagnostics)} valid diagnostics for fs_key: {fs_key}, uri: {uri}"
            )

            # Notify waiters that diagnostics for this file have arrived
            if uri in self._diagnostics_events:  # Use uri
                logger.info(f"_diagnostics_handler: Setting event for URI {uri}")
                self._diagnostics_events[uri].set()

        # Removed duplicate _tsconfig_mtime declaration

    async def start(self):
        """Starts the language server process and initializes the client."""
        if not self.client.stopped:
            logger.info("LSP client is already running.")
            return

        logger.info(
            f"Starting LSP server with command: {' '.join(self.server_command)}..."
        )
        try:
            workspace_uri = uris.from_fs_path(self.workspace_path)
            workspace_folders_list = [
                lsp_types.WorkspaceFolder(
                    uri=workspace_uri, name=Path(self.workspace_path).name
                )
            ]
            initialization_opts = {
                "tsserver": {
                    "logDirectory": "/tmp",  # Server will create tsserver.<PID>.log here
                    "logVerbosity": "verbose",
                }
            }

            logger.info(
                f"Attempting to start LSP server with command: {' '.join(self.server_command)}, cwd: {self.workspace_path}, root_uri: {workspace_uri}, init_options: {initialization_opts}"
            )
            # self.server_command[0] is the executable, self.server_command[1:] are the args.
            await self.client.start(
                self.server_command[0],
                *self.server_command[1:],
                cwd=str(self.workspace_path),  # Ensure cwd is a string
                root_uri=workspace_uri,
                workspace_folders=workspace_folders_list,
                initialization_options=initialization_opts,
            )
            logger.info(
                "LSP client start command issued. Waiting for initialization..."
            )
            await self.client.initialized()  # Wait for server to confirm initialization
            logger.info(
                f"LSP client started and initialized for workspace: {workspace_uri}"
            )

            if self.client.process and self.client.process.stderr:
                logger.info("Starting stderr drain task for LSP server process.")
                self._stderr_drain_task = asyncio.create_task(
                    self._drain_stderr(),
                    name=f"lsp_stderr_drain_{Path(self.workspace_path).name}",
                )
            else:
                logger.warning(
                    "LSP server process or stderr stream not available after start, cannot drain stderr."
                )

            self._update_tsconfig_mtime()  # Initial check and store of tsconfig mtime

        except Exception as e:
            logger.error(f"Failed to start LSP client: {e}")
            # Re-raise to ensure the caller knows the start failed.
            raise

    async def stop(self):
        """Stops the language server client."""
        if not (self.client and not self.client.stopped):
            logger.info("LSP client is not running or not initialized.")
            return

        if self._stderr_drain_task and not self._stderr_drain_task.done():
            logger.info("Cancelling LSP stderr drain task.")
            self._stderr_drain_task.cancel()
            try:
                await self._stderr_drain_task
            except asyncio.CancelledError:
                logger.info("LSP stderr drain task successfully cancelled during stop.")
            except Exception as e:
                logger.error(
                    f"Exception while awaiting cancelled stderr drain task during stop: {e}",
                    exc_info=True,
                )
            self._stderr_drain_task = None

        if self.client and not self.client.stopped:
            logger.info("Stopping LSP client...")
            try:
                await self.client.stop()
                logger.info("LSP client stopped.")
            except Exception as e:
                logger.error(f"Error stopping LSP client: {e}", exc_info=True)
        else:
            logger.info(
                "LSP client already stopped or not initialized during LspManager stop."
            )
        logger.info("LSP Manager stopped.")

    async def restart(self):
        """Restarts the language server."""
        logger.info("Restarting LSP server...")
        await self.stop()
        await self.start()

    async def get_definition(self, file_path: str, line: int, character: int) -> Any:
        """Requests a go-to-definition for a symbol at a given location."""
        if not self.client or self.client.stopped:
            raise ConnectionError("LSP client is not running.")

        uri = uris.from_fs_path(file_path)
        params = lsp_types.DefinitionParams(
            text_document=lsp_types.TextDocumentIdentifier(uri=uri),
            position=lsp_types.Position(line=line, character=character),
        )
        return await self.client.lsp.send_request(
            lsp_types.TEXT_DOCUMENT_DEFINITION, params
        )

    async def get_hover(self, file_path: str, line: int, character: int) -> Any:
        """Requests hover information for a symbol at a given location."""
        if not self.client or self.client.stopped:
            raise ConnectionError("LSP client is not running.")

        uri = uris.from_fs_path(file_path)
        params = lsp_types.HoverParams(
            text_document=lsp_types.TextDocumentIdentifier(uri=uri),
            position=lsp_types.Position(line=line, character=character),
        )
        return await self.client.lsp.send_request(lsp_types.TEXT_DOCUMENT_HOVER, params)

    async def get_cached_diagnostics(
        self, file_path: str
    ) -> list[lsp_types.Diagnostic]:
        uri = uris.from_fs_path(_norm(file_path))  # Use _norm for consistency
        diagnostics = self._diagnostics_cache.get(uri, [])
        logger.info(
            f"get_cached_diagnostics: Retrieving for URI '{uri}' (file: {file_path}). Found {len(diagnostics)} diagnostics: {diagnostics}"
        )
        return diagnostics

    async def get_diagnostics(self, file_path: str) -> list:
        """Retrieves diagnostic information (errors, warnings) for a file."""
        fs_key = _norm(file_path)
        uri_key = uris.from_fs_path(
            fs_key
        )  # Use normalized path to create the URI key for lookup
        logger.debug(
            f"Looking up diagnostics for original path {file_path} using normalized fs_key: {fs_key} and uri_key: {uri_key}"
        )
        async with self._diagnostics_lock:
            # Try normalized path first, then URI, then default to empty list
            raw_diags = (
                self._diagnostics.get(fs_key) or self._diagnostics.get(uri_key) or []
            )
            valid_diags = [d for d in raw_diags if isinstance(d, lsp_types.Diagnostic)]
            if (
                len(valid_diags) < len(raw_diags) and raw_diags
            ):  # only warn if raw_diags was not empty
                logger.warning(
                    f"Filtered out non-Diagnostic items from get_diagnostics for {file_path}. Original count: {len(raw_diags)}"
                )
            logger.debug(
                f"Retrieved {len(valid_diags)} diagnostics for {file_path} (keys: {fs_key}, {uri_key}): {valid_diags}"
            )
            return valid_diags

    async def get_all_diagnostics(self) -> list:
        """Retrieves all diagnostic information stored in the manager, flattened into a single list."""
        all_diags = []
        async with self._diagnostics_lock:
            for raw_diags_list in self._diagnostics.values():
                # Ensure only Diagnostic objects are added
                valid_diags_list = [
                    d for d in raw_diags_list if isinstance(d, lsp_types.Diagnostic)
                ]
                if len(valid_diags_list) < len(raw_diags_list):
                    logger.warning(
                        f"Filtered out non-Diagnostic items during get_all_diagnostics aggregation. Original count for list: {len(raw_diags_list)}"
                    )
                all_diags.extend(valid_diags_list)
        return all_diags

    async def wait_for_diagnostics(self, file_path: str, timeout: float = 5.0) -> None:
        uri = uris.from_fs_path(_norm(file_path))  # Use _norm for consistency
        logger.info(
            f"wait_for_diagnostics: Waiting for diagnostics for URI '{uri}' (file: {file_path}) with timeout {timeout}s"
        )
        """Waits for diagnostics to be published for a specific file."""
        # fs_path_key = str(Path(file_path).resolve()) # Normalize input path. URI is used for events.
        event = self._diagnostics_events.setdefault(uri, asyncio.Event())
        # Clear the event first, in case it was set by a previous, stale diagnostic notification
        event.clear()

        try:
            # logger.info(f"Waiting up to {timeout}s for diagnostics for {fs_path_key}...") # Already logged with URI above
            await asyncio.wait_for(event.wait(), timeout=timeout)
            logger.info(f"wait_for_diagnostics: Event received for {uri}")
            logger.info(
                f"wait_for_diagnostics: Current diagnostics cache for {uri}: {self._diagnostics_cache.get(uri)}"
            )
        except asyncio.TimeoutError:
            logger.warning(
                f"wait_for_diagnostics: Timeout waiting for diagnostics for {uri}. Cache content: {self._diagnostics_cache.get(uri)}"
            )

    async def _drain_stderr(self):
        """Drain and log the LSP server's stderr stream."""
        process = self.client.process  # Use public attribute
        if not (process and process.stderr):
            logger.warning(
                f"_drain_stderr: LSP server process or stderr stream not available for {self.workspace_path}."
            )
            return

        logger.info(f"Starting LSP stderr drain task for {self.workspace_path}.")
        try:
            while True:
                # Check if the process is still running before attempting to read
                if process.returncode is not None:
                    logger.info(
                        f"LSP server process for {self.workspace_path} exited with code {process.returncode}. Stopping stderr drain."
                    )
                    break

                try:
                    line = await asyncio.wait_for(
                        process.stderr.readline(), timeout=1.0
                    )
                except asyncio.TimeoutError:
                    # Timeout waiting for line, check process status and continue if running
                    if process.returncode is None:
                        continue  # Still running, try reading again
                    else:
                        logger.info(
                            f"LSP server process for {self.workspace_path} exited (during readline timeout) with code {process.returncode}. Stopping stderr drain."
                        )
                        break  # Process exited

                if line:
                    # Using DEBUG for potentially verbose stderr, ERROR was too high
                    logger.debug(
                        f"LSP Server STDERR ({Path(self.workspace_path).name}): {line.decode().strip()}"
                    )
                else:
                    # End of stream (stderr closed by server or process terminated)
                    if process.returncode is None:
                        # Stream closed but process might still be running (unlikely for stderr)
                        logger.info(
                            f"LSP server stderr stream for {self.workspace_path} ended (EOF), but process still running. Checking again..."
                        )
                        await asyncio.sleep(
                            0.1
                        )  # Brief pause before re-checking process status
                        if process.returncode is None:
                            logger.warning(
                                f"LSP server stderr for {self.workspace_path} EOF but process alive. Stopping drain."
                            )
                        else:
                            logger.info(
                                f"LSP server process for {self.workspace_path} exited (after EOF) with code {process.returncode}. Stopping stderr drain."
                            )
                        break
                    else:
                        logger.info(
                            f"LSP server process for {self.workspace_path} exited. Stopping stderr drain (EOF)."
                        )
                        break
        except asyncio.CancelledError:
            logger.info(f"LSP stderr drain task for {self.workspace_path} cancelled.")
            # Do not re-raise CancelledError, allow task to terminate gracefully
        except Exception as e:
            logger.error(
                f"Exception in LSP stderr drain task for {self.workspace_path}: {e}",
                exc_info=True,
            )
        finally:
            logger.info(f"LSP stderr drain task finished for {self.workspace_path}.")

    async def open_document(self, file_path: str) -> None:
        logger.info(f"open_document: Called for file_path: {file_path}")
        """Sends a textDocument/didOpen notification to the server."""
        if not self.client or self.client.stopped:
            logger.warning("Cannot open document, client is not running.")
            return

        uri = uris.from_fs_path(
            str(Path(file_path).resolve())
        )  # Convert normalized fs path to URI
        try:
            # Use utf-8 encoding for safety
            with open(file_path, "r", encoding="utf-8") as f:
                text = f.read()
        except Exception as e:
            logger.error(f"Failed to read file {file_path} for didOpen: {e}")
            return

        # Simple mapping for languageId
        language_id = "typescript"
        if file_path.endswith(".tsx"):
            language_id = "typescriptreact"
        elif file_path.endswith(".js"):
            language_id = "javascript"
        elif file_path.endswith(".jsx"):
            language_id = "javascriptreact"

        params = lsp_types.DidOpenTextDocumentParams(
            text_document=lsp_types.TextDocumentItem(
                uri=uri,
                language_id=language_id,
                version=1,  # Initial version
                text=text,
            )
        )
        self.client.text_document_did_open(params)
        logger.info(f"Sent textDocument/didOpen for {uri}")

    def _update_tsconfig_mtime(self):
        """Updates the stored modification time of tsconfig.json if it exists."""
        if not self._tsconfig_path:
            self._tsconfig_path = Path(self.workspace_path) / "tsconfig.json"

        if self._tsconfig_path.exists() and self._tsconfig_path.is_file():
            try:
                self._tsconfig_mtime = self._tsconfig_path.stat().st_mtime
                logger.info(
                    f"Updated tsconfig.json mtime: {self._tsconfig_mtime} for {self._tsconfig_path}"
                )
            except OSError as e:
                logger.warning(f"Could not stat {self._tsconfig_path}: {e}")
                self._tsconfig_mtime = None  # Reset if error
        else:
            self._tsconfig_mtime = None  # tsconfig.json does not exist
            logger.info(
                f"No tsconfig.json found at {self._tsconfig_path}, mtime check skipped."
            )

    async def check_and_restart_on_tsconfig_update(self):
        """Checks if tsconfig.json has been modified and restarts the LSP server if so."""
        if not self._tsconfig_path:  # Ensure path is initialized
            self._tsconfig_path = Path(self.workspace_path) / "tsconfig.json"

        if not self._tsconfig_path.exists() or not self._tsconfig_path.is_file():
            logger.debug(
                f"No tsconfig.json found at {self._tsconfig_path}. No restart needed based on it."
            )
            # If tsconfig was present and now deleted, we might want to restart or clear mtime.
            # For now, if it's gone, we consider the 'no tsconfig' state as current.
            if self._tsconfig_mtime is not None:
                logger.info(
                    f"tsconfig.json at {self._tsconfig_path} was present but now deleted. Clearing stored mtime."
                )
                self._tsconfig_mtime = None
            return

        try:
            current_mtime = self._tsconfig_path.stat().st_mtime
        except OSError as e:
            logger.warning(
                f"Could not stat {self._tsconfig_path} for mtime check: {e}. Skipping restart check."
            )
            return

        if self._tsconfig_mtime is None:
            # This is the first time we're seeing tsconfig.json (e.g., it was just created)
            # or it's the first check after manager start/restart.
            logger.info(
                f"Initial mtime for {self._tsconfig_path}: {current_mtime}. Storing it."
            )
            self._tsconfig_mtime = current_mtime
            # Potentially restart here if it was just created and we want the LSP to pick it up immediately.
            # For now, we'll assume the next explicit call or a natural restart will handle it.
            # Or, if we want to be proactive:
            # logger.info(f"tsconfig.json appeared or first check. Restarting LSP to ensure it's loaded.")
            # await self.restart() # This would call _update_tsconfig_mtime again.
            return

        if current_mtime != self._tsconfig_mtime:
            logger.info(
                f"Detected change in {self._tsconfig_path} (old_mtime: {self._tsconfig_mtime}, new_mtime: {current_mtime}). Restarting LSP server."
            )
            await self.restart()  # self.restart() will call _update_tsconfig_mtime() after successful start
        else:
            logger.debug(
                f"{self._tsconfig_path} mtime ({current_mtime}) unchanged. No restart needed."
            )

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


async def get_lsp_manager(
    workspace_path: str, server_command: Optional[List[str]] = None
) -> LspManager:
    """Factory function to get an LspManager instance for a given workspace path."""
    resolved_workspace_path = Path(workspace_path).resolve()

    async with _registry_lock:
        if resolved_workspace_path not in _lsp_managers_registry:
            logger.info(
                f"Creating new LspManager for workspace: {resolved_workspace_path}"
            )
            manager = LspManager(
                str(resolved_workspace_path), server_command=server_command
            )
            # We might want to defer the start() call to the consumer
            # await manager.start() # Or not start it here automatically
            _lsp_managers_registry[resolved_workspace_path] = manager
        else:
            logger.info(
                f"Reusing existing LspManager for workspace: {resolved_workspace_path}"
            )
        return _lsp_managers_registry[resolved_workspace_path]
