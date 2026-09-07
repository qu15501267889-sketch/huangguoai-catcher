# -*- coding: utf-8 -*-
"""hgcatcher —— huangguoai 短剧下载器包。

用法:
  python -m hgcatcher --config config.json --only 117
  python hgcatcher/cli.py   --config config.json --dry-run
"""
from .config import load_config, Config
from .parsers import get_parser, register, HuangguoParser
from .downloaders import get_downloader, register_downloader
from .orchestrator import Hook

__version__ = "3.0.0"
__all__ = [
    "load_config", "Config", "get_parser", "register", "HuangguoParser",
    "get_downloader", "register_downloader", "Hook",
]
