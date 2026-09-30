"""生成 summary.txt 运行摘要。"""
import os
from glob import glob

from .config import ARIA2_INPUT_PATH, BASE_PATH


def write_summary() -> None:
    """写入 summary.txt：各平台 simple 目录的条目数与 aria2 输入文件的任务数。

    每行格式为 "<数量> <相对路径>"，与镜像平台的运行状态检查脚本兼容。
    """
    summary_path = os.path.join(BASE_PATH, "summary.txt")
    with open(summary_path, "w") as out:
        for simple_dir in sorted(glob(os.path.join(BASE_PATH, "whl", "*", "simple"))):
            if os.path.isdir(simple_dir):
                count = len(os.listdir(simple_dir))
                out.write(f"{count} {os.path.relpath(simple_dir)}\n")

        if os.path.exists(ARIA2_INPUT_PATH):
            with open(ARIA2_INPUT_PATH) as fhandle:
                # aria2 输入文件中每个任务以 URL 行开头，统计以 http 开头的行数
                task_count = sum(1 if line.startswith("http") else 0 for line in fhandle)
            out.write(f"{task_count} {os.path.relpath(ARIA2_INPUT_PATH)}\n")
