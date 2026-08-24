# -*- coding: utf-8 -*-
"""
engine.py -- 用量提取编排层（开源部分）。

密码学核心（AES-256 页解密 / WAL 解析 / RVA 探测）在闭源组件
bin/trae_crypto.dll 中，通过 ctypes 调用：

  tc_decrypt_file(key32, path_w, is_main, &buf, &len)
      整文件"无 IV 批量解密"，返回拼接明文（每页体跳过首 16 字节）
  tc_probe_key_rva(dll_path_w, &rva)
      定位 ai_agent.dll 内 sqlite3_key_v2 实现体的 RVA
  tc_free(ptr)

本文件只包含：密钥读取、DLL 调用、正则提取、缓存、项目别名。
"""

import ctypes
import json
import os
import re
import threading
import time

from server.paths import Config

TU_RE = re.compile(
    rb'"trace_id":"([0-9a-f]{32})"[^\n]{0,4000}?"token_usage":(\{[^{}]*?"prompt_tokens"[^{}]*?\})'
)
WSF_RE = re.compile(rb'"workspace_folders":\s*\[\s*"((?:[^"\\]|\\.)*)"')

_lock = threading.RLock()


class EngineError(Exception):
    pass


# ------------------------------------------------------------------ DLL 绑定
class CryptoDll:
    def __init__(self, dll_path):
        if not os.path.isfile(dll_path):
            raise EngineError("找不到核心组件: %s" % dll_path)
        dll = ctypes.CDLL(dll_path)
        dll.tc_decrypt_file.argtypes = [
            ctypes.c_char_p, ctypes.c_wchar_p, ctypes.c_int,
            ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint64)]
        dll.tc_decrypt_file.restype = ctypes.c_int
        dll.tc_probe_key_rva.argtypes = [ctypes.c_wchar_p,
                                         ctypes.POINTER(ctypes.c_uint)]
        dll.tc_probe_key_rva.restype = ctypes.c_int
        dll.tc_free.argtypes = [ctypes.c_void_p]
        self._dll = dll
        self.path = dll_path

    def decrypt_file(self, key32, path, is_main):
        buf, olen = ctypes.c_void_p(), ctypes.c_uint64()
        rc = self._dll.tc_decrypt_file(
            key32, ctypes.c_wchar_p(os.path.abspath(path)), 1 if is_main else 0,
            ctypes.byref(buf), ctypes.byref(olen))
        if rc != 0:
            raise EngineError("核心解密失败 (code=%d)：%s" % (rc, os.path.basename(path)))
        data = ctypes.string_at(buf.value, olen.value)
        self._dll.tc_free(ctypes.c_void_p(buf.value))
        return data

    def probe_key_rva(self, dll_path):
        rva = ctypes.c_uint(0)
        rc = self._dll.tc_probe_key_rva(ctypes.c_wchar_p(os.path.abspath(dll_path)),
                                        ctypes.byref(rva))
        if rc != 0:
            raise EngineError("RVA 探测失败 (code=%d)" % rc)
        return rva.value


# ------------------------------------------------------------------ 密钥
def load_key_literal(key_log):
    """从 key_capture.log 尾部读取最新 x'<hex>' 密钥字面量。"""
    if not os.path.isfile(key_log):
        return None
    try:
        with open(key_log, encoding="utf-8", errors="ignore") as f:
            for line in reversed(f.readlines()):
                if "KEY_HEX=" in line:
                    hx = line.split("KEY_HEX=", 1)[1].strip()
                    raw = bytes.fromhex(hx).decode("ascii", errors="replace").strip()
                    if raw.startswith("x'"):
                        return raw
    except OSError:
        pass
    return None


def parse_key(literal):
    m = re.fullmatch(r"x'([0-9a-fA-F]+)'", literal or "")
    if not m or len(m.group(1)) < 64:
        raise EngineError("密钥字面量格式无法解析")
    return bytes.fromhex(m.group(1)[:64])


def key_age_seconds(key_log):
    try:
        return max(0.0, time.time() - os.path.getmtime(key_log))
    except OSError:
        return None


def recent_ai_agent_born_ts():
    import psutil
    best = 0
    for p in psutil.process_iter(["create_time", "name", "cmdline"]):
        try:
            if p.info["name"] != "TRAE SOLO CN.exe":
                continue
            cl = " ".join(p.info["cmdline"] or [])
            if "basil.mojom" in cl or "NativeExtensionService" in cl:
                best = max(best, p.info["create_time"] or 0)
        except Exception:
            continue
    return best


def kill_ai_agent():
    import psutil
    killed = []
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if p.info["name"] != "TRAE SOLO CN.exe":
                continue
            cl = " ".join(p.info["cmdline"] or [])
            if "basil.mojom" in cl or "NativeExtensionService" in cl:
                p.kill()
                killed.append(p.info["pid"])
        except Exception:
            continue
    return killed


# ------------------------------------------------------------------ 提取与别名
def extract_records(plaintext, records_out):
    """在解密明文中提取 token_usage 记录，合并进 records_out dict。"""
    for m in TU_RE.finditer(plaintext):
        trace = m.group(1).decode()
        try:
            usage = json.loads(m.group(2).decode("utf-8", errors="replace"))
        except Exception:
            continue
        lo_end = m.end()
        w = WSF_RE.search(plaintext, lo_end, min(len(plaintext), lo_end + 800))
        projects = []
        if w:
            try:
                folders = json.loads(b'["' + w.group(1) + b'"]')
                projects = folders if isinstance(folders, list) else []
            except Exception:
                pass
        usage["trace_id"] = trace
        usage["projects"] = projects
        records_out[trace] = usage
    return records_out


def load_aliases(repo):
    path = os.path.join(repo, "project_aliases.json")
    try:
        with open(path, encoding="utf-8") as f:
            a = json.load(f)
        return a if isinstance(a, dict) else {}
    except (OSError, ValueError):
        return {}


def alias_for(pid, aliases):
    for k in sorted(aliases.keys(), key=len, reverse=True):
        if k and (pid or "").startswith(k):
            return aliases[k]
    pid = pid or ""
    return pid[:8] + ("…" if len(pid) > 8 else "")


# ------------------------------------------------------------------ 引擎门面
class UsageEngine:
    def __init__(self, log=None, before_capture_hook=None, auto_fetch=True):
        self.cfg = Config()
        self.cfg.ensure_dirs()
        self.log = log or (lambda m: None)
        # 补获密钥前由 MCP 层注入的等待回调（确保 frida watcher 已进入监听）
        self.before_capture_hook = before_capture_hook
        # True=允许杀 ai-agent 自动补获（capture_key_once.py 手动采集用）；
        # False=只读已存密钥，绝不杀进程（MCP 服务用，防止对话中杀进程死循环）
        self.auto_fetch = auto_fetch
        self._dll = None
        self._cache = self._load_cache()
        # 本次进程内已验证过密钥有效；避免重启后每次都重复全量解密
        self._key_confirmed = False

    # ---- 基础设施
    @property
    def dll(self):
        if self._dll is None:
            self._dll = CryptoDll(self.cfg.dll_path)
        return self._dll

    def _load_cache(self):
        try:
            with open(self.cfg.cache_path, encoding="utf-8") as f:
                c = json.load(f)
            if isinstance(c.get("records"), dict):
                return c
        except (OSError, ValueError):
            pass
        return {"db_mtime": None, "records": {}, "updated_at": None}

    def _save_cache(self):
        self._cache["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        tmp = self.cfg.cache_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._cache, f, ensure_ascii=False)
        os.replace(tmp, self.cfg.cache_path)

    # ---- 密钥
    def key_is_stale(self):
        lit = load_key_literal(self.cfg.key_log)
        if not lit:
            return True
        age = key_age_seconds(self.cfg.key_log)
        if age is None:
            return True
        born = recent_ai_agent_born_ts()
        return born > 0 and (time.time() - age) < born

    def _existing_key_valid(self):
        """用已存密钥试解密主库，判断密钥是否仍然有效。
        正确密钥解出结构化 SQLite 内容（含大量 'sqlite' 字样）；
        错误密钥只能得到伪随机字节（'sqlite' 基本为 0）。
        """
        lit = load_key_literal(self.cfg.key_log)
        if not lit:
            return False
        try:
            key = parse_key(lit)
        except EngineError:
            return False
        if not os.path.isfile(self.cfg.db_path):
            return False
        try:
            data = self.dll.decrypt_file(key, self.cfg.db_path, True)
        except (EngineError, OSError):
            return False
        return data.count(b"sqlite") > 0

    def ensure_key(self, timeout=90):
        """确保密钥可用。返回 True/False。

        关键时序保证：杀进程之前必须让 watcher 完成 RVA 探测并进入监听状态，
        否则新进程开库会早于挂钩就位而永远错过。
        auto_fetch=False（MCP 服务）时绝不杀进程，只读已存密钥。
        """
        if self._key_confirmed:
            return True
        if not self.key_is_stale():
            self._key_confirmed = True
            return True
        # 已有密钥却判"过期"（刚重启过、TRAE 又拉起新 ai-agent）：
        # 先用存下来的密钥试解密主库，若仍产出结构化 SQLite 内容则密钥未轮换，直接复用。
        if self._existing_key_valid():
            self._key_confirmed = True
            self.log("[engine] 已存密钥仍有效，复用")
            return True
        if not self.auto_fetch:
            self.log("[engine] 无有效密钥：请先手动运行 capture_key_once.py 采集")
            return False
        try:
            self.get_key_rva()          # 强制完成探测（watcher 用同一结果）
        except EngineError as e:
            self.log("[engine] RVA 探测失败，无法安全补获：%s" % e)
            return False
        if self.before_capture_hook:
            self.log("[engine] 等待密钥监听就绪 ...")
            self.before_capture_hook()  # 阻塞直至 watcher 进入监听循环
        time.sleep(0.5)                 # 再给 watcher 一点进入监听的时间
        self.log("[engine] 密钥缺失/过期，自动补获（当前 AI 会话将中断几秒后恢复）...")
        if not os.path.isfile(self.cfg.key_log):
            open(self.cfg.key_log, "a", encoding="utf-8").close()
        baseline = os.path.getmtime(self.cfg.key_log)
        kill_ai_agent()
        deadline = time.time() + timeout
        lit = None
        while time.time() < deadline:
            try:
                if (os.path.getmtime(self.cfg.key_log) > baseline):
                    lit = load_key_literal(self.cfg.key_log)
                    if lit:
                        break
            except OSError:
                pass
            time.sleep(1)
        ok = bool(lit)
        self._key_confirmed = ok
        self.log("[engine] 自动补获%s" % ("成功" if ok else "失败"))
        return ok

    def get_key_rva(self):
        """探测挂钩地址；失败回退配置值。"""
        try:
            return self.dll.probe_key_rva(self._ai_agent_dll_path())
        except EngineError:
            return self.cfg.rva_fallback

    def _ai_agent_dll_path(self):
        """定位 ai_agent.dll：config 显式配置 > TRAE_INSTALL_DIR 环境变量 > 常见位置探测。"""
        if self.cfg.ai_agent_dll_path:
            return self.cfg.ai_agent_dll_path
        env = os.environ.get("TRAE_INSTALL_DIR")
        if env:
            cand = os.path.join(env, "resources", "app", "modules",
                                "ai-agent", "ai_agent.dll")
            if os.path.isfile(cand):
                return cand
        candidates = []
        for drive in ("C", "D", "E"):
            candidates.append(rf"{drive}:\TRAE SOLO CN\resources\app\modules"
                              rf"\ai-agent\ai_agent.dll")
        for pf_var in ("ProgramFiles", "ProgramFiles(x86)"):
            pf = os.environ.get(pf_var)
            if pf:
                candidates.append(os.path.join(
                    pf, "TRAE SOLO CN", "resources", "app", "modules",
                    "ai-agent", "ai_agent.dll"))
        for c in candidates:
            if os.path.isfile(c):
                return c
        return candidates[0]

    # ---- 主入口
    def get_records(self, force=False):
        with _lock:
            lit = load_key_literal(self.cfg.key_log)
            stale = self.key_is_stale()
            if not lit or (stale and not self.ensure_key()):
                raise EngineError(
                    "密钥不可用：请运行项目目录下的 capture_key_once.py 获取密钥"
                    "（脚本会引导采集，必要时自动重启 TRAE），采集成功后重新查询。")
            key = parse_key(load_key_literal(self.cfg.key_log))

            db_m = os.path.getmtime(self.cfg.db_path) if os.path.isfile(self.cfg.db_path) else None
            wal_p = self.cfg.db_path + "-wal"
            wal_m = os.path.getmtime(wal_p) if os.path.isfile(wal_p) else None
            if db_m is None:
                raise EngineError("找不到数据库文件: %s" % self.cfg.db_path)

            need_main = force or self._cache.get("db_mtime") != db_m
            recs = {} if need_main else dict(self._cache.get("records") or {})
            if need_main:
                self.log("[engine] 全量解密主库 ...")
                recs.update(extract_records(self.dll.decrypt_file(key, self.cfg.db_path, True), recs))
                self._cache["db_mtime"] = db_m
            if wal_m:
                recs.update(extract_records(self.dll.decrypt_file(key, wal_p, False), recs))
            self._cache["records"] = recs
            self._save_cache()
            return list(recs.values())

    def stats(self, records=None):
        recs = records if records is not None else self.get_records()
        keys = ("prompt_tokens", "completion_tokens", "reasoning_tokens",
                "cache_read_input_tokens", "cache_creation_input_tokens", "total_tokens")
        out = {"turns": len(recs)}
        for k in keys:
            out[k] = sum(r.get(k, 0) for r in recs)
        return out

