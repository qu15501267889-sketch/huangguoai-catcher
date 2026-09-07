# -*- coding: utf-8 -*-
"""元数据模块：封面(poster.jpg)+简介(.nfo/info.txt)，含并发抓取与首帧兜底。"""
import os
import time
import subprocess
from concurrent.futures import ThreadPoolExecutor
from xml.sax.saxutils import escape

from .http import fetch
from .crypto import fetch_cover
from .parsers import HuangguoParser
from .utils import ffmpeg_bin

_parser = HuangguoParser()


def build_nfo(title, vid, desc):
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<tvshow>\n'
        '  <title>' + escape(title) + '</title>\n'
        '  <uniqueid type="huangguoai" default="true">' + escape(str(vid)) + '</uniqueid>\n'
        '  <episode>0</episode>\n'
        '  <premiered>' + time.strftime('%Y-%m-%d') + '</premiered>\n'
        '  <year>' + time.strftime('%Y') + '</year>\n'
        '  <plot>' + escape(desc) + '</plot>\n'
        '  <thumb>poster.jpg</thumb>\n'
        '  <poster>poster.jpg</poster>\n'
        '  <fanart>poster.jpg</fanart>\n'
        '</tvshow>\n'
    )


def _snap(ff, src, dest, t=1):
    """从 HLS 抽首帧作为海报兜底。"""
    try:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        subprocess.run([ff, "-y", "-ss", str(t), "-i", src,
                        "-frames:v", "1", "-q:v", "2", dest],
                       capture_output=True, text=True, timeout=120)
        return os.path.exists(dest) and os.path.getsize(dest) > 5000
    except Exception:
        return False


def write_meta(cfg, limiter, vid, title, poster, desc, outdir, logger):
    """单部剧：写 poster.jpg（解密官方封面，失败截首帧）+ .nfo + info.txt。"""
    d = os.path.join(outdir, f"{title}(id{vid})")
    try:
        vh = fetch(cfg, limiter, f"{cfg.base}/video/{vid}/ep-1/")
        url = _parser.parse_poster(vh) or poster
        if url:
            fetch_cover(cfg, limiter, url, os.path.join(d, "poster.jpg"),
                        cfg.img_key, cfg.img_iv)
        # 若封面没拿到，尝试从 ep-1 源截首帧
        poster_path = os.path.join(d, "poster.jpg")
        if not os.path.exists(poster_path):
            src = _parser.parse_src(vh)
            if src:
                _snap(ffmpeg_bin(), src, poster_path)
        if desc:
            os.makedirs(d, exist_ok=True)
            nfo = build_nfo(title, vid, desc)
            try:
                with open(os.path.join(d, title + ".nfo"), "w", encoding="utf-8") as f:
                    f.write(nfo)
            except OSError:
                with open(os.path.join(d, "tvshow.nfo"), "w", encoding="utf-8") as f:
                    f.write(nfo)
            with open(os.path.join(d, "info.txt"), "w", encoding="utf-8") as f:
                f.write(f"片名: {title}\n剧id: {vid}\n\n简介:\n{desc}\n")
    except Exception as e:
        logger.error("meta %s ERR %s", vid, e)


def write_meta_all(cfg, limiter, meta_map, outdir, logger, workers=3):
    """并发写所有剧的元数据。meta_map: vid -> (title, poster, desc)"""
    def work(vid):
        title, poster, desc = meta_map[vid]
        write_meta(cfg, limiter, vid, title, poster, desc, outdir, logger)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(work, list(meta_map.keys())))
