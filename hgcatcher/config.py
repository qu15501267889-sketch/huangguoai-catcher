# -*- coding: utf-8 -*-
"""配置模块：加载 config.json，提供带默认值/校验的 Config 对象。

预留给升级：Config 是纯数据 + 只读访问，任何模块都要通过它拿参数，
未来想换成环境变量/数据库/argparse 驱动的配置层，只需改这里。
"""
import os
import json

# 图床 AES 密钥兜底（动态拉取失败时用）；下划线分隔十进制字节
_IMG_KEY_DEC = "102_53_100_57_54_53_100_102_55_53_51_51_54_50_55_48"
_IMG_IV_DEC = "57_55_98_54_48_51_57_52_97_98_99_50_102_98_101_49"

DEFAULT_CONFIG = {
    "base": "https://huangguoai.com",
    "category": "/ai-duanju/",
    "ua": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
           "AppleWebKit/537.36 (KHTML, like Gecko) "
           "Chrome/120.0 Safari/537.36"),
    "retry": 3,
    "sleep": 1.5,
    "workers": 3,
    "max_eps": 0,
    "rate_per_sec": 2.0,        # 每 worker 每秒请求数上限
    "min_episode_bytes": 100_000,
    "min_duration_sec": 1.0,
    "img_key_dec": _IMG_KEY_DEC,
    "img_iv_dec": _IMG_IV_DEC,
    "crypto_worker_url": "/static/web/js/plugins/crypto-worker.js",
    # 主动提醒(改版/异常)通道；type: webhook/bark/serverchan/wecom
    "notify": {"enabled": False, "type": "webhook", "url": ""},
    # 垃圾自动清理
    "cleanup": {"enabled": True, "max_age_h": 24},
    # 升级接口：站点解析器工厂名（预留多站点）
    "parser": "huangguoai",
    # 升级接口：自定义下载器注册表前缀（预留扩展）
    "module_prefix": "hgcatcher",
}


def load_config(path=None):
    """加载配置：默认值打底 + 文件覆盖 + 环境变量覆盖。

    优先级：内置默认 < config.json < 环境变量(HG_*)
    环境变量映射：HG_BASE / HG_CATEGORY / HG_WORKERS / HG_MAX_EPS / HG_RATE_PER_SEC
    """
    cfg = dict(DEFAULT_CONFIG)
    # 1) 文件覆盖
    if path and os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                file_cfg = json.load(f)
            if isinstance(file_cfg, dict):
                cfg.update(file_cfg)
        except Exception:
            pass
    # 2) 环境变量覆盖（升级接口，Docker 纯环境变量也能跑）
    env_map = {
        "HG_BASE": "base", "HG_CATEGORY": "category", "HG_WORKERS": "workers",
        "HG_MAX_EPS": "max_eps", "HG_RATE_PER_SEC": "rate_per_sec",
    }
    for env, key in env_map.items():
        if env in os.environ:
            val = os.environ[env]
            if key in ("workers", "max_eps"):
                try:
                    val = int(val)
                except ValueError:
                    continue
            elif key == "rate_per_sec":
                try:
                    val = float(val)
                except ValueError:
                    continue
            cfg[key] = val
    return cfg


def parse_dec_bytes(s):
    """'102_53_...' -> bytes（下划线分隔十进制）"""
    return bytes(int(x) for x in str(s).split("_"))


class Config:
    """只读配置对象。所有模块经此访问参数，不直接读文件。"""

    def __init__(self, cfg):
        self.base = cfg["base"]
        self.category = cfg["category"]
        self.ua = cfg["ua"]
        self.headers = {"User-Agent": cfg["ua"], "Accept-Language": "zh-CN,zh;q=0.9"}
        self.retry = cfg["retry"]
        self.sleep = cfg["sleep"]
        self.workers = cfg["workers"]
        self.max_eps = cfg["max_eps"]
        self.rate_per_sec = cfg["rate_per_sec"]
        self.min_episode_bytes = cfg["min_episode_bytes"]
        self.min_duration_sec = cfg["min_duration_sec"]
        # 图床密钥（动态拉取时会被覆盖）
        self.img_key = parse_dec_bytes(cfg["img_key_dec"])
        self.img_iv = parse_dec_bytes(cfg["img_iv_dec"])
        self.crypto_worker_url = cfg["crypto_worker_url"]
        self.notify = cfg.get("notify", {})
        self.cleanup = cfg.get("cleanup", {})
        self.parser_name = cfg.get("parser", "huangguoai")
