# /agent/lsp_manager.py

import asyncio
import logging

from pygls.lsp.client import BaseLanguageClient
from pygls.protocol import LanguageServerProtocol

logger = logging.getLogger(__name__)

class LspManager:
    """Manages a single Language Server Protocol (LSP) client instance for the workspace."""

    def __init__(self, workspace_path: str):
        self.workspace_path = workspace_path
        self.client = None
        self._process = None
        self._diagnostics = {}

    async def start(self):
        """Starts the language server process and initializes the client."""
        if self.client and self.client.is_running:
            logger.info("LSP client is already running.")
            return

        logger.info("Starting typescript-language-server...")
        self._process = await asyncio.create_subprocess_exec(
            'typescript-language-server', '--stdio',
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
        def _publish_diagnostics(params):
            uri = params.uri
            diagnostics = params.diagnostics
            self._diagnostics[uri] = diagnostics
            logger.info(f"Received diagnostics for {uri}: {len(diagnostics)} items")

        await self.client.start(self._process.stdin, self._process.stdout)

        # Initialize the server
        root_uri = f'file://{self.workspace_path}'
        await self.client.initialize({'processId': self._process.pid, 'rootUri': root_uri, 'capabilities': {}})
        logger.info(f"LSP client initialized for workspace: {root_uri}")

    async def stop(self):
        """Stops the language server client and process."""
        if self.client and self.client.is_running:
            logger.info("Stopping LSP client...")
            await self.client.shutdown()
            await self.client.exit()
            self.client = None

        if self._process and self._process.returncode is None:
            logger.info("Terminating LSP server process...")
            self._process.terminate()
            await self._process.wait()
            self._process = None
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
        return self._diagnostics.get(uri, [])

    def get_all_diagnostics(self) -> list:
        """Retrieves all diagnostic information stored in the manager, flattened into a single list."""
        all_diags = []
        for diags in self._diagnostics.values():
            all_diags.extend(diags)
        return all_diags

# Singleton instance to be used by tools
lsp_manager = None

def get_lsp_manager(workspace_path: str) -> LspManager:
    """Factory function to get the singleton LspManager instance."""
    global lsp_manager
    if lsp_manager is None:
        lsp_manager = LspManager(workspace_path)
    return lsp_manager
