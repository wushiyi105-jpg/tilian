"""Web UI:http.server 单文件,零依赖。"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from . import agent, llm, tools
from .db import Database

PAGE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>题练 · 今天复习几题</title>
<style>
:root{--bg:#f4f8f4;--card:#fff;--ink:#1e2620;--dim:#6b7a70;--accent:#2f7d52;--line:#dfe8e1}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.7 "Segoe UI","Microsoft YaHei",sans-serif}
.wrap{max-width:860px;margin:0 auto;padding:30px 18px 60px}
h1{font-size:25px;margin:0 0 4px}.sub{color:var(--dim);margin:0 0 16px}
.badge{display:inline-block;padding:2px 10px;border-radius:99px;font-size:13px;margin-left:6px}
.tabs{display:flex;gap:8px;margin:14px 0}
.tab{padding:8px 16px;border:1px solid var(--line);background:var(--card);border-radius:8px;cursor:pointer}
.tab.on{background:var(--accent);color:#fff;border-color:var(--accent)}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px;margin-bottom:14px}
label{display:block;font-size:14px;color:var(--dim);margin:10px 0 4px}
input,textarea,select{width:100%;padding:9px 11px;border:1px solid var(--line);border-radius:8px;font:inherit;background:#fff}
textarea{min-height:110px;resize:vertical}
button{padding:9px 18px;border:0;border-radius:8px;background:var(--accent);color:#fff;font:inherit;cursor:pointer}
button:disabled{opacity:.55;cursor:wait}
.out{white-space:pre-wrap;font:14px/1.8 Consolas,"Microsoft YaHei",monospace;background:#fbfdfb;border:1px solid var(--line);border-radius:8px;padding:14px;margin-top:12px;min-height:40px}
.q{border-bottom:1px dashed var(--line);padding:10px 0}
.q b{display:block}
.row{display:flex;gap:8px;margin-top:8px}.row input{flex:1}

h1{font-size:clamp(31px,5vw,39px);line-height:1.26}
.prod{display:block;font-size:11px;line-height:1.4;letter-spacing:.18em;font-weight:650;margin-bottom:8px;opacity:.72}
.lede,.sub{max-width:62ch;line-height:1.75}
.route{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1px;margin:0 0 20px;border:1px solid var(--line);background:var(--line)}
.route span{padding:11px 13px;background:var(--card);font-size:12px;line-height:1.5}
.route b{display:block;font-size:10px;letter-spacing:.1em;margin-bottom:3px;opacity:.66}
button{min-height:46px}
input,select{min-height:44px}
@media(max-width:680px){
  .wrap{padding:20px 16px 56px}
  .route{grid-template-columns:1fr}
  h1{font-size:30px!important}
  .row>div{min-width:100%!important}
  button{width:100%}
}

body{background:#f8f4e8;color:#26324a;font-family:"PingFang SC","Microsoft YaHei",sans-serif;background-image:repeating-linear-gradient(0deg,transparent 0 31px,#eee7d6 31px 32px)}
.wrap{max-width:860px}
header{padding:8px 0 20px;margin-bottom:20px;border-bottom:1px solid #cfc6b2}
header h1{font-family:"Songti SC","SimSun",Georgia,serif;font-size:38px;line-height:1.24}
header p{color:#6a6659;font-size:14px}
.card{background:#fffdf6;border:1px solid #dbd2bd;border-left:5px solid #2c4fa3;border-radius:0;box-shadow:none}
button{background:#2c4fa3;border-radius:0;letter-spacing:.05em}
button:hover{background:#24418a}
textarea,input,select{background:#fffef9;border-color:#d8ceb8;border-radius:0}
textarea:focus,input:focus,select:focus{border-color:#2c4fa3;box-shadow:0 0 0 2px #d9e1f2}
.item{border-left:3px solid #2c4fa3}
h3{color:#2c4fa3;letter-spacing:.08em}


/* palette-normalized */
:root{--bg:#f8f4e8;--card:#fffdf6;--ink:#26324a;--text:#26324a;--dim:#6a6659;--line:#dbd2bd;--accent:#2c4fa3}

/* polish-batch1 */
button.ghost,button.secondary{background:transparent!important;color:#2c4fa3!important;border:1px solid #dbd2bd!important}

/* mobile-32 */

@media(max-width:760px){
  main{grid-template-columns:1fr!important}
  aside{border-right:0!important;border-bottom:1px solid #dbd2bd;width:auto!important}
  section{padding:16px!important}
  .row{flex-wrap:wrap!important}
  .row>div{min-width:100%!important}
  h1{font-size:30px!important}
  .route{grid-template-columns:1fr!important}
  button{min-height:48px}
  pre{overflow-x:auto}
}

/* mobile-height */
@media(max-width:760px){main{min-height:auto!important}aside{min-height:0!important}}
</style></head><body><div class="wrap">
<h1><span class="prod">题练</span>今天，复习几题 <span id="st" class="badge"></span></h1>
<p class="sub">给用自己的材料备考的人：题目附来源段落，答完给错因，讲义支持的等价答案可以接受，答对但犹豫的单独回排。</p>
<div class="tabs"><div class="tab on" data-t="gen">出题</div><div class="tab" data-t="quiz">作答</div><div class="tab" data-t="due">待复习</div></div>


  <div class="route" aria-label="任务步骤"><span><b>01</b>选讲义和题量</span><span><b>02</b>作答不先看答案</span><span><b>03</b>按错因回排</span></div>
<div class="card" id="p-gen">
  <label>知识点</label><select id="gTopic"></select>
  <label>出几道</label><input id="gN" type="number" value="5" min="1" max="10">
  <div style="margin-top:12px"><button id="btnGen">出题</button></div>
  <div class="out" id="genOut"></div>
</div>

<div class="card" id="p-quiz" style="display:none">
  <label>题目</label><select id="qSel"></select>
  <div class="row"><input id="qAns" placeholder="写你的答案"><button id="btnAns">判分</button></div>
  <div class="out" id="ansOut"></div>
  <div style="margin-top:10px"><button id="btnExp" style="background:#e8f3ec;color:#2f7d52">看讲解</button></div>
</div>

<div class="card" id="p-due" style="display:none">
  <div style="margin-bottom:10px"><button id="btnDue">刷新今日待复习</button></div>
  <div id="dueList" class="out"></div>
</div>
</div>
<script>
const $=id=>document.getElementById(id);
const esc=s=>String(s==null?'':s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
function loading(btn,on){if(on){btn.dataset.label=btn.dataset.label||btn.textContent.trim();btn.disabled=true;btn.textContent='处理中…';}else{btn.disabled=false;btn.textContent=btn.dataset.label||btn.textContent;}}
document.querySelectorAll('.tab').forEach(t=>t.onclick=()=>{document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('on',x===t));['gen','quiz','due'].forEach(k=>$('p-'+k).style.display=k===t.dataset.t?'block':'none');});
async function api(path,body){const r=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});const j=await r.json();if(!r.ok)throw new Error(j.error||('HTTP '+r.status));return j;}
async function loadTopics(){const t=await api('/api/topics');$('gTopic').innerHTML=t.map(x=>`<option value="${x.id}">${esc(x.name)} (${x.questions} 题)</option>`).join('');}
async function loadQuestions(){const q=await api('/api/questions');$('qSel').innerHTML=q.map(x=>`<option value="${x.id}">[${x.id}] ${esc(x.stem)}</option>`).join('');}
$('btnGen').onclick=async()=>{const btn=$('btnGen');loading(btn,true);
 try{const r=await api('/api/gen',{topic:+$('gTopic').value,n:+$('gN').value});
  let t=(r.offline?'【离线模式】':'')+`出了 ${r.ids.length} 道题\\n\\n`;
  r.questions.forEach((q,i)=>t+=`[${r.ids[i]}] ${q.stem}\\n`);
  if(r.dropped.length)t+='\\n丢弃 ' + r.dropped.length + ' 道不合规的题';
  $('genOut').textContent=t;await loadQuestions();await loadTopics();}
 catch(e){$('genOut').textContent='❌ '+e.message;}finally{loading(btn,false);}};
$('btnAns').onclick=async()=>{const btn=$('btnAns');loading(btn,true);
 try{const r=await api('/api/answer',{qid:+$('qSel').value,answer:$('qAns').value});
  $('ansOut').textContent=(r.correct?'✅ 对':'❌ 错')+`\\n参考答案:${r.answer}\\n判分依据:${r.reason}\\n`+
   (r.missing.length?'没答到:'+r.missing.slice(0,4).join('、')+'\\n':'')+
   `下次复习:${r.next.due_date}(间隔 ${r.next.interval_days} 天,第 ${r.next.stage} 档)`;}
 catch(e){$('ansOut').textContent='❌ '+e.message;}finally{loading(btn,false);}};
$('btnExp').onclick=async()=>{const btn=$('btnExp');loading(btn,true);
 try{const r=await api('/api/explain',{qid:+$('qSel').value});
  $('ansOut').textContent=(r.offline?'【离线模式】\\n':'')+r.text+(r.checks?'\\n\\n'+r.checks.join('\\n'):'');}
 catch(e){$('ansOut').textContent='❌ '+e.message;}finally{loading(btn,false);}};
$('btnDue').onclick=async()=>{const btn=$('btnDue');loading(btn,true);
 try{const q=await api('/api/due');
  $('dueList').textContent=q.length?`今天 ${q.length} 道:\\n`+q.map(x=>`[${x.id}] ${x.topic}  ${x.stem}`).join('\\n'):'今天没有到期的题';}
 catch(e){$('dueList').textContent='❌ '+e.message;}finally{loading(btn,false);}};
(async()=>{try{const s=await api('/api/status');const b=$('st');b.textContent=s.mock?'离线模式':'模型模式';b.style.background=s.mock?'#fdecd6':'#dcefe3';b.style.color=s.mock?'#8a4a12':'#245c31';}catch(e){}
 await loadTopics();await loadQuestions();})();
</script></body></html>"""


class _Handler(BaseHTTPRequestHandler):
    db: Database
    cfg: dict
    force_mock: bool

    def log_message(self, fmt, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _read_json(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        raw = self.rfile.read(n)
        for enc in ("utf-8", "gbk"):
            try:
                return json.loads(raw.decode(enc))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
        return {}

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/api/status":
            cfg = {**llm.default_config(), **self.cfg}
            self._json({"mock": self.force_mock or not cfg.get("api_key"), "model": cfg.get("model")})
        elif path == "/api/topics":
            self._json(self.db.list_topics())
        elif path == "/api/questions":
            self._json(self.db.list_questions())
        elif path == "/api/due":
            self._json(self.db.due_questions(tools.today()))
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        data = self._read_json()
        if path == "/api/gen":
            topic = self.db.get_topic(data.get("topic"))
            if not topic:
                self._json({"error": "知识点不存在"}, 404)
                return
            try:
                n = max(1, min(10, int(data.get("n", 5))))
            except (TypeError, ValueError):
                n = 5
            try:
                r = agent.generate(topic, n, config=self.cfg, force_mock=self.force_mock)
            except Exception as e:  # noqa: BLE001
                self._json({"error": str(e)}, 502)
                return
            ids = [self.db.add_question(topic["id"], q["stem"], q["answer"], q.get("explain", ""))
                   for q in r["questions"]]
            r["ids"] = ids
            self._json(r)
            return
        if path == "/api/answer":
            q = self.db.get_question(data.get("qid"))
            if not q:
                self._json({"error": "题目不存在"}, 404)
                return
            ua = str(data.get("answer", "")).strip()
            if not ua:
                self._json({"error": "答案不能为空"}, 400)
                return
            stage = (self.db.get_review(q["id"]) or {}).get("stage", 0)
            r = agent.grade(q, ua, stage)
            self.db.add_attempt(q["id"], ua, r["correct"])
            nxt = r["next"]
            self.db.set_review(q["id"], nxt["due_date"], nxt["interval_days"], nxt["stage"], 3)
            r["answer"], r["qid"] = q["answer"], q["id"]
            self._json(r)
            return
        if path == "/api/explain":
            q = self.db.get_question(data.get("qid"))
            if not q:
                self._json({"error": "题目不存在"}, 404)
                return
            attempts = self.db.list_attempts(q["id"], 1)
            if not attempts:
                self._json({"error": "还没有作答记录"}, 400)
                return
            try:
                r = agent.explain(q, attempts[0], config=self.cfg, force_mock=self.force_mock)
            except Exception as e:  # noqa: BLE001
                self._json({"error": str(e)}, 502)
                return
            self._json(r)
            return
        self._json({"error": "not found"}, 404)


def _make_handler(db: Database, cfg: dict, force_mock: bool):
    class Handler(_Handler):
        pass

    Handler.db, Handler.cfg, Handler.force_mock = db, cfg, force_mock
    return Handler


def serve(host: str = "127.0.0.1", port: int = 8000, db_path: str | None = None, force_mock: bool = False):
    db = Database(db_path or os.environ.get("TILIAN_DB"))
    httpd = ThreadingHTTPServer((host, port), _make_handler(db, llm.default_config(), force_mock))
    print(f"📝 题练已启动  http://{host}:{httpd.server_address[1]}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        db.close()


if __name__ == "__main__":
    serve()
