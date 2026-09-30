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


class search_metadata_thread(threading.Thread):
    def __init__(self, thread_index, index_begin, index_end, show_progress):
        threading.Thread.__init__(self)
        self.thread_index = thread_index
        self.index_begin = index_begin
        self.index_end = index_end
        self.show_progress = show_progress
        self.fetch_list = []

    def run(self):
        thread_session = http.build_session()
        total = len(state.metadata_check_queue)
        if self.show_progress:
            from tqdm import tqdm
            rng = tqdm(range(self.index_begin, self.index_end), desc=f"thread #{self.thread_index}", leave=False)
        else:
            rng = range(self.index_begin, self.index_end)
        for i in rng:
            try:
                if thread_session.head(state.metadata_check_queue[i]["url"], timeout=REQUEST_TIMEOUT).status_code == 200:
                    self.fetch_list.append(state.metadata_check_queue[i])
            except Exception as err:
                logging.warning(f"metadata check failed for {state.metadata_check_queue[i]['url']}: {err}")
                logging.debug(traceback.format_exc())
            with state.metadata_progress_lock:
                state.metadata_checked_count += 1
                checked = state.metadata_checked_count
            if checked % 500 == 0 or checked == total:
                logging.info(f"metadata check progress: {checked}/{total}")

        with state.download_queue_lock:
            state.download_queue.extend(self.fetch_list)


def search_metadata(show_progress=False):
    threads = []
    search_metadata_per_thread = len(state.metadata_check_queue) // THREAD_COUNT
    for i in range(0, THREAD_COUNT, 1):
        thread = search_metadata_thread(
            i,
            i * search_metadata_per_thread,
            (i + 1) * search_metadata_per_thread if i != THREAD_COUNT - 1 else len(state.metadata_check_queue),
            show_progress,
        )
        threads.append(thread)
        thread.start()
    for t in threads:
        t.join()
    logging.info(f"metadata search finished: checked {len(state.metadata_check_queue)} urls")


def get_platforms():
    compute_platforms = []
    response = http.SESSION.get(PLATFORM_SOURCE_URL, timeout=REQUEST_TIMEOUT)
    version_result = re.search("version_map=({.*})", response.text)
    if version_result:
        try:
            version_map = json.loads(version_result.group(1))
            for info in version_map["release"].values():
                if info[0] == "cpu":
                    compute_platforms.append("cpu")
                elif info[0] == "cuda":
                    compute_platforms.append("cu" + info[1].replace(".", ""))
                else:
                    compute_platforms.append(info[0] + info[1])
        except Exception as err:
            logging.exception("failed to parse platform info")
            logging.error(traceback.format_exc())
    return compute_platforms
