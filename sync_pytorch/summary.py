"""生成 summary.txt 运行摘要。"""
import os
from glob import glob

from .config import ARIA2_INPUT_PATH, BASE_PATH


def write_summary():
    summary_path = os.path.join(BASE_PATH, "summary.txt")
    with open(summary_path, "w") as out:
        for d in sorted(glob(os.path.join(BASE_PATH, "whl", "*", "simple"))):
            if os.path.isdir(d):
                count = len(os.listdir(d))
                out.write(f"{count} {os.path.relpath(d)}\n")

        if os.path.exists(ARIA2_INPUT_PATH):
            with open(ARIA2_INPUT_PATH) as f:
                lines = sum(1 if i.startswith("http") else 0 for i in f)
            out.write(f"{lines} {os.path.relpath(ARIA2_INPUT_PATH)}\n")
