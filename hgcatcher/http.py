# -*- coding: utf-8 -*-
"""网络模块：线程安全 Session、令牌桶限流、带重试的 fetch。

升级预留：自定义 header/代理/cookie 多账号/重定向策略都在这层扩展，
调用方(下载器/主流程)只依赖 fetch 的签名。
"""
import time
import threading
import requests

_tl = threading.local()


class RateLimiter:
    """每线程令牌桶，限制请求频率，防 Cloudflare 封禁。"""

    def __init__(self, per_sec):
        self.per_sec = max(0.5, per_sec or 0.5)
        self._interval = 1.0 / self.per_sec if per_sec else 0
        self._lock = threading.Lock()
        self._bucket = {}

    def acquire(self):
        per = self.per_sec
        tid = threading.get_ident()
        with self._lock:
            now = time.time()
            tokens, last = self._bucket.get(tid, (per, now))
            tokens = min(per, tokens + (now - last) * per)
            self._bucket[tid] = (tokens, now)
            if tokens >= 1:
                self._bucket[tid] = (tokens - 1, now)
                return
        time.sleep(self._interval)


def get_session(cfg):
    """线程本地 Session，每个 worker 一个，避免连接池竞争。"""
    if not hasattr(_tl, "session"):
        s = requests.Session()
        s.headers.update(cfg.headers)
        _tl.session = s
    return _tl.session


def fetch(cfg, limiter, url, tries=None, timeout=30):
    """GET 文本，带限流+重试+临时错误退避。失败多次抛异常。

    tries=None 用 cfg.retry；429/5xx 等临时错误退避后重试。
    """
    s = get_session(cfg)
    tries = tries or cfg.retry
    for i in range(tries):
        try:
            limiter.acquire()
            r = s.get(url, timeout=timeout)
            if r.status_code == 200:
                return r.text
            if r.status_code in (429, 502, 503, 504):
                time.sleep(cfg.sleep * (i + 1))
                continue
            return r.text
        except requests.RequestException as e:
            time.sleep(cfg.sleep * (i + 1))
            if i == tries - 1:
                raise
    return ""
