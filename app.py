"""FastAPI 服务：按角色检索，带限流、缓存与失败降级。"""
import time
from collections import defaultdict, deque

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from query import ROLES, answer

app = FastAPI(title="kb-acl-agent")

RATE_LIMIT = 20          # 每个角色每分钟最多请求数
WINDOW = 60
CACHE_TTL = 60

_hits = defaultdict(deque)
_cache: dict[tuple[str, str], tuple[float, dict]] = {}


class Ask(BaseModel):
    question: str
    role: str = "guest"


def _rate_ok(role: str) -> bool:
    now = time.time()
    q = _hits[role]
    while q and now - q[0] > WINDOW:
        q.popleft()
    if len(q) >= RATE_LIMIT:
        return False
    q.append(now)
    return True


INDEX_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>企业知识库权限 Agent</title>
<style>
  :root { --bg:#f8fafc; --card:#fff; --line:#e2e8f0; --text:#0f172a; --muted:#64748b; --blue:#2563eb; }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--text); font-family: system-ui, -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif; }
  main { max-width: 780px; margin: 48px auto; padding: 0 16px; }
  h1 { font-size: 24px; margin: 0 0 6px; }
  .sub { color: var(--muted); font-size: 14px; margin: 0 0 24px; line-height: 1.6; }
  .card { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 18px; }
  .row { display: flex; gap: 8px; flex-wrap: wrap; }
  select, input, button { font: inherit; padding: 10px 12px; border-radius: 8px; border: 1px solid var(--line); }
  input { flex: 1 1 260px; min-width: 0; }
  button { background: var(--blue); color: #fff; border-color: var(--blue); cursor: pointer; }
  button:disabled { opacity: .6; cursor: wait; }
  .examples { margin-top: 10px; display: flex; gap: 8px; flex-wrap: wrap; }
  .examples button { background: #eff6ff; color: #1d4ed8; border-color: #bfdbfe; font-size: 13px; padding: 6px 10px; }
  #answer { margin-top: 16px; white-space: pre-wrap; line-height: 1.75; min-height: 90px; }
  #sources { margin-top: 10px; }
  .src { display: inline-block; background: #eef2ff; color: #3730a3; border-radius: 999px; padding: 2px 10px; margin: 4px 4px 0 0; font-size: 12px; }
  .hint { color: var(--muted); font-size: 13px; }
  .err { color: #b91c1c; }
</style>
</head>
<body>
<main>
  <h1>企业知识库权限 Agent</h1>
  <p class="sub">同一套知识库，不同角色只能检索到自己有权限的文档。用 <b>engineering</b> 问「公司每年调薪幅度多少」，会被拒答。</p>
  <div class="card">
    <div class="row">
      <select id="role">
        <option value="guest">guest（仅 public）</option>
        <option value="hr">hr（public + hr）</option>
        <option value="finance">finance（public + finance）</option>
        <option value="engineering">engineering（public + engineering）</option>
        <option value="admin">admin（全部）</option>
      </select>
      <input id="q" placeholder="例如：公司每年调薪幅度多少" autocomplete="off" />
      <button id="send">发送</button>
    </div>
    <div class="examples">
      <button data-q="公司每年调薪幅度多少">调薪幅度</button>
      <button data-q="报销单什么时候提交">报销时间</button>
      <button data-q="生产环境发布窗口是什么时候">发布窗口</button>
      <button data-q="公司什么时候成立，总部在哪">公司简介</button>
    </div>
    <div id="answer" class="hint">等待提问…</div>
    <div id="sources"></div>
  </div>
</main>
<script>
const $ = (id) => document.getElementById(id);
async function ask() {
  const q = $('q').value.trim();
  if (!q) return;
  $('send').disabled = true;
  $('answer').className = 'hint';
  $('answer').textContent = '检索中…';
  $('sources').innerHTML = '';
  try {
    const r = await fetch('/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({question: q, role: $('role').value})
    });
    const j = await r.json();
    if (!r.ok) { $('answer').className = 'err'; $('answer').textContent = j.detail || '请求失败'; return; }
    $('answer').className = '';
    $('answer').textContent = j.answer;
    $('sources').innerHTML = (j.sources || []).map(s => '<span class="src">' + s + '</span>').join('');
  } catch (e) {
    $('answer').className = 'err';
    $('answer').textContent = '网络错误：' + e.message;
  } finally {
    $('send').disabled = false;
  }
}
$('send').onclick = ask;
$('q').addEventListener('keydown', e => { if (e.key === 'Enter') ask(); });
document.querySelectorAll('.examples button').forEach(b => b.onclick = () => { $('q').value = b.dataset.q; ask(); });
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def index():
    return INDEX_HTML


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/roles")
def roles():
    return {"roles": list(ROLES)}


@app.post("/chat")
def chat(req: Ask):
    if req.role not in ROLES:
        raise HTTPException(status_code=400, detail=f"未知角色：{req.role}")
    if not _rate_ok(req.role):
        raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")

    key = (req.role, req.question)
    now = time.time()
    cached = _cache.get(key)
    if cached and now - cached[0] < CACHE_TTL:
        return {**cached[1], "cached": True}

    try:
        result = answer(req.question, req.role)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"检索或生成暂时不可用：{type(exc).__name__}",
        ) from exc

    payload = {
        "answer": result["answer"],
        "sources": sorted({h["source"] for h in result["hits"]}),
    }
    _cache[key] = (now, payload)
    return {**payload, "cached": False}
