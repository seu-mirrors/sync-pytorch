"""运行期配置、路径与日志初始化。"""
import logging
import os
import sys

# 同步根目录（TUNASYNC_WORKING_DIR，默认 ./sync_dir），
# 统一以 "/" 结尾，便于后续 os.path.join 拼接
BASE_PATH: str = os.path.abspath(os.getenv("TUNASYNC_WORKING_DIR", default="sync_dir"))
if BASE_PATH[-1] != "/":
    BASE_PATH += "/"

# PyTorch 官方 whl 索引源
UPSTREAM_BASE_URL: str = "https://download.pytorch.org/"
# PyPI JSON API，用于拉取无法从上游下载的包的发布信息
PYPI_JSON_URL: str = "https://pypi.org/pypi/"
# packages that 403 on download.pytorch.org/whl/<platform>/ and must be sourced from PyPI instead
PYPI_REPLACEMENT_PACKAGES: set[str] = {"xformers"}
# metadata 探测线程数
THREAD_COUNT: int = 16
USER_AGENT: str = "Mozilla/5.0 (compatible; sync-pytorch/0.1; +https://github.com/seu-mirrors/sync-pytorch)"
# (connect, read) 秒，避免 requests 默认无限等待
REQUEST_TIMEOUT: tuple[int, int] = (10, 30)

# 对外提供的镜像 whl 地址，用于改写索引页链接、生成安装命令
MIRROR_WHL_URL: str = "https://mirrors.seu.edu.cn/pytorch/whl"

# 运行期产物路径
ARIA2_INPUT_PATH: str = os.path.join(BASE_PATH, "packagelist.txt")
EXISTED_FILES_PATH: str = os.path.join(BASE_PATH, "existed_files.bin")
LOG_PATH: str = os.path.join(BASE_PATH, "script.log")


def ensure_working_dir() -> None:
    """创建同步根目录（已存在时忽略）。"""
    os.makedirs(BASE_PATH, 0o755, exist_ok=True)


def setup_logging() -> None:
    """配置根 logger：DEBUG 写入 script.log 并输出到 stdout，同时压低 urllib3/requests 噪音。"""
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
