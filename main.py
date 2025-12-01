#!/usr/bin/env python3
import requests
from urllib.parse import unquote, urljoin
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
# compute_platforms = ["cpu-cxx11-abi", "cpu_pypi_pkg"]
compute_platforms = ['cpu-cxx11-abi', 'cpu_pypi_pkg', 'cpu', 'cu126', 'cu128', 'cu130', 'rocm6.4']
threads_count = 16 #线程数量
user_agent = "Mozilla/5.0 (compatible; sync-pytorch/0.1; +https://github.com/seu-mirrors/sync-pytorch)"

existed_files = {} # name : path
current_files = {} # name : path
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

def load_existed_files():
    global existed_files
    existed_files_info_path = os.path.join(base_path, "existed_files.bin")
    if os.path.exists(existed_files_info_path) and os.path.isfile(existed_files_info_path):
        with open(existed_files_info_path, "rb") as fhandle:
            existed_files = pickle.load(fhandle)

def update_index(platform = ""):
    logging.info(f"current platform = {platform}")
    os.makedirs(os.path.join(base_path, "whl"), 0o755, True)
    local_dir = os.path.join(base_path, "whl", platform, "simple")

    url = f"{base_url}whl/"
    if platform != "":
        url += platform + "/"
    search_package_recursive(url, local_dir)

def search_package_recursive(url, local_dir):
    logging.info(f"current url = {url} local_dir = {local_dir}")
    try:
        response = session.get(url)
        if response.status_code == 200:
            html_content = response.text
            os.makedirs(local_dir, 0o755, True)
            with open(os.path.join(local_dir, "index.html"), "w") as fhandle:
                fhandle.write(html_content.replace("href=\"/whl", "href=\"https://mirrors.seu.edu.cn/pytorch/whl"))
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

            # 过滤url
            # cpu*
            # cu*
            # rocm*
            pattern_str = r'^(cpu|cu|rocm)\S*$'
            # item_url = unquote(res.group(1))
            html_label = res.group(0)
            # logging.debug(html_label)
            item_url = res.group(1)
            item_name = res.group(2)
            if re.match(pattern_str, item_url):
                res = next_res
                logging.info(f"skip item_url = {item_url}")
                continue
            if item_url.startswith("/"):
                # whl or archive
                whl_name = item_name
                if whl_name in is_whl_processed:
                    logging.debug(f"skip processed whl_name = {whl_name}")
                    res = next_res
                    continue
                is_whl_processed.add(whl_name)
                sha256 = None
                whl_url = item_url
                if "#" in whl_url:
                    split = whl_url.split("#sha256=")
                    whl_url = split[0]
                    sha256 = split[1]
                whl_local_path = unquote(whl_url)[1:] # whl/certifi-2022.12.7-py3-none-any.whl
                whl_url = urljoin(base_url, whl_url)
                assert whl_name.endswith(".whl") or whl_name.endswith(".tar.gz"), f"unexpected extension name (whl_name = ${whl_name})"
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
            else:
                # dir
                search_package_recursive(urljoin(url, item_url), os.path.join(local_dir, item_url))
            res = next_res
    except Exception as err:
        logging.exception("exception occurred")
        logging.error(traceback.format_exc(err))
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
        
def update_human_index():
    os.makedirs(os.path.join(base_path, "whl"), 0o755, True)
    with open(os.path.join(base_path, "whl", "index.html"), "w") as fhandle:
        index_html = '''<!DOCTYPE html>
<html>
  <body>
    <h1>PyPI improved indexes for PyTorch</h1>

Generated by <a href="https://github.com/sonatype-nexus-community/pytorch-pypi">sonatype-nexus-community/pytorch-pypi</a> from <a href="https://download.pytorch.org/whl/">https://download.pytorch.org/whl/</a>
<p>Choose from compute platform filtered indexes:</p>
<ul>
'''
        for platform in compute_platforms:
            index_html += f"<li><a href=\"{platform}\">{platform}</a></li>"
        index_html += '''</ul>
</body>
</html>'''
        fhandle.write(index_html)
    
    for platform in compute_platforms:
        os.makedirs(os.path.join(base_path, "whl", platform), 0o755, True)
        with open(os.path.join(base_path, "whl", platform, "index.html"), "w") as fhandle:
            index_html = f'''<!DOCTYPE html>
<html>
  <body>
    <h1>PyPI improved indexes for PyTorch</h1>

Generated by <a href="https://github.com/sonatype-nexus-community/pytorch-pypi">sonatype-nexus-community/pytorch-pypi</a> from <a href="https://download.pytorch.org/whl/{platform}/">https://download.pytorch.org/whl/{platform}/</a>
<p>
for {platform} compute platform index, use <code>--index-url <a href="simple">https://mirrors.seu.edu.cn/pytorch/whl/{platform}/simple</code></a>
<p>
see also <a href="..">other available indexes</a>
</body>
</html>'''
            fhandle.write(index_html)

def remove_outdated_files():
    outdated_files = []
    for info in fetch_list:
        current_files[info["name"]] = info["local_path"]
    for existed_file_name, existed_file_path in existed_files.items():
        if not existed_file_name in current_files:
            outdated_files.append(existed_file_path)
    for path in outdated_files:
        os.remove(path)
        logging.info(f"remove file: {path}")

def export_aria2c():
    with open(pkglist, "w") as fhandle:
        for info in fetch_list:
            if not info["name"] in existed_files:
                fhandle.write(info["url"] + "\n" + "    out=" + info["local_path"] + "\n")
                if "sha256" in info and info["sha256"]:
                    fhandle.write("    checksum=sha-256=" + info["sha256"] + "\n")

def perform_download():
    log_path = os.path.join(base_path, "aria2.log")
    truncate(log_path)
    status = os.system(f"aria2c --check-certificate=false --user-agent=\"{user_agent}\" --log-level=info --file-allocation=falloc --lowest-speed-limit=1K --check-integrity -d / -c -l {log_path} -i {pkglist}")
    if status != 0:
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
    if os.path.exists(files_info_path):
        if os.path.exists(files_info_path + ".old"):
            os.remove(files_info_path + ".old")
        os.rename(files_info_path, files_info_path + ".old")
        with open(files_info_path, "wb") as fhandle:
            pickle.dump(current_files, fhandle)

def main():
    # ensure umask
    os.umask(0o22)

    # get_platforms()
    update_human_index()
    load_existed_files()
    logging.info(compute_platforms)
    for platform in compute_platforms:
        update_index(platform)
    search_metadata()
    remove_outdated_files()
    export_aria2c()
    perform_download()
    summary()

if __name__ == "__main__":
    main()
