


"""MCP server：只通过 HTTP 端口暴露工具。

启动：python -m mcp_server.server
端点：http://127.0.0.1:8000/mcp
工具函数定义在 functions/ 下，由 load_all 统一加载。
"""
from mcp.server.fastmcp import FastMCP

from .functions import load_all

mcp = FastMCP("tool-server", host="127.0.0.1", port=8000)
load_all(mcp)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")













