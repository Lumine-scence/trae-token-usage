# -*- coding: utf-8 -*-
"""
paths.py -- 发行版路径与配置解析。

所有路径均可通过 config.json 覆盖；留空则使用自动探测：
  db_path  : %APPDATA%\\TRAE SOLO CN\\ModularData\\ai-agent\\database.db
  dll_path : <repo>/bin/trae_crypto.dll
  key_log  : <repo>/key_capture.log
"""

import json
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(REPO, "config.json")
EXAMPLE_CONFIG_PATH = os.path.join(REPO, "config.example.json")


def _default_db():
    appdata = os.environ.get("APPDATA", "")
    return os.path.join(appdata, "TRAE SOLO CN", "ModularData",
                        "ai-agent", "database.db")


def _default_dll():
    return os.path.join(REPO, "bin", "trae_crypto.dll")


def _default_keylog():
    return os.path.join(REPO, "key_capture.log")


class Config:
    def __init__(self):
        raw = {}
        for p in (EXAMPLE_CONFIG_PATH, CONFIG_PATH):
            if os.path.isfile(p):
                try:
                    with open(p, encoding="utf-8") as f:
                        raw.update(json.load(f))
                except (OSError, ValueError):
                    pass
        self.db_path = raw.get("db_path") or _default_db()
        self.dll_path = raw.get("dll_path") or _default_dll()
        self.key_log = raw.get("key_log") or _default_keylog()
        self.auto_capture = bool(raw.get("auto_capture", True))
        try:
            self.rva_fallback = int(str(raw.get("rva_fallback", "0x92B149C")), 16)
        except ValueError:
            self.rva_fallback = 0x92B149C
        # 运行产物目录（缓存等）默认放 repo 根
        self.cache_path = raw.get("cache_path") or os.path.join(
            REPO, "usage_cache.json")

    def ensure_dirs(self):
        for p in (self.key_log, self.cache_path):
            d = os.path.dirname(os.path.abspath(p))
            if d:
                os.makedirs(d, exist_ok=True)
