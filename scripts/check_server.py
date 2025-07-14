import httpx
import asyncio
import os

# This is a simple utility to check if a local server is running and responsive.
# It can be used to quickly diagnose connection issues.

async def main():
    # This script performs a simple GET request to the root URL by default.
    # For a full, valid check of the MCP tool server, you must:
    # 1. Target the /mcp/ endpoint (e.g., http://127.0.0.1:8080/mcp/)
    # 2. Send a POST request with a valid JSON-RPC payload.
    # 3. Include the header: {"Accept": "application/json, text/event-stream"}
    
    url = os.environ.get("CHECK_SERVER_URL", "http://127.0.0.1:8080/")
    
    print(f"Checking server at: {url}")
    try:
        async with httpx.AsyncClient() as client:
            # A simple GET request is enough to see if the server is listening.
            response = await client.get(url)
            print(f"Status Code: {response.status_code}")
            print(f"Headers: {response.headers}")
            print(f"Body: {response.text}")
    except httpx.ConnectError as e:
        print(f"Connection failed: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

if __name__ == "__main__":
    asyncio.run(main())
