# -*- coding: utf-8 -*-
"""媒体解密模块：图床 AES-128-CBC 加密封面 -> 明文图。

密钥来源：优先动态从站点 crypto-worker.js 解析，失败用 config 兜底。
"""
import os
import re
from Crypto.Cipher import AES

from .http import fetch, get_session

# 预编译
_RE_MEDIA_KEY = re.compile(r'media_key:\s*"([^"]+)"')
_RE_MEDIA_IV = re.compile(r'media_iv:\s*"([^"]+)"')


def fetch_media_keys(cfg, limiter, base):
    """从 crypto-worker.js 动态解析图床 AES key/iv。失败返回 (None, None)。"""
    try:
        html = fetch(cfg, limiter, base + cfg.crypto_worker_url, tries=2)
        km = _RE_MEDIA_KEY.search(html)
        im = _RE_MEDIA_IV.search(html)
        if km and im:
            return _parse_dec(km.group(1)), _parse_dec(im.group(1))
    except Exception:
        pass
    return None, None


def _parse_dec(s):
    return bytes(int(x) for x in str(s).split("_"))


def decrypt_image(enc, key, iv):
    """加密体 -> 明文图字节(JPEG/PNG/WEBP)，失败 None。"""
    if not enc:
        return None
    try:
        dec = AES.new(key, AES.MODE_CBC, iv).decrypt(enc)
        if dec[:2] == b"\xff\xd8" or dec[:3] == b"\x89PN" or dec[:4] == b"RIFF":
            return dec
    except Exception:
        pass
    return None


def fetch_cover(cfg, limiter, url, dest, key, iv):
    """抓图床封面 -> 解密 -> 写 dest。成功 True。"""
    if not url:
        return False
    try:
        s = get_session(cfg)
        limiter.acquire()
        r = s.get(url, timeout=30)
        if r.status_code == 200 and len(r.content) > 1000:
            img = decrypt_image(r.content, key, iv)
            if img:
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, "wb") as f:
                    f.write(img)
                return True
    except Exception:
        pass
    return False
