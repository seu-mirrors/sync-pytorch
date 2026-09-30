"""上一轮文件记录的加载/保存，以及过期文件和空目录清理。"""
import logging
import os
import pickle

from . import state
from .config import BASE_PATH, EXISTED_FILES_PATH


def scan_existing_files():
    # 没有 existed_files.bin 时回退：扫描 whl/ 下除 index.html 外的所有文件，
    # 这样即使没有上一次运行记录，也能清理索引中不再引用的冗余文件。
    existing = set()
    whl_dir = os.path.join(BASE_PATH, "whl")
    if not os.path.isdir(whl_dir):
        return existing
    for root, _dirs, files in os.walk(whl_dir):
        for name in files:
            if name == "index.html":
                continue
            existing.add(os.path.normpath(os.path.join(root, name)))
    return existing


def load_existed_files():
    loaded = None
    if os.path.exists(EXISTED_FILES_PATH) and os.path.isfile(EXISTED_FILES_PATH):
        try:
            with open(EXISTED_FILES_PATH, "rb") as fhandle:
                loaded = pickle.load(fhandle)
        except Exception:
            logging.warning("failed to load existed_files.bin, falling back to filesystem scan")
    if loaded is None:
        state.previous_run_files = scan_existing_files()
        logging.info(f"no usable existed_files.bin; tracking {len(state.previous_run_files)} existing files from filesystem")
        return
    # 路径统一 normpath，避免 BASE_PATH 以 "/" 结尾时 os.path.join 产生的
    # 混合分隔符（Windows 上 \ 与 / 混用）导致与 filesystem 扫描路径不匹配。
    normalize = lambda p: os.path.normpath(p)
    # migrate legacy name->path dict to a set of local paths so a file that
    # lives under multiple platform directories (e.g. filelock under whl/cpu
    # and whl/cu124) is tracked independently for each location.
    if isinstance(loaded, dict):
        state.previous_run_files = {normalize(p) for p in loaded.values()}
    else:
        state.previous_run_files = {normalize(p) for p in loaded}


def remove_outdated_files():
    state.current_run_files.clear()
    for info in state.download_queue:
        state.current_run_files.add(os.path.normpath(info["local_path"]))
    # tracked by local_path, so a file whose location changed between runs (e.g.
    # after a layout migration, or the same filename now served under a different
    # platform directory) is no longer in state.current_run_files: the stale copy at
    # the old path is pruned here, and export_aria2c requeues the new path for download.
    outdated_files = state.previous_run_files - state.current_run_files
    for path in outdated_files:
        try:
            os.remove(path)
            logging.info(f"remove file: {path}")
        except OSError as err:
            logging.warning(f"failed to remove {path}: {err}")


def remove_empty_dirs():
    # walk bottom-up so deleting a leaf dir lets its parent become empty and be
    # removed in the same pass. os.walk caches the dirs list at scandir time, so
    # re-check with os.listdir after children may have been deleted this pass.
    removed = 0
    for root, dirs, files in os.walk(BASE_PATH, topdown=False):
        if os.path.abspath(root) == os.path.abspath(BASE_PATH):
            continue
        if not os.listdir(root):
            try:
                os.rmdir(root)
                removed += 1
                logging.info(f"remove empty dir: {root}")
            except OSError:
                pass
    logging.info(f"removed {removed} empty directories")


def save_state():
    # 没有历史文件时也要写入，否则后续运行无法跟踪上一轮状态、无法清理冗余文件
    if os.path.exists(EXISTED_FILES_PATH + ".old"):
        os.remove(EXISTED_FILES_PATH + ".old")
    if os.path.exists(EXISTED_FILES_PATH):
        os.rename(EXISTED_FILES_PATH, EXISTED_FILES_PATH + ".old")
    with open(EXISTED_FILES_PATH, "wb") as fhandle:
        pickle.dump(state.current_run_files, fhandle)
