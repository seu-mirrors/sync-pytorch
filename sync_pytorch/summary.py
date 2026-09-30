"""生成 summary.txt 运行摘要。"""
import os
from glob import glob

from .config import ARIA2_INPUT_PATH, BASE_PATH


def write_summary():
    summary_path = os.path.join(BASE_PATH, "summary.txt")
    with open(summary_path, "w") as out:
        for simple_dir in sorted(glob(os.path.join(BASE_PATH, "whl", "*", "simple"))):
            if os.path.isdir(simple_dir):
                count = len(os.listdir(simple_dir))
                out.write(f"{count} {os.path.relpath(simple_dir)}\n")

        if os.path.exists(ARIA2_INPUT_PATH):
            with open(ARIA2_INPUT_PATH) as fhandle:
                task_count = sum(1 if line.startswith("http") else 0 for line in fhandle)
            out.write(f"{task_count} {os.path.relpath(ARIA2_INPUT_PATH)}\n")
