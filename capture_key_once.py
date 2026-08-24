# -*- coding: utf-8 -*-
"""capture_key_once.py -- 一键采集 TRAE 的数据库密钥。

与常驻查询分离：只在密钥缺失或已失效（首次使用 / TRAE 升级轮换密钥）时才需要跑。
流程：
  1) 若已存密钥仍能解密主库 -> 直接复用，无需重启本体，立即退出 0。
  2) 否则拉起 frida watcher，触发一次 ai-agent 重启以抓取新密钥（当前 AI 会话会中断几秒）。
  3) 抓到的密钥写入 key_capture.log，供 TRAE 自动托管的 MCP 子进程后续直接读取。

用法：python capture_key_once.py   成功返回 0，失败返回 1。
"""
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)


def log(m):
    print(time.strftime("[%H:%M:%S] ") + str(m), flush=True)


def main():
    log("==== 一键密钥采集 ====")
    try:
        from server.engine import UsageEngine
        from server.keywatch import start_watcher
    except Exception as e:
        log("依赖导入失败: %r" % e)
        log("请使用安装了 frida/psutil 的 Python 来运行本脚本（如 VS 自带 Python）。")
        return 1

    eng = UsageEngine(log=log)

    # 情形 A：现有的密钥仍然有效 —— 无需重启本体，日常工作也不用再开终端
    try:
        if eng._existing_key_valid():
            eng._key_confirmed = True
            log("现有密钥仍然有效，无需重采。")
            log("完成：后续日常使用无需终端窗口、无需重启 TRAE。")
            return 0
    except Exception as e:
        log("校验现有密钥时出错: %r（继续尝试重采）" % e)

    # 情形 B：需要重采。先清掉可能已失效的旧密钥痕迹，从干净状态开始
    try:
        open(eng.cfg.key_log, "w", encoding="utf-8").close()
        log("已清空旧密钥记录，开始重采。")
    except OSError as e:
        log("清空 key_capture.log 失败: %r" % e)

    def hook():
        log(">>> 补获触发：即将重启 TRAE 的 ai-agent 以抓取密钥（AI 会话中断数秒后恢复）...")

    eng.before_capture_hook = hook

    log("启动 frida watcher ...")
    ok, ready = start_watcher(eng, log=log)
    if not ok:
        log("无法启动密钥 watcher：缺少 frida/psutil，请改用装有依赖的 Python 运行本脚本。")
        return 1
    if not ready.wait(timeout=180):
        log("watcher 未能就绪，放弃采集。请先确认 TRAE 正在运行。")
        return 1
    log("watcher 就绪，开始补获（最多重试 2 轮）...")

    captured = False
    for attempt in (1, 2):
        try:
            if eng.ensure_key(timeout=180):
                captured = True
                break
        except Exception as e:
            log("ensure_key 异常: %r" % e)

    if not captured:
        log("采集失败：未能抓取到新密钥。")
        log("请确认 TRAE 正在运行后重试；若多次失败请重启 TRAE 本体现有会话后再跑。")
        return 1

    # 最终校验：抓到的密钥必须真正可解密主库才算成功
    try:
        if eng._existing_key_valid():
            eng._key_confirmed = True
            log("密钥已抓取并经解密主库验证有效。")
            log("完成：后续日常使用无需终端窗口、无需重启 TRAE。")
            return 0
    except Exception as e:
        log("抓取后校验异常: %r" % e)
    log("已抓取密钥但校验未通过，请重跑一次确认。")
    return 1


if __name__ == "__main__":
    sys.exit(main())