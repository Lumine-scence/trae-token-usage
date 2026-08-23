<div align="center">

# 📊 trae-token-usage

**在 TRAE 对话里直接问：「我用了多少 Token？」**

真实精确数据 · 输入 / 输出 / 推理 / 缓存命中 · 支持按项目统计

![License](https://img.shields.io/badge/License-MIT-green)
![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey)
![Python](https://img.shields.io/badge/Python-3.9%2B-green)
![Protocol](https://img.shields.io/badge/Protocol-MCP-orange)

*数据来自解密 TRAE 本地数据库 —— 不是估算，是账单。*

</div>

---

## ✨ 特性

| | |
|---|---|
| 🎯 **真实精确** | 直接读取 TRAE 本地加密数据库的 `token_usage` 记录，非 AI 估算 |
| 🧩 **字段完整** | 每轮的输入、输出、推理、缓存创建、缓存命中 tokens 一应俱全 |
| 🗂️ **按项目统计** | 自动识别消息所属工作区，分项目聚合用量与缓存命中率 |
| ⚡ **增量刷新** | 主库全量解析一次后日常仅重扫 WAL，秒级拿到最新对话 |
| 🔑 **全自动维护** | 密钥随 TRAE 重启轮换？后台 watcher 自动捕获，无需人工干预 |
| 🪶 **零安装负担** | 密码学核心已编译进 DLL，无需额外编译器或原生依赖 |

---

## 📦 安装

### 前置要求

| 依赖 | 说明 |
|---|---|
| Windows 10/11 | — |
| Python 3.9+ | 建议 64 位 |
| 三个 pip 包 | `pip install frida psutil cryptography` |
| TRAE SOLO CN | 本机已登录并可正常对话 |

> 💡 本仓库已附带编译好的核心组件 `bin/trae_crypto.dll`，无需安装 C 编译器。

### 三步接入 TRAE

**第 1 步 · 克隆或下载本仓库到本地任意位置**

```bat
git clone https://github.com/Lumine-scence/trae-token-usage.git
```

**第 2 步 · 安装依赖**

```bat
pip install frida psutil cryptography
```

**第 3 步 · 在 TRAE 中注册 MCP**

打开 TRAE → **设置** → **MCP** → **添加服务器**，粘贴：

```json
{
  "mcpServers": {
    "trae-real-usage": {
      "command": "python",
      "args": [
        "C:\\你的路径\\trae-token-usage\\server\\mcp_server.py"
      ]
    }
  }
}
```

保存并启用即可。

---

## 🚀 使用

启用后**无需任何初始化操作**，直接在对话里自然提问：

> 🙋 **「我最近的 token 用量是多少？」**
>
> 🤖 最近 3 轮 / 共 218 轮：
> - trae插件 | 输入 414.5k | 输出 363 | 推理 145 | 缓存读 405.5k
> ……
> 总计 218 轮：输入 25,577,124 | 输出 246,776 | 缓存命中率 94.4%

更多问法与对应工具：

| 你说 | AI 调用 | 你得到 |
|---|---|---|
| 「最近每轮对话各用了多少 token」 | `get_real_token_usage` | 逐轮明细 + 汇总 |
| 「每个项目分别用了多少 token」 | `get_usage_by_project` | 分项目聚合表 |
| 「xx 项目花了多少」 | `get_usage_by_project(project=…)` | 单项目过滤 |
| 「我总共用了多少 token」 | `get_usage_stats` | 全历史统计 + 缓存命中率 |
| 「重新统计一下用量」 | `refresh_token_usage` | 强制重扫数据库 |

### 需要手动运行什么脚本吗？

**不需要。** 配置完成后，每次 TRAE 启动都会自动拉起本服务（MCP 标准的
stdio 托管模式），密钥捕获、解密、缓存全部在后台自动完成，随 TRAE 一起
退出。仓库里的 \启动MCP服务.bat\ 仅用于排障时手动查看日志，日常完全用不到。

### 关于首次查询

服务启动时会自动确保数据库密钥可用。若 TRAE 刚刚重启过（密钥已轮换），
首次查询会触发一次**自动补获**：

- ⏳ 当前 AI 会话会中断几秒后自动恢复，属正常现象；
- 若该次请求恰好被中断，**再问一遍即可**——第二次密钥已就绪。

之后全程自动维护，无需关心。

---

## 🛠️ 工具一览

| 工具 | 参数 | 说明 |
|---|:---:|---|
| `get_real_token_usage` | `limit`(可选) | 最近 N 轮明细 + 总计，默认 20 轮 |
| `get_usage_by_project` | `project`(可选) | 按项目聚合；可传别名或 ID 前 8 位过滤 |
| `get_usage_stats` | — | 全历史总量统计与缓存命中率 |
| `refresh_token_usage` | `force`(可选) | 重扫数据库；`force=true` 全量重算 |
| `capture_db_key` | — | 手动触发密钥补获 |
| `get_key_status` | — | 密钥新鲜度诊断 |

---

## ⚙️ 配置

所有配置均可省略，默认值适配标准安装路径。

<details>
<summary><b>config.json</b> —— 路径与行为（复制 <code>config.example.json</code> 修改）</summary>

```jsonc
{
  // 数据库路径；留空自动定位 %APPDATA%\TRAE SOLO CN\...
  "db_path": "",
  // 核心组件路径；留空使用仓库内 bin\trae_crypto.dll
  "dll_path": "",
  // 密钥日志路径；留空使用仓库根 key_capture.log
  "key_log": "",
  // 启动时是否自动补获过期密钥
  "auto_capture": true,
  // 自动探测失败时的兜底挂钩地址
  "rva_fallback": "0x92B149C"
}
```

</details>

<details>
<summary><b>project_aliases.json</b> —— 给项目起个好记的名字</summary>

TRAE 内部以 24 位十六进制 ID 标识项目（SOLO 版无官方名称）。
在本文件中建立映射后，所有输出将显示友好名称：

```json
{
  "6a8abceb": "trae 插件开发",
  "6a6c4f40": "NLP 训练管线"
}
```

- 键只需 ID **前缀**（前 8 位即可唯一区分），不必写全 24 位；
- 未配置别名的项目显示为 `ID 前 8 位…`；
- 查询时同样支持传别名或 ID 前缀过滤。

</details>

---

## ❓ FAQ

<details>
<summary>提示「密钥不可用且自动补获失败」？</summary>

确认 TRAE 正在运行（ai-agent 进程存在），然后说「帮我捕获数据库密钥」或
调用 `capture_db_key`。成功标志见 `get_key_status`。
</details>

<details>
<summary>返回的记录数突然变少 / 为空？</summary>

几乎总是密钥过期（TRAE 升级或重启导致轮换）。执行一次 `capture_db_key`
即可恢复；历史数据不会丢失。
</details>

<details>
<summary>TRAE 升级后完全失效了？</summary>

TRAE 更新可能改变内部结构。本项目的挂钩地址支持<b>自动探测</b>（见
docs/HOW_IT_WORKS.md），多数升级可自愈；若探测失败会回退内置地址并在
日志告警。此时请提 Issue 反馈。
</details>

<details>
<summary>为什么每轮的输入 token 这么大？缓存命中是什么意思？</summary>

TRAE 会把历史上下文整体发给模型，因此"输入"包含全部上下文；
其中命中缓存的 部分（cache_read_input_tokens）计费/消耗远低于未命中部分，
命中率越高越省钱省时间。
</details>

<details>
<summary>隐私安全吗？</summary>

全部处理都在本机完成：数据库只读、密钥日志与用量缓存保存在本地仓库目录
（已被 .gitignore 排除），不上传任何服务器。
</details>

---

## 🔍 工作原理

```
┌─────────────┐   frida 挂钩 sqlite3_key_v2    ┌──────────────────┐
│ TRAE 启动    │ ────────────────────────────▶ │ 密钥捕获 (watcher)│
│ ai-agent 重启│      截获随机 per-launch 密钥   └────────┬─────────┘
└─────────────┘                                         ▼
                                            ┌──────────────────────┐
             database.db + WAL ────────────▶│ AES-256 无IV批量解密  │
             (SQLCipher 加密)                │ (bin/trae_crypto.dll)│
                                            └──────────┬───────────┘
                                                       ▼
                                        ┌────────────────────────────┐
                                        │ 提取 trace_id + token_usage │
                                        │ 按 trace 去重 / WAL 增量合并 │
                                        └──────────┬─────────────────┘
                                                   ▼
                                          usage_cache.json → MCP 工具
```

- TRAE 本地库为 SQLCipher v4 加密（page=4096，reserved=80），密钥每次启动随机；
- 利用 CBC 性质「第 i≥1 块明文 = D(Cᵢ) XOR Cᵢ₋₁，与 IV 无关」，整库可读而
  仅每页头 16 字节不可恢复；
- 挂钩地址由闭源核心基于 `ai_agent.dll` 内部 trace 格式串锚点**自动探测**，
  TRAE 升级通常可自愈，无需人工重新逆向。

深入细节（页布局、IV 分析、Rust 层 PRAGMA 路径等）见
[docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md)。

---

## 📁 目录结构

```
trae-token-usage/
├── server/
│   ├── mcp_server.py     # MCP 协议层与工具定义
│   ├── engine.py         # 编排层：DLL 调用、提取、缓存、别名
│   ├── keywatch.py       # frida 密钥 watcher 后台线程
│   └── paths.py          # 配置与路径解析
├── bin/
│   └── trae_crypto.dll   # 闭源密码学核心（AES/WAL/RVA 探测）
├── docs/
│   └── HOW_IT_WORKS.md   # 格式与逆向原理笔记
├── config.example.json   # 配置模板
├── smoke_test.py         # 端到端冒烟测试
├── LICENSE               # MIT

└── README.md
```

运行时生成的 `key_capture.log`、`usage_cache.json`、`project_aliases.json`
含个人数据，已在 `.gitignore` 中排除。

---

## ⚠️ 免责声明

本项目仅读取**你自己机器上你自己的**本地数据用于个人分析，与 TRAE 官方无关、
亦不受其认可。数据库格式可能随版本更新改变，闭源核心将尽力跟进。请遵守 TRAE
服务条款，使用风险自担。

## 📄 License

本项目基于 [MIT License](LICENSE) 开源 —— 可自由使用、修改、分发。

唯一的特别说明：\bin/trae_crypto.dll\ 以**预编译二进制**形式提供，
其实现源码不包含在本仓库中。你可以原样使用和分发该文件，但无法从这里
获得它的源码。

<div align="center">

**如果这个项目帮到了你，欢迎点个 ⭐ Star**

</div>
