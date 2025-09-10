"""
ServiceNow MCP Server

This module provides the main implementation of the ServiceNow MCP server.
"""

import argparse
import os
from typing import Dict, Union

import uvicorn
from dotenv import load_dotenv
from mcp.server import Server
from mcp.server.fastmcp import FastMCP
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, HTMLResponse
from starlette.routing import Mount, Route

from servicenow_mcp.server import ServiceNowMCP
from servicenow_mcp.utils.config import AuthConfig, AuthType, BasicAuthConfig, ServerConfig


def create_starlette_app(mcp_server: Server, *, debug: bool = False) -> Starlette:
    """Create a Starlette application that can serve the provided mcp server with SSE."""
    sse = SseServerTransport("/messages/")

    async def handle_sse(request: Request) -> None:
        async with sse.connect_sse(
            request.scope,
            request.receive,
            request._send,  # noqa: SLF001
        ) as (read_stream, write_stream):
            await mcp_server.run(
                read_stream,
                write_stream,
                mcp_server.create_initialization_options(),
            )

    async def handle_root(request: Request) -> HTMLResponse:
        """Serve API documentation at the root endpoint."""
        try:
            # Get the path to the HTML file
            current_dir = os.path.dirname(os.path.abspath(__file__))
            html_file_path = os.path.join(current_dir, "static", "index.html")
            
            # Read the HTML content from file
            with open(html_file_path, "r", encoding="utf-8") as f:
                html_content = f.read()
                
            return HTMLResponse(content=html_content, status_code=200)
            
        except FileNotFoundError:
            # Fallback HTML if file is not found
            fallback_html = """
            <!DOCTYPE html>
            <html>
            <head>
                <title>ServiceNow MCP Server</title>
                <style>
                    body { font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }
                    .container { max-width: 600px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; }
                    h1 { color: #e74c3c; }
                </style>
            </head>
            <body>
                <div class="container">
                    <h1>⚠️ ServiceNow MCP Server</h1>
                    <p>API documentation template not found. Server is running but documentation is unavailable.</p>
                    <p>Available endpoints:</p>
                    <ul>
                        <li><strong>GET /health</strong> - Health check</li>
                        <li><strong>GET /sse</strong> - MCP SSE endpoint</li>
                        <li><strong>POST /messages/</strong> - MCP messages</li>
                    </ul>
                </div>
            </body>
            </html>
            """
            return HTMLResponse(content=fallback_html, status_code=200)
            
        except Exception as e:
            # Error fallback
            error_html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>ServiceNow MCP Server - Error</title>
                <style>
                    body {{ font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }}
                    .container {{ max-width: 600px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; }}
                    h1 {{ color: #e74c3c; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <h1>❌ ServiceNow MCP Server - Error</h1>
                    <p>Error loading documentation: {str(e)}</p>
                    <p>Server is running but documentation display failed.</p>
                </div>
            </body>
            </html>
            """
            return HTMLResponse(content=error_html, status_code=500)

    async def handle_health(request: Request) -> JSONResponse:
        """Health check endpoint."""
        try:
            # Get environment info
            tool_package = os.getenv("MCP_TOOL_PACKAGE", "full")
            debug_mode = os.getenv("DEBUG_MODE", "false").lower() == "true"
            ssl_verify = os.getenv("SSL_VERIFY", "true").lower() == "true"
            log_level = os.getenv("LOG_LEVEL", "INFO")
            auth_type = os.getenv("SERVICENOW_AUTH_TYPE", "basic")
            instance_url = os.getenv("SERVICENOW_INSTANCE_URL", "not-configured")
            
            # Basic server health info
            health_data = {
                "status": "healthy",
                "service": "ServiceNow MCP Server",
                "version": "1.0.0",
                "endpoints": {
                    "root": "/",
                    "health": "/health", 
                    "sse": "/sse",
                    "messages": "/messages/"
                },
                "configuration": {
                    "tool_package": tool_package,
                    "debug_mode": debug_mode,
                    "ssl_verify": ssl_verify,
                    "log_level": log_level,
                    "auth_type": auth_type,
                    "instance_configured": "configured" if instance_url != "not-configured" else "not-configured"
                },
                "mcp": {
                    "protocol_version": "2024-11-05",
                    "server_ready": True
                }
            }
            
            return JSONResponse(content=health_data, status_code=200)
            
        except Exception as e:
            error_data = {
                "status": "unhealthy",
                "service": "ServiceNow MCP Server",
                "error": str(e)
            }
            return JSONResponse(content=error_data, status_code=500)

    return Starlette(
        debug=debug,
        routes=[
            Route("/", endpoint=handle_root),
            Route("/health", endpoint=handle_health),
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ],
    )


class ServiceNowSSEMCP(ServiceNowMCP):
    """
    ServiceNow MCP Server implementation.

    This class provides a Model Context Protocol (MCP) server for ServiceNow,
    allowing LLMs to interact with ServiceNow data and functionality.
    """

    def __init__(self, config: Union[Dict, ServerConfig]):
        """
        Initialize the ServiceNow MCP server.

        Args:
            config: Server configuration, either as a dictionary or ServerConfig object.
        """
        super().__init__(config)

    def start(self, host: str = "0.0.0.0", port: int = 8080):
        """
        Start the MCP server with SSE transport using Starlette and Uvicorn.

        Args:
            host: Host address to bind to
            port: Port to listen on
        """
        # Create Starlette app with SSE transport
        starlette_app = create_starlette_app(self.mcp_server, debug=True)

        # Run using uvicorn
        uvicorn.run(starlette_app, host=host, port=port)


def create_servicenow_mcp(instance_url: str, username: str, password: str):
    """
    Create a ServiceNow MCP server with minimal configuration.

    This is a simplified factory function that creates a pre-configured
    ServiceNow MCP server with basic authentication.

    Args:
        instance_url: ServiceNow instance URL
        username: ServiceNow username
        password: ServiceNow password

    Returns:
        A configured ServiceNowMCP instance ready to use

    Example:
        ```python
        from servicenow_mcp.server import create_servicenow_mcp

        # Create an MCP server for ServiceNow
        mcp = create_servicenow_mcp(
            instance_url="https://instance.service-now.com",
            username="admin",
            password="password"
        )

        # Start the server
        mcp.start()
        ```
    """

    # Create basic auth config
    auth_config = AuthConfig(
        type=AuthType.BASIC, basic=BasicAuthConfig(username=username, password=password)
    )

    # Create server config
    config = ServerConfig(instance_url=instance_url, auth=auth_config)

    # Create and return server
    return ServiceNowSSEMCP(config)


def main():
    load_dotenv()

    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Run ServiceNow MCP SSE-based server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on")
    args = parser.parse_args()

    server = create_servicenow_mcp(
        instance_url=os.getenv("SERVICENOW_INSTANCE_URL"),
        username=os.getenv("SERVICENOW_USERNAME"),
        password=os.getenv("SERVICENOW_PASSWORD"),
    )
    server.start(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
