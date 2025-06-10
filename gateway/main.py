# gateway/main.py

import logging
import uuid
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
import json
from common.config import settings
from common.ws_messages import FinalMessage, ErrorMessage
from agent.agent_graph import run_agent

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
    lifespan=lifespan
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
    Accepts user prompts and streams back agent responses.
    """
    await websocket.accept()
    logger.info("WebSocket connection accepted.")
    try:
        # For now, we'll use a new "thread" for each connection.
        # Later, this could be tied to a user session.
        thread_id = str(uuid.uuid4())
        logger.info(f"Generated new thread_id for connection: {thread_id}")

        while True:
            # Wait for a message from the client
            raw_data = await websocket.receive_text()
            logger.debug(f"Received raw data: {raw_data}")

            try:
                data = json.loads(raw_data)
                prompt = data.get("prompt", "No prompt provided")
                logger.info(f"Received prompt: '{prompt}'")

                # --- Phase 1: Call the agent and get the final response ---
                final_response_content = run_agent(prompt, thread_id)

                response_message = FinalMessage(d=final_response_content)
                await websocket.send_text(response_message.model_dump_json())
                logger.info(f"Sent agent's final response for thread '{thread_id}'.")

            except json.JSONDecodeError:
                logger.error(f"Failed to decode incoming JSON: {raw_data}")
                await websocket.send_text(ErrorMessage(d="Invalid JSON format.").model_dump_json())

    except WebSocketDisconnect:
        logger.info("WebSocket connection closed.")
    except Exception as e:
        logger.error(f"An unexpected error occurred in the WebSocket: {e}", exc_info=True)
        # Attempt to send an error message before closing
        try:
            await websocket.send_text(ErrorMessage(d="An internal server error occurred.").model_dump_json())
        except Exception:
            pass # Ignore if sending fails
    finally:
        logger.info("Closing WebSocket connection handler.")

# To run this application:
# uvicorn gateway.main:app --host 0.0.0.0 --port 8000 --reload