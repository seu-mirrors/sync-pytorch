"""运行期配置、路径与日志初始化。"""
import logging
import os
import sys

# 同步路径
BASE_PATH = os.path.abspath(os.getenv("TUNASYNC_WORKING_DIR", default="sync_dir"))
if BASE_PATH[-1] != "/":
    BASE_PATH += "/"

UPSTREAM_BASE_URL = "https://download.pytorch.org/"
PYPI_JSON_URL = "https://pypi.org/pypi/"
# packages that 403 on download.pytorch.org/whl/<platform>/ and must be sourced from PyPI instead
PYPI_REPLACEMENT_PACKAGES = {"xformers"}
THREAD_COUNT = 16  # 线程数量
USER_AGENT = "Mozilla/5.0 (compatible; sync-pytorch/0.1; +https://github.com/seu-mirrors/sync-pytorch)"
REQUEST_TIMEOUT = (10, 30)  # (connect, read) 秒，避免 requests 默认无限等待

MIRROR_WHL_URL = "https://mirrors.seu.edu.cn/pytorch/whl"

# 运行期产物路径
ARIA2_INPUT_PATH = os.path.join(BASE_PATH, "packagelist.txt")
EXISTED_FILES_PATH = os.path.join(BASE_PATH, "existed_files.bin")
LOG_PATH = os.path.join(BASE_PATH, "script.log")


def ensure_working_dir():
    os.makedirs(BASE_PATH, 0o755, exist_ok=True)


def setup_logging():
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        filename=LOG_PATH,
        filemode="w",
    )
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logging.getLogger().addHandler(console_handler)
    # requests 底层 urllib3 的 DEBUG/INFO 噪音（连接、HTTP 状态等）不写入输出
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
