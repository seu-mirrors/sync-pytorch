#!/usr/bin/env python3
import requests
from urllib.parse import unquote, urljoin, urlparse
import pickle # todo: 加入签名保证安全性
import os
import sys
import re
import json
import threading
from glob import glob
from requests.adapters import HTTPAdapter
import traceback
import logging

SHOW_PROGRESS = False
if "--show-progress" in sys.argv and __name__ == "__main__":
    SHOW_PROGRESS = True

if SHOW_PROGRESS:
    try:
        from tqdm import tqdm
    except:
        print("tqdm not found")
        SHOW_PROGRESS = False

base_path = os.path.abspath(os.getenv("TUNASYNC_WORKING_DIR", default = "sync_dir")) #同步路径
if base_path[-1] != "/":
    base_path += "/"
base_url = "https://download.pytorch.org/"
pypi_json_url = "https://pypi.org/pypi/"
# packages that 403 on download.pytorch.org/whl/<platform>/ and must be sourced from PyPI instead
pypi_replacement_packages = {"xformers"}
pre_release_pattern = re.compile(r'(?:\.dev\d)|(?:[abrc]\d)')
compute_platforms = []
threads_count = 16 #线程数量
user_agent = "Mozilla/5.0 (compatible; sync-pytorch/0.1; +https://github.com/seu-mirrors/sync-pytorch)"

existed_files = set() # set of local_path downloaded last run
current_files = set() # set of local_path seen this run
is_whl_processed = set()
re_pattern = re.compile(r"<a href=\"(\S*)\".*>(\S*)</a>")
fetch_list = []
search_metadata_list = []
fetch_list_lock = threading.Lock()
pkglist = os.path.join(base_path, "packagelist.txt")

session = requests.Session()
session.mount('http://', HTTPAdapter(max_retries=10, pool_connections = threads_count, pool_maxsize = threads_count))
session.mount('https://', HTTPAdapter(max_retries=10, pool_connections = threads_count, pool_maxsize = threads_count))
session.headers.update({"User-Agent": user_agent})

truncate = lambda path: open(path, "w").close()

os.makedirs(base_path, 0o755, True)
logging.basicConfig(
    level = logging.DEBUG,
    format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt = "%Y-%m-%d %H:%M:%S",
    filename = os.path.join(base_path, 'script.log'),
    filemode = "w"
)
_console_handler = logging.StreamHandler(sys.stdout)
_console_handler.setLevel(logging.DEBUG)
_console_handler.setFormatter(logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt = "%Y-%m-%d %H:%M:%S"
))
logging.getLogger().addHandler(_console_handler)
# requests 底层 urllib3 的 DEBUG/INFO 噪音（连接、HTTP 状态等）不写入输出
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("requests").setLevel(logging.WARNING)

class search_metadata_thread(threading.Thread):
    def __init__(self, thread_index, index_begin, index_end):
        threading.Thread.__init__(self)
        self.thread_index = thread_index
        self.index_begin = index_begin
        self.index_end = index_end
        self.fetch_list = []
    def run(self):
        rng = None
        if SHOW_PROGRESS:
            rng = tqdm(range(self.index_begin, self.index_end), desc = f"thread #{self.thread_index}", leave = False)
        else:
            rng = range(self.index_begin, self.index_end)
        for i in rng:
            try:
                if session.head(search_metadata_list[i]["url"]).status_code == 200:
                    self.fetch_list.append(search_metadata_list[i])
            except Exception as err:
                logging.exception("network error")
                logging.error(traceback.format_exc())
                os._exit(1)

        with fetch_list_lock:
            fetch_list.extend(self.fetch_list)

def scan_existing_files():
    # 没有 existed_files.bin 时回退：扫描 whl/ 下除 index.html 外的所有文件，
    # 这样即使没有上一次运行记录，也能清理索引中不再引用的冗余文件。
    existing = set()
    whl_dir = os.path.join(base_path, "whl")
    if not os.path.isdir(whl_dir):
        return existing
    for root, _dirs, files in os.walk(whl_dir):
        for name in files:
            if name == "index.html":
                continue
            existing.add(os.path.normpath(os.path.join(root, name)))
    return existing

def load_existed_files():
    global existed_files
    existed_files_info_path = os.path.join(base_path, "existed_files.bin")
    loaded = None
    if os.path.exists(existed_files_info_path) and os.path.isfile(existed_files_info_path):
        try:
            with open(existed_files_info_path, "rb") as fhandle:
                loaded = pickle.load(fhandle)
        except Exception:
            logging.warning("failed to load existed_files.bin, falling back to filesystem scan")
    if loaded is None:
        existed_files = scan_existing_files()
        logging.info(f"no usable existed_files.bin; tracking {len(existed_files)} existing files from filesystem")
        return
    # 路径统一 normpath，避免 base_path 以 "/" 结尾时 os.path.join 产生的
    # 混合分隔符（Windows 上 \ 与 / 混用）导致与 filesystem 扫描路径不匹配。
    normalize = lambda p: os.path.normpath(p)
    # migrate legacy name->path dict to a set of local paths so a file that
    # lives under multiple platform directories (e.g. filelock under whl/cpu
    # and whl/cu124) is tracked independently for each location.
    if isinstance(loaded, dict):
        existed_files = {normalize(p) for p in loaded.values()}
    else:
        existed_files = {normalize(p) for p in loaded}

def fetch_pypi_package(pkg_name, pkg_local_dir):
    # download.pytorch.org/whl/cpu/<pkg>/ returns 403 for every wheel, so pull
    # the package from PyPI instead and serve it under the cpu index.
    logging.info(f"fetching {pkg_name} from PyPI for cpu index -> {pkg_local_dir}")
    try:
        response = session.get(pypi_json_url + pkg_name + "/json")
        response.raise_for_status()
        data = response.json()
    except Exception:
        logging.exception(f"failed to fetch {pkg_name} from PyPI")
        logging.error(traceback.format_exc())
        return

    entries = []
    for version, files in data.get("releases", {}).items():
        if pre_release_pattern.search(version):
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
    os.makedirs(pkg_local_dir, 0o755, True)
    index_lines = []
    for entry in entries:
        fetch_list.append(entry)
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

def update_index(platform = ""):
    logging.info(f"current platform = {platform}")
    os.makedirs(os.path.join(base_path, "whl"), 0o755, True)
    local_dir = os.path.join(base_path, "whl", platform, "simple")

    url = f"{base_url}whl/"
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
        # rewrite the fetch host to base_url, because the R2 mirror can lag behind S3
        # and ship stale wheels whose sha256 no longer matches the index. URLs from
        # other hosts (e.g. files.pythonhosted.org for PyPI-fallback packages) are
        # kept as-is for fetching, but the local path is flattened to
        # whl/<platform>/<filename> so the on-disk layout matches the rest of the
        # index and the rewritten href in index.html resolves on the local mirror.
        parsed = urlparse(whl_url)
        if parsed.hostname and parsed.hostname.endswith("pytorch.org"):
            whl_url = urljoin(base_url, parsed.path)
            whl_local_path = unquote(parsed.path)[1:]
        elif platform:
            whl_local_path = f"whl/{platform}/{unquote(os.path.basename(parsed.path))}"
        else:
            whl_local_path = unquote(parsed.path)[1:]
    else:
        # root-relative URL (e.g. /whl/cpu/...): join with base_url for fetch.
        whl_local_path = unquote(whl_url)[1:]
        whl_url = urljoin(base_url, whl_url)
    # dedupe by local_path so the same wheel referenced from multiple platform
    # indexes still lands under each platform's directory instead of being skipped
    # after the first encounter (e.g. filelock is referenced by both cpu and cu124).
    if whl_local_path in is_whl_processed:
        logging.debug(f"skip processed whl_local_path = {whl_local_path}")
        return
    is_whl_processed.add(whl_local_path)
    # assert whl_name.endswith(".whl") or whl_name.endswith(".tar.gz") or whl_name.endswith(".zip") or whl_name.endswith(".win32.exe"), f"unexpected extension name (whl_name = ${whl_name})"
    fetch_list.append({
        "name" : whl_name,
        "url" : whl_url,
        "local_path" : os.path.join(base_path, whl_local_path),
        "sha256" : sha256
    })
    logging.debug(f"fetch_info = {fetch_list[-1]}")
    metadata_hash = re.match(r"data-dist-info-metadata=\"sha256=([\S]*)\"", html_label)
    if metadata_hash:
        fetch_list.append({
            "name" : whl_name + ".metadata",
            "url" : whl_url.replace(".whl", ".whl.metadata").replace(".tar.gz", ".tar.gz.metadata"),
            "local_path" : os.path.join(base_path, whl_local_path + ".metadata"),
            "sha256" : metadata_hash.group(1)
        })
        logging.debug(f"fetch_info = {fetch_list[-1]}")
    else:
        search_metadata_list.append({
            "name" : whl_name + ".metadata",
            "url" : whl_url.replace(".whl", ".whl.metadata").replace(".tar.gz", ".tar.gz.metadata"),
            "local_path" : os.path.join(base_path, whl_local_path + ".metadata")
        })
        logging.debug(f"search_metadata_info = {search_metadata_list[-1]}")

def search_package_recursive(url, local_dir, platform = ""):
    logging.info(f"current url = {url} local_dir = {local_dir}")
    try:
        response = session.get(url)
        if response.status_code != 200:
            logging.info(f"skip non-200 url (status={response.status_code}): {url}")
            return
        html_content = response.text
        os.makedirs(local_dir, 0o755, True)
        with open(os.path.join(local_dir, "index.html"), "w") as fhandle:
            rewritten = html_content.replace("href=\"/whl", "href=\"https://mirrors.seu.edu.cn/pytorch/whl")
            rewritten = rewritten.replace("href=\"https://download-r2.pytorch.org/whl", "href=\"https://mirrors.seu.edu.cn/pytorch/whl")
            if platform:
                # rewrite PyPI-fallback hrefs (e.g. files.pythonhosted.org) to the
                # local mirror so pip resolves them under whl/<platform>/<filename>, which
                # matches the local_path computed in process_whl_entry for those URLs.
                rewritten = re.sub(
                    r'href="https://files\.pythonhosted\.org/packages/[^"]*/([^"#]+)(#[^"]*)?"',
                    lambda m: f'href="https://mirrors.seu.edu.cn/pytorch/whl/{platform}/{m.group(1)}{m.group(2) or ""}"',
                    rewritten
                )
            fhandle.write(rewritten)
        # 搜索包或者whl
        search_pos = 0
        res = re_pattern.search(html_content, search_pos)
        while res:
            search_pos = res.span(0)[1]
            next_res = re_pattern.search(html_content, search_pos)
            # res.group(1) <-> url
            # eg.
            # certifi/
            # /whl/certifi-2022.12.7-py3-none-any.whl#sha256=4ad3232f5e926d6718ec31cfc1fcadfde020920e278684144551c91769c7bc18
            # /whl/cpu/torch-2.8.0%2Bcpu-cp312-cp312-win_arm64.whl#sha256=99fc421a5d234580e45957a7b02effbf3e1c884a5dd077afc85352c77bf41434

            # res.group(2) <-> name
            # eg.
            # certifi
            # certifi-2022.12.7-py3-none-any.whl

            # 过滤url: 平台目录链接 (cpu/ cu126/ rocm7.2/ 等)
            pattern_str = r'^(cpu|cu\d+|rocm[\d.]+)/?$'
            # item_url = unquote(res.group(1))
            html_label = res.group(0)
            # logging.debug(html_label)
            item_url = res.group(1)
            item_name = res.group(2)
            if re.match(pattern_str, item_url):
                res = next_res
                logging.info(f"skip item_url = {item_url}")
                continue
            if item_url.startswith("/") or item_url.startswith("http://") or item_url.startswith("https://"):
                # whl or archive (root-relative /whl/... or absolute https://host/whl/...)
                process_whl_entry(item_name, item_url, html_label, platform)
            else:
                # dir
                if platform == "cpu" and item_name in pypi_replacement_packages:
                    fetch_pypi_package(item_name, os.path.join(local_dir, item_name))
                    res = next_res
                    continue
                search_package_recursive(urljoin(url, item_url), os.path.join(local_dir, item_url), platform)
            res = next_res
    except Exception as err:
        logging.exception("exception occurred")
        logging.error(traceback.format_exc())
        os._exit(1)

def search_metadata():
    threads = []
    search_metadata_per_thread = len(search_metadata_list) // threads_count
    for i in range(0, threads_count, 1):
        thread = search_metadata_thread(i, i * search_metadata_per_thread, (i + 1) * search_metadata_per_thread if i != threads_count - 1 else len(search_metadata_list))
        threads.append(thread)
        thread.start()
    for t in threads:
        t.join()

def get_platforms():
    response = session.get("https://raw.githubusercontent.com/pytorch/pytorch.github.io/refs/heads/site/assets/quick-start-module.js")
    version_result = re.search("version_map=({.*})", response.text)
    if version_result:
        try:
            version_map = json.loads(version_result.group(1))
            for info in version_map["release"].values() :
                if info[0] == "cpu":
                    compute_platforms.append("cpu")
                elif info[0] == "cuda":
                    compute_platforms.append("cu" + info[1].replace(".", ""))
                else:
                    compute_platforms.append(info[0] + info[1])
        except Exception as err:
            logging.exception("failed to parse platform info")
            logging.error(traceback.format_exc())
        
SEU_MIRROR_URL = "https://mirrors.seu.edu.cn/pytorch/whl"

HUMAN_INDEX_CSS = """    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
      max-width: 960px;
      margin: 2rem auto;
      padding: 0 1rem;
      line-height: 1.65;
      color: #1f2328;
      background: #fff;
    }
    h1 { font-size: 1.55rem; margin: 0 0 0.5rem; }
    h2 { font-size: 1.2rem; margin: 1.6rem 0 0.6rem; padding-bottom: 0.3rem; border-bottom: 1px solid #d0d7de; }
    h3 { font-size: 1.05rem; margin: 1.2rem 0 0.4rem; }
    p { margin: 0.5rem 0; }
    code {
      font-family: ui-monospace, SFMono-Regular, Consolas, "Liberation Mono", Menlo, monospace;
      background: #f6f8fa;
      padding: 0.15em 0.4em;
      border-radius: 4px;
      font-size: 0.9em;
    }
    pre {
      background: #f6f8fa;
      border: 1px solid #d0d7de;
      border-radius: 6px;
      padding: 0.8rem 1rem;
      overflow-x: auto;
      margin: 0.5rem 0;
    }
    pre code { background: none; padding: 0; font-size: 0.9rem; }
    table { border-collapse: collapse; width: 100%; margin: 0.8rem 0; }
    th, td { border: 1px solid #d0d7de; padding: 0.45rem 0.7rem; text-align: left; vertical-align: top; }
    th { background: #f6f8fa; }
    a { color: #0969da; text-decoration: none; }
    a:hover { text-decoration: underline; }
    ul.platforms { list-style: none; display: flex; flex-wrap: wrap; gap: 0.4rem 0.6rem; padding: 0; margin: 0.5rem 0; }
    ul.platforms li { margin: 0; }
    ul.platforms li a {
      display: inline-block; padding: 0.25rem 0.7rem; border: 1px solid #d0d7de;
      border-radius: 999px; font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
    }
    blockquote { margin: 0.8rem 0; padding: 0.4rem 1rem; border-left: 4px solid #d0d7de; color: #57606a; }
    .copy-btn {
      font: inherit; padding: 0.25rem 0.8rem; border: 1px solid #d0d7de;
      border-radius: 6px; background: #fff; cursor: pointer; color: #24292f;
    }
    .copy-btn:hover { background: #f6f8fa; }
    .copy-btn.copied { color: #1a7f37; border-color: #1a7f37; }
    .footer { margin-top: 2rem; padding-top: 0.8rem; border-top: 1px solid #d0d7de; font-size: 0.9rem; color: #57606a; }"""

HUMAN_INDEX_JS = """    function copyCmd(id, btn) {
      const code = document.getElementById(id).textContent;
      const done = function() {
        const orig = btn.textContent;
        btn.textContent = "已复制 ✓";
        btn.classList.add("copied");
        setTimeout(function() { btn.textContent = orig; btn.classList.remove("copied"); }, 1500);
      };
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(code).then(done).catch(function() { fallback(code, done); });
      } else {
        fallback(code, done);
      }
    }
    function fallback(text, done) {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.left = "-9999px";
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand("copy"); } catch (e) {}
      document.body.removeChild(ta);
      done();
    }"""

# 人类可读的总览索引页（whl/index.html）
TOP_INDEX_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>SEU 镜像站 · PyTorch 索引</title>
  <style>
__CSS__
  </style>
</head>
<body>
  <h1>SEU 镜像站 · PyTorch 索引</h1>
  <p>符合 <a href="https://peps.python.org/pep-0503/">PEP 503</a> 标准、面向 <a href="https://pytorch.org/">PyTorch</a> 的索引。数据由 <a href="https://download.pytorch.org/whl/">https://download.pytorch.org/whl/</a> 同步而来。</p>

  <h2>选择计算平台</h2>
  <ul class="platforms">
__PLATFORM_LIST__
  </ul>

  <h2>我怎么选择 PyTorch 版本？</h2>
  <p>选择合适索引的关键是看你的显卡和加速 SDK 的版本号。流程如下：</p>

  <h3>1. 查看显卡类型与 SDK 版本</h3>
  <ul>
    <li><strong>NVIDIA 显卡</strong>：在终端执行 <code>nvidia-smi</code>，查看输出右上角的 <code>CUDA Version: X.Y</code>（即当前 NVIDIA 驱动所支持的 CUDA Runtime 最大版本）。示例如下：</li>
  </ul>
  <pre><code>+-----------------------------------------------------------------------------+
| NVIDIA-SMI 535.171.04   Driver Version: 535.171.04   CUDA Version: 12.6   |
+-------------------------------+----------------------+----------------------+
|   ...                         | ...                  | ...                  |
+-------------------------------+----------------------+----------------------+</code></pre>
  <ul>
    <li><strong>AMD 显卡</strong>：执行 <code>rocminfo</code> 查看所安装的 ROCm 版本。</li>
    <li><strong>无 GPU，或不使用 GPU 加速</strong>：选择 <code>cpu</code> 即可。</li>
  </ul>

  <h3>2. 根据版本选择索引</h3>
  <table>
    <thead>
      <tr><th>硬件 / 加速 SDK</th><th>对应的索引名</th></tr>
    </thead>
    <tbody>
      <tr><td>无 GPU / 不使用加速</td><td><code>cpu</code></td></tr>
      <tr><td>NVIDIA 显卡 + CUDA Runtime X.Y</td><td><code>cu</code> 后接去掉小数点的 X.Y<br>（CUDA 12.6 → <code>cu126</code>；CUDA 13.0 → <code>cu130</code>；CUDA 13.2 → <code>cu132</code>）</td></tr>
      <tr><td>AMD 显卡 + ROCm X.Y</td><td><code>rocm</code> 后接 X.Y<br>（ROCm 7.2 → <code>rocm7.2</code>）</td></tr>
    </tbody>
  </table>
  <p>从上方列表点进对应索引页，内有 <code>pip</code> / <code>uv</code> / <code>conda</code> / <code>mamba</code> 的安装命令以及“复制命令”按钮。</p>
  <blockquote>提示：PyTorch 的 <code>cuXXX</code> 包内已自带 CUDA Runtime 动态库，通常无需单独安装 CUDA Toolkit；但需保证 NVIDIA 显卡驱动版本支持对应的 CUDA Runtime 版本（参考 <code>nvidia-smi</code> 输出的 <code>Driver Version</code> 与 <code>CUDA Version</code>，或 <a href="https://docs.nvidia.com/cuda/cuda-toolkit-release-notes/index.html#cuda-major-component-versions">NVIDIA CUDA Toolkit Release Notes</a>）。</blockquote>

  <div class="footer">
    镜像同步脚本：
    <a href="https://gitlab.seu.edu.cn/mirrors/sync-pytorch">校内 GitLab</a>
    ·
    <a href="https://github.com/seu-mirrors/sync-pytorch">GitHub</a>
  </div>
</body>
</html>"""

# 人类可读的按平台索引页（whl/<platform>/index.html）
PLATFORM_INDEX_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>SEU 镜像站 · PyTorch __PLATFORM__ 索引</title>
  <style>
__CSS__
  </style>
</head>
<body>
  <h1>SEU 镜像站 · PyTorch <code>__PLATFORM__</code> 索引</h1>
  <p>面向计算平台 <code>__PLATFORM__</code> 的 <a href="https://peps.python.org/pep-0503/">PEP 503</a> 索引。数据同步自 <a href="https://download.pytorch.org/whl/__PLATFORM__/">https://download.pytorch.org/whl/__PLATFORM__/</a>；进入 <a href="simple/">simple/</a> 即可作为 <code>--index-url</code> 直接使用的简单仓库索引。</p>

  <h2>配置镜像站</h2>

  <h3>① pip</h3>
  <pre><code id="cmd-pip">pip install torch torchvision --index-url """ + SEU_MIRROR_URL + """/__PLATFORM__/simple</code></pre>
  <button type="button" class="copy-btn" onclick="copyCmd('cmd-pip', this)">复制命令</button>

  <h3>② uv</h3>
  <p>推荐：把下面的内容追加到项目 <code>pyproject.toml</code>（这样 <code>torch</code> 会写入项目依赖配置，删除 <code>.venv</code> 后 <code>uv sync</code> 会自动重新下载安装）：</p>
  <pre><code id="cmd-uv-toml">__UV_TOML_SNIPPET__</code></pre>
  <button type="button" class="copy-btn" onclick="copyCmd('cmd-uv-toml', this)">复制配置</button>
  <p>之后执行以下命令</p>
  <pre><code id="cmd-uv-add">uv add torch torchvision</code></pre>
  <button type="button" class="copy-btn" onclick="copyCmd('cmd-uv-add', this)">复制命令</button>
  <p>即可从本镜像安装 PyTorch。更多 uv 与 PyTorch 集成方式见官方《<a href="https://docs.astral.sh/uv/guides/integration/pytorch/">Using uv with PyTorch</a>》（按 <code>sys_platform</code> 选择不同 backend、用 optional-dependencies 切换等）。把指南中的 <code>https://download.pytorch.org/whl/__PLATFORM__</code> 替换为 <code>""" + SEU_MIRROR_URL + """/__PLATFORM__/simple</code> 即指向本镜像。</p>
  <p>备选（<strong>不会写入项目配置文件</strong>，删除 <code>.venv</code> 后不会自动重新下载，仅适合临时一次性安装）：将 <code>pip</code> 命令替换为 <code>uv pip</code> 直接安装：</p>
  <pre><code id="cmd-uv-pip">uv pip install torch torchvision --index-url """ + SEU_MIRROR_URL + """/__PLATFORM__/simple</code></pre>
  <button type="button" class="copy-btn" onclick="copyCmd('cmd-uv-pip', this)">复制命令</button>

  <h3>③ conda</h3>
  <p>conda 本身不消费 PyPI 风格索引，但可在 conda 环境中通过 pip 使用本镜像安装 PyTorch，请将 <code>base</code> 替换为需要安装 <code>PyTorch</code> 的环境：</p>
  <pre><code id="cmd-conda">conda run -n base pip install torch torchvision --index-url """ + SEU_MIRROR_URL + """/__PLATFORM__/simple</code></pre>
  <button type="button" class="copy-btn" onclick="copyCmd('cmd-conda', this)">复制命令</button>

  <h3>④ mamba</h3>
  <p><a href="https://mamba.readthedocs.io/">mamba</a> 是 conda 的高性能替代品。在 mamba 环境中通过 pip 使用本镜像安装 PyTorch，请将 <code>base</code> 替换为需要安装 <code>PyTorch</code> 的环境：</p>
  <pre><code id="cmd-mamba">mamba run -n base pip install torch torchvision --index-url """ + SEU_MIRROR_URL + """/__PLATFORM__/simple</code></pre>
  <button type="button" class="copy-btn" onclick="copyCmd('cmd-mamba', this)">复制命令</button>

  <p>查看其它计算平台的索引请回到 <a href="..">索引总览</a>。</p>

  <div class="footer">
    镜像同步脚本：
    <a href="https://gitlab.seu.edu.cn/mirrors/sync-pytorch">校内 GitLab</a>
    ·
    <a href="https://github.com/seu-mirrors/sync-pytorch">GitHub</a>
  </div>
  <script>
__JS__
  </script>
</body>
</html>"""


def build_uv_sources_snippet(platform):
    index_name = f"pytorch-{platform}"
    if platform == "cpu":
        marker = None
    elif platform.startswith("cu") or platform.startswith("xpu"):
        marker = "sys_platform == 'linux' or sys_platform == 'win32'"
    elif platform.startswith("rocm"):
        marker = "sys_platform == 'linux'"
    else:
        marker = None

    pkgs = ["torch", "torchvision"]
    lines = ["[tool.uv.sources]"]
    for pkg in pkgs:
        if marker:
            lines.append(f'{pkg} = [')
            lines.append(f'  {{ index = "{index_name}", marker = "{marker}" }},')
            lines.append(']')
        else:
            lines.append(f'{pkg} = [')
            lines.append(f'  {{ index = "{index_name}" }},')
            lines.append(']')
    lines.append("")
    lines.append("[[tool.uv.index]]")
    lines.append(f'name = "{index_name}"')
    lines.append(f'url = "{SEU_MIRROR_URL}/{platform}/simple"')
    lines.append("explicit = true")
    return "\n".join(lines)


def update_human_index():
    os.makedirs(os.path.join(base_path, "whl"), 0o755, True)
    platform_list_items = "    " + "\n    ".join(
        f'<li><a href="{platform}">{platform}</a></li>' for platform in compute_platforms
    )
    top_html = (TOP_INDEX_TEMPLATE
                .replace("__CSS__", HUMAN_INDEX_CSS)
                .replace("__PLATFORM_LIST__", platform_list_items))
    with open(os.path.join(base_path, "whl", "index.html"), "w", encoding = "utf-8") as fhandle:
        fhandle.write(top_html)

    for platform in compute_platforms:
        os.makedirs(os.path.join(base_path, "whl", platform), 0o755, True)
        uv_toml = build_uv_sources_snippet(platform)
        platform_html = (PLATFORM_INDEX_TEMPLATE
                         .replace("__CSS__", HUMAN_INDEX_CSS)
                         .replace("__JS__", HUMAN_INDEX_JS)
                         .replace("__UV_TOML_SNIPPET__", uv_toml)
                         .replace("__PLATFORM__", platform))
        with open(os.path.join(base_path, "whl", platform, "index.html"), "w", encoding = "utf-8") as fhandle:
            fhandle.write(platform_html)

def dedupe_shared_files():
    # 同一内容（同名 + 同 sha256）的文件被多个平台索引引用时，只保留一份
    # 在 whl/<filename>，所有 fetch 条目统一指向它，避免跨平台重复下载。
    by_name = {}
    for info in fetch_list:
        name = os.path.basename(info["local_path"])
        sha = info.get("sha256") or "?"
        by_name.setdefault(name, {}).setdefault(sha, []).append(info)

    deduped_shas = set()
    for name, sha_groups in by_name.items():
        entries = [info for group in sha_groups.values() for info in group]
        if len(entries) < 2 or len(sha_groups) != 1:
            continue
        canonical = os.path.join(base_path, "whl", name)
        for info in entries:
            if info["local_path"] != canonical:
                info["local_path"] = canonical
                if info.get("sha256"):
                    deduped_shas.add(info["sha256"])
    if deduped_shas:
        logging.info(f"deduplicated {len(deduped_shas)} files referenced by multiple platforms -> whl/<filename>")
    return deduped_shas

_whl_href_pattern = re.compile(
    r'href="(?:https://mirrors\.seu\.edu\.cn/pytorch|https://download(?:-r2)?\.pytorch\.org)/whl/'
    r'([^"#/]+)/([^"#/]+\.(?:whl|tar\.gz|zip))(#sha256=[0-9a-f]{64})?"'
)

def rewrite_shared_hrefs(deduped_shas):
    if not deduped_shas:
        return
    rewritten = 0
    for idx_path in glob(os.path.join(base_path, "whl", "**", "index.html"), recursive=True):
        with open(idx_path, "r") as fhandle:
            text = fhandle.read()
        def repl(match):
            filename, fragment = match.group(2), match.group(3)
            if fragment and fragment[len("#sha256="):] in deduped_shas:
                return f'href="https://mirrors.seu.edu.cn/pytorch/whl/{filename}{fragment}"'
            return match.group(0)
        new_text = _whl_href_pattern.sub(repl, text)
        if new_text != text:
            with open(idx_path, "w") as fhandle:
                fhandle.write(new_text)
            rewritten += 1
    logging.info(f"rewrote shared-file hrefs in {rewritten} index files")

def remove_outdated_files():
    current_files.clear()
    for info in fetch_list:
        current_files.add(os.path.normpath(info["local_path"]))
    # tracked by local_path, so a file whose location changed between runs (e.g.
    # after a layout migration, or the same filename now served under a different
    # platform directory) is no longer in current_files: the stale copy at the old
    # path is pruned here, and export_aria2c requeues the new path for download.
    outdated_files = existed_files - current_files
    for path in outdated_files:
        try:
            os.remove(path)
            logging.info(f"remove file: {path}")
        except OSError as err:
            logging.warning(f"failed to remove {path}: {err}")

def remove_empty_dirs():
    # walk bottom-up so deleting a leaf dir lets its parent become empty and be
    # removed in the same pass. os.walk caches the dirs list at scandir time, so
    # re-check with os.listdir after children may have been deleted this pass.
    removed = 0
    for root, dirs, files in os.walk(base_path, topdown=False):
        if os.path.abspath(root) == os.path.abspath(base_path):
            continue
        if not os.listdir(root):
            try:
                os.rmdir(root)
                removed += 1
                logging.info(f"remove empty dir: {root}")
            except OSError:
                pass
    logging.info(f"removed {removed} empty directories")

def export_aria2c():
    seen_local_paths = set()
    with open(pkglist, "w") as fhandle:
        for info in fetch_list:
            # dedupe_shared_files 会把多平台重复的文件统一指向 whl/<filename>，
            # 这里按 local_path 去重，同一份内容只写一条 aria2 任务。
            local_path = os.path.normpath(info["local_path"])
            if local_path in existed_files or local_path in seen_local_paths:
                continue
            seen_local_paths.add(local_path)
            fhandle.write(info["url"] + "\n" + "    out=" + local_path + "\n")
            if "sha256" in info and info["sha256"]:
                fhandle.write("    checksum=sha-256=" + info["sha256"] + "\n")

def parse_aria2_length_mismatch_uris(log_path):
    uris = []
    last_uri = None
    if not os.path.exists(log_path):
        return uris
    with open(log_path, "r", errors="replace") as fhandle:
        for line in fhandle:
            m = re.search(r"errorCode=1 URI=(\S+)", line)
            if m:
                last_uri = m.group(1)
                continue
            if "total length mismatch" in line and last_uri:
                if last_uri not in uris:
                    uris.append(last_uri)
                last_uri = None
    return uris

def load_pkglist_uri_map(pkglist_path):
    uri_map = {}
    if not os.path.exists(pkglist_path):
        return uri_map
    current_uri = None
    with open(pkglist_path, "r") as fhandle:
        for line in fhandle:
            line = line.rstrip("\n")
            if not line:
                continue
            if line.startswith(" "):
                value = line.lstrip()
                if current_uri is not None and value.startswith("out="):
                    uri_map[current_uri] = value.split("=", 1)[1]
            else:
                current_uri = line
    return uri_map

def cleanup_aria2_partial(uri, uri_map):
    local_path = uri_map.get(uri)
    if not local_path:
        logging.warning(f"could not resolve local path for length-mismatch URI: {uri}")
        return False
    removed = False
    for p in (local_path, local_path + ".aria2"):
        if os.path.exists(p):
            try:
                os.remove(p)
                logging.info(f"removed stale partial file: {p}")
                removed = True
            except OSError as err:
                logging.warning(f"failed to remove {p}: {err}")
    return removed

def perform_download():
    log_path = os.path.join(base_path, "aria2.log")
    uri_map = load_pkglist_uri_map(pkglist)
    max_attempts = 5
    for attempt in range(1, max_attempts + 1):
        truncate(log_path)
        cmd = (
            f"aria2c --check-certificate=false --user-agent=\"{user_agent}\" "
            f"--log-level=info --file-allocation=falloc --lowest-speed-limit=1K "
            f"--check-integrity --max-tries=10 --retry-wait=3 "
            f"-d / -c -l {log_path} -i {pkglist}"
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

def summary():
    summary_path = os.path.join(base_path, "summary.txt")
    with open(summary_path, "w") as out:
        for d in sorted(glob(os.path.join(base_path, "whl", "*", "simple"))):
            if os.path.isdir(d):
                count = len(os.listdir(d))
                out.write(f"{count} {os.path.relpath(d)}\n")

        if os.path.exists(pkglist):
            with open(pkglist) as f:
                lines = sum(1 if i.startswith("http") else 0 for i in f)
            out.write(f"{lines} {os.path.relpath(pkglist)}\n")
    
    files_info_path = os.path.join(base_path, "existed_files.bin")
    # 没有历史文件时也要写入，否则后续运行无法跟踪上一轮状态、无法清理冗余文件
    if os.path.exists(files_info_path + ".old"):
        os.remove(files_info_path + ".old")
    if os.path.exists(files_info_path):
        os.rename(files_info_path, files_info_path + ".old")
    with open(files_info_path, "wb") as fhandle:
        pickle.dump(current_files, fhandle)

def main():
    # ensure umask
    os.umask(0o22)

    get_platforms()
    update_human_index()
    load_existed_files()
    logging.info(compute_platforms)
    for platform in compute_platforms:
        update_index(platform)
    search_metadata()
    deduped_shas = dedupe_shared_files()
    rewrite_shared_hrefs(deduped_shas)
    remove_outdated_files()
    remove_empty_dirs()
    export_aria2c()
    perform_download()
    summary()

if __name__ == "__main__":
    main()
