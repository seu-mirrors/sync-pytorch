#!/bin/bash

set -euo pipefail

export PYTHONUNBUFFERED=1

uv run main.py

echo "size-sum:" $(du -sh ${TUNASYNC_WORKING_DIR})
echo "finished"

