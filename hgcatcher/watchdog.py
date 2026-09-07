# -*- coding: utf-8 -*-
"""看门狗模块：改版检测/主动提醒(webhook) + 垃圾自动清理。

升级接口：notify 支持 webhook/bark/serverchan/wecom；未来加自有渠道只需扩 send_notify。
"""
import os
import time
import shutil
import urllib.parse

from .http import get_session


def send_notify(cfg, title, body, logger):
    """webhook 提醒。config['notify'] 配置通道，失败不阻断。"""
    n = cfg.notify
    if not n or not n.get("enabled"):
        return
    url = n.get("url", "")
    if not url:
        logger.warning("notify 未配置 url，已跳过: %s", title)
        return
    try:
        s = get_session(cfg)
        kind = n.get("type", "webhook").lower()
        if kind == "bark":
            if "https://api.day.app/" not in url:
                resp = s.get(url, timeout=15)
            else:
                resp = s.get(f"{url}/{urllib.parse.quote(title)}/{urllib.parse.quote(body)}",
                             timeout=15)
        elif kind == "serverchan":
            resp = s.post(url, data={"title": title, "desp": body}, timeout=15)
        elif kind == "wecom":
            resp = s.post(url, json={"msgtype": "text",
                                     "text": {"content": f"{title}\n{body}"}}, timeout=15)
        else:
            resp = s.post(url, json={"title": title, "content": body}, timeout=15)
        logger.info("通知已发送(%s): status=%s", kind, getattr(resp, "status_code", "?"))
    except Exception as e:
        logger.error("通知发送失败: %s", e)


def check_health(series_count, ok_count, failed_count, manifest, logger, cfg):
    """健康检查：命中异常则提醒。返回 alerts 列表。"""
    state = manifest.setdefault("_meta", {})
    last_series = state.get("series_count", 0)
    state["last_run"] = time.strftime("%Y-%m-%d %H:%M:%S")
    state["series_count"] = series_count
    alerts = []
    if last_series and series_count < last_series * 0.7:
        alerts.append(f"枚举数骤降: {last_series} -> {series_count} (±30%，疑似改版/限流)")
    got = ok_count + failed_count
    if got > 5 and ok_count < got * 0.2 and failed_count:
        alerts.append(f"成功率异常: 成功{ok_count}/总{got}，多数失败，疑似内容格式改版")
    if alerts:
        body = "\n".join(alerts)
        logger.warning("⚠ 检测到异常，触发提醒:\n%s", body)
        send_notify(cfg, f"⚠ 黄果下载器异常 ({len(alerts)}项)", body, logger)
    else:
        logger.info("健康检查正常(上次=%s 本次=%s)", last_series, series_count)
    return alerts


def cleanup_junks(root, logger, max_age_h=24):
    """清理下载残片：.part.ts / .ep{N}/ / .tmp / 极小且老 mp4。返回清理字节数。"""
    if not root or not os.path.isdir(root):
        return 0
    freed = 0
    cutoff = time.time() - max_age_h * 3600
    for dirpath, dirnames, filenames in os.walk(root):
        for dn in list(dirnames):
            d = os.path.join(dirpath, dn)
            if dn.startswith(".ep") and os.path.isdir(d):
                sz = _dir_size(d)
                shutil.rmtree(d, ignore_errors=True)
                freed += sz
                logger.info("清理 chunked 残留目录: %s (%d B)", d, sz)
                dirnames.remove(dn)
        for fn in filenames:
            f = os.path.join(dirpath, fn)
            try:
                if fn.endswith((".part.ts", ".tmp", ".mp4.tmp")):
                    sz = os.path.getsize(f)
                    os.remove(f)
                    freed += sz
                    logger.info("清理临时文件: %s (%d B)", f, sz)
                elif fn.endswith(".mp4") and os.path.getmtime(f) < cutoff \
                        and os.path.getsize(f) < 50_000:
                    sz = os.path.getsize(f)
                    os.remove(f)
                    freed += sz
                    logger.info("清理疑似残片 mp4: %s (%d B)", f, sz)
            except OSError:
                pass
    return freed


def _dir_size(path):
    tot = 0
    for dirpath, _, files in os.walk(path):
        for fn in files:
            try:
                tot += os.path.getsize(os.path.join(dirpath, fn))
            except OSError:
                pass
    return tot
