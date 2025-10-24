FROM astral/uv:python3.14-alpine

COPY pyproject.toml uv.lock .

RUN uv sync

COPY main.py .

CMD ["uv", "run", "main.py"]
