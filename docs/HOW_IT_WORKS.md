# HOW_IT_WORKS -- 格式与逆向笔记

本文档记录 TRAE 本地数据库的格式细节与关键逆向结论（不含闭源 DLL 的实现源码）。

## 1. 数据库与加密

- 路径：`%APPDATA%\TRAE SOLO CN\ModularData\ai-agent\database.db`
- 引擎：TRAE 的 ai-agent 模块静态链接了 SQLCipher（无导出符号）。
- 密钥：进程每次启动随机生成，通过 `sqlite3_key_v2(db, zDb, pKey, nKey)` 传入，
  nKey=67，字面量格式 `x'<64 hex>'` —— 即 SQLCipher "raw key" 语义
  （hex 解码后直接作为 AES-256 密钥，跳过 PBKDF2）。
- 页参数：page_size=4096，reserved=80（IV16 + HMAC-SHA512 64）。
- 布局（官方 SQLCipher v4 一致）：
  - page1: `[salt 16][data .. 4016][IV 4016..4032][HMAC 4032..4096]`
  - pageN: `[data 0..4016][IV][HMAC]`
- WAL 头为标准明文（magic `0x377F0682/83`），帧 = [24B 帧头][加密页]。

## 2. IV 之谜

按上述布局用捕获密钥解密时，每页首块（前 16 字节明文）无法恢复，但 CBC 链上
其余块全部正确。IV 不存储于页内任何位置，也不在进程内存中，且不匹配任何常见
派生（salt/zero/hash 族/AES(salt)）。推测 TRAE 修改了 IV 管理方式。

因此本项目采用**无 IV 批量解密**：

```
P_i = AES_dec(C_i) XOR C_{i-1}    (i >= 1, 与 IV 无关)
```

代价仅为每页头 16 字节不可读；对文本型数据（消息 JSON、token 数字段）无实际影响。

## 3. 挂钩点自动探测

ai_agent.dll 中存在 SQLCipher trace 日志引用自身符号名的格式串：

```
"sqlite3_key: db=%p"
"sqlite3_key_v2: db=%p zDb=%s"
```

定位这两个字符串的 RVA 后，扫描 `.text` 中 RIP 相对寻址的
`lea r64, [rip+disp32]`（REX + 8D + modrm(mod=00,rm=101)），命中者即位于对应函数内部。

- sqlite3_key wrapper 内部引用 `"sqlite3_key: db=%p"`；其尾部为
  `jmp rel32`（实测 rel32=0）直落紧邻的下一个函数 —— 该相邻函数即
  `sqlite3_key_v2` 实现体。
- 校验：目标处必须为常见 x64 函数序言，且 v2 格式串的 lea 必须落在候选入口
  之后 1024 字节以内。

挂钩 `sqlite3_key_v2` 实现体入口即可截获 `(db, zDbName, pKey, nKey)`，
从 pKey/nKey 读出完整密钥字面量。

注意：主库实际走 Rust 层拼接的 `PRAGMA key = <key>;` 文本路径
（见 `apps/icube_server_rs/modules/ai-agent/src/infrastructure/dal/connection.rs`
日志模板），`sqlite3_key_v2` API 捕获到的是其他附属库的连接——但两把密钥相同。

## 4. 用量数据的存储位置

- `chat_message_general / chat_message` 表 content 列：
  每条 AI 回复 JSON 含 `"trace_id"`、`"token_usage":{prompt_tokens,
  completion_tokens,total_tokens,reasoning_tokens,cache_creation_input_tokens,
  cache_read_input_tokens}`、`"workspace_folders":[...]`（项目归属）、
  `"fee_usage"` 等。
- 其他相关表：`history_v2(token_usage)`、`server_history_info(token_usage)`、
  `chat_session_goal(tokens_used, rounds_used)`、`project(project_id,
  absolute_path)`、`model_config_cache`。

## 5. 已知限制

- 每页头 16 字节不可恢复 → 无法重组完整明文数据库文件做任意 SQL；
  文本提取覆盖率不受影响。
- 大 BLOB 跨页内容不保证完整。
- TRAE 更新可能改变页格式或 trace 锚点；DLL 探测失败时回退内置 RVA，
  并在日志中明确告警。
