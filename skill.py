# cc_agent/skill.py
from pathlib import Path
import json
from cc_agent.config import SKILL_DIR, USER_DIR, MODEL_CFG_DIR
from cc_agent.users.model_cfg import check_name

# 用户目录下存放 skill 的子文件夹名，和 session、model_cfg 同级
USER_SKILL_DIRNAME = "skills"


# 用户目录下存放模型配置的子文件夹名
USER_CFG_DIRNAME = "model_cfg"


def parse_markdown(text):
    """把 SKILL.md 的文本拆成 (元信息字典, 正文)。

    文件格式：
        ---
        name: code-review
        description: 审查 Python 代码时使用
        ---
        （正文，可以很长）

    元信息只支持 "键: 值" 的单行写法，值两端的引号会去掉。
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("SKILL.md 必须以 --- 开头")

    end_index = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end_index = index
            break
    if end_index is None:
        raise ValueError("SKILL.md 开头的元信息缺少结束的 ---")

    meta = {}
    for line in lines[1:end_index]:
        if not line.strip():
            continue
        if ":" not in line:
            raise ValueError(f"元信息格式错误（需要 键: 值）：{line!r}")
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip("\"'")

    content = "\n".join(lines[end_index + 1:]).strip()
    return meta, content


def skill_root_of(belong=None):
    """某个归属对应的 skill 根目录：belong 为 None 是全局目录，否则是该用户自己的 skill 目录。"""
    if belong is None:
        return Path(SKILL_DIR)
    check_name(belong)
    return Path(USER_DIR) / belong / USER_SKILL_DIRNAME

def cfg_root_of(belong=None):
    """某个归属对应的模型配置根目录：belong 为 None 是全局目录，否则是该用户自己的配置目录。"""
    if belong is None:
        return Path(MODEL_CFG_DIR)
    check_name(belong)
    return Path(USER_DIR) / belong / USER_CFG_DIRNAME


class Skill:
    """一个 skill：名字、一句话描述、完整指令正文。

    两种 skill（和 ModelCfg 的全局配置 / 用户配置对应）：
    - 全局 skill：belong 为 None，文件在 SKILL_DIR/<name>/SKILL.md
    - 用户 skill：belong 是 user_name，文件在 USER_DIR/<user_name>/skills/<name>/SKILL.md
    user 的配置要使用全局 skill 时，会复制一份成为自己的用户 skill（见 copy_to_user）。

    落盘规则：
    - 新建出来的对象只在内存里，file_path 为 None
    - 显式调用 save() 才写盘：belong 为 None 写到全局目录，否则写到该用户的 skill 目录；已有同名文件默认不覆盖
    - ModelCfg.skill 里只记名字，真正的内容靠 名字 + 配置的 belong 到对应目录读取

    description 会拼进 system prompt，让模型知道有哪些 skill 可用；
    content 只在模型调用 load_skill 时才返回给模型。
    """

    def __init__(self, name, description, content):
        check_name(name)
        if not description or "\n" in description:
            raise ValueError("description 不能为空，且必须是单行")
        if not content or not content.strip():
            raise ValueError("content 不能为空")
        self.name = name
        self.description = description
        self.content = content.strip()
        self.belong = None
        self.file_path = None

    # ---------- 路径 / 存在性 ----------

    @classmethod
    def path_of(cls, name, belong=None):
        """某个名字在某个归属下的 SKILL.md 路径（不要求文件存在）。"""
        check_name(name)
        return skill_root_of(belong) / name / "SKILL.md"

    @classmethod
    def exists(cls, name, belong=None):
        return cls.path_of(name, belong).is_file()


    # ---------- 文本转换 ----------

    def to_markdown(self):
        return f"---\nname: {self.name}\ndescription: {self.description}\n---\n\n{self.content}\n"

    @classmethod
    def from_markdown(cls, text, name=None):
        """从 SKILL.md 的文本创建对象（只在内存里，belong 为 None）。

        name 优先级：参数 > 元信息里的 name。两者都没有就报错。
        """
        meta, content = parse_markdown(text)
        final_name = name or meta.get("name")
        if not final_name:
            raise ValueError("缺少 name：元信息里没有，也没有通过参数传入")
        if "description" not in meta:
            raise ValueError("元信息里缺少 description")
        return cls(final_name, meta["description"], content)

    @classmethod
    def from_file(cls, file_path, name=None):
        """读取任意位置的 SKILL.md 创建对象（用于导入别处写好的 skill，只在内存里，不会落盘）。

        encoding 用 utf-8-sig：Windows 记事本保存的文件带 BOM，普通 utf-8 会把 BOM 当成正文的一部分。
        """
        with open(file_path, "r", encoding="utf-8-sig") as file:
            text = file.read()
        return cls.from_markdown(text, name)

    # ---------- 复制 / 给用户 ----------

    def copy(self):
        """复制出一个新对象：内容相同，但 belong 为 None、没有 file_path（还没落盘）。"""
        return Skill(self.name, self.description, self.content)

    def copy_to_user(self, user_name):
        """让这个 skill 成为某个用户自己的 skill，返回用户那一份（belong 是 user_name，已落盘）。

        - 用户目录下已有同名 skill：直接读出来复用，不覆盖。用户自己的多个配置可以共用同一个 skill，
          代价是两份内容不同时会沿用用户已有的那份
        - 没有：复制一份写进用户的 skill 目录
        传入的对象本身不会被改动，之后改用户那份不影响原来的。
        """
        if self.exists(self.name, user_name):
            return self.load(self.name, user_name)
        user_skill = self.copy()
        user_skill.belong = user_name
        user_skill.save()
        return user_skill

    # ---------- 持久化 ----------

    def save(self, overwrite=False):
        """belong 为 None 写到全局目录，否则写到该用户的 skill 目录。已有同名文件默认报错，overwrite=True 才覆盖。"""
        if self.belong is not None and not (Path(USER_DIR) / self.belong).is_dir():
            raise FileNotFoundError(f"user not found: {self.belong}")   # 避免给不存在的用户凭空建目录
        target_path = self.path_of(self.name, self.belong)
        if target_path.exists() and not overwrite:
            raise FileExistsError(f"skill already exists: {self.name}")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with open(target_path, "w", encoding="utf-8") as file:
            file.write(self.to_markdown())
        self.file_path = target_path

    @classmethod
    def load(cls, name, belong=None):
        """按名字和归属读出一个 skill。文件夹名当作 name，不信任文件里写的 name。"""
        target_path = cls.path_of(name, belong)
        if not target_path.is_file():
            raise FileNotFoundError(f"skill not found: {name} (belong={belong})")
        skill = cls.from_file(target_path, name=name)
        skill.belong = belong
        skill.file_path = target_path
        return skill


    def list_used_by(self):
        """返回仍然记录着这个 skill 名字的配置名列表。

        只看和这个 skill 同一归属的配置：全局 skill 看全局配置，用户 skill 只看该用户自己的配置。
        直接读 json 里的 skill 字段，不用 ModelCfg.load：加载旧格式的配置会抛 ValueError，
        不能因为一个无关的旧配置文件让查询失败。读不出来的配置文件会打印提示并跳过。
        """
        cfg_names = []
        cfg_root = cfg_root_of(self.belong)
        if not cfg_root.is_dir():
            return cfg_names
        for cfg_path in sorted(cfg_root.glob("*.json")):
            try:
                with open(cfg_path, "r", encoding="utf-8") as file:
                    data = json.load(file)
            except (OSError, json.JSONDecodeError):
                print(f"skip unreadable model_cfg file: {cfg_path}")
                continue
            if not isinstance(data, dict):
                continue
            skill_names = data.get("skill", [])
            if isinstance(skill_names, list) and self.name in skill_names:
                cfg_names.append(cfg_path.stem)
        return cfg_names

    def delete(self):
        """删除 SKILL.md；文件夹里没有别的文件时一并删掉文件夹。

        仍有配置记录着这个名字时拒绝删除（什么都不删），并列出是哪几个配置；
        需要先对这些配置调用 delete_skill，再删除 skill。
        """
        if self.file_path is None:
            raise ValueError("skill is not saved")
        cfg_names = self.list_used_by()
        if cfg_names:
            raise ValueError(
                f"skill {self.name} (belong={self.belong}) is still used by model_cfg: {cfg_names}; "
                "call delete_skill on them first"
            )
        Path(self.file_path).unlink(missing_ok=True)
        try:
            Path(self.file_path).parent.rmdir()   # 文件夹非空（有附加文件）时会失败，保留文件夹
        except OSError:
            pass
        self.file_path = None

    # ---------- 给 Agent 用 ----------

    def prompt_line(self):
        """拼进 system prompt 的一行，如：- code-review: 审查 Python 代码时使用"""
        return f"- {self.name}: {self.description}"




