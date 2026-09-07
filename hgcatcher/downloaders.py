# -*- coding: utf-8 -*-
"""下载器模块：单集 m3u8 -> mp4。

升级接口：抽象 BaseDownloader。新下载方式(如 yt-dlp / 自定义)继承并
注册进 DOWNLOADERS 即可，主流程通过名字选择，无需改动。
"""
import os
import json
import re
import time
import shutil
import subprocess
from abc import ABC, abstractmethod

from Crypto.Cipher import AES

from .http import fetch, get_session
from .parsers import HuangguoParser
from .utils import ffmpeg_bin, ffprobe_bin, probe_duration

# 预编译正则
_RE_KEY_URI = re.compile(r'URI="([^"]+)"')
_RE_KEY_IV = re.compile(r"IV=0x([0-9a-fA-F]+)")

_parser = HuangguoParser()


def _unescape(s):
    return (s.replace("\\u0026", "&").replace("\\u002F", "/")
            .replace("\\u002f", "/"))


def _point_to(cfg, limiter, vid, ep):
    """从视频页解析单集 m3u8 源。"""
    html = fetch(cfg, limiter, f"{cfg.base}/video/{vid}/ep-{ep}/")
    return _parser.parse_src(html)


class BaseDownloader(ABC):
    """单集下载器接口。mode 参数留给子类各自配置。"""

    name = "base"

    @abstractmethod
    def download(self, cfg, limiter, vid, ep, src, outdir, logger):
        """下载 vid/ep 到 outdir/ep{ep}.mp4，成功 True。"""
        raise NotImplementedError


class FfmpegDownloader(BaseDownloader):
    """ffmpeg 整体合成 HLS(AES-128) -> mp4。成熟省事。"""

    name = "ffmpeg"

    def download(self, cfg, limiter, vid, ep, src, outdir, logger):
        os.makedirs(outdir, exist_ok=True)
        final = os.path.join(outdir, f"ep{ep:02d}.mp4")
        part = final + ".part.ts"
        ff, fp = ffmpeg_bin(), ffprobe_bin()

        def scmd(s):
            return [ff, "-y", "-headers", "Referer: https://huangguoai.com/\r\n",
                    "-i", s, "-c", "copy", "-movflags", "+faststart", part]

        cur_src, cmd = src, scmd(src)
        for _ in range(cfg.retry):
            try:
                p = subprocess.run(cmd, capture_output=True, text=True,
                                   timeout=900, check=False)
                if p.returncode == 0 and os.path.exists(part) \
                        and os.path.getsize(part) > cfg.min_episode_bytes \
                        and probe_duration(part, fp) > cfg.min_duration_sec:
                    os.replace(part, final)
                    return True
            except subprocess.TimeoutExpired:
                logger.warning("ffmpeg timeout vid=%s ep=%s", vid, ep)
            time.sleep(cfg.sleep)
            # auth_key 可能过期，重抓页面刷新签名
            new_src = _point_to(cfg, limiter, vid, ep)
            if new_src and new_src != cur_src:
                cur_src = new_src
                cmd = scmd(cur_src)
        return False


class ChunkedDownloader(BaseDownloader):
    """m3u8 逐分片下载 + AES 解密 + concat，支持中断续传。"""

    name = "chunked"

    def download(self, cfg, limiter, vid, ep, src, outdir, logger):
        os.makedirs(outdir, exist_ok=True)
        final = os.path.join(outdir, f"ep{ep:02d}.mp4")
        workdir = os.path.join(outdir, f".ep{ep:02d}")
        os.makedirs(workdir, exist_ok=True)
        done_list = os.path.join(workdir, "done.json")
        ff, fp = ffmpeg_bin(), ffprobe_bin()

        def refresh():
            return _point_to(cfg, limiter, vid, ep)

        m3u8_url = src
        try:
            s = get_session(cfg)
            r = None
            for _ in range(cfg.retry):
                limiter.acquire()
                r = s.get(m3u8_url, timeout=30)
                if r.status_code == 200:
                    break
                m3u8_url = refresh() or m3u8_url
            else:
                raise RuntimeError("m3u8 fetch failed")
            playlist = r.text

            key_url, iv = None, None
            segs = []
            for line in playlist.splitlines():
                if line.startswith("#EXT-X-KEY"):
                    km = _RE_KEY_URI.search(line)
                    if km:
                        key_url = _unescape(km.group(1))
                    im = _RE_KEY_IV.search(line)
                    if im:
                        iv = bytes.fromhex(im.group(1))
                elif line and not line.startswith("#"):
                    segs.append(_unescape(line))

            limiter.acquire()
            kr = s.get(key_url, timeout=30) if key_url else None
            key = kr.content if kr and kr.status_code == 200 else None
            if not key or len(key) != 16:
                raise RuntimeError("AES key invalid")
            cipher = AES.new(key, AES.MODE_CBC, iv or bytes(16))

            local_ts = os.path.join(workdir, "full.ts")
            done = set()
            if os.path.exists(done_list):
                try:
                    with open(done_list, encoding="utf-8") as f:
                        done = set(json.load(f))
                except Exception:
                    pass

            # 逐分片下载（续传：跳过已下载）
            for i, seg in enumerate(segs):
                if i in done:
                    continue
                pp = os.path.join(workdir, f"{i:05d}.ts")
                for _ in range(cfg.retry):
                    try:
                        limiter.acquire()
                        gr = s.get(seg, timeout=60)
                        if gr.status_code == 200:
                            with open(pp, "wb") as f:
                                f.write(cipher.decrypt(gr.content))
                            done.add(i)
                            if len(done) % 16 == 0:
                                with open(done_list, "w", encoding="utf-8") as f:
                                    json.dump(sorted(done), f)
                            break
                    except Exception:
                        pass
                    time.sleep(cfg.sleep)
                    m3u8_url = refresh() or m3u8_url
                else:
                    logger.warning("segment %d failed vid=%s ep=%s", i, vid, ep)

            with open(done_list, "w", encoding="utf-8") as f:
                json.dump(sorted(done), f)

            with open(local_ts, "wb") as out:
                for i in range(len(segs)):
                    pp = os.path.join(workdir, f"{i:05d}.ts")
                    if os.path.exists(pp):
                        with open(pp, "rb") as f:
                            out.write(f.read())

            p = subprocess.run(
                [ff, "-y", "-i", local_ts, "-c", "copy",
                 "-movflags", "+faststart", final],
                capture_output=True, text=True, timeout=600)
            if p.returncode == 0 and os.path.exists(final) \
                    and os.path.getsize(final) > cfg.min_episode_bytes \
                    and probe_duration(final, fp) > cfg.min_duration_sec:
                shutil.rmtree(workdir, ignore_errors=True)
                return True
        except Exception as e:
            logger.error("chunked download err vid=%s ep=%s %s", vid, ep, e)
        return False


# ── 注册表（升级接口：加新下载器在此注册） ──
DOWNLOADERS = {}


def register_downloader(cls):
    DOWNLOADERS[cls.name] = cls
    return cls


register_downloader(FfmpegDownloader)
register_downloader(ChunkedDownloader)


def get_downloader(name):
    cls = DOWNLOADERS.get(name)
    if cls is None:
        raise KeyError(f"未知下载器: {name}，可用: {sorted(DOWNLOADERS)}")
    return cls()
