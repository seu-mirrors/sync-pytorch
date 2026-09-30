"""跨平台重复文件的去重与索引 href 重写。"""
import logging
import os
import re
from glob import glob

from . import state
from .config import BASE_PATH, MIRROR_WHL_URL

_whl_href_pattern = re.compile(
    r'href="(?:' + re.escape(MIRROR_WHL_URL) + r'|https://download(?:-r2)?\.pytorch\.org/whl)/'
    r'([^"#/]+)/([^"#/]+\.(?:whl|tar\.gz|zip))(#sha256=[0-9a-f]{64})?"'
)


def dedupe_shared_files():
    # 同一内容（同名 + 同 sha256）的文件被多个平台索引引用时，只保留一份
    # 在 whl/<filename>，所有 fetch 条目统一指向它，避免跨平台重复下载。
    by_name = {}
    for info in state.download_queue:
        name = os.path.basename(info["local_path"])
        sha = info.get("sha256") or "?"
        by_name.setdefault(name, {}).setdefault(sha, []).append(info)

    deduped_shas = set()
    for name, sha_groups in by_name.items():
        entries = [info for group in sha_groups.values() for info in group]
        if len(entries) < 2 or len(sha_groups) != 1:
            continue
        canonical = os.path.join(BASE_PATH, "whl", name)
        for info in entries:
            if info["local_path"] != canonical:
                info["local_path"] = canonical
                if info.get("sha256"):
                    deduped_shas.add(info["sha256"])
    if deduped_shas:
        logging.info(f"deduplicated {len(deduped_shas)} files referenced by multiple platforms -> whl/<filename>")
    return deduped_shas


def rewrite_shared_hrefs(deduped_shas):
    if not deduped_shas:
        return
    rewritten = 0
    for idx_path in glob(os.path.join(BASE_PATH, "whl", "**", "index.html"), recursive=True):
        with open(idx_path, "r") as fhandle:
            text = fhandle.read()

        def repl(match):
            filename, fragment = match.group(2), match.group(3)
            if fragment and fragment[len("#sha256="):] in deduped_shas:
                return f'href="{MIRROR_WHL_URL}/{filename}{fragment}"'
            return match.group(0)

        new_text = _whl_href_pattern.sub(repl, text)
        if new_text != text:
            with open(idx_path, "w") as fhandle:
                fhandle.write(new_text)
            rewritten += 1
    logging.info(f"rewrote shared-file hrefs in {rewritten} index files")
