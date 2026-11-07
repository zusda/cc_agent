# cc_agent/users/model_cfg.py
# import json
from copy import deepcopy
from pathlib import Path
import json
# from config import MODEL_CFG_DIR
from cc_agent.config import MODEL_CFG_DIR

def check_name(name):
    """名字会被拼进文件路径，禁止空名和路径分隔符，防止写到目标目录之外。"""
    if not name or name in (".", "..") or "/" in name or "\\" in name:
        raise ValueError(f"invalid name: {name!r}")


class ModelCfg:
    """一个模型配置：配置名、模型名、url、可选 key、server 别名到 url 的映射、各 server 上的工具。

    cfg_name 必填，就是配置文件的文件名（<cfg_name>.json）。

    两种配置：
    - 全局配置：belong 为 None，文件放在 MODEL_CFG_DIR/<cfg_name>.json
    - 用户配置：belong 是 user_name，文件放在该用户的 model_cfg 文件夹里
    user 要使用全局配置时，会复制一份成为自己的用户配置（见 User.add_model_cfg）。

    落盘规则：
    - 新建出来的对象只在内存里，不会自动写盘。
    - 全局配置：显式调用 save() 时第一次写到 MODEL_CFG_DIR，已有同名文件不覆盖。
    - 用户配置：文件由 User.add_model_cfg 放进用户的 model_cfg 文件夹。
    - 一旦有了文件（file_path 不为 None），之后每次修改自动写回。
    """
    MODEL_TYPES = ["ollama", "vllm", "deepseek"]

    def __init__(self, cfg_name, model_name, url, key=None, type="ollama"):
        check_name(cfg_name)
        self.cfg_name = cfg_name
        self.type = type    # 用于后续解析模型使用哪个子类
        self.model_name = model_name
        self.url = url
        self.key = key
        self.belong = None
        self.dict_server2url = {}
        # 格式和 mcp_server.client 里的 tools_cache 一致：{url: [OpenAI 格式的工具, ...]}，工具名是服务上的原始名字
        self.tools = {}
        self.file_path = None

        # 这个配置启用的 skill 名字列表（只记名字，内容在 skill 文件里）；不是每个配置都要添加所有 skill
        self.skill = []


    # ---------- skill ----------
    # self.skill 只记名字。内容按 名字 + self.belong 到对应目录读取（见 skill.py）。

    def add_skill(self, skill):
        """给配置添加一个 skill，配置里只记名字，返回这个名字。

        skill 文件按配置的归属处理：
        - 用户配置：复制到该用户的 skill 目录（用户目录里已有同名 skill 就复用，不覆盖）
        - 全局配置：skill 必须是全局 skill；全局目录里还没有就先保存
        """
        skill_name = skill.name
        if skill_name in self.skill:
            raise ValueError(f"skill already exists: {skill_name}")

        # 如果该model配置有归属用户，把skill添加到归属用户下
        if self.belong is not None:
            skill.copy_to_user(self.belong)
        else:
            # 如果model没有归属用户，且该skill时有归属的，则报错。不能够把有归属用户的skill挂到全局目录下
            if skill.belong is not None:
                raise ValueError(f"global model_cfg can't use a user's skill: {skill_name}")

            if not skill.exists(skill_name):
                skill.save()

        self.skill.append(skill_name)
        self.autosave()
        return skill_name

    def list_skill(self):
        return list(self.skill)

    def delete_skill(self, skill_name):
        """只把名字从这个配置里去掉，不删 skill 文件：文件可能还被同一用户的其他配置用着。"""
        if skill_name not in self.skill:
            raise KeyError(f"skill not found: {skill_name}")
        self.skill.remove(skill_name)
        self.autosave()

    # ---------- 复制 / 全局配置 / 删除 ----------

    def copy(self):
        """深拷贝出一个新对象：内容相同，但没有 file_path（还没落盘）。"""
        return ModelCfg.from_dict(self.cfg_name, deepcopy(self.to_dict()))

    @classmethod
    def load_global(cls, cfg_name):
        # 使用默认全局路径进行load
        check_name(cfg_name)
        return cls.load(Path(MODEL_CFG_DIR) / f"{cfg_name}.json")

    def delete(self):
        """删除这个配置的文件。用户配置会先让所属用户把记录去掉，再删文件。"""
        if self.file_path is None:
            raise ValueError("model_cfg is not saved")
        if self.belong is not None:
            # 延迟导入：user.py 在模块顶部导入了本文件，这里再在顶部导入会循环
            from cc_agent.users.user import User

            try:
                user = User.open_user(self.belong)
            except FileNotFoundError:
                user = None
            if user is not None:
                user.forget_model_cfg(self.cfg_name)
        Path(self.file_path).unlink(missing_ok=True)
        self.file_path = None

    # ---------- server ----------

    def add_server(self, server_name, url):
        if server_name in self.dict_server2url:
            raise ValueError(f"server already exists: {server_name}")
        self.dict_server2url[server_name] = url
        self.autosave()

    def list_server(self):
        return dict(self.dict_server2url)

    def delete_server(self, server_name):
        if server_name not in self.dict_server2url:
            raise KeyError(f"server not found: {server_name}")
        url = self.dict_server2url.pop(server_name)
        # 没有别的 server 别名再指向这个 url 时，这个 url 下的工具也一并删除
        if url not in self.dict_server2url.values():
            self.tools.pop(url, None)
        self.autosave()

    # ---------- tool ----------
    # self.tools 的格式和 mcp_server.client 里的 tools_cache 一致：
    #   {url: [{"type": "function", "function": {"name": 原始名, "description": ..., "parameters": ...}}, ...]}
    # 里面存的是服务上的原始工具名（add）；加上 server 别名前缀（local__add）是在
    # list_tool / delete_tool / to_openai_tools 里按 dict_server2url 现算的。

    async def add_tool(self, server_name, func_name):
        """从指定 MCP 服务器获取工具并添加到配置中。"""
        if server_name not in self.dict_server2url:
            raise KeyError(f"server not found: {server_name}")

        url = self.dict_server2url[server_name]

        from cc_agent.mcp_server.client import get_tools

        tools = await get_tools(url)

        for tool in tools:
            if tool["function"]["name"] == func_name:
                tool_name = f"{server_name}__{func_name}"

                if tool_name in self.list_tool():
                    raise ValueError(f"tool already exists: {tool_name}")

                self.tools.setdefault(url, []).append(deepcopy(tool))
                self.autosave()

                return tool_name

        raise KeyError(f"tool not found on server {server_name}: {func_name}")

    def delete_tool(self, tool_name):
        """按带前缀的工具名（list_tool 返回的那种，如 local__add）删除一个工具。"""
        for server_name, url in self.dict_server2url.items():
            for index, tool in enumerate(self.tools.get(url, [])):
                if f"{server_name}__{tool['function']['name']}" == tool_name:
                    del self.tools[url][index]
                    if not self.tools[url]:
                        del self.tools[url]
                    self.autosave()
                    return
        raise KeyError(f"tool not found: {tool_name}")

    def list_tool(self):
        """返回所有工具带前缀的名字，如 ["local__add", "local__func1"]。"""
        tool_names = []
        for server_name, url in self.dict_server2url.items():
            for tool in self.tools.get(url, []):
                tool_names.append(f"{server_name}__{tool['function']['name']}")
        return tool_names

    def to_openai_tools(self):
        """转成可以直接传给 OpenAI 兼容模型 tools 参数的列表，工具名加上 server 别名前缀：add -> local__add。

        返回的是深拷贝，随便改不会影响配置里存的内容。
        """
        openai_tools = []
        for server_name, url in self.dict_server2url.items():
            for tool in self.tools.get(url, []):
                prefixed_tool = deepcopy(tool)
                prefixed_tool["function"]["name"] = f"{server_name}__{tool['function']['name']}"
                openai_tools.append(prefixed_tool)
        return openai_tools

    # ---------- 持久化 ----------

    def to_dict(self):
        return {
            "type": self.type,
            "model_name": self.model_name,
            "url": self.url,
            "key": self.key,
            "belong": self.belong,
            "dict_server2url": self.dict_server2url,
            "tools": self.tools,
            "skill": self.skill,
        }

    @classmethod
    def from_dict(cls, cfg_name, data):
        model_cfg = cls(
            cfg_name,
            data["model_name"],
            data["url"],
            data.get("key"),
            data.get("type", "ollama"),

        )
        model_cfg.belong = data.get("belong")
        model_cfg.dict_server2url = data.get("dict_server2url", {})
        tools = data.get("tools", {})
        if isinstance(tools, list):
            raise ValueError(f"model_cfg {cfg_name}: tools 是旧的存储格式（列表），请删除这个配置文件后重新生成")
        model_cfg.tools = tools
        model_cfg.skill = list(data.get("skill", []))
        return model_cfg

    def save(self):
        """写文件。全局配置第一次保存时绑定到 MODEL_CFG_DIR，已有同名文件不覆盖。"""
        if self.file_path is None:
            if self.belong is not None:
                # 用户配置的位置由 User.add_model_cfg 指定，这里不知道
                return
            global_path = Path(MODEL_CFG_DIR) / f"{self.cfg_name}.json"
            if global_path.exists():
                raise FileExistsError(f"global model_cfg already exists: {self.cfg_name}")
            global_path.parent.mkdir(parents=True, exist_ok=True)
            self.file_path = global_path
        with open(self.file_path, "w", encoding="utf-8") as file:
            json.dump(self.to_dict(), file, ensure_ascii=False, indent=2)

    def autosave(self):
        """修改之后调用：已经有文件才写回，还在内存里的对象不会因为修改而凭空落盘。"""
        if self.file_path is not None:
            self.save()

    @classmethod
    def load(cls, file_path):
        # 需要提供完整文件路径
        with open(file_path, "r", encoding="utf-8") as file:
            data = json.load(file)
        file_path = Path(file_path)
        model_cfg = cls.from_dict(file_path.stem, data)
        model_cfg.file_path = file_path
        return model_cfg