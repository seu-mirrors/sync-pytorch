"""aria2 下载输入导出与下载执行/重试。"""
import logging
import os
import re

from . import state
from .config import ARIA2_INPUT_PATH, BASE_PATH, USER_AGENT


def truncate_file(path):
    open(path, "w").close()


def write_aria2_input():
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


def parse_aria2_length_mismatch_uris(log_path):
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


def load_aria2_input_uri_map(input_path):
    uri_map = {}
    if not os.path.exists(input_path):
        return uri_map
    current_uri = None
    with open(input_path, "r") as fhandle:
        for line in fhandle:
            line = line.rstrip("\n")
            if not line:
                continue
            if line.startswith(" "):
                option = line.lstrip()
                if current_uri is not None and option.startswith("out="):
                    uri_map[current_uri] = option.split("=", 1)[1]
            else:
                current_uri = line
    return uri_map


def cleanup_aria2_partial(uri, uri_map):
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


def perform_download():
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
