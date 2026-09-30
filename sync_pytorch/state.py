"""一次同步运行中的可变共享状态。

只保存跨函数/跨线程共享的数据，避免各处再声明全局变量。
"""
import threading

# 待下载任务列表，元素为 dict：
#   name (str)            文件名（日志/展示用）
#   url (str)             下载地址
#   local_path (str)      本地绝对落地路径
#   sha256 (str | None)   校验值，metadata 探测任务可能没有
# PyPI 回退任务额外带 requires_python (str | None)。
# 由 crawl 主线程写入，metadata 线程持有 download_queue_lock 追加。
download_queue: list[dict[str, str | None]] = []

# 待用 HEAD 探测可用性的 metadata 任务，元素字段：
#   name (str)、url (str)、local_path (str)
metadata_check_queue: list[dict[str, str | None]] = []

# 已登记过的文件相对路径（相对 BASE_PATH，如 whl/cpu/torch-xxx.whl），
# 避免同一文件被多个平台重复入队
processed_whl_paths: set[str] = set()

# 上一轮已下载的本地路径集合（os.path.normpath 规范化后的绝对路径）
previous_run_files: set[str] = set()

# 本轮索引到的本地路径集合（os.path.normpath 规范化后的绝对路径），
# 运行结束时由 save_state() 写入 existed_files.bin
current_run_files: set[str] = set()

# 保护 download_queue 的跨线程追加
download_queue_lock = threading.Lock()
# 保护 metadata_checked_count 的并发自增
metadata_progress_lock = threading.Lock()
# 已完成的 metadata 探测计数（多线程共享）
metadata_checked_count: int = 0
