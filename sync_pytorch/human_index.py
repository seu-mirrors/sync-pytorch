"""生成人类可读的总览索引页和各平台索引页。"""
import os

from .config import BASE_PATH, MIRROR_WHL_URL
from .templates import HUMAN_INDEX_CSS, HUMAN_INDEX_JS, PLATFORM_INDEX_TEMPLATE, TOP_INDEX_TEMPLATE


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


def update_human_index(platforms: list[str]) -> None:
    """生成 whl/index.html 总览页与 whl/<platform>/index.html 平台页。

    Args:
        platforms: 平台名列表（来自 fetch_compute_platforms）。
    """
    os.makedirs(os.path.join(BASE_PATH, "whl"), 0o755, exist_ok=True)
    # 总览页里的平台链接 <li> 列表
    platform_list_items = "    " + "\n    ".join(
        f'<li><a href="{platform}">{platform}</a></li>' for platform in platforms
    )
    top_html = (TOP_INDEX_TEMPLATE
                .replace("__CSS__", HUMAN_INDEX_CSS)
                .replace("__PLATFORM_LIST__", platform_list_items))
    with open(os.path.join(BASE_PATH, "whl", "index.html"), "w", encoding="utf-8") as fhandle:
        fhandle.write(top_html)

    for platform in platforms:
        os.makedirs(os.path.join(BASE_PATH, "whl", platform), 0o755, exist_ok=True)
        # 该平台的 uv 配置片段与渲染结果
        uv_toml = build_uv_sources_snippet(platform)
        platform_html = (PLATFORM_INDEX_TEMPLATE
                         .replace("__CSS__", HUMAN_INDEX_CSS)
                         .replace("__JS__", HUMAN_INDEX_JS)
                         .replace("__UV_TOML_SNIPPET__", uv_toml)
                         .replace("__PLATFORM__", platform))
        with open(os.path.join(BASE_PATH, "whl", platform, "index.html"), "w", encoding="utf-8") as fhandle:
            fhandle.write(platform_html)
