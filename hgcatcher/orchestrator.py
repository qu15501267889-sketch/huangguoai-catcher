# -*- coding: utf-8 -*-
"""编排模块：枚举剧集、discover(逐剧解析)、并发下载调度。

升级接口：Hook 事件回调（on_series_enum/on_episode_done/on_run_done），
方便接数据库、自定义通知、Webhook 等，无需改主流程。
"""
import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from .http import fetch
from .parsers import get_parser
from .downloaders import get_downloader
from .utils import save_manifest
from . import metadata as metadata_mod


# ── Hook 事件（升级接口） ──
class Hook:
    """订阅式事件。默认 no-op。子类覆写即可接业务。"""

    def on_series_enum(self, count, logger):
        pass

    def on_episode_done(self, vid, ep, ok, logger):
        pass

    def on_run_done(self, success, failed, logger):
        pass


def enumerate_series(cfg, limiter, logger, parser=None, max_pages=60, hook=None):
    """遍历分类全部分页 -> {vid: title}。抗断页：连续2空页才中止。"""
    parser = parser or get_parser(cfg.parser_name)
    series = {}
    page, empty_streak = 1, 0
    while True:
        url = (f"{cfg.base}{cfg.category}" if page == 1
               else f"{cfg.base}{cfg.category}{page}/")
        html = ""
        for att in range(cfg.retry):
            html = fetch(cfg, limiter, url)
            if html and html.strip():
                break
            time.sleep(cfg.sleep * (att + 1))
        if not html or not html.strip():
            empty_streak += 1
            if page == 1 or empty_streak >= 2:
                logger.warning("枚举在第 %d 页中止(连续%d空页)", page, empty_streak)
                break
            page += 1
            continue

        pairs = parser.parse_list(html)
        if not pairs:
            ids = set(parser.parse_plain_detail_ids(html))
            if not ids:
                empty_streak += 1
                if page == 1 or empty_streak >= 2:
                    break
                page += 1
                continue
            for vid in ids:
                series.setdefault(vid, f"series_{vid}")
        else:
            for title, vid in pairs:
                series.setdefault(vid, title)
        empty_streak = 0
        page += 1
        if page > max_pages:
            break
    if hook:
        hook.on_series_enum(len(series), logger)
    return series


def discover(cfg, limiter, logger, target, manifest, parser=None, workers=3):
    """并发逐剧解析。返回 (to_download, meta_map)。"""
    parser = parser or get_parser(cfg.parser_name)
    to_download, meta = [], {}
    lock = threading.Lock()

    def work(item):
        vid, init_title = item
        title, poster, desc = init_title, "", ""
        max_ep, got = 0, False
        for att in range(cfg.retry):
            try:
                html = fetch(cfg, limiter, f"{cfg.base}/detail/{vid}/")
                if html and html.strip():
                    t2, max_ep, poster, desc = parser.parse_detail(html, vid)
                    if t2 and t2 != f"series_{vid}":
                        title = t2
                    got = True
                    break
            except Exception as e:
                logger.error("get_series %s attempt%d ERR %s", vid, att + 1, e)
            time.sleep(cfg.sleep * (att + 1))
        if not got:
            logger.warning("跳过 %s(id=%s)：detail 页解析失败", init_title, vid)
            return
        with lock:
            meta[vid] = (title, poster, desc)
        if cfg.max_eps and max_ep > cfg.max_eps:
            max_ep = cfg.max_eps
        done = set(manifest.get(str(vid), {}).get("done", []))
        missing = sorted(set(range(1, max_ep + 1)) - done)
        with lock:
            for ep in missing:
                to_download.append((vid, ep, title))

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(work, list(target.items())))
    return to_download, meta


def _download_one(cfg, limiter, logger, dl, vid, ep, title, outdir):
    """worker：抓源 + 下载单集，返回 bool。源在 worker 内抓（避免提交阶段串行+签名过期）。"""
    from .http import fetch
    src = fetch(cfg, limiter, f"{cfg.base}/video/{vid}/ep-{ep}/")
    src = get_parser(cfg.parser_name).parse_src(src)
    if not src:
        return False
    d = os.path.join(outdir, f"{title}(id{vid})")
    return dl.download(cfg, limiter, vid, ep, src, d, logger)


def download_all(cfg, limiter, logger, to_download, outdir, manifest, manifest_path,
                 mode, workers=3, hook=None, meta_map=None, with_meta=False):
    """并发下载全部待下分集。返回 (ok_count, failed_list)。

    每集成功即原子落盘 manifest；with_meta 时先并发写元数据再下载。
    """
    dl = get_downloader(mode)
    ok_count, failed = 0, []

    if with_meta and meta_map:
        metadata_mod.write_meta_all(cfg, limiter, meta_map, outdir, logger, workers)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {}
        for vid, ep, title in to_download:
            futs[ex.submit(_download_one, cfg, limiter, logger, dl, vid, ep,
                           title, outdir)] = (vid, ep, title)

        for fut in as_completed(futs):
            vid, ep, title = futs[fut]
            try:
                ok = fut.result()
            except Exception as e:
                ok = False
                logger.error("ERR id=%s ep=%s %s", vid, ep, e)
            if ok:
                ok_count += 1
                v = manifest.setdefault(str(vid), {"title": title, "done": []})
                v["title"] = title
                dset = set(v.get("done", []))
                dset.add(ep)
                v["done"] = sorted(dset)
                save_manifest(manifest, manifest_path)
            else:
                failed.append((vid, ep, title))
                logger.warning("FAIL id=%s ep=%s", vid, ep)
            if hook:
                hook.on_episode_done(vid, ep, ok, logger)
    return ok_count, failed
