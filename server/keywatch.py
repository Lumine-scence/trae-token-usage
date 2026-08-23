# -*- coding: utf-8 -*-
"""keywatch.py -- frida watcher 后台线程：TRAE 重启 ai-agent 时自动截获新密钥。"""

import os
import threading
import time


def start_watcher(engine, log=None, wait_probe_timeout=180):
    """启动 daemon 线程。返回 False 表示 frida 缺失。"""
    def _log(m):
        if log:
            log("[watcher] " + str(m)[:160])

    try:
        import frida
        import psutil
    except ImportError as e:
        _log("依赖缺失：%s —— 自动抓取不可用" % e)
        return False

    # 等 RVA 探测就绪（engine.get_key_rva 首调会触发 DLL 探测，毫秒级）
    deadline = time.time() + wait_probe_timeout

    def run():
        key_rva = None
        while key_rva is None and time.time() < deadline:
            try:
                key_rva = engine.get_key_rva()
            except Exception as e:  # noqa: BLE001
                _log("RVA 探测未就绪: %s" % str(e)[:80])
                time.sleep(2)
        if key_rva is None:
            _log("RVA 探测超时，watcher 退出")
            return
        log("start pid=%d KEY_RVA=%x" % (os.getpid(), key_rva))

        hook_js = r"""
function mkReader(){
  return function(args){
    var a1=args[2], a2=args[3];
    function tryHex(p,len){ try{ if(p.isNull()||len<=0||len>4096) return null;
      var b=Memory.readByteArray(p,len);
      return Array.from(new Uint8Array(b)).map(function(x){return ('0'+x.toString(16)).slice(-2);}).join(''); }catch(e){ return null; } }
    var n=-1; try{ n=a2.toInt32(); }catch(e){}
    var h=tryHex(a1,n);
    if(h){ send('KEY_HEX='+h); }
  };
}
function install(){
  var m = Process.findModuleByName('ai_agent.dll');
  if(!m) return false;
  try{ Interceptor.attach(m.base.add(%d), { onEnter: mkReader() }); send('HOOK_OK'); }catch(e){ send('HOOK_ERR '+e); }
  return true;
}
if(!install()){ var t=setInterval(function(){ if(install()) clearInterval(t); },5); setTimeout(function(){ clearInterval(t); },20000); }
""" % key_rva

        device = frida.get_local_device()
        seen = set(psutil.pids())
        handled = set()

        def is_target(pid):
            try:
                p = psutil.Process(pid)
                if p.name() != "TRAE SOLO CN.exe":
                    return False
                cl = " ".join(p.cmdline() or [])
                return "basil.mojom" in cl or "NativeExtensionService" in cl
            except Exception:
                return False

        while True:
            try:
                cur = psutil.pids()
                for pid in [p for p in cur if p not in seen]:
                    seen.add(pid)
                    if pid in handled or not is_target(pid):
                        continue
                    handled.add(pid)
                    _log("新 ai-agent pid=%d -> 注入" % pid)
                    try:
                        session = device.attach(pid)
                        script = session.create_script(hook_js)

                        def on_msg(m, d, _pid=pid):
                            pl = str(m.get("payload", m))
                            if pl.startswith("KEY_HEX="):
                                hx = pl.split("KEY_HEX=", 1)[1].strip()
                                with open(engine.cfg.key_log, "a", encoding="utf-8") as f:
                                    f.write("%s KEY_HEX=%s\n"
                                            % (time.strftime("%H:%M:%S"), hx))
                                _log("已捕获新密钥")
                            elif "HOOK_ERR" in pl or "HOOK_OK" in pl:
                                _log(pl[:80])

                        script.on("message", on_msg)
                        session.on("detached",
                                   lambda *a, _p=pid: _log("p%d detached" % _p))
                        script.load()
                        _log("注入完成 pid=%d" % pid)
                    except Exception as e:  # noqa: BLE001
                        _log("注入失败 %d: %s" % (pid, str(e)[:100]))
                alive = set(cur)
                seen &= alive
                handled &= alive
            except Exception as e:  # noqa: BLE001
                _log("loop err: %s" % str(e)[:120])
                time.sleep(1)
            time.sleep(0.01)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return True
