"""生成人类可读的总览索引页和各平台索引页。"""
import os

from .config import BASE_PATH, MIRROR_WHL_URL
from .templates import HUMAN_INDEX_CSS, HUMAN_INDEX_JS, PLATFORM_INDEX_TEMPLATE, TOP_INDEX_TEMPLATE


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
    lines.append(f'url = "{MIRROR_WHL_URL}/{platform}/simple"')
    if not platform.startswith("rocm"):
        lines.append("explicit = true")
    return "\n".join(lines)


def update_human_index(compute_platforms):
    os.makedirs(os.path.join(BASE_PATH, "whl"), 0o755, exist_ok=True)
    platform_list_items = "    " + "\n    ".join(
        f'<li><a href="{platform}">{platform}</a></li>' for platform in compute_platforms
    )
    top_html = (TOP_INDEX_TEMPLATE
                .replace("__CSS__", HUMAN_INDEX_CSS)
                .replace("__PLATFORM_LIST__", platform_list_items))
    with open(os.path.join(BASE_PATH, "whl", "index.html"), "w", encoding="utf-8") as fhandle:
        fhandle.write(top_html)

    for platform in compute_platforms:
        os.makedirs(os.path.join(BASE_PATH, "whl", platform), 0o755, exist_ok=True)
        uv_toml = build_uv_sources_snippet(platform)
        platform_html = (PLATFORM_INDEX_TEMPLATE
                         .replace("__CSS__", HUMAN_INDEX_CSS)
                         .replace("__JS__", HUMAN_INDEX_JS)
                         .replace("__UV_TOML_SNIPPET__", uv_toml)
                         .replace("__PLATFORM__", platform))
        with open(os.path.join(BASE_PATH, "whl", platform, "index.html"), "w", encoding="utf-8") as fhandle:
            fhandle.write(platform_html)
