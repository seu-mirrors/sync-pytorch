FROM astral/uv:python3.14-trixie-slim

RUN apt-get update && apt-get install -y --no-install-recommends aria2 && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock .

RUN uv sync

COPY main.py .

COPY scripts/run.sh .

CMD ["/run.sh"]
