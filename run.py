# Import the Uvicorn ASGI server for running the FastAPI application
# Uvicorn is an ASGI server that handles HTTP requests for the application
import uvicorn

# Import application settings from the configuration module
# This allows us to access configurable parameters like host and port
from app.core.config import settings

# This block executes only when the script is run directly (not imported)
# It ensures the application starts properly when this file is executed as a script
if __name__ == "__main__":
    # Start the Uvicorn server with the following configuration:
    # - "app.main:app" - Specifies the application instance to run (module:variable)
    # - host=settings.proxy_host - Host address from settings (default: "0.0.0.0")
    # - port=settings.proxy_port - Port number from settings (default: 8080)
    # - reload=True - Enable auto-reload during development for code changes
    uvicorn.run(
        "app.main:app",
        host=settings.proxy_host,
        port=settings.proxy_port,
        reload=True,
    )