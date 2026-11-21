"""检索与生成：检索层按角色过滤 ACL，越权文档不会进入上下文。"""
import os

import chromadb
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI(api_key=os.environ["LLM_API_KEY"], base_url=os.environ["LLM_BASE_URL"])
col = chromadb.PersistentClient(path=".chroma").get_or_create_collection("kb_acl")

# guest 只能看 public；admin 不传 where，可见全部
ROLES = {
    "guest": "public",
    "hr": "hr",
    "finance": "finance",
    "engineering": "engineering",
    "admin": None,
}


def search(question: str, role: str = "guest", k: int = 5) -> list[dict]:
    """按角色过滤后检索。返回 [{'text','source','distance'}]。"""
    group = ROLES.get(role, "public")
    emb = client.embeddings.create(
        model=os.environ["EMBED_MODEL"], input=question
    ).data[0].embedding
    if group is None:
        r = col.query(query_embeddings=[emb], n_results=k)
    elif group == "public":
        r = col.query(query_embeddings=[emb], n_results=k, where={"acl_public": {"$eq": 1}})
    else:
        r = col.query(query_embeddings=[emb], n_results=k, where={
            "$or": [{"acl_public": {"$eq": 1}}, {f"acl_{group}": {"$eq": 1}}]
        })
    return [
        {"text": d, "source": m["source"], "distance": round(dist, 4)}
        for d, m, dist in zip(r["documents"][0], r["metadatas"][0], r["distances"][0])
    ]


def answer(question: str, role: str = "guest", k: int = 5) -> dict:
    """返回 {'answer', 'hits'}；检索为空时明确拒答。"""
    hits = search(question, role, k)
    if not hits:
        return {"answer": "资料中没有（或你没有权限查看）。", "hits": []}

    ctx = "\n\n".join(f"[{h['source']}] {h['text'][:400]}" for h in hits)
    prompt = (
        "只根据下面的资料回答，资料中的正文和表格条目都算有效依据。\n"
        "只有当资料里完全没有相关内容时，才回答「资料中没有」；\n"
        "若资料中有相关条目，即使表述简略也要据此作答，不要补充资料外的信息。\n\n"
        f"{ctx}\n\n问题：{question}"
    )
    resp = client.chat.completions.create(
        model=os.environ["LLM_MODEL"],
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    return {"answer": resp.choices[0].message.content or "", "hits": hits}
