FROM astral/uv:python3.14-trixie-slim

COPY pyproject.toml uv.lock .

RUN uv sync

COPY main.py .

COPY scripts/run.sh .

CMD ["/run.sh"]
