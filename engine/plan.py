#!/usr/bin/env python3
"""设计「问题域」——检索路由的关键。

一个常见误区：按学科分类（经济学/营销学/管理学）建目录。
但用户将来是带着问题来的（"客户一直砍价该不该让"），所以路由要按**问题场景**切。

两种来源：
1. brain.json 里给了 "domains" → 直接用（推荐给有明确主题的用户）
2. 没给 → 采样式调用模型生成；没有模型时按资料名兜底
"""
from __future__ import annotations

import json
import random
from pathlib import Path

import llm

CARD_TYPES = [
    {"id": "M", "name": "心智模型"},
    {"id": "D", "name": "决策规则"},
    {"id": "S", "name": "操作流程"},
    {"id": "T", "name": "工具模板"},
    {"id": "C", "name": "案例证据"},
    {"id": "W", "name": "反模式"},
]

SYS = ("你是知识库架构师。你要为一个「按问题检索」的第二大脑设计路由域。"
       "注意：不要按学科分类，要按『用户将来会带着什么问题来找资料』来切分。"
       "只输出 JSON，不要解释。")

USR_TMPL = """资料清单（{ndoc} 份）：
{docs}

抽样段落：
{samples}

请设计 6–9 个问题域（太少会让检索互相干扰，太多会稀释每个域的样例）。
每个域输出：
- id: D1..D9
- name: 6–10 字的中文名，像用户会说的话（例："定价与报价"、"带团队"、"选赛道"）
- category: 所属板块 id（先设计 3–5 个板块，C1..C5，比问题域更粗一层）
- keywords: 10–14 个**口语化**检索词（用户在提问时真会打出来的词，例：砍价、涨价、报价、折扣、太贵）
- typical_questions: 3–5 个**真实问题**（像人话，带具体情境，例："客户一直砍价，这单该不该让？"）

输出 JSON：
{{"categories":[{{"id":"C1","name":"板块名"}}],
 "domains":[{{"id":"D1","name":"...","category":"C1","keywords":["..."],"typical_questions":["..."]}}]}}"""


def from_docs(docs: list[dict], chunks: list[dict]) -> dict:
    """无模型兜底：按资料名建域（每份资料一个域，超过 8 份就合并成 1 个）。"""
    names = [d["name"] for d in docs][:8]
    if not names:
        names = ["全部资料"]
    if len(names) == 1:
        names = [names[0]]
    cats = [{"id": "C1", "name": "全部资料"}]
    doms = []
    for i, n in enumerate(names, 1):
        doms.append({"id": f"D{i}", "name": n[:12], "category": "C1",
                     "keywords": [], "typical_questions": []})
    return {"categories": cats, "domains": doms, "card_types": CARD_TYPES}


def run(project: Path, seed: dict | None = None, use_llm: bool = True) -> dict:
    cfg = json.loads((project / "brain.json").read_text(encoding="utf-8"))
    chunks = [json.loads(l) for l in
              (project / "data" / "chunks.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    docs = json.loads((project / "data" / "sources.json").read_text(encoding="utf-8")) \
        if (project / "data" / "sources.json").exists() else []

    tax = cfg.get("domains") or seed
    if tax and isinstance(tax, list):
        cats = cfg.get("categories") or []
        if not cats:
            ids = sorted({d.get("category") or "C1" for d in tax})
            cats = [{"id": i, "name": "知识库" if len(ids) == 1 else "板块 " + str(n)}
                    for n, i in enumerate(ids, 1)]
        tax = {"categories": cats, "domains": tax}

    if not tax:
        conf = llm.load_conf(project)
        if use_llm and llm.ready(conf):
            sample = random.sample(chunks, min(10, len(chunks)))
            samples = "\n---\n".join(
                f"[{c['doc']} · {c['title']}]\n{c['text'][:420]}" for c in sample)
            doclist = "\n".join(f"- {d['name']}（{d['chunks']} 段）" for d in docs) or "- （未统计）"
            try:
                raw = llm.chat(conf, SYS, USR_TMPL.format(ndoc=len(docs), docs=doclist, samples=samples),
                               json_mode=True, temperature=0.3)
                data = llm.parse_json(raw)
            except Exception as e:  # noqa: BLE001
                print(f"! 生成问题域失败：{e}")
                print("  先用资料名兜底；修好配置后重跑 plan 即可覆盖")
                data = {}
            doms = data.get("domains") or []
            cats = data.get("categories") or [{"id": "C1", "name": "知识库"}]
            if not doms:
                tax = from_docs(docs, chunks)
            cid = {c["id"] for c in cats}
            if doms:
              clean = []
              for i, d in enumerate(doms, 1):
                clean.append({
                    "id": d.get("id") or f"D{i}",
                    "name": (d.get("name") or f"域{i}")[:16],
                    "category": d.get("category") if d.get("category") in cid else cats[0]["id"],
                    "keywords": [str(k) for k in (d.get("keywords") or [])][:16],
                    "typical_questions": [str(q) for q in (d.get("typical_questions") or [])][:6],
                })
              tax = {"categories": cats, "domains": clean}
        else:
            tax = from_docs(docs, chunks)
            print("（未配置模型，按资料名生成占位问题域；建议补 domains 后重跑）")

    tax["card_types"] = CARD_TYPES
    tax.setdefault("categories", [{"id": "C1", "name": "知识库"}])
    have = {c["id"] for c in tax["categories"]}
    for d in tax["domains"]:
        cid = d.get("category")
        if cid and cid not in have:
            tax["categories"].append({"id": cid, "name": cid})
            have.add(cid)
    cat_ids = [c["id"] for c in tax["categories"]]
    for d in tax["domains"]:
        if d.get("category") not in cat_ids:
            d["category"] = cat_ids[0]

    # 关键词兜底：模型容易给抽象词，这里补上域名的字面拆分
    for d in tax["domains"]:
        d.setdefault("keywords", [])
        d.setdefault("typical_questions", [])
        for w in (d["name"].replace("/", " ").replace("与", " ").split()):
            if 2 <= len(w) <= 6 and w not in d["keywords"]:
                d["keywords"].append(w)

    (project / "data" / "taxonomy.json").write_text(
        json.dumps(tax, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"✓ {len(tax['domains'])} 个问题域 / {len(tax['categories'])} 个板块 → data/taxonomy.json")
    for d in tax["domains"]:
        print(f"  {d['id']} {d['name']}  · {len(d['keywords'])} 词 · {len(d['typical_questions'])} 问")
    return tax


if __name__ == "__main__":
    import sys
    run(Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve())
