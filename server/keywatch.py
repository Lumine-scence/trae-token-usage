# -*- coding: utf-8 -*-
"""keywatch.py -- frida watcher 后台线程：TRAE 重启 ai-agent 时自动截获新密钥。"""

import os
import threading
import time


def start_watcher(engine, log=None, wait_probe_timeout=180):
    """启动 daemon 线程。返回 (False, None) 表示 frida 缺失；否则 (True, ready_event)。
    ready_event 在 watcher 进入监听循环后置位——补获密钥前必须等待它。"""
    ready = threading.Event()
    def _log(m):
        if log:
            log("[watcher] " + str(m)[:160])

    try:
        import frida
        import psutil
    except ImportError as e:
        _log("依赖缺失：%s —— 自动抓取不可用" % e)
        ready.set()          # 不阻塞调用方，但监听实际不可用
        return False, ready

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
            ready.set()
            return
        log("start pid=%d KEY_RVA=%x" % (os.getpid(), key_rva))
        ready.set()   # 即将进入监听循环——补获流程可以开始了

        hook_js = r"""
var TARGET='ai_agent.dll';
var TRVA=%d;
var attached=false;

function attachKey(){
  if(attached) return true;
  var m=Process.findModuleByName(TARGET);
  if(!m) return false;
  try{
    Interceptor.attach(m.base.add(TRVA), { onEnter: function(args){
      var a1=args[2], a2=args[3];   // pKey, nKey (历史实测位)
      var n=-1; try{ n=a2.toInt32(); }catch(e){}
      var h='';
      try{
        if(n>0&&n<=4096&&!a1.isNull()){
          var b=Memory.readByteArray(a1,n);
          h=Array.from(new Uint8Array(b)).map(function(x){return ('0'+x.toString(16)).slice(-2);}).join('');
        }
      }catch(e){ h='ERR'; }
      send('CALL nKey='+n+' hex='+h.slice(0,64));
      if(h.length>0){ send('KEY_HEX='+h); }   // 引擎负责解码为 x'<hex>' 并校验
    }});
    attached=true;
    send('HOOK_OK rva='+TRVA);
    return true;
  }catch(e){ send('HOOK_ERR '+e); attached=true; return true; }
}

// 预埋：ai_agent.dll 一映射完成立刻挂钩，抢在紧随其后开库(sqlite3_key_v2)之前
(function(){
  try{
    var L=Module.getExportByName('ntdll.dll','LdrLoadDll');
    Interceptor.attach(L, {
      onEnter: function(args){
        this._w=false;
        try{
          var u=args[2].readPointer();      // PUNICODE_STRING
          var len=(u.readUShort()&0xffff)/2;
          var s=u.add(4).readPointer().readUtf16String(len)||'';
          if(s.toLowerCase().indexOf('ai_agent.dll')>=0) this._w=true;
        }catch(e){}
      },
      onLeave: function(){ if(this._w){ try{ attachKey(); }catch(e){} } }
    });
  }catch(e){}
})();
// 兜底：模块加载轮询快扫
(function(){ var t=setInterval(function(){ if(attachKey()) clearInterval(t); },1);
  setTimeout(function(){ clearInterval(t); },60000); })();
try{ attachKey(); }catch(e){}
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

                        _seen_keys = set()
                        def on_msg(m, d, _pid=pid):
                            pl = str(m.get("payload", m))
                            if pl.startswith("KEY_HEX="):
                                hx = pl.split("KEY_HEX=", 1)[1].strip()
                                if hx and hx not in _seen_keys:
                                    _seen_keys.add(hx)
                                    with open(engine.cfg.key_log, "a", encoding="utf-8") as f:
                                        f.write("%s KEY_HEX=%s\n"
                                                % (time.strftime("%H:%M:%S"), hx))
                                    _log("已捕获新密钥")
                            elif "HOOK_ERR" in pl or "HOOK_OK" in pl:
                                _log(pl[:80])
                            elif pl.startswith("CALL "):
                                _log("p%d %s" % (_pid, pl[:120]))

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
    return True, ready
