#!/usr/bin/env python3
import logging
import os
import sys

from sync_pytorch import config, crawl, dedupe, download, file_state, human_index, metadata, summary


def parse_show_progress():
    if "--show-progress" not in sys.argv:
        return False
    try:
        import tqdm  # noqa: F401
    except Exception:
        print("tqdm not found")
        return False
    return True


def main():
    # ensure umask
    os.umask(0o22)

    config.ensure_working_dir()
    config.setup_logging()

    show_progress = parse_show_progress()
    compute_platforms = metadata.get_platforms()
    human_index.update_human_index(compute_platforms)
    file_state.load_existed_files()
    logging.info(compute_platforms)
    for platform in compute_platforms:
        crawl.update_index(platform)
    metadata.search_metadata(show_progress)
    deduped_shas = dedupe.dedupe_shared_files()
    dedupe.rewrite_shared_hrefs(deduped_shas)
    file_state.remove_outdated_files()
    file_state.remove_empty_dirs()
    download.export_aria2c()
    download.perform_download()
    summary.write_summary()
    file_state.save_state()


if __name__ == "__main__":
    main()
