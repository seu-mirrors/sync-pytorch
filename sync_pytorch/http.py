"""HTTP 会话构建。"""
import requests
from requests.adapters import HTTPAdapter

from .config import THREAD_COUNT, USER_AGENT


def build_session():
    new_session = requests.Session()
    new_session.mount("http://", HTTPAdapter(max_retries=10, pool_connections=THREAD_COUNT, pool_maxsize=THREAD_COUNT))
    new_session.mount("https://", HTTPAdapter(max_retries=10, pool_connections=THREAD_COUNT, pool_maxsize=THREAD_COUNT))
    new_session.headers.update({"User-Agent": USER_AGENT})
    return new_session


SESSION = build_session()
