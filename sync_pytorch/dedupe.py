"""跨平台重复文件的去重与索引 href 重写。"""
import logging
import os
import re
from glob import glob

from . import state
from .config import BASE_PATH, MIRROR_WHL_URL

WHL_HREF_PATTERN = re.compile(
    r'href="(?:' + re.escape(MIRROR_WHL_URL) + r'|https://download(?:-r2)?\.pytorch\.org/whl)/'
    r'([^"#/]+)/([^"#/]+\.(?:whl|tar\.gz|zip))(#sha256=[0-9a-f]{64})?"'
)


def dedupe_shared_files():
    # 同一内容（同名 + 同 sha256）的文件被多个平台索引引用时，只保留一份
    # 在 whl/<filename>，所有 fetch 条目统一指向它，避免跨平台重复下载。
    entries_by_name = {}
    for entry in state.download_queue:
        name = os.path.basename(entry["local_path"])
        sha256 = entry.get("sha256") or "?"
        entries_by_name.setdefault(name, {}).setdefault(sha256, []).append(entry)

    deduped_shas = set()
    for name, sha_groups in entries_by_name.items():
        entries = [entry for group in sha_groups.values() for entry in group]
        if len(entries) < 2 or len(sha_groups) != 1:
            continue
        canonical = os.path.join(BASE_PATH, "whl", name)
        for entry in entries:
            if entry["local_path"] != canonical:
                entry["local_path"] = canonical
                if entry.get("sha256"):
                    deduped_shas.add(entry["sha256"])
    if deduped_shas:
        logging.info(f"deduplicated {len(deduped_shas)} files referenced by multiple platforms -> whl/<filename>")
    return deduped_shas


def rewrite_shared_hrefs(deduped_shas):
    if not deduped_shas:
        return
    rewritten = 0
    for index_path in glob(os.path.join(BASE_PATH, "whl", "**", "index.html"), recursive=True):
        with open(index_path, "r") as fhandle:
            text = fhandle.read()

        def repl(match):
            filename, fragment = match.group(2), match.group(3)
            if fragment and fragment[len("#sha256="):] in deduped_shas:
                return f'href="{MIRROR_WHL_URL}/{filename}{fragment}"'
            return match.group(0)

        new_text = WHL_HREF_PATTERN.sub(repl, text)
        if new_text != text:
            with open(index_path, "w") as fhandle:
                fhandle.write(new_text)
            rewritten += 1
    logging.info(f"rewrote shared-file hrefs in {rewritten} index files")
