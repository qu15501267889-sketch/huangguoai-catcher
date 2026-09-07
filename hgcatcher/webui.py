# -*- coding: utf-8 -*-
"""WebUI 模块：浏览器搜索/点选下载，替代"全站扫描"。

设计：
  - 站点索引 {vid: title} 首次启动枚举一次并缓存到 <out>/index.json，
    之后搜索/点选全部走本地缓存，零站点请求
  - 下载任务单线程队列：一次一部剧，防打爆站点/被 Cloudflare 盯上
  - 状态与 CLI 共用 manifest.json，已下过的集数自动跳过
接口：
  GET  /                单页界面
  GET  /api/search?q=   按剧名搜索索引
  GET  /api/series      全部索引 + 各剧已下集数
  POST /api/download    {"vid": <id>} 入队下载
  GET  /api/status      队列/当前任务/历史
  POST /api/refresh     后台重建索引
"""
import os
import json
import time
import threading
import traceback
from collections import deque
from datetime import datetime

from flask import Flask, request, jsonify

from .http import RateLimiter
from .orchestrator import enumerate_series, discover, download_all, Hook


# ── 下载进度 Hook：每集完成回调，喂给状态面板 ──
class _ProgressHook(Hook):
    def __init__(self, mgr):
        self.mgr = mgr

    def on_episode_done(self, vid, ep, ok, logger):
        with self.mgr.lock:
            cur = self.mgr.current
            if cur:
                cur["done"] += 1
                if not ok:
                    cur["failed_eps"].append(ep)


class Manager:
    """索引 + 下载队列 + 状态，供 Flask 接口调用。"""

    def __init__(self, cfg, out, manifest_path, logger,
                 mode="ffmpeg", with_meta=True):
        self.cfg = cfg
        self.out = out
        self.manifest_path = manifest_path
        self.logger = logger
        self.mode = mode
        self.with_meta = with_meta
        self.limiter = RateLimiter(cfg.rate_per_sec)
        self.lock = threading.RLock()
        self.queue = deque()          # 待下载 vid 队列
        self.current = None           # 当前任务状态 dict
        self.history = []             # 最近任务记录（新的在前）
        self.index = {}               # {vid:int -> title}
        self.index_state = "empty"    # empty/building/ready/error
        self.manifest = {}
        self._load_manifest()
        self._load_index()
        threading.Thread(target=self._worker_loop, daemon=True).start()
        self.ensure_index()

    # ---------- 持久化 ----------
    def _load_manifest(self):
        try:
            with open(self.manifest_path, encoding="utf-8") as f:
                self.manifest = json.load(f)
        except Exception:
            self.manifest = {}

    def _index_path(self):
        return os.path.join(self.out, "index.json")

    def _load_index(self):
        try:
            with open(self._index_path(), encoding="utf-8") as f:
                data = json.load(f)
            self.index = {int(k): v for k, v in data.get("series", {}).items()}
            self.index_state = "ready" if self.index else "empty"
        except Exception:
            self.index = {}
            self.index_state = "empty"

    def _save_index(self):
        os.makedirs(self.out, exist_ok=True)
        tmp = {"updated_at": datetime.now().strftime("%F %T"),
               "series": {str(k): v for k, v in self.index.items()}}
        with open(self._index_path(), "w", encoding="utf-8") as f:
            json.dump(tmp, f, ensure_ascii=False, indent=1)

    # ---------- 索引 ----------
    def rebuild_index(self):
        """后台重建站点索引（改版/新剧后手动刷新用）。"""
        def run():
            with self.lock:
                if self.index_state == "building":
                    return
                self.index_state = "building"
            try:
                series = enumerate_series(self.cfg, self.limiter, self.logger)
                with self.lock:
                    self.index = {int(k): v for k, v in series.items()}
                    self.index_state = "ready"
                self._save_index()
                self.logger.info("索引重建完成: %d 部", len(series))
            except Exception as e:
                self.logger.error("索引重建失败: %s\n%s", e, traceback.format_exc())
                with self.lock:
                    self.index_state = "error"
        threading.Thread(target=run, daemon=True).start()

    def ensure_index(self):
        """索引为空/出错时自动重建。"""
        with self.lock:
            st = self.index_state
        if st in ("empty", "error"):
            self.rebuild_index()

    # ---------- 任务队列 ----------
    def enqueue(self, vid):
        vid = int(vid)
        with self.lock:
            if self.current and self.current["vid"] == vid:
                return "downloading"
            if vid in self.queue:
                return "queued"
            self.queue.append(vid)
        return "enqueued"

    def _worker_loop(self):
        while True:
            with self.lock:
                vid = self.queue.popleft() if self.queue else None
            if vid is None:
                time.sleep(1.0)
                continue
            try:
                self._run_job(vid)
            except Exception as e:
                self.logger.error("任务 %s 异常: %s\n%s", vid, e,
                                  traceback.format_exc())
                with self.lock:
                    self.current = None

    def _run_job(self, vid):
        t0 = time.time()
        init_title = self.index.get(vid, f"series_{vid}")
        self.logger.info("=== 任务开始 id=%s %s ===", vid, init_title)
        with self.lock:
            self.current = {"vid": vid, "title": init_title, "state": "parsing",
                            "total": 0, "done": 0, "failed_eps": [], "start": t0}
        to_dl, meta = discover(self.cfg, self.limiter, self.logger,
                               {str(vid): init_title}, self.manifest)
        title = meta[str(vid)][0] if str(vid) in meta else init_title
        ok_count, failed_eps = 0, []
        if to_dl:
            with self.lock:
                cur = self.current
                if cur:
                    cur.update(state="downloading", total=len(to_dl), title=title)
            ok_count, failed = download_all(
                self.cfg, self.limiter, self.logger, to_dl,
                self.out, self.manifest, self.manifest_path,
                self.mode, workers=self.cfg.workers,
                meta_map=meta, with_meta=self.with_meta, hook=_ProgressHook(self))
            failed_eps = [ep for _, ep, _ in failed]
        state = ("no_new" if not to_dl else
                 "failed" if ok_count == 0 else "ok")
        with self.lock:
            rec = {"vid": vid, "title": title, "new_ok": ok_count,
                   "failed": failed_eps, "state": state,
                   "secs": round(time.time() - t0, 1),
                   "at": datetime.now().strftime("%F %T")}
            self.history.insert(0, rec)
            del self.history[20:]
            self.current = None
        self.logger.info("=== 任务完成 id=%s %s 新下=%d 失败=%d ===",
                         vid, title, ok_count, len(failed_eps))

    # ---------- 查询 ----------
    def search(self, q, limit=80):
        q = (q or "").strip().lower()
        with self.lock:
            items = sorted(self.index.items())
        if q:
            items = [(v, t) for v, t in items
                     if q in t.lower() or q in str(v)]
        out = []
        for v, t in items[:limit]:
            done = len(self.manifest.get(str(v), {}).get("done", []))
            out.append({"vid": v, "title": t, "done": done})
        return out

    def status(self):
        with self.lock:
            cur = dict(self.current) if self.current else None
            q = [{"vid": v, "title": self.index.get(v, f"series_{v}")}
                 for v in self.queue]
            hist = list(self.history)
            idx_state, idx_n = self.index_state, len(self.index)
        total_eps = sum(len(v.get("done", [])) for v in self.manifest.values())
        return {"index_state": idx_state, "index_count": idx_n,
                "queue": q, "current": cur, "history": hist,
                "total_series": len(self.manifest), "total_eps": total_eps}


# ── Flask 应用 ──
def create_app(mgr):
    app = Flask(__name__)

    @app.get("/")
    def index_page():
        return PAGE

    @app.get("/api/search")
    def api_search():
        return jsonify({"results": mgr.search(request.args.get("q", ""))})

    @app.get("/api/series")
    def api_series():
        return jsonify({"results": mgr.search("")})

    @app.post("/api/download")
    def api_download():
        data = request.get_json(silent=True) or {}
        try:
            vid = int(data.get("vid"))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "msg": "vid 无效"}), 400
        st = mgr.enqueue(vid)
        return jsonify({"ok": True, "state": st})

    @app.get("/api/status")
    def api_status():
        return jsonify(mgr.status())

    @app.post("/api/refresh")
    def api_refresh():
        mgr.rebuild_index()
        return jsonify({"ok": True})

    return app


# ── 单页界面（内联，免模板目录） ──
PAGE = """<!doctype html><html lang=zh><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>黄果短剧下载器</title><style>
body{background:#0f1115;color:#d8dce4;font-family:system-ui,'Microsoft YaHei';margin:0;padding:24px}
.wrap{max-width:920px;margin:0 auto}
h1{font-size:20px;margin:0 0 4px}.sub{color:#7a8291;font-size:12px;margin-bottom:16px}
input[type=text]{width:100%;box-sizing:border-box;padding:11px 14px;border-radius:8px;border:1px solid #2a2f3a;background:#171a21;color:#e8ebf0;font-size:15px;outline:none}
input[type=text]:focus{border-color:#2f6fed}
table{width:100%;border-collapse:collapse;margin-top:12px;font-size:14px}
th{color:#7a8291;text-align:left;font-weight:500;padding:6px 8px;border-bottom:1px solid #232833}
td{padding:8px;border-bottom:1px solid #1b1f28}
button{padding:5px 14px;border-radius:6px;border:0;background:#2f6fed;color:#fff;cursor:pointer;font-size:13px}
button:disabled{background:#333a46;color:#7a8291;cursor:default}
button.ghost{background:#232833;color:#aeb6c2}
.tag{font-size:12px;color:#7a8291}.ok{color:#42c37d}.warn{color:#e5b04c}.err{color:#e05b5b}
.card{background:#14171d;border:1px solid #232833;border-radius:10px;padding:14px 16px;margin-top:14px}
.bar{height:6px;background:#232833;border-radius:3px;overflow:hidden;margin-top:8px}
.bar>i{display:block;height:100%;background:#2f6fed;transition:width .5s}
.row{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap}
.small{font-size:12px;color:#7a8291}
.hbtn{font-size:12px;padding:3px 10px}
</style></head><body><div class=wrap>
<div class=row><h1>黄果短剧下载器</h1>
<button class="ghost hbtn" onclick="refreshIdx()">重建索引</button></div>
<div class=sub id=stat>加载中…</div>
<input type=text id=q placeholder="搜索剧名（本地索引，不发请求到站点）" oninput="onQ()">
<table><thead><tr><th style=width:55%>剧名</th><th>ID</th><th>进度</th><th></th></tr></thead>
<tbody id=tb><tr><td colspan=4 class=small>加载中…</td></tr></tbody></table>
<div class=card id=cur style=display:none></div>
<div class=card id=queue style=display:none></div>
<div class=card><b style=font-size:14px>最近任务</b><div id=hist class=small>暂无</div></div>
</div><script>
let t=null, known={};
function esc(s){return (s||'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
function onQ(){clearTimeout(t);t=setTimeout(doSearch,300)}
async function doSearch(){const q=document.getElementById('q').value;
 const r=await fetch('/api/search?q='+encodeURIComponent(q));const d=await r.json();
 render(d.results)}
function render(list){document.getElementById('tb').innerHTML=(list||[]).map(x=>{
 const p=x.done>0?'<span class=ok>已下'+x.done+'集</span>':'<span class=tag>未下载</span>';
 const b=known[x.vid]?'<button disabled>'+known[x.vid]+'</button>':'<button onclick="dl('+x.vid+',this)">下载</button>';
 return '<tr><td>'+esc(x.title)+'</td><td class=small>'+x.vid+'</td><td>'+p+'</td><td style=text-align:right>'+b+'</td></tr>'
}).join('')||'<tr><td colspan=4 class=small>无结果</td></tr>'}
async function dl(vid,btn){btn.disabled=true;btn.textContent='入队…';
 await fetch('/api/download',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({vid})});
 known[vid]='已入队';btn.textContent='已入队';loadStatus()}
async function refreshIdx(){await fetch('/api/refresh',{method:'POST'});loadStatus()}
function pct(c){return c.total?Math.round(c.done*100/c.total):0}
async function loadStatus(){const r=await fetch('/api/status');const s=await r.json();
 const idx={'empty':'索引未构建','building':'<span class=warn>索引构建中…</span>','ready':'索引就绪: '+s.index_count+' 部','error':'<span class=err>索引构建失败，点右上角重试</span>'}[s.index_state];
 document.getElementById('stat').innerHTML=idx+' · 已入库 '+s.total_series+' 部 / '+s.total_eps+' 集';
 const cur=s.current;const ce=document.getElementById('cur');
 if(cur){ce.style.display='block';
  const st={'parsing':'解析详情中…','downloading':'下载中'}


[cur.state];
  ce.innerHTML='<div class=row><b>'+esc(cur.title)+'</b><span class=small>'+st+'</span></div>'+
   '<div class=bar><i style=width:'+pct(cur)+'%></i></div>'+
   '<div class=row style=margin-top:6px><span class=small>'+cur.done+' / '+cur.total+' 集</span>'+
   (cur.failed_eps.length?'<span class=err>失败: '+cur.failed_eps.join(',')+'</span>':'')+'</div>';
 }else ce.style.display='none';
 const qe=document.getElementById('queue');
 if(s.queue.length){qe.style.display='block';
  qe.innerHTML='<b style=font-size:14px>排队中 ('+s.queue.length+')</b>'+s.queue.map(x=>'<div class=small style=margin-top:6px>'+esc(x.title)+' (id'+x.vid+')</div>').join('');
 }else qe.style.display='none';
 document.getElementById('hist').innerHTML=s.history.length?s.history.map(h=>{
  const c={'ok':'ok','no_new':'tag','failed':'err'}[h.state]||'tag';
  const msg={'ok':'新下 '+h.new_ok+' 集','no_new':'无新增（已全下）','failed':'全部失败'}[h.state]||h.state;
  return '<div class=row style=margin-top:8px><span>'+esc(h.title)+' <span class="small '+c+'">'+msg+
   (h.failed.length?' · 失败'+h.failed.length+'集':'')+'</span></span><span class=small>'+h.at+'</span></div>'
 }).join(''):'暂无';
}
loadStatus();doSearch();setInterval(loadStatus,2000);
</script></body></html>"""
