# gateway/main.py

import logging
import uuid
import json
import os
import datetime
from typing import Dict
from uuid import UUID

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from langchain_core.messages import HumanMessage, AIMessage
import asyncio
import re

from common.ws_messages import BrowserPreviewData, BrowserPreviewMessage

from agent.agent_graph import compile_agent_graph
from agent.pty.manager import get_pty_manager
from tools.template_init import template_init
from agent.state import AgentState
from common.config import settings, PROJECT_ROOT
from common.ws_messages import (
    ErrorMessage,
    FinalMessage,
    ToolCallMessage,
    ToolResultMessage,
    TaskStartedMessage,
    TaskLogMessage,
    TaskFinishedMessage,
    TokenMessage,
    TaskStartedData,
    TaskLogData,
    TaskFinishedData,
    FileContentMessage,
    InitialFilesLoadedMessage,
)

# Configure logging
# The log level is loaded from the settings instance
logging.basicConfig(level=settings.LOG_LEVEL.upper())
logger = logging.getLogger(__name__)

from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan manager for the FastAPI application.
    Resolves REPO_DIR to an absolute path and creates it if it doesn't exist.
    """
    if not settings.REPO_DIR.is_absolute():
        settings.REPO_DIR = (PROJECT_ROOT / settings.REPO_DIR).resolve()
    settings.REPO_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("--- Gateway Startup ---")
    logger.info(f"Host: {settings.HOST}")
    logger.info(f"Port: {settings.PORT}")
    logger.info(f"Log Level: {settings.LOG_LEVEL}")
    logger.info(f"Workspace (REPO_DIR): {settings.REPO_DIR}")
    logger.info("-----------------------")
    yield
    # Code here would run on shutdown
    logger.info("--- Gateway Shutdown ---")


# Create the FastAPI app instance with the lifespan manager
app = FastAPI(
    title="Autonomous AI Agent Gateway",
    description="API Gateway for the Autonomous AI Agent",
    version="0.1.0",
    lifespan=lifespan,
)

@app.get("/health", tags=["Health"])
async def health_check():
    """
    Health check endpoint to verify that the server is running.
    """
    logger.info("Health check endpoint was called.")
    return {"status": "ok"}


@app.websocket("/api/agent")
async def agent_websocket(websocket: WebSocket):
    """
    Handles the WebSocket connection for the agent.
    Accepts user prompts and streams back agent events and PTY logs.
    """
    await websocket.accept()
    logger.info("WebSocket connection accepted. Sending initial greeting.")

    pty_manager = get_pty_manager()

    # Send initial greeting message from the agent
    initial_greeting = "Hello, I'm App Agent. Let me know if you'd like to brainstorm your idea, or get straight into building!"
    await websocket.send_text(FinalMessage(d=initial_greeting).model_dump_json())

    # --- PTY Task Management ---
    task_start_times: Dict[UUID, datetime.datetime] = {}

    async def on_pty_started(task_id: UUID, name: str):
        task_start_times[task_id] = datetime.datetime.now(datetime.timezone.utc)
        await websocket.send_text(
            TaskStartedMessage(
                d=TaskStartedData(
                    task_id=task_id,
                    name=name,
                    started_at=task_start_times[task_id]
                )
            ).model_dump_json()
        )

    preview_sent = False
    async def on_pty_output(task_id: UUID, chunk: str):
        nonlocal preview_sent
        # Forward the log to the client
        await websocket.send_text(
            TaskLogMessage(d=TaskLogData(task_id=task_id, chunk=chunk)).model_dump_json()
        )

        # Check for the Next.js ready signal and send browser preview URL
        if not preview_sent and ('ready in' in chunk.lower() or 'started server on' in chunk.lower()):
            # Extract the URL from the log message
            match = re.search(r'(https?://localhost:\d+)', chunk)
            if match:
                url = match.group(1)
                logger.info(f"Dev server ready. Sending preview URL: {url}")
                await websocket.send_text(
                    BrowserPreviewMessage(
                        d=BrowserPreviewData(url=url, title="Live App Preview")
                    ).model_dump_json()
                )
                preview_sent = True

    async def on_pty_complete(task_id: UUID, exit_code: int):
        start_time = task_start_times.pop(task_id, datetime.datetime.now(datetime.timezone.utc))
        duration_ms = (datetime.datetime.now(datetime.timezone.utc) - start_time).total_seconds() * 1000
        await websocket.send_text(
            TaskFinishedMessage(
                d=TaskFinishedData(
                    task_id=task_id,
                    exit_code=exit_code,
                    state="success" if exit_code == 0 else "error",
                    duration_ms=duration_ms
                )
            ).model_dump_json()
        )

    pty_manager.set_callbacks({
        "on_started": on_pty_started,
        "on_output": on_pty_output,
        "on_complete": on_pty_complete,
    })

    # --- Project Initialization Step ---
    project_name = f"session-{uuid.uuid4()}"
    try:
        await websocket.send_text(TokenMessage(d="Initializing new project...").model_dump_json())
        project_path = template_init.invoke({"project_name": project_name})
        logger.info(f"Project '{project_name}' initialized at {project_path}")
        await websocket.send_text(TokenMessage(d=f"Project '{project_name}' created. Starting dev server...").model_dump_json())

        # Start the dev server
        await pty_manager.spawn(
            task_name="Next.js Dev Server",
            command=["npm", "run", "dev"],
            cwd=project_path,
        )
        # The browser_preview call is now handled by the on_pty_output callback.
        # We'll add a small delay to ensure the dev server has a moment to start
        # before we proceed to the agent loop.
        await asyncio.sleep(2)  # Allow time for server to start

    except Exception as e:
        logger.error(f"Failed to initialize project or start dev server: {e}", exc_info=True)
        await websocket.send_text(ErrorMessage(d=f"Error setting up project: {e}").model_dump_json())
        await websocket.close(code=1011)
        return

    try:
        # For now, we'll use a new "thread" for each connection.
        # Later, this could be tied to a user session.
        thread_id = str(uuid.uuid4())
        logger.info(f"Generated new thread_id for connection: {thread_id}")

        messages: list[HumanMessage | AIMessage] = []

        while True:
            raw_data = await websocket.receive_text()
            logger.debug(f"Received raw data: {raw_data}")

            try:
                data = json.loads(raw_data)
                message_type = data.get("t")

                if message_type == "request_initial_files":
                    logger.info("Received request for initial files. Streaming workspace content.")
                    workspace_dir = settings.REPO_DIR
                    for root, _, files in os.walk(workspace_dir):
                        for filename in files:
                            # Skip files in .git directory
                            if '.git' in root.split(os.sep):
                                continue
                            
                            filepath = os.path.join(root, filename)
                            rel_path = os.path.relpath(filepath, workspace_dir)

                            try:
                                with open(filepath, 'r', encoding='utf-8') as f:
                                    content = f.read()
                                await websocket.send_text(
                                    FileContentMessage(d={"path": rel_path, "content": content}).model_dump_json()
                                )
                            except (IOError, UnicodeDecodeError) as e:
                                logger.warning(f"Could not read or send file {rel_path}: {e}")

                    await websocket.send_text(
                        InitialFilesLoadedMessage(d=None).model_dump_json()
                    )
                    logger.info("Finished streaming initial files.")
                    continue # Wait for the next message

                prompt = data.get("prompt", "No prompt provided")
                logger.info(f"Received prompt: '{prompt}' for thread '{thread_id}'")
                messages.append(HumanMessage(content=prompt))

                # Compile a fresh graph for each session/request
                agent_graph = compile_agent_graph()

                config = {"configurable": {"thread_id": thread_id}}
                initial_state = AgentState(
                    messages=messages
                )

                # --- Stream Agent Events --- #
                task_in_progress = False
                async for event in agent_graph.astream_events(initial_state, config, version="v1"):
                    kind = event["event"]

                    if kind == "on_chain_end" and event["name"] == "planner":
                        output = event['data'].get('output')
                        if output and isinstance(output, dict) and output.get('messages'):
                            ai_message = output['messages'][-1]
                            if isinstance(ai_message, AIMessage):
                                # Persist the full AIMessage from the planner to maintain agent context
                                messages.append(ai_message)

                                # NOTE: We no longer handle tool calls here. See on_tool_start.
                                if ai_message.content and not ai_message.tool_calls:
                                    # No tool, so it's a conversational reply.
                                    reply = ai_message.content
                                    logger.info(f"Sending agent message: {reply}")
                                    await websocket.send_text(FinalMessage(d=reply).model_dump_json())
                                elif not ai_message.content and not ai_message.tool_calls:
                                    # Fallback for unexpected cases where there's no tool and no reply.
                                    logger.warning(f"No tool or reply found in AI message: {ai_message}")

                    elif kind == "on_tool_start":
                        logger.info(f"Tool Start: {event['name']} with args {event['data'].get('input')}")
                        # A tool was chosen, so a task is starting.
                        task_in_progress = True
                        # The summary is on the last AI message from the planner.
                        last_ai_message = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
                        if last_ai_message:
                            summary = last_ai_message.additional_kwargs.get('summary', 'Starting task...')
                            logger.info(f"Sending tool summary: {summary}")
                            await websocket.send_text(TokenMessage(d=summary).model_dump_json())

                    elif kind == "on_tool_end":
                        logger.info(f"Tool End: {event['name']}")
                        output = event['data'].get('output')
                        # Don't send PTY task handles to the UI
                        if isinstance(output, dict) and output.get("type") == "pty_task":
                            continue
                    
                    elif kind == "on_chat_model_stream":
                        # Suppress token streaming if a task is in progress
                        if not task_in_progress:
                            content = event['data']['chunk'].content
                            if content:
                                await websocket.send_text(
                                    TokenMessage(d=content).model_dump_json()
                                )

                    elif kind == "on_graph_end":
                        logger.info("Graph End")
                        # The full conversation history is now managed by appending messages as they occur.
                        # We no longer need to send a final message here, as it's either a confirmation or a reply.
                        pass
                    else:
                        # For other events, we can just pass as they are not critical for the UI
                        pass

            except json.JSONDecodeError:
                logger.error(f"Failed to decode incoming JSON: {raw_data}")
                try:
                    serializable_data = json.dumps({"t": "error", "d": "Invalid JSON format."})
                except TypeError:
                    logger.warning(f"Could not serialize event data for event type error. Skipping.")
                    continue
                await websocket.send_text(serializable_data)

    except WebSocketDisconnect:
        logger.info("WebSocket connection closed.")
    except Exception as e:
        logger.error(
            f"An unexpected error occurred: {e}", exc_info=True
        )
        # Ensure the websocket is closed on error
        await websocket.close(code=1011)
        try:
            await websocket.send_text(
                ErrorMessage(d="An internal server error occurred.").model_dump_json()
            )
        except Exception:
            pass  # Ignore if sending fails
    finally:
        # Clean up the PTY callbacks for this session
        if pty_manager:
            pty_manager.clear_callbacks()
        logger.info("Closing WebSocket connection handler.")


@app.on_event("startup")
async def startup_event():
    pass

async def initialize_project(session_id: str, websocket: WebSocket):
    """Initializes a new project directory and dev server."""
    logger.info(f"Initializing new project for session: {session_id}")
    await send_message("token", f"Initializing new project: {session_id}", websocket)
    project_path = template_init.invoke({"session_id": session_id})
    get_pty_manager().set_project_path(project_path)


# To run this application:
# uvicorn gateway.main:app --host 0.0.0.0 --port 8000 --reload
