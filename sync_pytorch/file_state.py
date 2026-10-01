"""上一轮文件记录的加载/保存，以及过期文件和空目录清理。"""
import logging
import os
import pickle

from . import state
from .config import BASE_PATH, EXISTED_FILES_PATH


def scan_existing_files() -> set[str]:
    """扫描 whl/ 下除 index.html 外的所有文件。

    用于 existed_files.bin 缺失/损坏时的兜底：即使没有上一轮记录，
    也能掌握现存文件、清理索引中不再引用的冗余文件。

    Returns:
        normpath 规范化后的绝对路径集合。
    """
    existing = set()
    whl_dir = os.path.join(BASE_PATH, "whl")
    if not os.path.isdir(whl_dir):
        return existing
    for root, _dirs, filenames in os.walk(whl_dir):
        for name in filenames:
            if name == "index.html":
                continue
            existing.add(os.path.normpath(os.path.join(root, name)))
    return existing


def load_previous_run_files() -> None:
    """加载上一轮的 existed_files.bin，写入 state.previous_run_files。

    兼容两种历史格式：
    - set[str]：上一轮记录的本地路径集合；
    - dict[str, str]：更早版本的 {文件名: 路径} 映射，取 values 迁移为集合。
    文件缺失、损坏或类型不符时回退到 scan_existing_files()。
    """
    # pickle 反序列化结果：dict（旧格式）/ set（现格式）/ None（加载失败）
    loaded: dict[str, str] | set[str] | None = None
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


def prune_stale_files() -> None:
    """删除上一轮存在、但本轮索引不再引用的本地文件。

    同时把 state.current_run_files 刷新为本轮所有任务的 local_path，
    供运行结束时的 save_state() 持久化。
    """
    state.current_run_files.clear()
    for entry in state.download_queue:
        state.current_run_files.add(os.path.normpath(entry["local_path"]))
    # tracked by local_path, so a file whose location changed between runs (e.g.
    # after a layout migration, or the same filename now served under a different
    # platform directory) is no longer in state.current_run_files: the stale copy at
    # the old path is pruned here, and write_aria2_input requeues the new path for download.
    # stale_files 为待删除的旧路径集合
    stale_files = state.previous_run_files - state.current_run_files
    for path in stale_files:
        try:
            os.remove(path)
            logging.info(f"remove file: {path}")
        except OSError as err:
            logging.warning(f"failed to remove {path}: {err}")


def prune_empty_dirs() -> None:
    """自底向上删除 BASE_PATH 下的空目录（不含 BASE_PATH 本身）。"""
    # walk bottom-up so deleting a leaf dir lets its parent become empty and be
    # removed in the same pass. os.walk caches the dirs list at scandir time, so
    # re-check with os.listdir after children may have been deleted this pass.
    removed = 0
    for root, _dirs, _files in os.walk(BASE_PATH, topdown=False):
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


def save_state() -> None:
    """把本轮文件集合写入 existed_files.bin，原文件轮转为 .old。

    即使集合为空也必须写入，否则后续运行无法跟踪上一轮状态、无法清理冗余文件。
    """
    if os.path.exists(EXISTED_FILES_PATH + ".old"):
        os.remove(EXISTED_FILES_PATH + ".old")
    if os.path.exists(EXISTED_FILES_PATH):
        os.rename(EXISTED_FILES_PATH, EXISTED_FILES_PATH + ".old")
    with open(EXISTED_FILES_PATH, "wb") as fhandle:
        pickle.dump(state.current_run_files, fhandle)
