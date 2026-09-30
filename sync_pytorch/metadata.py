"""metadata 可用性探测与计算平台发现。"""
import json
import logging
import re
import threading
import traceback

from . import http, state
from .config import REQUEST_TIMEOUT, THREAD_COUNT

PLATFORM_SOURCE_URL = (
    "https://raw.githubusercontent.com/pytorch/pytorch.github.io/refs/heads/site/assets/quick-start-module.js"
)


class MetadataCheckThread(threading.Thread):
    """用 HEAD 探测一批 metadata URL 是否可用（200），命中项最终并入下载队列。

    Args:
        thread_index: 线程序号，仅用于进度条描述。
        index_begin: 负责的 state.metadata_check_queue 起始下标（含）。
        index_end: 结束下标（不含）。
        show_progress: 是否用 tqdm 展示进度。
    """

    def __init__(self, thread_index: int, index_begin: int, index_end: int, show_progress: bool) -> None:
        threading.Thread.__init__(self)
        self.thread_index = thread_index
        self.index_begin = index_begin
        self.index_end = index_end
        self.show_progress = show_progress
        # 本线程命中的任务，run() 结束时统一并入 state.download_queue
        self.matched_items: list[dict[str, str | None]] = []

    def run(self) -> None:
        """执行探测：逐条 HEAD 并推进全局计数，最后持锁合并命中任务。"""
        session = http.create_session()
        total = len(state.metadata_check_queue)
        if self.show_progress:
            from tqdm import tqdm
            iterator = tqdm(range(self.index_begin, self.index_end), desc=f"thread #{self.thread_index}", leave=False)
        else:
            iterator = range(self.index_begin, self.index_end)
        for index in iterator:
            item = state.metadata_check_queue[index]
            try:
                if session.head(item["url"], timeout=REQUEST_TIMEOUT).status_code == 200:
                    self.matched_items.append(item)
            except Exception as err:
                logging.warning(f"metadata check failed for {item['url']}: {err}")
                logging.debug(traceback.format_exc())
            # 单条计数：checked 为本条处理后的全局进度
            with state.metadata_progress_lock:
                state.metadata_checked_count += 1
                checked = state.metadata_checked_count
            if checked % 500 == 0 or checked == total:
                logging.info(f"metadata check progress: {checked}/{total}")

        with state.download_queue_lock:
            state.download_queue.extend(self.matched_items)


def check_metadata_availability(show_progress: bool = False) -> None:
    """把 metadata_check_queue 均分给 THREAD_COUNT 个线程做 HEAD 探测。

    Args:
        show_progress: 是否在各线程内用 tqdm 展示进度。
    """
    threads = []
    # 每个线程负责的条数；最后一个线程兜底拿到余数
    items_per_thread = len(state.metadata_check_queue) // THREAD_COUNT
    for i in range(0, THREAD_COUNT, 1):
        thread = MetadataCheckThread(
            i,
            i * items_per_thread,
            (i + 1) * items_per_thread if i != THREAD_COUNT - 1 else len(state.metadata_check_queue),
            show_progress,
        )
        threads.append(thread)
        thread.start()
    for thread in threads:
        thread.join()
    logging.info(f"metadata search finished: checked {len(state.metadata_check_queue)} urls")


def fetch_compute_platforms() -> list[str]:
    """从 PyTorch 官网脚本解析支持的计算平台列表（cpu/cu126/rocm7.2/xpu...）。

    页面中 version_map 形如 {"release": {"2.8.0": ["cuda", "12.6"], ...}}：
    - "cpu" → cpu；
    - "cuda" + X.Y → cuXY（去掉小数点）；
    - 其余（如 "rocm" + "7.2"）直接拼接。

    Returns:
        计算平台名列表；解析失败时返回已收集到的部分（可能为空）。
    """
    platforms = []
    response = http.SESSION.get(PLATFORM_SOURCE_URL, timeout=REQUEST_TIMEOUT)
    # version_map_match.group(1) 为 version_map 的 JSON 文本
    version_map_match = re.search("version_map=({.*})", response.text)
    if version_map_match:
        try:
            version_map = json.loads(version_map_match.group(1))
            for release in version_map["release"].values():
                if release[0] == "cpu":
                    platforms.append("cpu")
                elif release[0] == "cuda":
                    platforms.append("cu" + release[1].replace(".", ""))
                else:
                    platforms.append(release[0] + release[1])
        except Exception as err:
            logging.exception("failed to parse platform info")
            logging.error(traceback.format_exc())
    return platforms
