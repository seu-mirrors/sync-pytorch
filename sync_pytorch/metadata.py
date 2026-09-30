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
    def __init__(self, thread_index, index_begin, index_end, show_progress):
        threading.Thread.__init__(self)
        self.thread_index = thread_index
        self.index_begin = index_begin
        self.index_end = index_end
        self.show_progress = show_progress
        self.matched_items = []

    def run(self):
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
            with state.metadata_progress_lock:
                state.metadata_checked_count += 1
                checked = state.metadata_checked_count
            if checked % 500 == 0 or checked == total:
                logging.info(f"metadata check progress: {checked}/{total}")

        with state.download_queue_lock:
            state.download_queue.extend(self.matched_items)


def check_metadata_availability(show_progress=False):
    threads = []
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


def fetch_compute_platforms():
    platforms = []
    response = http.SESSION.get(PLATFORM_SOURCE_URL, timeout=REQUEST_TIMEOUT)
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
