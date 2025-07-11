# gateway/main.py

import logging
import uuid
import json
import datetime
from typing import Dict
from uuid import UUID

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from langchain_core.messages import HumanMessage, AIMessage

from agent.agent_graph import agent_graph
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
    TaskStartedData,
    TaskLogData,
    TaskFinishedData,
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
    logger.info("WebSocket connection accepted.")
    try:
        # For now, we'll use a new "thread" for each connection.
        # Later, this could be tied to a user session.
        thread_id = str(uuid.uuid4())
        logger.info(f"Generated new thread_id for connection: {thread_id}")

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

        async def on_pty_output(task_id: UUID, chunk: str):
            await websocket.send_text(
                TaskLogMessage(d=TaskLogData(task_id=task_id, chunk=chunk)).model_dump_json()
            )

        async def on_pty_complete(task_id: UUID, exit_code: int):
            start_time = task_start_times.pop(task_id, None)
            duration_ms = (datetime.datetime.now(datetime.timezone.utc) - start_time).total_seconds() * 1000 if start_time else 0
            await websocket.send_text(
                TaskFinishedMessage(
                    d=TaskFinishedData(
                        task_id=task_id,
                        exit_code=exit_code,
                        state="success" if exit_code == 0 else "error",
                        duration_ms=duration_ms,
                    )
                ).model_dump_json()
            )

        pty_callbacks = {
            "on_started": on_pty_started,
            "on_output": on_pty_output,
            "on_complete": on_pty_complete,
        }

        while True:
            raw_data = await websocket.receive_text()
            logger.debug(f"Received raw data: {raw_data}")

            try:
                data = json.loads(raw_data)
                prompt = data.get("prompt", "No prompt provided")
                logger.info(f"Received prompt: '{prompt}' for thread '{thread_id}'")

                config = {"configurable": {"thread_id": thread_id}}
                initial_state = AgentState(
                    messages=[HumanMessage(content=prompt)]
                )

                # --- Stream Agent Events --- #
                async for event in agent_graph.astream_events(initial_state, config, version="v1"):
                    kind = event["event"]
                    
                    if kind == "on_tool_start":
                        logger.info(f"Tool Start: {event['name']} with args {event['data'].get('input')}")
                        await websocket.send_text(
                            ToolCallMessage(d={"name": event['name'], "args": event['data'].get('input')}).model_dump_json()
                        )

                    elif kind == "on_tool_end":
                        logger.info(f"Tool End: {event['name']}")
                        output = event['data'].get('output')
                        # Don't send PTY task handles to the UI
                        if isinstance(output, dict) and output.get("type") == "pty_task":
                            continue
                        await websocket.send_text(
                            ToolResultMessage(d={"tool_name": event['name'], "result": output}).model_dump_json()
                        )
                    
                    elif kind == "on_chat_model_stream":
                        content = event['data']['chunk'].content
                        if content:
                            await websocket.send_text(
                                TokenMessage(d=content).model_dump_json()
                            )

                    elif kind == "on_graph_end":
                        logger.info("Graph End")
                        final_state = event['data'].get('output')
                        if final_state and final_state.get('messages'):
                            last_message = final_state['messages'][-1]
                            if isinstance(last_message, AIMessage) and last_message.content:
                                await websocket.send_text(
                                    FinalMessage(d=last_message.content).model_dump_json()
                                )
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
            f"An unexpected error occurred in the WebSocket: {e}", exc_info=True
        )
        # Attempt to send an error message before closing
        try:
            await websocket.send_text(
                ErrorMessage(d="An internal server error occurred.").model_dump_json()
            )
        except Exception:
            pass  # Ignore if sending fails
    finally:
        logger.info("Closing WebSocket connection handler.")


# To run this application:
# uvicorn gateway.main:app --host 0.0.0.0 --port 8000 --reload
