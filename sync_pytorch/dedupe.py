"""跨平台重复文件的去重与索引 href 重写。"""
import logging
import os
import re
from glob import glob

from . import state
from .config import BASE_PATH, MIRROR_WHL_URL

# 匹配指向 wheelfile 的 href：镜像地址或上游地址，捕获
# group(1)=平台目录，group(2)=文件名，group(3)=#sha256 片段（可选）
WHL_HREF_PATTERN = re.compile(
    r'href="(?:' + re.escape(MIRROR_WHL_URL) + r'|https://download(?:-r2)?\.pytorch\.org/whl)/'
    r'([^"#/]+)/([^"#/]+\.(?:whl|tar\.gz|zip))(#sha256=[0-9a-f]{64})?"'
)


def dedupe_shared_files() -> set[str]:
    """把多个平台重复引用、内容相同的文件收敛到 whl/<filename>。

    判定条件：文件名相同、sha256 相同，且该文件名下的条目 sha 完全一致。
    被改写的条目 local_path 指向 whl/<filename>。

    Returns:
        被去重文件的 sha256 集合，供 rewrite_shared_hrefs 同步改写索引链接；
        没有需要去重的文件时为空集合。
    """
    # {文件名: {sha256: [任务, ...]}}，按内容给同名文件分组
    entries_by_name: dict[str, dict[str, list[dict[str, str | None]]]] = {}
    for entry in state.download_queue:
        name = os.path.basename(entry["local_path"])
        sha256 = entry.get("sha256") or "?"
        entries_by_name.setdefault(name, {}).setdefault(sha256, []).append(entry)

    deduped_shas = set()
    for name, sha_groups in entries_by_name.items():
        entries = [entry for group in sha_groups.values() for entry in group]
        if len(entries) < 2 or len(sha_groups) != 1:
            continue
        # 去重后的统一落盘路径
        canonical = os.path.join(BASE_PATH, "whl", name)
        for entry in entries:
            if entry["local_path"] != canonical:
                entry["local_path"] = canonical
                if entry.get("sha256"):
                    deduped_shas.add(entry["sha256"])
    if deduped_shas:
        logging.info(f"deduplicated {len(deduped_shas)} files referenced by multiple platforms -> whl/<filename>")
    return deduped_shas


def rewrite_shared_hrefs(deduped_shas: set[str]) -> None:
    """把索引页中指向 whl/<platform>/<file> 的去重文件链接改写到 whl/<file>。

    仅改写带 sha256 片段且该 sha 属于 deduped_shas 的链接。

    Args:
        deduped_shas: dedupe_shared_files() 返回的 sha256 集合。
    """
    if not deduped_shas:
        return
    # 被改写的索引文件数
    rewritten = 0
    for index_path in glob(os.path.join(BASE_PATH, "whl", "**", "index.html"), recursive=True):
        with open(index_path, "r") as fhandle:
            text = fhandle.read()

        def repl(match):
            # match.group(2)/group(3) 即 WHL_HREF_PATTERN 捕获的文件名与 sha256 片段
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
