# sync-pytorch

符合 [PEP 503 – Simple Repository API](https://peps.python.org/pep-0503/) 标准的 pytorch 同步工具，基于 [sonatype-nexus-community/pytorch-pypi](https://github.com/sonatype-nexus-community/pytorch-pypi)。

## 运行

```Bash
uv run main.py                 # 同步目录取环境变量 TUNASYNC_WORKING_DIR，默认 ./sync_dir
uv run main.py --show-progress # 可选：用 tqdm 展示 metadata 探测进度
```

脚本可重复执行（幂等）：每轮根据上游索引重建本地索引，下载缺失文件，并清理不再引用的文件。

## 项目结构

```
.
├── main.py                  # 入口：初始化环境，按顺序编排一次完整同步
├── sync_pytorch/            # 同步逻辑（按功能拆分）
│   ├── __init__.py          # 包标记
│   ├── config.py            # 常量、运行期路径、日志初始化
│   ├── http.py              # requests 会话（重试连接池 / User-Agent）
│   ├── state.py             # 一次运行内的共享状态（下载队列、锁、文件集合）
│   ├── crawl.py             # 爬取上游 whl 索引并生成待下载任务（含 PyPI 回退）
│   ├── metadata.py          # metadata HEAD 探测线程 + 计算平台发现
│   ├── templates.py         # 人类可读索引页的 HTML/CSS/JS 模板
│   ├── human_index.py       # 生成总览页/平台页与 uv 配置片段
│   ├── dedupe.py            # 跨平台重复文件去重与索引 href 重写
│   ├── file_state.py        # existed_files.bin 读写、过期文件/空目录清理
│   ├── download.py          # aria2 输入导出、下载执行/重试、断点清理
│   └── summary.py           # summary.txt 运行摘要
├── scripts/run.sh           # 容器入口脚本
├── Dockerfile               # 镜像构建（会拷贝 sync_pytorch/ 整个包）
├── pyproject.toml / uv.lock # 依赖（requests、tqdm；Python >= 3.12）
└── README.md
```

## 执行流程

`main.py` 中 `main()` 的调用顺序即数据流：

1. `config.ensure_working_dir()` / `setup_logging()`：创建同步目录、配置日志；
2. `metadata.fetch_compute_platforms()`：从 PyTorch 官网脚本解析计算平台列表（cpu/cu126/rocm7.2…）；
3. `human_index.update_human_index()`：生成 `whl/index.html` 及各平台页；
4. `file_state.load_previous_run_files()`：加载上一轮文件记录；
5. `crawl.sync_platform_index()`（逐平台）：递归爬取上游索引，填充 `state.download_queue` 与 `state.metadata_check_queue`；
6. `metadata.check_metadata_availability()`：多线程 HEAD 探测 metadata，命中项并入下载队列；
7. `dedupe.dedupe_shared_files()` / `rewrite_shared_hrefs()`：跨平台去重并改写索引链接；
8. `file_state.prune_stale_files()` / `prune_empty_dirs()`：清理过期文件与空目录；
9. `download.write_aria2_input()` / `perform_download()`：导出 `packagelist.txt` 并调用 aria2c 下载；
10. `summary.write_summary()` / `file_state.save_state()`：输出摘要并持久化本轮状态。

## 模块维护指南

### 常见改动改哪里

| 需求 | 位置 |
|---|---|
| 线程数、超时、User-Agent、日志格式 | `config.py` |
| 镜像域名 / 对外 URL（索引页、href 重写） | `config.MIRROR_WHL_URL` |
| 需要改从 PyPI 获取的包 | `config.PYPI_REPLACEMENT_PACKAGES` 与 `crawl.fetch_pypi_package` |
| 平台目录过滤、URL 改写、metadata 登记规则 | `crawl.py`（`enqueue_dist_file` / `crawl_index_page`） |
| 索引页样式、安装命令文案与占位符 | `templates.py`（占位符见模块 docstring） |
| uv 配置片段生成规则（`marker` / `explicit`） | `human_index.build_uv_sources_snippet` |
| 去重判定与 href 重写 | `dedupe.py` |
| 历史文件格式、清理策略 | `file_state.py` |
| aria2c 参数、重试与断点清理策略 | `download.py` |
| summary.txt 格式 | `summary.py` |

### 共享状态约定

- 跨函数/跨线程的数据统一放在 `state.py`，不要在业务模块里另起全局变量；
- 队列元素为 dict，字段含义见 `state.download_queue` 注释（`name/url/local_path/sha256`，PyPI 回退任务额外带 `requires_python`）；
- 线程安全：向 `download_queue` 追加需持有 `state.download_queue_lock`；`state.metadata_checked_count` 的自增由 `metadata_progress_lock` 保护；
- 路径集合一律使用 `os.path.normpath` 规范化后的绝对路径，避免与文件系统扫描结果不匹配。

### 磁盘产物契约（不要随意改名/改格式）

| 产物 | 用途 |
|---|---|
| `whl/<platform>/simple/`、`whl/<filename>` | PEP 503 索引与文件，直接对外服务 |
| `packagelist.txt` | aria2c 输入文件 |
| `summary.txt` | 镜像站运行状态检查读取 |
| `existed_files.bin` | 上一轮文件记录（pickle，兼容旧 dict 格式） |
| `script.log` / `aria2.log` | 调试日志 |

### 编码约定

- 函数/类需有中文 docstring，公开函数签名带类型标注；
- 不要在 import 期产生副作用：建目录、配置日志等只在 `main()` 中显式调用；
- 异常行为保持现状：`crawl` 抓取失败会 `os._exit(1)`，`perform_download` 最终失败以 aria2 退出码结束进程，便于任务平台感知失败；
- 需要并发时参考 `metadata.MetadataCheckThread`（每线程独立会话 + 锁保护共享计数）；
- 新增/删除模块后，同步更新本文档的结构与“常见改动”表；`Dockerfile` 已整包拷贝 `sync_pytorch/`，通常无需改动。

### 提交前检查

```Bash
uv run python -m py_compile main.py sync_pytorch/*.py
uv run python -c "import main"                      # 导入不应产生输出或创建目录
TUNASYNC_WORKING_DIR=$(mktemp -d) uv run main.py   # 完整跑一次（涉及网络与下载）
```
