# -*- coding: utf-8 -*-
"""mcp_server.py -- trae-token-usage MCP Server (stdio + JSON-RPC 2.0)。"""

import json
import os
import sys
import threading
import time
import traceback

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
for _p in (_REPO, _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from server import engine as eng_mod          # noqa: E402
from server.engine import EngineError         # noqa: E402
from server.keywatch import start_watcher     # noqa: E402

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "trae-real-usage"
SERVER_VERSION = "1.0.0"

_engine = eng_mod.UsageEngine(log=lambda m: _elog(m))
_state = {"auto_capture_done": False, "last_capture_info": None}


def _elog(m):
    try:
        print(time.strftime("[%H:%M:%S] ") + m, file=sys.stderr, flush=True)
    except Exception:
        pass


def _maybe_auto_capture(delay):
    def worker():
        time.sleep(delay)
        if _state["auto_capture_done"]:
            return
        _state["auto_capture_done"] = True
        if not _engine.cfg.auto_capture:
            return
        if not _engine.key_is_stale():
            _elog("[auto] 密钥有效，跳过补获")
            return
        _elog("[auto] 密钥缺失/过期，后台自动补获 ...")
        t0 = time.time()
        ok = _engine.ensure_key()
        _state["last_capture_info"] = {"got": ok, "elapsed": round(time.time() - t0, 1)}
        if ok:
            _elog("[auto] 补获成功")

    threading.Thread(target=worker, daemon=True).start()


# ------------------------------------------------------------------ 工具
def _fmt(n):
    n = int(n)
    if n >= 1_000_000:
        return "%.1fM" % (n / 1_000_000)
    if n >= 1_000:
        return "%.1fk" % (n / 1_000)
    return str(n)


def _proj_id(rec):
    ps = rec.get("projects") or []
    if not ps:
        return ""
    p = ps[0].replace("\\\\", "\\").rstrip("\\/")
    return p.split("\\")[-1] if "\\" in p else p


def tool_get_real_token_usage(args):
    limit = int((args or {}).get("limit", 20))
    recs = list(_engine.get_records())
    tot = _engine.stats(recs)
    tail = recs[-limit:] if limit and limit > 0 else recs
    aliases = eng_mod.load_aliases(os.path.dirname(_engine.cfg.cache_path))
    lines = ["最近 %d 轮 / 共 %d 轮：" % (len(tail), tot["turns"])]
    for r in tail:
        pid = _proj_id(r)
        label = eng_mod.alias_for(pid, aliases)
        lines.append(
            "- %s | trace %.8s… | 输入 %s | 输出 %s | 推理 %s | 缓存读 %s"
            % (label, r.get("trace_id", "?"), _fmt(r.get("prompt_tokens", 0)),
               _fmt(r.get("completion_tokens", 0)), _fmt(r.get("reasoning_tokens", 0)),
               _fmt(r.get("cache_read_input_tokens", 0))))
    hit = round(100.0 * tot["cache_read_input_tokens"] / tot["prompt_tokens"], 1) \
        if tot["prompt_tokens"] else 0.0
    lines.append("")
    lines.append(
        "总计 %d 轮：输入 %d | 输出 %d | 推理 %d | 缓存读 %d | 缓存写 %d | 缓存命中率 %.1f%%"
        % (tot["turns"], tot["prompt_tokens"], tot["completion_tokens"],
           tot["reasoning_tokens"], tot["cache_read_input_tokens"],
           tot["cache_creation_input_tokens"], hit))
    return "\n".join(lines)


def tool_get_usage_stats(args):
    tot = _engine.stats()
    hit = round(100.0 * tot["cache_read_input_tokens"] / tot["prompt_tokens"], 1) \
        if tot["prompt_tokens"] else 0.0
    return (
        "TRAE 全部历史 AI 用量统计：\n"
        "- 对话轮次: %d\n- 输入 tokens: %d\n- 输出 tokens: %d\n- 推理 tokens: %d\n"
        "- 缓存读取 tokens: %d\n- 缓存写入 tokens: %d\n- 总 tokens: %d\n"
        "- 缓存命中率: %.1f%%\n- 数据文件: usage_cache.json（主库+WAL 实时解析）"
        % (tot["turns"], tot["prompt_tokens"], tot["completion_tokens"],
           tot["reasoning_tokens"], tot["cache_read_input_tokens"],
           tot["cache_creation_input_tokens"], tot["total_tokens"], hit))


def tool_get_usage_by_project(args):
    recs = _engine.get_records()
    flt = ((args or {}).get("project") or "").strip().lower()
    aliases = eng_mod.load_aliases(os.path.dirname(_engine.cfg.cache_path))

    groups = {}
    for r in recs:
        pid = _proj_id(r) or "(未知)"
        label = eng_mod.alias_for(pid, aliases)
        if flt:
            hay = (label + " " + pid).lower()
            alias_hit = any(flt in (k.lower() or "") or flt in (v or "").lower()
                            for k, v in aliases.items())
            if flt not in hay and not pid.lower().startswith(flt) and not alias_hit:
                continue
        g = groups.setdefault(pid, {"label": label, "turns": 0, "prompt_tokens": 0,
                                    "completion_tokens": 0, "reasoning_tokens": 0,
                                    "cache_read_input_tokens": 0})
        g["turns"] += 1
        for f in ("prompt_tokens", "completion_tokens", "reasoning_tokens",
                  "cache_read_input_tokens"):
            g[f] += r.get(f, 0)

    if not groups:
        ids = sorted({_proj_id(r) for r in recs if _proj_id(r)})
        return ("没有匹配的项目。当前库中的项目 ID（可在 project_aliases.json 配置别名）：\n"
                + "\n".join("- %s…" % i[:8] for i in ids[:40]))

    order = sorted(groups.values(), key=lambda g: -g["prompt_tokens"])
    total_turns = sum(g["turns"] for g in order)
    lines = ["按项目聚合的 token 用量（%d 个项目 / %d 轮）：" % (len(order), total_turns)]
    for g in order:
        hit = (100.0 * g["cache_read_input_tokens"] / g["prompt_tokens"]) \
            if g["prompt_tokens"] else 0.0
        lines.append("- %s | %d 轮 | 输入 %s | 输出 %s | 缓存读 %s | 命中率 %.1f%%"
                     % (g["label"], g["turns"], _fmt(g["prompt_tokens"]),
                        _fmt(g["completion_tokens"]), _fmt(g["cache_read_input_tokens"]), hit))
    lines.append("\n提示：项目名太长？在 project_aliases.json 里配置别名，查询时可传别名或 ID 前缀。")
    return "\n".join(lines)


def tool_refresh_token_usage(args):
    force = bool((args or {}).get("force", False))
    t0 = time.time()
    recs = _engine.get_records(force=force)
    return "刷新完成（%.1fs）：共 %d 轮记录。" % (time.time() - t0, len(recs))


def tool_capture_db_key(args):
    ok = _engine.ensure_key(timeout=120)
    return ("密钥已就绪。" if ok else
            "补获失败：请确认 TRAE 正在运行，稍后重试。")


def tool_get_key_status(args):
    lit = eng_mod.load_key_literal(_engine.cfg.key_log)
    age = eng_mod.key_age_seconds(_engine.cfg.key_log)
    stale = _engine.key_is_stale()
    cap = _state["last_capture_info"]
    return (
        "密钥状态：\n- 已捕获: %s\n- 捕获时间: %s前\n- 相对最近 ai-agent 进程: %s\n"
        "- 后台上次补获: %s"
        % ("是" if lit else "否",
           ("%.0f 秒" % age) if age is not None else "无记录",
           ("有效" if not stale else "已过期（查询时会自动补获）"),
           json.dumps(cap, ensure_ascii=False) if cap else "尚未执行"))


TOOLS = [
    {"name": "get_real_token_usage",
     "description": "获取 TRAE 每轮对话的真实精确 token 用量（输入/输出/推理/缓存命中）。",
     "inputSchema": {"type": "object",
                     "properties": {"limit": {"type": "integer", "description": "返回最近 N 轮，默认 20"}},
                     "required": []}},
    {"name": "get_usage_stats",
     "description": "全部历史的 token 用量汇总统计与缓存命中率。",
     "inputSchema": {"type": "object", "properties": {}, "required": []}},
    {"name": "get_usage_by_project",
     "description": "按项目聚合 token 用量。可选 project 参数：传别名或项目 ID 前缀过滤。",
     "inputSchema": {"type": "object",
                     "properties": {"project": {"type": "string"}}, "required": []}},
    {"name": "refresh_token_usage",
     "description": "强制重新解析本地数据库刷新缓存。",
     "inputSchema": {"type": "object",
                     "properties": {"force": {"type": "boolean"}}, "required": []}},
    {"name": "capture_db_key",
     "description": "确保数据库密钥可用（必要时重启 TRAE 的 ai-agent 进程补获，会话会短暂中断后恢复）。",
     "inputSchema": {"type": "object", "properties": {}, "required": []}},
    {"name": "get_key_status",
     "description": "查看数据库密钥状态。",
     "inputSchema": {"type": "object", "properties": {}, "required": []}},
]

TOOL_IMPL = {
    "get_real_token_usage": tool_get_real_token_usage,
    "get_usage_stats": tool_get_usage_stats,
    "get_usage_by_project": tool_get_usage_by_project,
    "refresh_token_usage": tool_refresh_token_usage,
    "capture_db_key": tool_capture_db_key,
    "get_key_status": tool_get_key_status,
}

# ------------------------------------------------------------------ 协议层
def _send(msg):
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _handle(request):
    method = request.get("method")
    msg_id = request.get("id")
    params = request.get("params") or {}

    if method == "notifications/initialized":
        return None
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION}}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        impl = TOOL_IMPL.get(name)
        if not impl:
            return {"jsonrpc": "2.0", "id": msg_id, "result": {
                "content": [{"type": "text", "text": "未知工具: %s" % name}], "isError": True}}
        try:
            text = impl(args)
            result = {"content": [{"type": "text", "text": text}], "isError": False}
        except Exception as e:  # noqa: BLE001
            hint = ""
            if isinstance(e, EngineError):
                hint = "\n提示：可调用 capture_db_key 工具重试。"
            result = {"content": [{"type": "text",
                                   "text": "工具 %s 执行失败: %s%s" % (name, e, hint)}],
                      "isError": True}
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}
    return {"jsonrpc": "2.0", "id": msg_id,
            "error": {"code": -32601, "message": "不支持的方法: %s" % method}}


def main():
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    try:
        start_watcher(_engine, log=_elog)
    except Exception as e:  # noqa: BLE001
        _elog("watcher 启动失败: %s" % e)

    def warmup():
        try:
            _engine.get_records()
            _elog("[warmup] 用量缓存就绪")
        except Exception as e:  # noqa: BLE001
            _elog("[warmup] 预热跳过: %s" % str(e)[:140])
        _maybe_auto_capture(5)

    threading.Thread(target=warmup, daemon=True).start()
    _elog("server ready (%s v%s)" % (SERVER_NAME, SERVER_VERSION))

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            response = _handle(request)
        except Exception as e:  # noqa: BLE001
            _elog("处理请求出错: %s" % traceback.format_exc(limit=1))
            response = {"jsonrpc": "2.0", "id": request.get("id"),
                        "error": {"code": -32603, "message": "internal error: %s" % e}}
        if response is not None:
            _send(response)


if __name__ == "__main__":
    main()
