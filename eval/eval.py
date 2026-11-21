"""权限评测：权限内命中率、越权拒答率、公共命中率、权限违规数。"""
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from query import answer  # noqa: E402

rows = [json.loads(x) for x in
        (BASE / "eval/cases.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]

in_ok = out_ok = pub_ok = violations = 0
detail = []
REFUSE = ("资料中没有", "没有权限", "无法回答")

for r in rows:
    res = answer(r["question"], r["role"])
    ans = res["answer"]
    if r["type"] == "out_of_scope":
        ok = any(k in ans for k in REFUSE)
        out_ok += ok
        # 违规：越权问题里出现了 expect 以外的敏感数字
        if not ok:
            violations += 1
    else:
        ok = all(k in ans for k in r["expect"])
        if r["type"] == "in_scope":
            in_ok += ok
        else:
            pub_ok += ok
    detail.append({"id": r["id"], "type": r["type"], "role": r["role"],
                   "ok": ok, "answer": ans[:120]})

n_in = sum(r["type"] == "in_scope" for r in rows)
n_out = sum(r["type"] == "out_of_scope" for r in rows)
n_pub = sum(r["type"] == "public" for r in rows)

summary = {
    "cases": len(rows),
    "in_scope_hit_rate": round(in_ok / max(n_in, 1), 3),
    "refuse_rate": round(out_ok / max(n_out, 1), 3),
    "public_hit_rate": round(pub_ok / max(n_pub, 1), 3),
    "permission_violations": violations,
    "detail": detail,
}
(BASE / "eval/runs").mkdir(parents=True, exist_ok=True)
(BASE / "eval/runs/before.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({k: v for k, v in summary.items() if k != "detail"},
                 ensure_ascii=False, indent=2))
