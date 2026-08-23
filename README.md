# trae-token-usage

Real, per-turn token usage for the TRAE IDE — exposed as an **MCP server** so you can
ask your AI assistant directly: *"how many tokens did I burn recently?"*

Data comes from decrypting TRAE's local SQLite database (SQLCipher-encrypted).
No estimation, no guessing — actual `prompt_tokens / completion_tokens /
reasoning_tokens / cache_read_input_tokens` for every single turn.

中文说明见下方 [中文](#中文)。

---

## How it works

TRAE's local session database (`database.db`) is SQLCipher encrypted with a random
per-launch key that is passed to `sqlite3_key_v2` once when a hidden helper process
opens it. This project:

1. **Captures that key** — a background watcher thread (frida) attaches to the
   helper process (`basil.mojom.NativeExtensionService`) and hooks
   `sqlite3_key_v2`. The hook address is found automatically by
   `trae_crypto.dll` via trace-format-string anchors inside `ai_agent.dll`
   (no hardcoded offsets needed across updates; a known-good fallback is included).
2. **Decrypts without knowing the IV** — each 4 KiB page body is AES-256-CBC
   encrypted with the page IV stored in its reserve area. We exploit the CBC
   property that *blocks i≥1 decrypt fine with just the previous cipher block*,
   so the whole database can be read while only the first 16 bytes of every page
   stay opaque.
3. **Extracts usage records** — every assistant reply embeds a
   `"token_usage": {...}` JSON block plus a `trace_id`; results are deduplicated
   by trace id and cached (`usage_cache.json`). The write-ahead log is re-scanned
   incrementally (seconds) so fresh conversations show up immediately.

## Install

Requirements: Windows, Python 3.9+, and `pip install frida psutil cryptography`.
The crypto core ships prebuilt as `bin/trae_crypto.dll`.

### Register in TRAE

Settings → MCP → add server:

```json
{
  "mcpServers": {
    "trae-real-usage": {
      "command": "python",
      "args": ["<path-to-this-folder>\\server\\mcp_server.py"]
    }
  }
}
```

That's it. On first query the server will ensure a database key exists — this
restarts TRAE's ai-agent process once (your current AI chat drops for a few
seconds, then recovers). After that everything is automatic.

## Tools

| Tool | Description |
|---|---|
| `get_real_token_usage(limit)` | Per-turn breakdown for the latest N turns |
| `get_usage_by_project(project?)` | Aggregated per workspace; filter by alias or id prefix |
| `get_usage_stats()` | All-time totals + cache hit-rate |
| `refresh_token_usage(force?)` | Re-scan db/wal |
| `capture_db_key()` | Ensure a fresh key is available |
| `get_key_status()` | Key freshness diagnostics |

## Configuration

Copy `config.example.json` to `config.json` and adjust if TRAE is installed in a
non-default location. Every field is optional.

```json
{
  "db_path": "",          // defaults to %APPDATA%\TRAE SOLO CN\ModularData\ai-agent\database.db
  "dll_path": "",         // defaults to <repo>/bin/trae_crypto.dll
  "key_log": "",          // defaults to <repo>/key_capture.log
  "auto_capture": true,
  "rva_fallback": "0x92B149C"
}
```

Optional `project_aliases.json` maps long project ids to friendly names:

```json
{ "6a8abceb": "my-cool-plugin" }
```

## Repository layout

```
bin/trae_crypto.dll     closed-source core: AES-256 page decryption, WAL parsing,
                        sqlite3_key_v2 RVA auto-detection
server/                 open source (GPL-3.0): MCP server, extraction logic,
                        key watcher, config handling
docs/HOW_IT_WORKS.md    deeper dive into the format & reverse-engineering notes
```

## Disclaimer

This tool reads **your own** local data from **your own** machine for personal
analytics. It is not affiliated with or endorsed by TRAE. Database formats may
change at any time; the closed-source core will be updated on a best-effort
basis. Use at your own risk and respect TRAE's terms of service.

Licensed under [GPL-3.0](LICENSE).

---

# 中文

为 TRAE IDE 提供**真实的、按轮次统计的 token 用量**，以 MCP 服务器的形式暴露给
对话中的 AI 助手。数据来自对 TRAE 本地 SQLCipher 加密数据库的解密，非估算。

## 工作原理

1. **密钥捕获**：后台 frida 线程挂钩 ai-agent 隐藏进程中的 `sqlite3_key_v2`。
   挂钩地址由 `trae_crypto.dll` 基于 `ai_agent.dll` 内部 trace 格式串锚点自动探测，
   TRAE 升级无需人工重新逆向（内置已知值兜底）。
2. **无 IV 解密**：利用 CBC 模式性质（第 i≥1 块明文只依赖前一块密文），
   整库可读，仅每页头 16 字节不可恢复。
3. **用量提取**：每条 AI 回复内嵌 `token_usage` JSON 与 trace_id，去重后缓存；
   WAL 增量重扫（秒级），新对话立即可见。

## 安装

Windows + Python 3.9+，`pip install frida psutil cryptography`。
在 TRAE → 设置 → MCP 中添加服务器（JSON 见上文英文部分），启用后直接对话提问：

- 「我最近的 token 用量」
- 「每个项目各用了多少 token」
- 「我总共用了多少 token」

首次查询会自动确保数据库密钥可用：TRAE 的 ai-agent 进程会被重启一次，
当前 AI 会话中断数秒后自动恢复；之后全程自动维护。

## 配置

复制 `config.example.json` 为 `config.json`，所有字段均可留空使用默认值。
`project_aliases.json` 可给项目 ID 起易读别名（键支持 ID 前缀）。

## 目录结构

```
bin/trae_crypto.dll     闭源核心：AES-256 页解密、WAL 解析、RVA 自动探测
server/                 开源（GPL-3.0）：MCP 服务器、提取逻辑、密钥 watcher
docs/HOW_IT_WORKS.md    格式与逆向原理深入说明
```

## 免责声明

本工具仅读取你自己机器上的本地数据用于个人分析，与 TRAE 官方无关。
数据库格式可能随时变化，闭源核心将尽力跟进更新。请遵守 TRAE 服务条款，
风险自担。

基于 [GPL-3.0](LICENSE) 授权。
