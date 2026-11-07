# config.py
from pathlib import Path

# 运行脚本时所在的文件夹（当前工作目录）下，创建 users_data / model_cfg_data
BASE_DIR = Path.cwd()
USER_DIR = BASE_DIR / "users_data"
MODEL_CFG_DIR = BASE_DIR / "model_cfg_data"

MAX_MESSAGES = 300       # 窗口达到这个条数就触发压缩
COMPACT_COUNT = 200      # 压缩时取最旧的多少条


SKILL_DIR = BASE_DIR / "skills_data"












