# /tests/tools/test_lsp_integration.py

import os
import pytest
import tempfile
from pathlib import Path
import pytest_lsp # Required for the @pytest_lsp.fixture decorator
import asyncio

from lsprotocol import types as lsp_types
from pytest_lsp import LanguageClient, ClientServerConfig, client_capabilities

# Sample TypeScript code with a variable and a type error
TS_CODE_WITH_ERROR = """
const myVariable: string = 123; // Error: Type 'number' is not assignable to type 'string'.
"""

# tsconfig.json to enable strict type checking
TSCONFIG_CONTENT = """
{
  "compilerOptions": {
    "strict": true,
    "target": "ESNext",
    "module": "CommonJS"
  }
}
"""

@pytest.fixture(scope="module")
def workspace_info():
    """Creates a temporary workspace with a tsconfig.json and a sample TS file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        # Create tsconfig.json
        (repo_path / "tsconfig.json").write_text(TSCONFIG_CONTENT)

        # Create the sample TypeScript file
        file_path = repo_path / "test.ts"
        file_path.write_text(TS_CODE_WITH_ERROR)
        
        yield repo_path, file_path

@pytest_lsp.fixture(
    config=ClientServerConfig(
        server_command=["typescript-language-server", "--stdio"]
        # root_uri is set during initialize_session for more dynamic control if needed,
        # or can be added here if static for the fixture's scope.
    )
)
async def client(lsp_client: LanguageClient, workspace_info):
    """Setup and teardown for the LSP test client using the new API."""
    repo_path, _ = workspace_info
    await lsp_client.initialize_session(
        lsp_types.InitializeParams(
            process_id=os.getpid(),
            root_uri=repo_path.as_uri(),
            capabilities=client_capabilities("neovim")
        )
    )
    yield lsp_client
    await lsp_client.shutdown_session()

@pytest.mark.asyncio
async def test_lsp_integration(client: LanguageClient, workspace_info):
    """End-to-end test for LSP server interactions using the new API."""
    repo_path, file_path = workspace_info
    file_uri = file_path.as_uri()

    # Notify the server that the document is open
    client.text_document_did_open(
        lsp_types.DidOpenTextDocumentParams(
            text_document=lsp_types.TextDocumentItem(
                uri=file_uri,
                language_id="typescript",
                version=1,
                text=file_path.read_text()
            )
        )
    )

    # 1. Test Diagnostics: Wait for the server to send diagnostics
    # Ensure the server has time to process and send diagnostics.
    # wait_for_notification_async will raise TimeoutError if not received.
    try:
        diagnostics_params = await asyncio.wait_for(
            client.wait_for_notification(lsp_types.TEXT_DOCUMENT_PUBLISH_DIAGNOSTICS),
            timeout=10 # seconds
        )
    except asyncio.TimeoutError:
        pytest.fail("Test timed out waiting for diagnostics notification")
    
    assert diagnostics_params.uri == file_uri
    assert len(diagnostics_params.diagnostics) > 0
    diagnostic = diagnostics_params.diagnostics[0]
    assert "is not assignable to type 'string'" in diagnostic.message

    # 2. Test Hover
    hover_result = await client.text_document_hover_async(
        lsp_types.HoverParams(
            text_document=lsp_types.TextDocumentIdentifier(uri=file_uri),
            position=lsp_types.Position(line=1, character=7) # 0-indexed, on 'myVariable'
        )
    )
    assert isinstance(hover_result, lsp_types.Hover)
    assert hover_result.contents is not None
    if isinstance(hover_result.contents, lsp_types.MarkupContent):
        assert "const myVariable: string" in hover_result.contents.value
    elif isinstance(hover_result.contents, list):
        # Handle list of MarkedString or MarkupContent if necessary
        assert any("const myVariable: string" in item.value for item in hover_result.contents if hasattr(item, 'value'))
    else: # MarkedString (assuming lsp_types.MarkedString which is just a string)
        assert "const myVariable: string" in hover_result.contents

    # 3. Test Definition
    definition_result = await client.text_document_definition_async(
        lsp_types.DefinitionParams(
            text_document=lsp_types.TextDocumentIdentifier(uri=file_uri),
            position=lsp_types.Position(line=1, character=7) # 0-indexed, on 'myVariable'
        )
    )
    # Definition can return a single Location or a list of Locations or LocationLink[]
    if isinstance(definition_result, list):
        assert len(definition_result) > 0
        # Assuming we expect one definition for this simple case
        loc = definition_result[0]
        if isinstance(loc, lsp_types.LocationLink):
            loc_uri = loc.target_uri
            loc_range_start_line = loc.target_selection_range.start.line
        else: # Location
            loc_uri = loc.uri
            loc_range_start_line = loc.range.start.line
    elif isinstance(definition_result, lsp_types.Location): # Single Location
        loc_uri = definition_result.uri
        loc_range_start_line = definition_result.range.start.line
    else:
        pytest.fail(f"Unexpected definition result type: {type(definition_result)}. Expected Location or list of Location/LocationLink.")
        loc_uri = "" # Should not reach here if assertion passes
        loc_range_start_line = -1

    assert loc_uri.endswith('test.ts')
    assert loc_range_start_line == 1 # 0-indexed, definition is on line 1
