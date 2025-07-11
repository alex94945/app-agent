# common/mcp_session.py
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from mcp.client.streamable_http import streamablehttp_client
from mcp import ClientSession
from common.config import get_settings

@asynccontextmanager
async def open_mcp_session() -> AsyncGenerator[ClientSession, None]:
    settings = get_settings()
    mcp_url = os.environ.get("MCP_SERVER_URL", settings.MCP_SERVER_URL)

    # The streamable-http transport requires the path to be /mcp/
    if not mcp_url.endswith('/'):
        mcp_url += '/'
    if not mcp_url.endswith('/mcp/'):
        mcp_url += 'mcp/'

    # The streamable-http transport requires a specific Accept header.
    headers = {"Accept": "application/json, text/event-stream"}

    # Set a long timeout to accommodate slow shell commands like `npx create-next-app`
    async with streamablehttp_client(mcp_url, headers=headers, timeout=1200.0) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()          # <— NEW mandatory step
            yield session                       # caller uses call_tool(...)
