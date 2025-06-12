# /tests/tools/test_lsp_integration.py

import os
import pytest
import tempfile
import textwrap
from pathlib import Path
import pytest_lsp # Required for the @pytest_lsp.fixture decorator
import asyncio

from lsprotocol import types as lsp_types
from pytest_lsp import LanguageClient, ClientServerConfig, client_capabilities

# Sample TypeScript code with a variable and a type error
TS_CODE_WITH_ERROR = textwrap.dedent("""
    const myVariable: string = 123; // Error: Type 'number' is not assignable to type 'string'.
""").strip()

# tsconfig.json to enable strict type checking
TSCONFIG_CONTENT = {
  "compilerOptions": {
    "strict": True,
    "target": "ESNext",
    "module": "CommonJS"
  },
  "include": ["**/*"],
}

@pytest.fixture(scope="function")
def workspace():
    """Creates a temporary workspace with a tsconfig.json and a sample TS file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        # Create tsconfig.json
        (repo_path / "tsconfig.json").write_text(str(TSCONFIG_CONTENT).replace("'", '"'))

        # Create the sample TypeScript file
        file_path = repo_path / "test.ts"
        file_path.write_text(TS_CODE_WITH_ERROR)
        
        yield repo_path, file_path

@pytest_lsp.fixture(
    config=ClientServerConfig(
        server_command=["typescript-language-server", "--stdio"]
    )
)
async def client(lsp_client: LanguageClient, workspace):
    """Setup and teardown for the LSP test client using the new API."""
    repo_path, _ = workspace
    capabilities = client_capabilities("visual-studio-code")
    
    await lsp_client.initialize_session(
        lsp_types.InitializeParams(
            process_id=os.getpid(),
            root_uri=repo_path.as_uri(),
            capabilities=capabilities,
            workspace_folders=[
                lsp_types.WorkspaceFolder(uri=repo_path.as_uri(), name="test-workspace")
            ],
        )
    )
    yield lsp_client
    await lsp_client.shutdown_session()

@pytest.mark.asyncio
async def test_lsp_full_lifecycle(client: LanguageClient, workspace):
    """End-to-end test for LSP server interactions using the new API."""
    repo_path, file_path = workspace
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
            position=lsp_types.Position(line=0, character=6) # on 'myVariable'
        )
    )
    assert isinstance(hover_result, lsp_types.Hover)
    assert hover_result.contents is not None
    if isinstance(hover_result.contents, lsp_types.MarkupContent):
        assert "const myVariable: string" in hover_result.contents.value
    elif isinstance(hover_result.contents, list):
        assert any("const myVariable: string" in item.value for item in hover_result.contents if hasattr(item, 'value'))
    else:
        assert "const myVariable: string" in hover_result.contents

    # 3. Test Definition
    definition_result = await client.text_document_definition_async(
        lsp_types.DefinitionParams(
            text_document=lsp_types.TextDocumentIdentifier(uri=file_uri),
            position=lsp_types.Position(line=0, character=6) # on 'myVariable'
        )
    )
    
    if isinstance(definition_result, list):
        assert len(definition_result) > 0
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

    assert loc_uri.endswith('test.ts')
    assert loc_range_start_line == 0
