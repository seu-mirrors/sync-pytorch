"""HTTP 会话构建。"""
import requests
from requests.adapters import HTTPAdapter

from .config import THREAD_COUNT, USER_AGENT


def create_session():
    session = requests.Session()
    session.mount("http://", HTTPAdapter(max_retries=10, pool_connections=THREAD_COUNT, pool_maxsize=THREAD_COUNT))
    session.mount("https://", HTTPAdapter(max_retries=10, pool_connections=THREAD_COUNT, pool_maxsize=THREAD_COUNT))
    session.headers.update({"User-Agent": USER_AGENT})
    return session


SESSION = create_session()
