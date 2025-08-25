from langchain_mcp_adapters.client import MultiServerMCPClient
import asyncio

client = MultiServerMCPClient(
    {
        "Email": {
            "transport": "stdio",
            "command": "D:\\MyProject\\its-Friday\\.venv\\Scripts\\python.exe",
            "args": [
                "d:\\MyProject\\its-Friday\\skills\\MCP\\email_server.py"
            ]
        },
        "Weather": {
            "transport": "stdio",
            "command": "D:\\MyProject\\its-Friday\\.venv\\Scripts\\python.exe",
            "args": [
                "d:\\MyProject\\its-Friday\\skills\\MCP\\weather_server.py"
            ]
        }
    }
)

its_friday_tools = asyncio.run(client.get_tools())
