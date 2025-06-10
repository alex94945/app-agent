import pytest
from unittest.mock import patch, MagicMock

from tools.vector_store_tools import vector_search

@pytest.mark.asyncio
@patch('tools.vector_store_tools.vector_store_adapter')
async def test_vector_search_success(mock_adapter):
    """Tests that vector_search successfully calls the adapter and returns results."""
    # 1. Setup Mock
    mock_adapter.search.return_value = [
        {"content": "some relevant text", "metadata": {}, "score": 0.9}
    ]

    # 2. Call Tool
    result = await vector_search.ainvoke({"query": "test query", "k": 1})

    # 3. Assertions
    mock_adapter.search.assert_called_once_with(query="test query", k=1)
    assert len(result) == 1
    assert result[0]["content"] == "some relevant text"

@pytest.mark.asyncio
@patch('tools.vector_store_tools.vector_store_adapter')
async def test_vector_search_adapter_not_initialized(mock_adapter):
    """Tests that vector_search handles the case where the adapter is not initialized."""
    # 1. Setup Mock
    # To simulate this, we can set the mock_adapter to None within the tool's module
    with patch('tools.vector_store_tools.vector_store_adapter', None):
        # 2. Call Tool
        result = await vector_search.ainvoke({"query": "test query"})

        # 3. Assertions
        assert len(result) == 1
        assert "not initialized" in result[0].get("error", "")

@pytest.mark.asyncio
@patch('tools.vector_store_tools.vector_store_adapter')
async def test_vector_search_exception(mock_adapter):
    """Tests that vector_search handles an unexpected exception from the adapter."""
    # 1. Setup Mock
    mock_adapter.search.side_effect = Exception("Something went wrong")

    # 2. Call Tool
    result = await vector_search.ainvoke({"query": "test query"})

    # 3. Assertions
    assert len(result) == 1
    assert "An unexpected error occurred" in result[0].get("error", "")
