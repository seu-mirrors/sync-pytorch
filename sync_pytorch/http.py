"""HTTP 会话构建。"""
import requests
from requests.adapters import HTTPAdapter

from .config import THREAD_COUNT, USER_AGENT


def create_session() -> requests.Session:
    """创建带重试连接池和统一 User-Agent 的 requests 会话。"""
    session = requests.Session()
    session.mount("http://", HTTPAdapter(max_retries=10, pool_connections=THREAD_COUNT, pool_maxsize=THREAD_COUNT))
    session.mount("https://", HTTPAdapter(max_retries=10, pool_connections=THREAD_COUNT, pool_maxsize=THREAD_COUNT))
    session.headers.update({"User-Agent": USER_AGENT})
    return session


# 主线程共享会话；metadata 探测线程各自 create_session()，避免连接池争用
SESSION: requests.Session = create_session()
