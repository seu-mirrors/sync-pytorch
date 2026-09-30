"""一次同步运行中的可变共享状态。"""
import threading

# 待下载任务：{"name": ..., "url": ..., "local_path": ..., "sha256": ...}
download_queue = []
# 待 HEAD 探测可用性的 metadata 任务
metadata_check_queue = []
# 已登记过的 whl 相对路径，避免同一文件被多个平台重复入队
processed_whl_paths = set()
# 上一轮已下载的本地路径集合（normpath）
previous_run_files = set()
# 本轮索引到的本地路径集合（normpath）
current_run_files = set()

download_queue_lock = threading.Lock()
metadata_progress_lock = threading.Lock()
metadata_checked_count = 0
