"""FastAPI 服务：按角色检索，带限流、缓存与失败降级。"""
import time
from collections import defaultdict, deque

from fastapi import FastAPI, HTTPException
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
