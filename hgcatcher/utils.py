# -*- coding: utf-8 -*-
"""通用工具：ffmpeg/ffprobe 定位、时长探测、manifest 原子写、字节格式化。"""
import os
import json
import time
import shutil
import subprocess


def ffmpeg_bin():
    b = shutil.which("ffmpeg")
    if b:
        return b
    wg = os.path.expanduser("~")
    cand = os.path.join(wg, "AppData", "Local", "Microsoft", "WinGet",
                        "Packages", "Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe",
                        "ffmpeg-8.1.2-full_build", "bin", "ffmpeg.exe")
    return cand if os.path.exists(cand) else "ffmpeg"


def ffprobe_bin():
    b = shutil.which("ffprobe")
    if b:
        return b
    ff = ffmpeg_bin()
    cand = os.path.join(os.path.dirname(ff), "ffprobe.exe")
    return cand if os.path.exists(cand) else "ffprobe"


def probe_duration(path, fp=None):
    """ffprobe 返回视频时长(秒)。失败/损坏返回 -1。"""
    fp = fp or ffprobe_bin()
    try:
        p = subprocess.run(
            [fp, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=30)
        return float(p.stdout.strip()) if p.returncode == 0 else -1
    except Exception:
        return -1


def save_manifest(manifest, path):
    """原子写 manifest：tmp + os.replace，杜绝中断导致 JSON 半截/损坏。"""
    dirn = os.path.dirname(path)
    if dirn:
        os.makedirs(dirn, exist_ok=True)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)
        except Exception:
            pass


def human_size(n):
    if n >= 1 << 30:
        return f"{n / (1 << 30):.2f} GB"
    if n >= 1 << 20:
        return f"{n / (1 << 20):.1f} MB"
    if n >= 1 << 10:
        return f"{n / (1 << 10):.0f} KB"
    return f"{n} B"
