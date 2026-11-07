

# 在cc_agent的父文件夹下打开cmd
# python -m cc_agent.mcp_server.test.test_nmap_tool

import asyncio

from cc_agent.mcp_server.functions import nmap_tool

print(asyncio.run(nmap_tool.scan_open_ports("127.0.0.1")))

