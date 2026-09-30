#!/usr/bin/env python3
import logging
import os
import sys

from sync_pytorch import config, crawl, dedupe, download, file_state, human_index, metadata, summary


def parse_show_progress() -> bool:
    """解析 --show-progress 参数；tqdm 不可用时提示并关闭进度条。"""
    if "--show-progress" not in sys.argv:
        return False
    try:
        import tqdm  # noqa: F401
    except Exception:
        print("tqdm not found")
        return False
    return True


def main() -> None:
    """执行一次完整同步。

    流程：初始化环境 → 平台发现 → 人类可读索引 → 爬取各平台索引 →
    metadata 探测 → 跨平台去重与链接改写 → 清理过期文件/空目录 →
    导出并执行 aria2 下载 → 输出摘要并持久化状态。
    """
    # ensure umask
    os.umask(0o22)

    config.ensure_working_dir()
    config.setup_logging()

    show_progress = parse_show_progress()
    platforms = metadata.fetch_compute_platforms()
    human_index.update_human_index(platforms)
    file_state.load_previous_run_files()
    logging.info(platforms)
    for platform in platforms:
        crawl.sync_platform_index(platform)
    metadata.check_metadata_availability(show_progress)
    deduped_shas = dedupe.dedupe_shared_files()
    dedupe.rewrite_shared_hrefs(deduped_shas)
    file_state.prune_stale_files()
    file_state.prune_empty_dirs()
    download.write_aria2_input()
    download.perform_download()
    summary.write_summary()
    file_state.save_state()


if __name__ == "__main__":
    main()
