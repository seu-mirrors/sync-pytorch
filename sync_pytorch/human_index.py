"""生成同步根目录下的人类可读索引页，并清理旧版帮助页。"""
import html
import logging
import os
import re

from .config import BASE_PATH, MIRROR_WHL_URL
from .templates import (
    HUMAN_INDEX_CSS,
    HUMAN_INDEX_JS,
    INDEX_TEMPLATE,
    LEGACY_REDIRECT_TEMPLATE,
    PLATFORM_CONFIG_TEMPLATE,
    PLATFORM_TAB_BUTTON_TEMPLATE,
    PLATFORM_TABLE_ROW_TEMPLATE,
)

# HTML id 中需要替换掉的字符（平台名 rocm7.2 里的 "." 等）
PLATFORM_ID_PATTERN = re.compile(r"[^0-9A-Za-z_-]")

# 平台列表为空（上游解析失败）时表格里显示的占位行
EMPTY_PLATFORM_ROW = """      <tr>
        <td colspan="3" class="hint">平台列表暂不可用（上游解析失败），请稍后重试。</td>
      </tr>"""


def build_uv_sources_snippet(platform: str) -> str:
    """生成写入 pyproject.toml 的 [tool.uv.sources]/[[tool.uv.index]] 片段。

    - marker 限定平台条件：cuda/xpu 限 linux/win32，rocm 限 linux；
    - rocm 索引不设置 explicit，避免传递依赖无法从镜像解析。

    Args:
        platform: 计算平台名（如 cpu/cu126/rocm7.2）。

    Returns:
        可直接追加到 pyproject.toml 的 TOML 文本。
    """
    index_name = f"pytorch-{platform}"
    # 该平台的 sys_platform 条件表达式；None 表示不限平台
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
    lines.append(f'url = "{MIRROR_WHL_URL}/{platform}/simple"')
    if not platform.startswith("rocm"):
        lines.append("explicit = true")
    return "\n".join(lines)


def build_simple_repo_url(platform: str) -> str:
    """返回该平台对外提供的 PEP 503 索引地址。

    Args:
        platform: 计算平台名（如 cpu/cu126/rocm7.2）。

    Returns:
        形如 https://mirrors.seu.edu.cn/pytorch/whl/cu126/simple 的地址。
    """
    return f"{MIRROR_WHL_URL}/{platform}/simple"


def platform_element_id(platform: str) -> str:
    """把平台名转换成可安全用于 HTML id 与 CSS 选择器的片段。

    Args:
        platform: 计算平台名（如 rocm7.2）。

    Returns:
        只含字母、数字、下划线和连字符的片段（rocm7.2 → rocm7-2）。
    """
    return PLATFORM_ID_PATTERN.sub("-", platform)


def build_platform_table_row(platform: str) -> str:
    """渲染「计算平台 + PEP 503 地址 + 复制按钮」表格行。"""
    return (PLATFORM_TABLE_ROW_TEMPLATE
            .replace("__PLATFORM_ID__", platform_element_id(platform))
            .replace("__PLATFORM__", html.escape(platform))
            .replace("__SIMPLE_REPO_URL__", html.escape(build_simple_repo_url(platform))))


def build_platform_tab_button(platform: str) -> str:
    """渲染配置帮助里的平台切换按钮（点击展开对应配置面板）。"""
    return (PLATFORM_TAB_BUTTON_TEMPLATE
            .replace("__PLATFORM_ID__", platform_element_id(platform))
            .replace("__PLATFORM__", html.escape(platform)))


def build_platform_config_panel(platform: str) -> str:
    """渲染单个平台的 pip/uv/conda/mamba 配置面板（默认折叠）。"""
    return (PLATFORM_CONFIG_TEMPLATE
            .replace("__PLATFORM_ID__", platform_element_id(platform))
            .replace("__PLATFORM__", html.escape(platform))
            .replace("__SIMPLE_REPO_URL__", html.escape(build_simple_repo_url(platform)))
            .replace("__UV_TOML_SNIPPET__", html.escape(build_uv_sources_snippet(platform))))


def build_index_html(platforms: list[str]) -> str:
    """渲染同步根目录的索引页（平台表 + 配置帮助 + 调试日志）。

    Args:
        platforms: 平台名列表（来自 fetch_compute_platforms）。

    Returns:
        完整的 index.html 文本。
    """
    # 上游 version_map 会为多个 PyTorch 版本重复给出同一平台：按渲染用的 HTML id 去重，
    # 既保持原有顺序，又保证 id 唯一（platform_element_id 会把 rocm7.2/rocm7-2 映射成同一个 id）
    unique_platforms = []
    # element id -> 首个使用它的平台名，用于区分「同名重复」与「不同名撞 id」
    element_id_owner = {}
    for platform in platforms:
        element_id = platform_element_id(platform)
        if element_id in element_id_owner:
            if element_id_owner[element_id] == platform:
                logging.debug(f"skip duplicate platform for index page: {platform}")
            else:
                logging.warning(
                    f"platform id collision on index page: {platform} and "
                    f"{element_id_owner[element_id]} both map to {element_id}; skipping {platform}"
                )
            continue
        element_id_owner[element_id] = platform
        unique_platforms.append(platform)
    if unique_platforms:
        table_rows = "\n".join(build_platform_table_row(platform) for platform in unique_platforms)
        tab_buttons = "\n".join(build_platform_tab_button(platform) for platform in unique_platforms)
        panels = "\n".join(build_platform_config_panel(platform) for platform in unique_platforms)
    else:
        table_rows = EMPTY_PLATFORM_ROW
        tab_buttons = '    <span class="hint">暂无可用平台。</span>'
        panels = ""
    return (INDEX_TEMPLATE
            .replace("__CSS__", HUMAN_INDEX_CSS)
            .replace("__JS__", HUMAN_INDEX_JS)
            .replace("__PLATFORM_TABLE_ROWS__", table_rows)
            .replace("__PLATFORM_BUTTONS__", tab_buttons)
            .replace("__PLATFORM_PANELS__", panels))


def build_index_page_url() -> str:
    """返回新索引页对外的绝对地址。

    Returns:
        形如 https://mirrors.seu.edu.cn/pytorch/index.html 的地址。
    """
    return MIRROR_WHL_URL.rstrip("/").rsplit("/", 1)[0] + "/index.html"


def write_legacy_redirect() -> None:
    """把旧总览页 whl/index.html 覆写为跳转到新索引页的极简页面。

    旧地址（如 https://mirrors.seu.edu.cn/pytorch/whl/）继续可用，
    但不再包含任何帮助内容；跳转使用绝对地址，兼容不带结尾斜杠的旧地址。
    """
    legacy_path = os.path.join(BASE_PATH, "whl", "index.html")
    os.makedirs(os.path.dirname(legacy_path), 0o755, exist_ok=True)
    with open(legacy_path, "w", encoding="utf-8") as fhandle:
        fhandle.write(LEGACY_REDIRECT_TEMPLATE.replace("__INDEX_URL__", html.escape(build_index_page_url())))


def remove_legacy_platform_pages() -> None:
    """删除旧版平台帮助页 whl/<platform>/index.html。

    只处理 whl/ 下第一层的真实目录：
    - 跳过软链接目录，避免删除 BASE_PATH 之外的文件；
    - 跳过保留目录名 simple（上游根索引 whl/simple/index.html 的落点）；
    - crawl 生成的 PEP 503 索引位于 whl/<platform>/simple/**/index.html，不会被命中。
    """
    whl_dir = os.path.join(BASE_PATH, "whl")
    if not os.path.isdir(whl_dir):
        return
    removed = 0
    with os.scandir(whl_dir) as dir_entries:
        entries = sorted(dir_entries, key=lambda entry: entry.name)
    for entry in entries:
        if entry.is_symlink():
            logging.warning(f"skip symlinked directory when removing legacy help pages: {entry.path}")
            continue
        if not entry.is_dir() or entry.name == "simple":
            continue
        path = os.path.join(entry.path, "index.html")
        if not os.path.isfile(path):
            continue
        try:
            os.remove(path)
            removed += 1
            logging.info(f"remove legacy help page: {path}")
        except OSError as err:
            logging.warning(f"failed to remove {path}: {err}")
    if removed:
        logging.info(f"removed {removed} legacy platform help pages")


def update_human_index(platforms: list[str]) -> None:
    """生成同步根目录的 index.html，并清理旧版帮助页。

    Args:
        platforms: 平台名列表（来自 fetch_compute_platforms）。
    """
    os.makedirs(BASE_PATH, 0o755, exist_ok=True)
    index_html = build_index_html(platforms)
    with open(os.path.join(BASE_PATH, "index.html"), "w", encoding="utf-8") as fhandle:
        fhandle.write(index_html)
    write_legacy_redirect()
    remove_legacy_platform_pages()
    logging.info(f"human index page written to {os.path.join(BASE_PATH, 'index.html')}")
