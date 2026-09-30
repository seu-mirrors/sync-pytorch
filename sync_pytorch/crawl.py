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

# 索引页中的 <a href="...">name</a>
INDEX_LINK_PATTERN = re.compile(r"<a href=\"(\S*)\".*>(\S*)</a>")
# 平台目录链接 (cpu/ cu126/ rocm7.2/ 等)
PLATFORM_DIR_PATTERN = re.compile(r"^(cpu|cu\d+|rocm[\d.]+)/?$")
# 预发布版本 (dev/a/b/rc)
PRE_RELEASE_PATTERN = re.compile(r"(?:\.dev\d)|(?:[abrc]\d)")


def fetch_pypi_package(pkg_name, pkg_local_dir):
    # download.pytorch.org/whl/cpu/<pkg>/ returns 403 for every wheel, so pull
    # the package from PyPI instead and serve it under the cpu index.
    logging.info(f"fetching {pkg_name} from PyPI for cpu index -> {pkg_local_dir}")
    try:
        response = SESSION.get(PYPI_JSON_URL + pkg_name + "/json", timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()
    except Exception:
        logging.exception(f"failed to fetch {pkg_name} from PyPI")
        logging.error(traceback.format_exc())
        return

    entries = []
    for version, files in data.get("releases", {}).items():
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

    entries.sort(key=lambda e: e["name"])
    os.makedirs(pkg_local_dir, 0o755, exist_ok=True)
    index_lines = []
    for entry in entries:
        state.download_queue.append(entry)
        logging.debug(f"fetch_info = {entry}")
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


def update_index(platform=""):
    logging.info(f"current platform = {platform}")
    os.makedirs(os.path.join(BASE_PATH, "whl"), 0o755, exist_ok=True)
    local_dir = os.path.join(BASE_PATH, "whl", platform, "simple")

    url = f"{UPSTREAM_BASE_URL}whl/"
    if platform != "":
        url += platform + "/"
    search_package_recursive(url, local_dir, platform)


def process_whl_entry(item_name, item_url, html_label, platform=""):
    whl_name = item_name
    sha256 = None
    whl_url = item_url
    if "#" in whl_url:
        split = whl_url.split("#sha256=")
        whl_url = split[0]
        sha256 = split[1]
    if item_url.startswith("http://") or item_url.startswith("https://"):
        # absolute URL. Local path is derived from the URL path so wheels land under
        # whl/<platform>/. For PyTorch CDN hosts (e.g. download-r2.pytorch.org) we
        # rewrite the fetch host to UPSTREAM_BASE_URL, because the R2 mirror can lag
        # behind S3 and ship stale wheels whose sha256 no longer matches the index.
        # URLs from other hosts (e.g. files.pythonhosted.org for PyPI-fallback
        # packages) are kept as-is for fetching, but the local path is flattened to
        # whl/<platform>/<filename> so the on-disk layout matches the rest of the
        # index and the rewritten href in index.html resolves on the local mirror.
        parsed = urlparse(whl_url)
        if parsed.hostname and parsed.hostname.endswith("pytorch.org"):
            whl_url = urljoin(UPSTREAM_BASE_URL, parsed.path)
            whl_local_path = unquote(parsed.path)[1:]
        elif platform:
            whl_local_path = f"whl/{platform}/{unquote(os.path.basename(parsed.path))}"
        else:
            whl_local_path = unquote(parsed.path)[1:]
    else:
        # root-relative URL (e.g. /whl/cpu/...): join with UPSTREAM_BASE_URL for fetch.
        whl_local_path = unquote(whl_url)[1:]
        whl_url = urljoin(UPSTREAM_BASE_URL, whl_url)
    # dedupe by local_path so the same wheel referenced from multiple platform
    # indexes still lands under each platform's directory instead of being skipped
    # after the first encounter (e.g. filelock is referenced by both cpu and cu124).
    if whl_local_path in state.processed_whl_paths:
        logging.debug(f"skip processed whl_local_path = {whl_local_path}")
        return
    state.processed_whl_paths.add(whl_local_path)
    # assert whl_name.endswith(".whl") or whl_name.endswith(".tar.gz") or whl_name.endswith(".zip") or whl_name.endswith(".win32.exe"), f"unexpected extension name (whl_name = ${whl_name})"
    state.download_queue.append({
        "name": whl_name,
        "url": whl_url,
        "local_path": os.path.join(BASE_PATH, whl_local_path),
        "sha256": sha256
    })
    logging.debug(f"fetch_info = {state.download_queue[-1]}")
    metadata_hash = re.match(r"data-dist-info-metadata=\"sha256=([\S]*)\"", html_label)
    if metadata_hash:
        state.download_queue.append({
            "name": whl_name + ".metadata",
            "url": whl_url.replace(".whl", ".whl.metadata").replace(".tar.gz", ".tar.gz.metadata"),
            "local_path": os.path.join(BASE_PATH, whl_local_path + ".metadata"),
            "sha256": metadata_hash.group(1)
        })
        logging.debug(f"fetch_info = {state.download_queue[-1]}")
    else:
        state.metadata_check_queue.append({
            "name": whl_name + ".metadata",
            "url": whl_url.replace(".whl", ".whl.metadata").replace(".tar.gz", ".tar.gz.metadata"),
            "local_path": os.path.join(BASE_PATH, whl_local_path + ".metadata")
        })
        logging.debug(f"search_metadata_info = {state.metadata_check_queue[-1]}")


def search_package_recursive(url, local_dir, platform=""):
    logging.info(f"current url = {url} local_dir = {local_dir}")
    try:
        response = SESSION.get(url, timeout=REQUEST_TIMEOUT)
        if response.status_code != 200:
            logging.info(f"skip non-200 url (status={response.status_code}): {url}")
            return
        html_content = response.text
        os.makedirs(local_dir, 0o755, exist_ok=True)
        with open(os.path.join(local_dir, "index.html"), "w") as fhandle:
            rewritten = html_content.replace("href=\"/whl", f"href=\"{MIRROR_WHL_URL}")
            rewritten = rewritten.replace("href=\"https://download-r2.pytorch.org/whl", f"href=\"{MIRROR_WHL_URL}")
            if platform:
                # rewrite PyPI-fallback hrefs (e.g. files.pythonhosted.org) to the
                # local mirror so pip resolves them under whl/<platform>/<filename>, which
                # matches the local_path computed in process_whl_entry for those URLs.
                rewritten = re.sub(
                    r'href="https://files\.pythonhosted\.org/packages/[^"]*/([^"#]+)(#[^"]*)?"',
                    lambda m: f'href="{MIRROR_WHL_URL}/{platform}/{m.group(1)}{m.group(2) or ""}"',
                    rewritten
                )
            fhandle.write(rewritten)
        # 搜索包或者whl
        search_pos = 0
        res = INDEX_LINK_PATTERN.search(html_content, search_pos)
        while res:
            search_pos = res.span(0)[1]
            next_res = INDEX_LINK_PATTERN.search(html_content, search_pos)
            # res.group(1) <-> url
            # eg.
            # certifi/
            # /whl/certifi-2022.12.7-py3-none-any.whl#sha256=4ad3232f5e926d6718ec31cfc1fcadfde020920e278684144551c91769c7bc18
            # /whl/cpu/torch-2.8.0%2Bcpu-cp312-cp312-win_arm64.whl#sha256=99fc421a5d234580e45957a7b02effbf3e1c884a5dd077afc85352c77bf41434

            # res.group(2) <-> name
            # eg.
            # certifi
            # certifi-2022.12.7-py3-none-any.whl

            html_label = res.group(0)
            item_url = res.group(1)
            item_name = res.group(2)
            if PLATFORM_DIR_PATTERN.match(item_url):
                res = next_res
                logging.info(f"skip item_url = {item_url}")
                continue
            if item_url.startswith("/") or item_url.startswith("http://") or item_url.startswith("https://"):
                # whl or archive (root-relative /whl/... or absolute https://host/whl/...)
                process_whl_entry(item_name, item_url, html_label, platform)
            else:
                # dir
                if platform == "cpu" and item_name in PYPI_REPLACEMENT_PACKAGES:
                    fetch_pypi_package(item_name, os.path.join(local_dir, item_name))
                    res = next_res
                    continue
                search_package_recursive(urljoin(url, item_url), os.path.join(local_dir, item_url), platform)
            res = next_res
    except Exception as err:
        logging.exception("exception occurred")
        logging.error(traceback.format_exc())
        os._exit(1)
