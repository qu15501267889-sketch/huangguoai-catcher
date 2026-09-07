# -*- coding: utf-8 -*-
"""CLI 入口：argparse 解析 + 组装各模块。薄壳，逻辑都在模块里。"""
import os
import json
import argparse

from .config import load_config, Config
from .logging_utils import setup_logging
from .http import RateLimiter
from .crypto import fetch_media_keys
from .orchestrator import enumerate_series, discover, download_all
from .watchdog import check_health, cleanup_junks, send_notify
from .utils import save_manifest, human_size, ffmpeg_bin, ffprobe_bin

DEFAULT_OUT = os.path.join(os.path.expanduser("~"), "hg_dumps", "huangguoai")


def build_parser():
    ap = argparse.ArgumentParser(description="huangguoai AI短剧下载器 v3")
    ap.add_argument("--config", default="config.json", help="配置文件路径")
    ap.add_argument("--out", default=None, help="输出目录(覆盖config)")
    ap.add_argument("--manifest", default=None, help="增量状态文件(覆盖config)")
    ap.add_argument("--only", default="", help="只下指定剧id,逗号分隔")
    ap.add_argument("--max-eps", type=int, default=None, help="单剧最多集数(0=全部)")
    ap.add_argument("--workers", type=int, default=None, help="并发数")
    ap.add_argument("--dry-run", action="store_true", help="只列计划不下载")
    ap.add_argument("--with-meta", action="store_true", help="抓封面+简介")
    ap.add_argument("--mode", choices=["ffmpeg", "chunked"], default="ffmpeg",
                    help="下载模式")
    ap.add_argument("--log", default=None, help="日志文件路径")
    ap.add_argument("--test-notify", action="store_true", help="只测发送提醒后退出")
    ap.add_argument("--no-ratelimit", action="store_true", help="关闭限流(调试)")
    return ap


def _defaults(cfg):
    """读 config.json 里的 out/manifest（若配置了），否则用默认。"""
    return cfg.get("out", DEFAULT_OUT), cfg.get("out", "") and cfg.get("manifest", "")


def main():
    args = build_parser().parse_args()
    cfg_raw = load_config(args.config)
    cfg = Config(cfg_raw)

    cfg_out = cfg_raw.get("out", DEFAULT_OUT)
    cfg_manifest = cfg_raw.get("manifest", os.path.join(cfg_out, "manifest.json"))
    out = args.out or cfg_out
    manifest = args.manifest or cfg_manifest
    if args.max_eps is not None:
        cfg.max_eps = args.max_eps
    if args.workers:
        cfg.workers = args.workers

    logger = setup_logging(args.log)
    logger.info("ffmpeg=%s ffprobe=%s mode=%s out=%s", ffmpeg_bin(), ffprobe_bin(),
                args.mode, out)

    if args.test_notify:
        send_notify(cfg, "测试提醒 - 黄果下载器", "收到即表示通知通道配置正常。", logger)
        if cfg.cleanup.get("enabled", True):
            freed = cleanup_junks(out, logger, cfg.cleanup.get("max_age_h", 24))
            logger.info("测试清理完成，释放 %s", human_size(freed))
        return

    limiter = RateLimiter(cfg.rate_per_sec if not args.no_ratelimit else 9999.0)

    key, iv = fetch_media_keys(cfg, limiter, cfg.base)
    if key and iv:
        cfg.img_key, cfg.img_iv = key, iv
        logger.info("图床密钥已从 crypto-worker.js 动态解析")
    else:
        logger.info("图床密钥使用硬编码兜底")

    os.makedirs(os.path.dirname(manifest), exist_ok=True)
    os.makedirs(out, exist_ok=True)
    manifest_data = {}
    if os.path.exists(manifest):
        try:
            manifest_data = json.load(open(manifest, encoding="utf-8"))
        except Exception:
            manifest_data = {}

    series = enumerate_series(cfg, limiter, logger)
    if not series:
        logger.error("!! 没枚举到任何剧集")
        return

    target = {k: v for k, v in series.items()}
    if args.only:
        sel = {x.strip() for x in args.only.split(",")}
        target = {k: v for k, v in series.items() if k in sel}
    logger.info("剧集总数=%d 目标=%d", len(series), len(target))

    to_download, meta = discover(cfg, limiter, logger, target, manifest_data,
                                 workers=cfg.workers)
    logger.info("待下载 %d 集", len(to_download))
    if args.dry_run:
        for vid, ep, title in to_download[:50]:
            logger.info("  %s (id=%s) ep%02d", title, vid, ep)
        return

    ok_count, failed = download_all(cfg, limiter, logger, to_download, out,
                                    manifest_data, manifest, args.mode,
                                    workers=cfg.workers, meta_map=meta,
                                    with_meta=args.with_meta)
    save_manifest(manifest_data, manifest)
    logger.info("完成: 成功=%d 失败=%d", ok_count, len(failed))
    for vid, ep, title in failed[:50]:
        logger.warning("  失败 id=%s ep=%s %s", vid, ep, title)
    if failed:
        logger.warning("重跑可自动补下失败的 %d 集", len(failed))

    check_health(len(series), ok_count, len(failed), manifest_data, logger, cfg)
    save_manifest(manifest_data, manifest)

    if cfg.cleanup.get("enabled", True):
        freed = cleanup_junks(out, logger, cfg.cleanup.get("max_age_h", 24))
        if freed:
            logger.info("垃圾清理完成，释放 %s", human_size(freed))
    else:
        logger.info("垃圾清理已禁用")


if __name__ == "__main__":
    main()
