# -*- coding: utf-8 -*-
"""日志模块：控制台 + 滚动文件双输出。

升级预留：想接远程日志/结构化(JSON)日志，改这里即可，调用方不感知。
"""
import os
import logging
import logging.handlers


def setup_logging(logfile=None, level=logging.INFO):
    """初始化日志。logfile 给定则同时写滚动文件(5MB×3)。返回 logger。"""
    handlers = []
    if logfile:
        os.makedirs(os.path.dirname(logfile) or ".", exist_ok=True)
        handlers.append(logging.handlers.RotatingFileHandler(
            logfile, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"))
    handlers.append(logging.StreamHandler())

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s %(message)s",
        handlers=handlers,
        force=True)
    return logging.getLogger("hg")
