#!/usr/bin/env python3
import requests
import os
import re
import json
import threading
from glob import glob
from requests.adapters import HTTPAdapter

base_path = os.getenv("TUNASYNC_WORKING_DIR", default = "./sync_dir/") #同步路径
if base_path[-1] != "/":
    base_path += "/"
base_url = "https://download.pytorch.org/"
compute_platforms = ["cpu-cxx11-abi", "cpu_pypi_pkg"]
threads_count = 16 #线程数量
user_agent = "Mozilla/5.0 (compatible; sync-pytorch/0.1; +https://github.com/seu-mirrors/sync-pytorch)"

is_whl_processed = set()
re_pattern = re.compile(r"<a href=\"(\S*)\".*>(\S*)</a>")
fetch_list = []
search_metadata_list = []
thread_lock = threading.Lock()
pkglist = "{base_path}packagelist.txt"

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
        for i in range(self.index_begin, self.index_end):
            try:
                if session.head(search_metadata_list[i]["url"]).status_code == 200:
                    self.fetch_list.append(search_metadata_list[i])
            except Exception as err:
                print("network error")
                print(err)
                exit(1)
            print(f"thread {self.thread_index} : {i - self.index_begin + 1} / {self.index_end - self.index_begin}")

        print("merging")
        thread_lock.acquire()
        fetch_list.extend(self.fetch_list)
        thread_lock.release()
        print("thread complete")

class update_package_thread(threading.Thread):
    def __init__(self, thread_index, package_info_list, index_begin, index_end, local_dir):
        threading.Thread.__init__(self)
        self.thread_index = thread_index
        self.package_info_list = package_info_list
        self.index_begin = index_begin
        self.index_end = index_end
        self.local_dir = local_dir
    def run(self):
        self.fetch_list = []
        self.search_metadata_list = []
        local_dir = self.local_dir
        for index in range(self.index_begin, self.index_end):
            package_info = self.package_info_list[index]
            package_url = package_info["url"]
            try:
                package_response = session.get(package_url)
                if package_response.status_code == 200:
                    package_html = package_response.text
                    os.makedirs(local_dir + package_info["name"], 0o755, True)
                    with open(local_dir + package_info["name"] + "/index.html", "w") as fhandle:
                        fhandle.write(package_html.replace("href=\"/whl", "href=\"https://mirrors.seu.edu.cn/pytorch/whl"))
                    search_pos = 0
                    res = re_pattern.search(package_html, search_pos)
                    while res:
                        whl_name = res.group(2)
                        if not whl_name in is_whl_processed:
                            is_whl_processed.add(whl_name)
                            whl_url = base_url[0:-1] + res.group(1)
                            sha256 = None
                            if "#" in whl_url:
                                split = whl_url.split("#sha256=")
                                whl_url = split[0]
                                sha256 = split[1]
                            self.fetch_list.append({
                                "url" : whl_url,
                                "local_path" : "whl/" + whl_name,
                                # "sha256" : sha256
                            })
                            self.search_metadata_list.append({
                                "url" : whl_url + ".metadata",
                                "local_path" : "whl/" + whl_name + ".metadata"
                            })
                        search_pos = res.span(0)[1]
                        res = re_pattern.search(package_html, search_pos)
                else:
                    print(package_info["name"] + " network error " + str(package_response.status_code))
            except Exception as err:
                print("network error")
                print(err)
                exit(1)
        
        print("merging")
        thread_lock.acquire()
        fetch_list.extend(self.fetch_list)
        search_metadata_list.extend(self.search_metadata_list)
        thread_lock.release()
        print("thread complete")

def update_index(platform = ""):
    os.makedirs(base_path + "whl/", 0o755, True)
    local_dir = base_path + "whl/" + platform + "/simple/"

    url = f"{base_url}whl/{platform}/"
    try:
        projects_list_response = session.get(url)
        if projects_list_response.status_code == 200:
            projects_list_html = projects_list_response.text
            os.makedirs(local_dir, 0o755, True)
            with open(local_dir + "index.html", "w") as fhandle:
                fhandle.write(projects_list_html)

            # 获取包列表
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

            threads = []
            search_metadata_list.clear()
            package_per_thread = package_counts // threads_count
            for i in range(0, threads_count, 1):
                thread = update_package_thread(i, package_info_list, i * package_per_thread, (i + 1) * package_per_thread if i != threads_count - 1 else package_counts, local_dir)
                threads.append(thread)
                thread.start()
            for t in threads:
                t.join()

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

def get_platforms():
    response = session.get("https://raw.githubusercontent.com/pytorch/pytorch.github.io/refs/heads/site/assets/quick-start-module.js")
    version_result = re.search("version_map=({.*})", response.text)
    if version_result:
        version_map = json.loads(version_result.group(1))
        for info in version_map["release"].values() :
            if info[0] == "cpu":
                compute_platforms.append("cpu")
            elif info[0] == "cuda":
                compute_platforms.append("cu" + info[1].replace(".", ""))
            else:
                compute_platforms.append(info[0] + info[1])
        
def update_human_index():
    os.makedirs(base_path + "whl/", 0o755, True)
    with open(base_path + "whl/index.html", "w") as fhandle:
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
        os.makedirs(base_path + "whl/" + platform + "/", 0o755, True)
        with open(base_path + "whl/" + platform + "/index.html", "w") as fhandle:
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

def export_aria2c():
    with open(pkglist, "w") as fhandle:
        for info in fetch_list:
            fhandle.write(info["url"] + "\n" + "    out=" + info["local_path"] + "\n")

def perform_download():
    truncate(f"{base_path}aria2.log")
    os.system(f"aria2c --check-certificate=false --user-agent=\"{user_agent}\" --log-level=info --file-allocation=falloc --lowest-speed-limit=1K --check-integrity -c -l {base_path}aria2.log -i {pkglist}")

def summary():
    with open(f"{base_path}summary.txt", "w") as out:
        for d in sorted(glob("{base_path}whl/*/simple")):
            if os.path.isdir(d):
                count = len(os.listdir(d))
                out.write(f"{count} {os.path.relpath(d)}\n")

        if os.path.exists(pkglist):
            with open(pkglist) as f:
                lines = sum(1 if i.startswith("http") else 0 for i in f)
            out.write(f"{lines} {os.path.relpath(pkglist)}\n")


def main():
    get_platforms()
    update_human_index()
    for platform in compute_platforms:
        update_index(platform)
    export_aria2c()
    perform_download()
    summary()

if __name__ == "__main__":
    main()
