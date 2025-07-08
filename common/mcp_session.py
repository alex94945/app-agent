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
        # Set a long timeout to accommodate slow shell commands like `npx create-next-app`
    async with streamablehttp_client(mcp_url, timeout=1200.0) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()          # <— NEW mandatory step
            yield session                       # caller uses call_tool(...)
