# -*- coding: utf-8 -*-
"""smoke_test.py -- 发行版端到端冒烟测试（模拟 TRAE MCP 客户端）。"""
import json
import os
import subprocess
import sys
import threading
import time

REPO = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(REPO, "server", "mcp_server.py")

proc = subprocess.Popen([sys.executable, SERVER], stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        encoding="utf-8")
resp = {}


def reader():
    for line in proc.stdout:
        try:
            m = json.loads(line)
            resp[m.get("id")] = m
        except Exception:
            pass


threading.Thread(target=reader, daemon=True).start()


def send(o):
    proc.stdin.write(json.dumps(o) + "\n")
    proc.stdin.flush()


def wait(i, t=300):
    t0 = time.time()
    while i not in resp and time.time() - t0 < t:
        time.sleep(0.2)
    return resp.get(i)


fails = []
send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
r = wait(1)
print("1 initialize:", "OK" if r else "FAIL")
if not r:
    fails.append(1)

send({"jsonrpc": "2.0", "method": "notifications/initialized"})
send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
r = wait(2)
tools = [t["name"] for t in (r["result"]["tools"] if r else [])]
print("2 tools/list:", len(tools), tools)
if len(tools) != 6:
    fails.append(2)

cases = [
    ("get_real_token_usage", {"limit": 3}, "总计"),
    ("get_usage_by_project", {}, "按项目聚合"),
    ("get_usage_stats", {}, "对话轮次"),
]
for idx, (name, args, marker) in enumerate(cases, start=3):
    send({"jsonrpc": "2.0", "id": idx, "method": "tools/call",
          "params": {"name": name, "arguments": args}})
    r = wait(idx)
    txt = r["result"]["content"][0]["text"] if r else ""
    ok = marker in txt
    print(idx, name + ":", "OK" if ok else "FAIL -> " + txt[:150])
    if not ok:
        fails.append(idx)

send({"jsonrpc": "2.0", "id": 6, "method": "tools/call",
      "params": {"name": "get_key_status", "arguments": {}}})
r = wait(6)
txt = r["result"]["content"][0]["text"] if r else ""
print("6 get_key_status:", "OK" if "已捕获" in txt else "FAIL")

proc.terminate()
if fails:
    print("FAILED ids:", fails)
    sys.exit(1)
print("ALL SMOKE TESTS PASSED")
