import pytest

from tools.lsp_tools import lsp_definition, lsp_hover, get_diagnostics

@pytest.mark.asyncio
async def test_lsp_definition_stub():
    """Tests the stubbed lsp_definition tool."""
    # 1. Call Tool
    result = await lsp_definition.ainvoke({
        "file_path_in_repo": "src/index.ts",
        "line": 10,
        "character": 5
    })

    # 2. Assertions
    assert "uri" in result
    assert "This is a stubbed response" in result.get("comment", "")

@pytest.mark.asyncio
async def test_lsp_hover_stub():
    """Tests the stubbed lsp_hover tool."""
    # 1. Call Tool
    result = await lsp_hover.ainvoke({
        "file_path_in_repo": "src/index.ts",
        "line": 10,
        "character": 5
    })

    # 2. Assertions
    assert "contents" in result
    assert isinstance(result["contents"], list)
    assert result["contents"][1] == "This is a stubbed hover response."

@pytest.mark.asyncio
async def test_get_diagnostics_stub():
    """Tests the stubbed get_diagnostics tool."""
    # 1. Call Tool
    result = await get_diagnostics.ainvoke({})

    # 2. Assertions
    assert isinstance(result, list)
    assert len(result) == 0

@pytest.mark.asyncio
async def test_get_diagnostics_stub_with_path():
    """Tests the stubbed get_diagnostics tool with a file path."""
    # 1. Call Tool
    result = await get_diagnostics.ainvoke({"file_path_in_repo": "src/index.ts"})

    # 2. Assertions
    assert isinstance(result, list)
    assert len(result) == 0
