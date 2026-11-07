
"""
工具函数包：每个模块写普通函数，并用模块级 TOOLS 列表声明要导出的工具。

load_all 会扫描本包下所有模块，把各模块 TOOLS 里的函数统一注册到 FastMCP。

新增工具：在本目录新建 xxx.py，写函数 + TOOLS = [...]，无需改 server.py。
"""
import importlib
import pkgutil


def load_all(mcp) -> list[str]:
    """注册本包所有模块导出的工具，返回已注册的工具名列表。"""

    registered = []  # 创建空列表，用来记录已注册的工具名

    # 遍历当前包目录下的所有模块。
    # __path__ 是包自带的目录路径
    # 只扫直接放在 functions/ 下的 .py 文件，返回每个 .py 文件的信息info，info.name为去除.py后缀的文件名
    for info in pkgutil.iter_modules(__path__):

        # __name__ 是当前包的完整名 mcp_server.functions，这里是导入对应包，比如导入text.py: mcp_server.functions.text
        module = importlib.import_module(f"{__name__}.{info.name}")

        # 从刚导入的 module 里取出名为 TOOLS 的变量。等价于 for func in 该模块的 TOOLS 列表
        # getattr(对象, "属性名", 默认值)，只有对象上找不到这个属性名时，才会返回默认值
        for func in getattr(module, "TOOLS", []):
            # 检查是否已经在已注册的函数名中
            if func.__name__ in registered: # func.__name__ 是函数的名字
                print(f"跳过重名工具: {func.__name__} (模块 {info.name}.py)")
                continue

            # 把函数注册为 MCP 工具。
            # mcp.tool() 先返回装饰器，再用 (func) 调用它，效果等同于在函数上写 @mcp.tool()
            mcp.tool()(func)
            registered.append(func.__name__)

    # registered 最后是所有已成功注册的工具名
    # ['add', 'func1']   # 先扫到 calc.py（add），再扫到 text.py（func1）
    return registered







