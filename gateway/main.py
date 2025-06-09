# gateway/main.py

import logging
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
import json
from common.config import settings
from common.ws_messages import FinalMessage, ErrorMessage

# Configure logging
# The log level is loaded from the settings instance
logging.basicConfig(level=settings.LOG_LEVEL.upper())
logger = logging.getLogger(__name__)

# Create the FastAPI app instance
app = FastAPI(
    title="Autonomous AI Agent Gateway",
    description="API Gateway for the Autonomous AI Agent",
    version="0.1.0"
)

@app.on_event("startup")
async def startup_event():
    """
    Event handler for application startup.
    Logs the configuration being used.
    """
    logger.info("--- Gateway Startup ---")
    logger.info(f"Host: {settings.HOST}")
    logger.info(f"Port: {settings.PORT}")
    logger.info(f"Log Level: {settings.LOG_LEVEL}")
    logger.info(f"Workspace (REPO_DIR): {settings.REPO_DIR}")
    logger.info("-----------------------")

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
        while True:
            # Wait for a message from the client
            raw_data = await websocket.receive_text()
            logger.debug(f"Received raw data: {raw_data}")

            # For now, we assume the incoming message is a simple JSON with a "prompt" key
            try:
                data = json.loads(raw_data)
                prompt = data.get("prompt", "No prompt provided")
                logger.info(f"Received prompt: '{prompt}'")

                # --- Phase 0: Echo the prompt back using the FinalMessage schema ---
                echo_message = FinalMessage(d=f"Echo: {prompt}")
                await websocket.send_text(echo_message.model_dump_json())
                logger.info(f"Sent echo response: {echo_message.model_dump_json()}")

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