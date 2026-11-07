import json
import shutil
import uuid
from pathlib import Path
from cc_agent.skill import Skill

# from config import USER_DIR
# from users.model_cfg import ModelCfg, check_name
from cc_agent.config import USER_DIR
from cc_agent.users.model_cfg import ModelCfg, check_name
# 项目根目录下的 users_data/，每个用户一个子文件夹
USERS_ROOT = USER_DIR


def list_json_names(dir_path):
    """返回文件夹下所有 .json 文件的文件名（不含后缀），按修改时间从旧到新。"""
    entries = []
    for file_path in Path(dir_path).glob("*.jsonl"):
        entries.append((file_path.stat().st_mtime, file_path.stem))
    entries.sort()
    names = []
    for mtime, name in entries:
        names.append(name)
    return names


class User:
    """一个用户：session id 列表 + 自己的模型配置名列表。

    USERS_ROOT/<user_name>/<user_name>.json          记录 user_name / session_id / model_cfg
    USERS_ROOT/<user_name>/session/<session_id>.json
    USERS_ROOT/<user_name>/model_cfg/<cfg_name>.json

    session_id 以 session 文件夹的扫描结果为准（open_user 时重新扫描）；
    model_cfg 就是这个用户自己 add 进来的配置名。
    """

    def __init__(self, user_name):
        check_name(user_name)
        self.user_name = user_name
        self.user_dir = Path(USERS_ROOT) / user_name
        self.session_dir = self.user_dir / "session"
        self.model_cfg_dir = self.user_dir / "model_cfg"
        self.user_file = self.user_dir / f"{user_name}.json"
        self.session_id = []
        self.model_cfg = []
        self.skill_dir = self.user_dir / "skills"

    def save(self):
        data = {
            "user_name": self.user_name,
            "session_id": self.session_id,
            "model_cfg": self.model_cfg,
        }
        with open(self.user_file, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)

    # ---------- user 生命周期 ----------

    @classmethod
    def create_user(cls, user_name):
        user = cls(user_name)
        if user.user_dir.exists():
            raise FileExistsError(f"user already exists: {user_name}")
        user.session_dir.mkdir(parents=True)
        user.model_cfg_dir.mkdir(parents=True)
        user.skill_dir.mkdir(parents=True)
        user.save()
        return user

    @classmethod
    def open_user(cls, user_name):
        user = cls(user_name)
        if not user.user_dir.is_dir():
            raise FileNotFoundError(f"user not found: {user_name}")
        user.session_dir.mkdir(parents=True, exist_ok=True)
        user.model_cfg_dir.mkdir(parents=True, exist_ok=True)
        if user.user_file.exists():
            with open(user.user_file, "r", encoding="utf-8") as file:
                data = json.load(file)
            user.model_cfg = data.get("model_cfg", [])
        user.session_id = list_json_names(user.session_dir)
        return user

    @classmethod
    def delete_user(cls, user_name):
        user = cls(user_name)
        if not user.user_dir.is_dir():
            raise FileNotFoundError(f"user not found: {user_name}")
        shutil.rmtree(user.user_dir)

    @classmethod
    def list_user(cls):
        """打印 USERS_ROOT 下已存在的用户（每个子文件夹算一个用户），同时返回用户名列表。"""
        user_names = []
        users_root = Path(USERS_ROOT)
        if users_root.is_dir():
            for user_dir in users_root.iterdir():
                if user_dir.is_dir():
                    user_names.append(user_dir.name)
        user_names.sort()
        if not user_names:
            print("(no users)")
        for user_name in user_names:
            print(user_name)
        return user_names

    # ---------- session ----------

    def new_session(self):
        """新建一个空文件（0 字节）作为 session，登记到 self.session_id，返回新 session 的 id。"""
        session_id = uuid.uuid4().hex
        file_path = self.session_dir / f"{session_id}.jsonl"
        file_path.touch()
        self.session_id.append(session_id)
        self.save()
        return session_id

    def delete_session(self, session_id):
        if session_id not in self.session_id:
            raise KeyError(f"session not found: {session_id}")
        file_path = self.session_dir / f"{session_id}.jsonl"
        file_path.unlink(missing_ok=True)
        self.session_id.remove(session_id)
        self.save()

    def list_session(self):
        """打印当前用户的所有 session id，同时返回 session id 列表的副本。"""
        if not self.session_id:
            print("(no sessions)")
        for session_id in self.session_id:
            print(session_id)
        return list(self.session_id)

    # ---------- model_cfg ----------

    def has_model_cfg(self, cfg_name):
        """配置名是否已被占用：在记录里，或者 model_cfg 文件夹里已有同名文件。"""
        return cfg_name in self.model_cfg or (self.model_cfg_dir / f"{cfg_name}.json").exists()

    # 在用户自己的配置文件夹下创建cfg文件
    def add_model_cfg(self, model_cfg, cfg_name=None):
        """复制传入的配置，作为当前用户自己的配置存进 model_cfg 文件夹，返回配置名。

        配置名默认用 model_cfg.cfg_name，也可以用 cfg_name 参数改名；名字已被占用会报错。
        传入的对象本身不会被改动（全局配置也不会），之后改用户这份不影响原来的。
        """
        if cfg_name is None:
            cfg_name = model_cfg.cfg_name
        else:
            check_name(cfg_name)
        if self.has_model_cfg(cfg_name):
            raise ValueError(f"model_cfg already exists: {cfg_name}")
        user_cfg = model_cfg.copy()
        user_cfg.belong = self.user_name
        user_cfg.cfg_name = cfg_name
        # 传入的配置里记录的 skill 文件在它自己的归属目录里（全局配置在全局目录），用户配置要自己拥有一份
        for skill_name in user_cfg.skill:
            Skill.load(skill_name, model_cfg.belong).copy_to_user(self.user_name)

        user_cfg.file_path = self.model_cfg_dir / f"{cfg_name}.json"
        user_cfg.save()
        self.model_cfg.append(cfg_name)
        self.save()
        return cfg_name

    def list_model_cfg(self):
        """打印当前用户的所有模型配置名，同时返回配置名列表的副本。"""
        if not self.model_cfg:
            print("(no model_cfg)")
        for cfg_name in self.model_cfg:
            print(cfg_name)
        return list(self.model_cfg)

    # 获取用户自己的cfg实例
    def get_model_cfg(self, cfg_name):
        """读出用户自己的一个 ModelCfg 对象，对它调用 add_server / add_tool 等会自动写回文件。"""
        if cfg_name not in self.model_cfg:
            raise KeyError(f"model_cfg not found: {cfg_name}")
        return ModelCfg.load(self.model_cfg_dir / f"{cfg_name}.json")

    def delete_model_cfg(self, cfg_name):
        """删除用户自己的配置：去掉记录并删除文件。"""
        if cfg_name not in self.model_cfg:
            raise KeyError(f"model_cfg not found: {cfg_name}")
        try:
            model_cfg = self.get_model_cfg(cfg_name)
        except FileNotFoundError:
            # 文件已经被手动删掉，只清理记录
            self.forget_model_cfg(cfg_name)
            return
        # model_cfg.delete() 改的是另一个 User 对象并写了 json，当前对象里的记录要自己同步
        model_cfg.delete()
        self.forget_model_cfg(cfg_name)

    def forget_model_cfg(self, cfg_name):
        """只把名字从当前用户的记录里去掉并保存，不碰配置文件；ModelCfg.delete 会调用它。"""
        if cfg_name in self.model_cfg:
            self.model_cfg.remove(cfg_name)
            self.save()
    # ---------- skill ----------

    def list_skill_name(self):
        """打印当前用户拥有的所有 skill 名字，同时返回名字列表。

        不扫描目录：skill 的名字只记在各个 model_cfg 里，这里把用户所有配置里记录的名字合并去重。
        """
        skill_names = []
        for cfg_name in self.model_cfg:
            try:
                model_cfg = self.get_model_cfg(cfg_name)
            except FileNotFoundError:
                continue    # 配置文件被手动删掉了，跳过
            for skill_name in model_cfg.skill:
                if skill_name not in skill_names:
                    skill_names.append(skill_name)
        if not skill_names:
            print("(no skills)")
        for skill_name in skill_names:
            print(skill_name)
        return skill_names


