from contextlib import asynccontextmanager

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

# 本地 server 的地址
DEFAULT_URL = "http://127.0.0.1:8000/mcp"

# 缓存：{url: 该 server 的完整工具列表}，整个进程共用
tools_cache = {}
# {"http://127.0.0.1:8000/mcp": [
#     "type": "function","function": {"name": "add", "description": "...", "parameters": {...}},
#     "type": "function","function": {"name": "func1", "description": "...", "parameters": {...}},
# ]}

# openai兼容模型的tool格式
# "type": "function","function": {"name": "add", "description": "...", "parameters": {...}},

class ToolExecuteError(Exception):
    pass



# 连上 server，返回一个能发请求的会话
@asynccontextmanager
async def open_session(url=DEFAULT_URL):
    async with streamablehttp_client(url) as (read, write, session_id):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session

# def 前的async是必须的。因为函数体里用到了 async with 和 await，这两个关键字只能写在 async def 定义的函数里面

# 取工具列表（带缓存）
async def get_tools(url=DEFAULT_URL, refresh=False):
    # 调用方要求刷新（refresh 为真），或者这个 url 还没缓存，就连接目标mcp服务器进行缓存更新
    if refresh or url not in tools_cache:
        async with open_session(url) as session:
            result = await session.list_tools()
        tools = []

        # openai 兼容格式
        # for tool in result.model_tools:
        for tool in result.tools:
            tools.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": tool.inputSchema,
                },
            })
        tools_cache[url] = tools

    # [
    #     "type": "function","function": {"name": "add", "description": "...", "parameters": {...}},
    #     "type": "function","function": {"name": "func1", "description": "...", "parameters": {...}},
    # ]
    # 否则就跳过整个 if，直接用缓存
    return tools_cache[url]


# 执行一个工具
async def execute_tool(url, name, arguments=None):
    # arguments 是模型生成的实参字典，例如 {"a": 1, "b": 2}。默认值写 None

    # 连上 server，请求执行工具
    async with open_session(url) as session:
        result = await session.call_tool(name, arguments or {})
    texts = []

    # result 是一个 CallToolResult 对象，里面有两个我们要用的属性：
    # 1. content（返回内容列表）
    # 2. isError（是否出错）。
    for item in result.content:
        if item.type == "text":
            texts.append(item.text)
    output = "\n".join(texts)

    if result.isError:
        # 具执行在loop中要求用try包起来
        # 专门交给报错解决的部分
        raise ToolExecuteError(output or f"工具执行失败: {name}")

    # except ToolExecuteError as e:
    #   output = f"工具执行出错: {e}"  # {e} 就是 raise 时传入的那段文字
    return output



# def match_tool(tools, name):
#     # 在工具列表里按原名找，找到返回整项，找不到返回 None
#     for tool in tools:
#         if tool["function"]["name"] == name:
#             return tool  # {"type": "function", "function": {"name": "add", "description": "...", "parameters": {...}}}
#     return None


# async def find_tool(url, name):
#     # 缓存里没有这个 url，说明下面这次 get_tools 本身就是新拉取的
#     fresh = url not in tools_cache
#     tools = await get_tools(url)
#
#     found = match_tool(tools, name)
#
#     # 缓存命中过但没找到名字：server 可能后来新增了工具，强制刷新一次再找
#     # 刚拉取过（fresh 为真）就不再重复拉取
#     if found is None and not fresh:
#         tools = await get_tools(url, refresh=True)
#         found = match_tool(tools, name)
#
#     if found is None:
#         raise KeyError(f"server {url} 上没有工具 {name}")
#
#     return found # {"type": "function", "function": {"name": "add", "description": "...", "parameters": {...}}}
#

