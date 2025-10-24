#!/usr/bin/env python3
import requests
from urllib.parse import urljoin
import pickle # todo: 加入签名保证安全性
import os
import sys
import re
import json
import threading
from glob import glob
from requests.adapters import HTTPAdapter
import traceback

SHOW_PROGRESS = False
if "--show-progress" in sys.argv and __name__ == "__main__":
    SHOW_PROGRESS = True

if SHOW_PROGRESS:
    try:
        from tqdm import tqdm
    except:
        print("tqdm not found")
        SHOW_PROGRESS = False

# USE_SPDLOG = False
# if "--spdlog" in sys.argv and __name__ == "__main__":
#     USE_SPDLOG = True

# if USE_SPDLOG:
#     try:
#         import spdlog
#     except:
#         print("spdlog not found")
#         USE_SPDLOG = False

base_path = os.getenv("TUNASYNC_WORKING_DIR", default = "./sync_dir/") #同步路径
if base_path[-1] != "/":
    base_path += "/"
base_url = "https://download.pytorch.org/"
compute_platforms = ["cpu-cxx11-abi", "cpu_pypi_pkg"]
threads_count = 16 #线程数量
user_agent = "Mozilla/5.0 (compatible; sync-pytorch/0.1; +https://github.com/seu-mirrors/sync-pytorch)"

existed_files = {} # name : path
current_files = {} # name : path
is_whl_processed = set()
re_pattern = re.compile(r"<a href=\"(\S*)\".*>(\S*)</a>")
fetch_list = []
search_metadata_list = []
fetch_list_lock = threading.Lock()
whl_set_lock = threading.Lock()
pkglist = os.path.join(base_path, "packagelist.txt")

session = requests.Session()
session.mount('http://', HTTPAdapter(max_retries=10))
session.mount('https://', HTTPAdapter(max_retries=10))
session.headers.update({"User-Agent": user_agent})

truncate = lambda path: open(path, "w").close()

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
                print("network error")
                print(err)
                traceback.print_exc()
                os._exit(1)

        with fetch_list_lock:
            fetch_list.extend(self.fetch_list)

class update_package_thread(threading.Thread):
    def __init__(self, thread_index, package_info_list, index_begin, index_end, local_dir):
        threading.Thread.__init__(self)
        self.thread_index = thread_index
        self.package_info_list = package_info_list
        self.index_begin = index_begin
        self.index_end = index_end
        self.local_dir = local_dir
    def run(self):
        rng = None
        if SHOW_PROGRESS:
            rng = tqdm(range(self.index_begin, self.index_end), desc = f"thread #{self.thread_index}", leave = False)
        else:
            rng = range(self.index_begin, self.index_end)
        self.fetch_list = []
        self.search_metadata_list = []
        local_dir = self.local_dir
        for index in rng:
            package_info = self.package_info_list[index]
            package_url = package_info["url"]
            try:
                package_response = session.get(package_url)
                if package_response.status_code == 200:
                    package_html = package_response.text
                    os.makedirs(os.path.join(local_dir, package_info["name"]), 0o755, True)
                    with open(os.path.join(local_dir, package_info["name"], "index.html"), "w") as fhandle:
                        fhandle.write(package_html.replace("href=\"/whl", "href=\"https://mirrors.seu.edu.cn/pytorch/whl"))
                    search_pos = 0
                    res = re_pattern.search(package_html, search_pos)
                    while res:
                        whl_name = res.group(2)
                        if not whl_name in is_whl_processed:
                            with whl_set_lock:
                                is_whl_processed.add(whl_name)
                            whl_url = urljoin(base_url, res.group(1))
                            sha256 = None
                            if "#" in whl_url:
                                split = whl_url.split("#sha256=")
                                whl_url = split[0]
                                sha256 = split[1]
                            self.fetch_list.append({
                                "name" : whl_name,
                                "url" : whl_url,
                                "local_path" : os.path.join(base_path, "whl/", whl_name),
                                "sha256" : sha256
                            })
                            self.search_metadata_list.append({
                                "name" : whl_name + ".metadata",
                                "url" : whl_url + ".metadata",
                                "local_path" : os.path.join(base_path, "whl/", whl_name + ".metadata"),
                            })
                        search_pos = res.span(0)[1]
                        res = re_pattern.search(package_html, search_pos)
                else:
                    print(package_info["name"] + " network error " + str(package_response.status_code))
            except Exception as err:
                print("network error")
                print(err)
                traceback.print_exc()
                os._exit(1)
        
        with fetch_list_lock:
            fetch_list.extend(self.fetch_list)
            search_metadata_list.extend(self.search_metadata_list)

def load_existed_files():
    global existed_files
    existed_files_info_path = os.path.join(base_path, "existed_files.bin")
    if os.path.exists(existed_files_info_path) and os.path.isfile(existed_files_info_path):
        with open(existed_files_info_path, "rb") as fhandle:
            existed_files = pickle.load(fhandle)

def update_index(platform = ""):
    os.makedirs(os.path.join(base_path, "whl"), 0o755, True)
    local_dir = os.path.join(base_path, "whl", platform, "simple")

    url = f"{base_url}whl/"
    if platform != "":
        url += platform + "/"
    try:
        projects_list_response = session.get(url)
        if projects_list_response.status_code == 200:
            projects_list_html = projects_list_response.text
            os.makedirs(local_dir, 0o755, True)
            with open(os.path.join(local_dir, "index.html"), "w") as fhandle:
                fhandle.write(projects_list_html)

            # 获取包列表
            print("fetch package list")
            package_info_list = []
            search_pos = 0
            res = re_pattern.search(projects_list_html, search_pos)
            while res:
                # 包信息
                package_url = url + res.group(1)
                package_name = res.group(2)
                package_info_list.append({"url" : package_url, "name" : package_name})
                # 更新搜索条件
                search_pos = res.span(0)[1]
                res = re_pattern.search(projects_list_html, search_pos)
            package_counts = len(package_info_list)
            print(f"platform: {platform}    " + "package counts: " + str(package_counts))

            print("fetch file list")
            threads = []
            search_metadata_list.clear()
            package_per_thread = package_counts // threads_count
            for i in range(0, threads_count, 1):
                thread = update_package_thread(i, package_info_list, i * package_per_thread, (i + 1) * package_per_thread if i != threads_count - 1 else package_counts, local_dir)
                threads.append(thread)
                thread.start()
            for t in threads:
                t.join()

            print("fetch file metadata")
            threads.clear()
            search_metadata_per_thread = len(search_metadata_list) // threads_count
            for i in range(0, threads_count, 1):
                thread = search_metadata_thread(i, i * search_metadata_per_thread, (i + 1) * search_metadata_per_thread if i != threads_count - 1 else len(search_metadata_list))
                threads.append(thread)
                thread.start()
            for t in threads:
                t.join()
    except Exception as err:
        print("error")
        print(err)
        traceback.print_exc()
        os._exit(1)

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
            print("failed to parse platform info")
            print(err)
            traceback.print_exc()
        
def update_human_index():
    os.makedirs(os.path.join(base_path, "whl"), 0o755, True)
    with open(os.path.join(base_path, "whl" + "index.html"), "w") as fhandle:
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
    status = os.system(f"aria2c --check-certificate=false --user-agent=\"{user_agent}\" --log-level=info --file-allocation=falloc --lowest-speed-limit=1K --check-integrity -c -l {log_path} -i {pkglist}")
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
    get_platforms()
    update_human_index()
    load_existed_files()
    for platform in compute_platforms:
        update_index(platform)
    remove_outdated_files()
    export_aria2c()
    perform_download()
    summary()

if __name__ == "__main__":
    main()
