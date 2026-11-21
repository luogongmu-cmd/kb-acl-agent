"""切片 + embedding + 入 Chroma，并写入部门 ACL。

目录即权限：data/corpus/<dept>/*.md，dept ∈ public/hr/finance/engineering。
每个 chunk 写入 acl_<group>=1 字段，检索时按角色过滤。
"""
import glob
import os

import chromadb
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
CHUNK, OVERLAP = 500, 50
COLLECTION = "kb_acl"

# 角色 -> 可见的文档组（admin 不写 where，见 query.py）
client = OpenAI(api_key=os.environ["LLM_API_KEY"], base_url=os.environ["LLM_BASE_URL"])
col = chromadb.PersistentClient(path=".chroma").get_or_create_collection(COLLECTION)


def chunk(text, size=CHUNK, overlap=OVERLAP):
    out, i = [], 0
    while i < len(text):
        out.append(text[i:i + size])
        i += size - overlap
    return out


for path in sorted(glob.glob("data/corpus/*/*.md")):
    dept = os.path.basename(os.path.dirname(path))
    name = f"{dept}/{os.path.basename(path)}"
    text = open(path, encoding="utf-8").read()
    for idx, piece in enumerate(chunk(text)):
        if len(piece.strip()) < 30:          # 跳过切分碎片
            continue
        # 只写自己部门的 ACL 字段；public 文档的 acl_public 对所有角色可见
        meta = {"source": name, "dept": dept, "idx": idx, f"acl_{dept}": 1}
        emb = client.embeddings.create(
            model=os.environ["EMBED_MODEL"], input=f"{name}\n{piece}"
        ).data[0].embedding
        col.add(
            ids=[f"{name}-{idx}"],
            documents=[piece],
            embeddings=[emb],
            metadatas=[meta],
        )

print("indexed chunks:", col.count())
