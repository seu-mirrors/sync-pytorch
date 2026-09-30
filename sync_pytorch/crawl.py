"""爬取上游 PyTorch whl 索引并生成待下载任务。"""
import logging
import os
import re
import traceback
from urllib.parse import unquote, urljoin, urlparse

from . import state
from .config import (
    BASE_PATH,
    MIRROR_WHL_URL,
    PYPI_JSON_URL,
    PYPI_REPLACEMENT_PACKAGES,
    REQUEST_TIMEOUT,
    UPSTREAM_BASE_URL,
)
from .http import SESSION

# 索引页中的 <a href="...">name</a>；group(1)=链接地址，group(2)=链接文本
INDEX_LINK_PATTERN = re.compile(r"<a href=\"(\S*)\".*>(\S*)</a>")
# 平台目录链接 (cpu/ cu126/ rocm7.2/ 等)
PLATFORM_DIR_PATTERN = re.compile(r"^(cpu|cu\d+|rocm[\d.]+)/?$")
# 预发布版本 (dev/a/b/rc)
PRE_RELEASE_PATTERN = re.compile(r"(?:\.dev\d)|(?:[abrc]\d)")


def fetch_pypi_package(pkg_name: str, pkg_local_dir: str) -> None:
    """从 PyPI 拉取包的全部发布文件，并为 cpu 索引生成本地 index.html。

    download.pytorch.org/whl/cpu/<pkg>/ 对所有 wheel 返回 403，
    因此这些包改从 PyPI 获取，但仍登记到 cpu 索引下。

    Args:
        pkg_name: PyPI 包名。
        pkg_local_dir: 包页面的本地目录（whl/cpu/simple/<pkg>）。
    """
    logging.info(f"fetching {pkg_name} from PyPI for cpu index -> {pkg_local_dir}")
    try:
        response = SESSION.get(PYPI_JSON_URL + pkg_name + "/json", timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        # PyPI JSON：{"releases": {版本号: [文件信息, ...], ...}}
        pypi_data = response.json()
    except Exception:
        # PyPI 拉取失败只记录日志并返回，不中断整体同步
        logging.exception(f"failed to fetch {pkg_name} from PyPI")
        logging.error(traceback.format_exc())
        return

    # 过滤后的待下载任务；元素字段见 state.download_queue 注释
    entries = []
    for version, files in pypi_data.get("releases", {}).items():
        if PRE_RELEASE_PATTERN.search(version):
            continue
        for file_info in files:
            if file_info.get("yanked"):
                continue
            if file_info.get("packagetype") not in ("bdist_wheel", "sdist"):
                continue
            filename = file_info["filename"]
            entries.append({
                "name": filename,
                "url": file_info["url"],
                "local_path": os.path.join(pkg_local_dir, filename),
                "sha256": file_info.get("digests", {}).get("sha256"),
                "requires_python": file_info.get("requires_python")
            })

    entries.sort(key=lambda entry: entry["name"])
    os.makedirs(pkg_local_dir, 0o755, exist_ok=True)
    # 本地索引页的 <a> 行
    index_lines = []
    for entry in entries:
        state.download_queue.append(entry)
        logging.debug(f"fetch_info = {entry}")
        # href 带 #sha256= 校验片段；attrs 为可选的 data-requires-python
        href = entry["name"]
        if entry["sha256"]:
            href += f"#sha256={entry['sha256']}"
        attrs = ""
        if entry["requires_python"]:
            attrs += f' data-requires-python="{entry["requires_python"]}"'
        index_lines.append(f'    <a href="{href}"{attrs}>{entry["name"]}</a><br/>')

    index_html = '<!DOCTYPE html>\n<html>\n  <head><meta name="pypi:repository-version" content="1.0"></head>\n  <body>\n    <h1>Links for ' + pkg_name + '</h1>\n' + "\n".join(index_lines) + '\n  </body>\n</html>\n'
    with open(os.path.join(pkg_local_dir, "index.html"), "w") as fhandle:
        fhandle.write(index_html)
    logging.info(f"added {len(entries)} {pkg_name} files from PyPI into cpu index")


def sync_platform_index(platform: str = "") -> None:
    """爬取指定平台的 whl 索引。

    Args:
        platform: 平台名（如 cpu/cu126）；空字符串表示上游根索引 whl/。
    """
    logging.info(f"current platform = {platform}")
    os.makedirs(os.path.join(BASE_PATH, "whl"), 0o755, exist_ok=True)
    local_dir = os.path.join(BASE_PATH, "whl", platform, "simple")

    url = f"{UPSTREAM_BASE_URL}whl/"
    if platform != "":
        url += platform + "/"
    crawl_index_page(url, local_dir, platform)


def enqueue_dist_file(item_name: str, item_url: str, anchor_html: str, platform: str = "") -> None:
    """登记一个文件下载任务，并按需登记其 .metadata 任务。

    处理逻辑：
    - 从 item_url 拆出 #sha256 片段，得到干净的下载地址；
    - PyTorch 系主机（*.pytorch.org）的绝对 URL 改写回 UPSTREAM_BASE_URL 取源
      （R2 镜像可能滞后于 S3，导致 sha256 对不上）；
    - 非 PyTorch 绝对 URL（如 PyPI 回退的 files.pythonhosted.org）保留下载地址，
      但本地路径压平为 whl/<platform>/<filename>；
    - 根相对 URL（/whl/...）补全为绝对地址；
    - anchor_html 带 data-dist-info-metadata 时直接登记 .metadata 下载，
      否则放入 state.metadata_check_queue 等待 HEAD 探测。

    Args:
        item_name: 链接文本，即文件名。
        item_url: 原始链接地址（可能带 #sha256= 片段）。
        anchor_html: 完整 <a ...> 标签，用于提取 metadata 校验值。
        platform: 当前平台名（如 cpu/cu126），根索引为空字符串。
    """
    filename = item_name
    sha256 = None
    download_url = item_url
    if "#" in download_url:
        # url_parts[0] 为去片段后的地址，url_parts[1] 为 sha256 值
        url_parts = download_url.split("#sha256=")
        download_url = url_parts[0]
        sha256 = url_parts[1]
    if item_url.startswith("http://") or item_url.startswith("https://"):
        # absolute URL. Local path is derived from the URL path so wheels land under
        # whl/<platform>/. For PyTorch CDN hosts (e.g. download-r2.pytorch.org) we
        # rewrite the fetch host to UPSTREAM_BASE_URL, because the R2 mirror can lag
        # behind S3 and ship stale wheels whose sha256 no longer matches the index.
        # URLs from other hosts (e.g. files.pythonhosted.org for PyPI-fallback
        # packages) are kept as-is for fetching, but the local path is flattened to
        # whl/<platform>/<filename> so the on-disk layout matches the rest of the
        # index and the rewritten href in index.html resolves on the local mirror.
        parsed_url = urlparse(download_url)
        if parsed_url.hostname and parsed_url.hostname.endswith("pytorch.org"):
            download_url = urljoin(UPSTREAM_BASE_URL, parsed_url.path)
            relative_path = unquote(parsed_url.path)[1:]
        elif platform:
            relative_path = f"whl/{platform}/{unquote(os.path.basename(parsed_url.path))}"
        else:
            relative_path = unquote(parsed_url.path)[1:]
    else:
        # root-relative URL (e.g. /whl/cpu/...): join with UPSTREAM_BASE_URL for fetch.
        relative_path = unquote(download_url)[1:]
        download_url = urljoin(UPSTREAM_BASE_URL, download_url)
    # dedupe by local_path so the same wheel referenced from multiple platform
    # indexes still lands under each platform's directory instead of being skipped
    # after the first encounter (e.g. filelock is referenced by both cpu and cu124).
    # relative_path 为相对 BASE_PATH 的落盘路径（如 whl/cpu/torch-xxx.whl）
    if relative_path in state.processed_whl_paths:
        logging.debug(f"skip processed relative_path = {relative_path}")
        return
    state.processed_whl_paths.add(relative_path)
    # assert filename.endswith(".whl") or filename.endswith(".tar.gz") or filename.endswith(".zip") or filename.endswith(".win32.exe"), f"unexpected extension name (filename = ${filename})"
    state.download_queue.append({
        "name": filename,
        "url": download_url,
        "local_path": os.path.join(BASE_PATH, relative_path),
        "sha256": sha256
    })
    logging.debug(f"fetch_info = {state.download_queue[-1]}")
    # data-dist-info-metadata="sha256=..."：索引已给出 metadata 校验值
    metadata_hash = re.match(r"data-dist-info-metadata=\"sha256=([\S]*)\"", anchor_html)
    if metadata_hash:
        state.download_queue.append({
            "name": filename + ".metadata",
            "url": download_url.replace(".whl", ".whl.metadata").replace(".tar.gz", ".tar.gz.metadata"),
            "local_path": os.path.join(BASE_PATH, relative_path + ".metadata"),
            "sha256": metadata_hash.group(1)
        })
        logging.debug(f"fetch_info = {state.download_queue[-1]}")
    else:
        state.metadata_check_queue.append({
            "name": filename + ".metadata",
            "url": download_url.replace(".whl", ".whl.metadata").replace(".tar.gz", ".tar.gz.metadata"),
            "local_path": os.path.join(BASE_PATH, relative_path + ".metadata")
        })
        logging.debug(f"search_metadata_info = {state.metadata_check_queue[-1]}")


def crawl_index_page(url: str, local_dir: str, platform: str = "") -> None:
    """递归抓取并改写一个上游索引页，解析其中的目录/文件链接。

    - 保存改写后的页面到 local_dir/index.html：把 /whl 与 download-r2 链接
      指向 MIRROR_WHL_URL，并把 PyPI 回退链接压平到 whl/<platform>/<file>；
    - 平台目录链接（cpu/cu126/...）直接跳过；
    - 普通目录递归抓取；cpu 下的 PyPI 替换包改走 fetch_pypi_package；
    - 文件链接交给 enqueue_dist_file 登记。

    出现异常时记录日志并 os._exit(1)，让任务平台感知失败。

    Args:
        url: 上游索引页地址。
        local_dir: 本地保存目录。
        platform: 当前平台名，根索引为空字符串。
    """
    logging.info(f"current url = {url} local_dir = {local_dir}")
    try:
        response = SESSION.get(url, timeout=REQUEST_TIMEOUT)
        if response.status_code != 200:
            logging.info(f"skip non-200 url (status={response.status_code}): {url}")
            return
        # 上游原始页面（解析链接用）；rewritten 为替换镜像地址后的页面（保存用）
        html_content = response.text
        os.makedirs(local_dir, 0o755, exist_ok=True)
        with open(os.path.join(local_dir, "index.html"), "w") as fhandle:
            rewritten = html_content.replace("href=\"/whl", f"href=\"{MIRROR_WHL_URL}")
            rewritten = rewritten.replace("href=\"https://download-r2.pytorch.org/whl", f"href=\"{MIRROR_WHL_URL}")
            if platform:
                # rewrite PyPI-fallback hrefs (e.g. files.pythonhosted.org) to the
                # local mirror so pip resolves them under whl/<platform>/<filename>, which
                # matches the local_path computed in enqueue_dist_file for those URLs.
                rewritten = re.sub(
                    r'href="https://files\.pythonhosted\.org/packages/[^"]*/([^"#]+)(#[^"]*)?"',
                    lambda m: f'href="{MIRROR_WHL_URL}/{platform}/{m.group(1)}{m.group(2) or ""}"',
                    rewritten
                )
            fhandle.write(rewritten)
        # 搜索包或者whl
        search_pos = 0
        # match / next_match 为 INDEX_LINK_PATTERN 的匹配对象
        match = INDEX_LINK_PATTERN.search(html_content, search_pos)
        while match:
            search_pos = match.span(0)[1]
            next_match = INDEX_LINK_PATTERN.search(html_content, search_pos)
            # match.group(1) <-> url
            # eg.
            # certifi/
            # /whl/certifi-2022.12.7-py3-none-any.whl#sha256=4ad3232f5e926d6718ec31cfc1fcadfde020920e278684144551c91769c7bc18
            # /whl/cpu/torch-2.8.0%2Bcpu-cp312-cp312-win_arm64.whl#sha256=99fc421a5d234580e45957a7b02effbf3e1c884a5dd077afc85352c77bf41434

            # match.group(2) <-> name
            # eg.
            # certifi
            # certifi-2022.12.7-py3-none-any.whl

            # anchor_html 为完整 <a ...> 标签（提取 metadata 校验值用）
            anchor_html = match.group(0)
            item_url = match.group(1)
            item_name = match.group(2)
            if PLATFORM_DIR_PATTERN.match(item_url):
                match = next_match
                logging.info(f"skip item_url = {item_url}")
                continue
            if item_url.startswith("/") or item_url.startswith("http://") or item_url.startswith("https://"):
                # whl or archive (root-relative /whl/... or absolute https://host/whl/...)
                enqueue_dist_file(item_name, item_url, anchor_html, platform)
            else:
                # dir
                if platform == "cpu" and item_name in PYPI_REPLACEMENT_PACKAGES:
                    fetch_pypi_package(item_name, os.path.join(local_dir, item_name))
                    match = next_match
                    continue
                crawl_index_page(urljoin(url, item_url), os.path.join(local_dir, item_url), platform)
            match = next_match
    except Exception as err:
        logging.exception("exception occurred")
        logging.error(traceback.format_exc())
        os._exit(1)
