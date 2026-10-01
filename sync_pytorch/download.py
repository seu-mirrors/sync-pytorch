"""aria2 下载输入导出与下载执行/重试。"""
import logging
import os
import re

from . import state
from .config import ARIA2_INPUT_PATH, BASE_PATH, USER_AGENT


def truncate_file(path: str) -> None:
    """清空文件内容（不存在则创建）。"""
    open(path, "w").close()


def write_aria2_input() -> None:
    """把下载队列导出为 aria2c 输入文件（packagelist.txt）。

    - 已存在于上一轮（state.previous_run_files）或已写过的不重复写；
    - 每个任务两行：URL 行 + 缩进的 out=/checksum= 配置行。
    """
    # 已在本次输入文件中出现过的本地路径
    seen_local_paths = set()
    with open(ARIA2_INPUT_PATH, "w") as fhandle:
        for task in state.download_queue:
            # dedupe_shared_files 会把多平台重复的文件统一指向 whl/<filename>，
            # 这里按 local_path 去重，同一份内容只写一条 aria2 任务。
            local_path = os.path.normpath(task["local_path"])
            if local_path in state.previous_run_files or local_path in seen_local_paths:
                continue
            seen_local_paths.add(local_path)
            fhandle.write(task["url"] + "\n" + "    out=" + local_path + "\n")
            if "sha256" in task and task["sha256"]:
                fhandle.write("    checksum=sha-256=" + task["sha256"] + "\n")


def parse_aria2_length_mismatch_uris(log_path: str) -> list[str]:
    """从 aria2 日志中解析出现 "total length mismatch" 的 URI。

    aria2 先在 "errorCode=1 URI=<uri>" 行给出出错的 URI，随后另起一行记录
    中止原因；因此用 last_uri 暂存最近一次错误 URI，遇到 mismatch 行时配对。

    Args:
        log_path: aria2 日志文件路径。

    Returns:
        去重后的 URI 列表；日志不存在时为空列表。
    """
    # uris 为命中的 URI 列表；last_uri 为最近一次 errorCode=1 的 URI
    uris = []
    last_uri = None
    if not os.path.exists(log_path):
        return uris
    with open(log_path, "r", errors="replace") as fhandle:
        for line in fhandle:
            uri_match = re.search(r"errorCode=1 URI=(\S+)", line)
            if uri_match:
                last_uri = uri_match.group(1)
                continue
            if "total length mismatch" in line and last_uri:
                if last_uri not in uris:
                    uris.append(last_uri)
                last_uri = None
    return uris


def load_aria2_input_uri_map(input_path: str) -> dict[str, str]:
    """解析 aria2 输入文件，返回 {URL: 本地 out= 路径} 映射。

    用于按 URI 反查本地文件位置，清理续传残留。

    Args:
        input_path: aria2 输入文件（packagelist.txt）路径。

    Returns:
        URL 到本地路径的映射；文件不存在时为空字典。
    """
    uri_map: dict[str, str] = {}
    if not os.path.exists(input_path):
        return uri_map
    # current_uri 为最近一个任务行（URL）的地址
    current_uri = None
    with open(input_path, "r") as fhandle:
        for line in fhandle:
            line = line.rstrip("\n")
            if not line:
                continue
            if line.startswith(" "):
                # 缩进行为任务配置，如 "    out=/data/xxx.whl"
                option = line.lstrip()
                if current_uri is not None and option.startswith("out="):
                    uri_map[current_uri] = option.split("=", 1)[1]
            else:
                current_uri = line
    return uri_map


def cleanup_aria2_partial(uri: str, uri_map: dict[str, str]) -> bool:
    """删除指定 URI 对应的残缺文件和 .aria2 控制文件。

    Args:
        uri: 出错的下载地址。
        uri_map: load_aria2_input_uri_map() 得到的 URI→本地路径映射。

    Returns:
        是否有文件被删除；URI 无法解析出本地路径或删除失败时返回 False。
    """
    local_path = uri_map.get(uri)
    if not local_path:
        logging.warning(f"could not resolve local path for length-mismatch URI: {uri}")
        return False
    removed = False
    for path in (local_path, local_path + ".aria2"):
        if os.path.exists(path):
            try:
                os.remove(path)
                logging.info(f"removed stale partial file: {path}")
                removed = True
            except OSError as err:
                logging.warning(f"failed to remove {path}: {err}")
    return removed


def perform_download() -> None:
    """调用 aria2c 执行下载，失败时清理断点并重试。

    最多重试 max_attempts 次；若失败由 "total length mismatch" 引起，
    先删除对应残缺文件和 .aria2 控制文件再重试；最终仍失败则以 aria2 的退出码结束进程。
    """
    log_path = os.path.join(BASE_PATH, "aria2.log")
    uri_map = load_aria2_input_uri_map(ARIA2_INPUT_PATH)
    max_attempts = 5
    for attempt in range(1, max_attempts + 1):
        truncate_file(log_path)
        cmd = (
            f"aria2c --check-certificate=false --user-agent=\"{USER_AGENT}\" "
            f"--log-level=info --file-allocation=falloc --lowest-speed-limit=1K "
            f"--check-integrity --max-tries=10 --retry-wait=3 "
            f"-d / -c -l {log_path} -i {ARIA2_INPUT_PATH}"
        )
        logging.info(f"aria2c attempt {attempt}/{max_attempts}")
        status = os.system(cmd)
        if status == 0:
            return
        # mismatch_uris 为本轮因长度不符而失败的 URI 列表
        mismatch_uris = parse_aria2_length_mismatch_uris(log_path)
        if mismatch_uris:
            for uri in mismatch_uris:
                cleanup_aria2_partial(uri, uri_map)
            logging.warning(
                f"aria2c attempt {attempt} failed ({len(mismatch_uris)} "
                f"length-mismatch); removed stale partials; retrying"
            )
            continue
        if attempt < max_attempts:
            logging.warning(f"aria2c attempt {attempt} failed (status={status}); retrying")
            continue
        logging.error(f"aria2c failed after {max_attempts} attempts")
        os._exit(os.waitstatus_to_exitcode(status))
