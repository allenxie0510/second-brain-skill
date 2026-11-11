#!/usr/bin/env python3
"""语义块 → 原子知识卡。

一张卡 = 一个可判断、可反驳的主张 + 依据 + 适用条件 + 失效边界 + 一个动作。
这就是这个产品跟"N 篇读书笔记"的根本区别：检索的粒度是判断，不是文档。

分两遍：
1) 逐块提炼（layer=要点）——保证全量覆盖，不漏资料
2) 按问题域归纳（layer=综合）——横切多份资料，直接回答某类问题，这是最值钱的产物
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import llm

BAD_LIMITS = {"", "无", "没有", "视情况而定", "具体情况具体分析", "暂无", "-", "n/a", "na"}

SYS = """你是知识工程师。把资料整理成「原子知识卡」：一张卡只讲一个可判断、可反驳的主张。
硬性规则：
1. claim 必须是能判断对错的句子（有主语、有因果或取舍），不要写"XX 很重要""要重视 XX"这类空话。
2. conditions 写清什么前提/场景下成立，要具体；不能写"一般情况下"。
3. limits 必须是真实的反例或失效条件；不能写"无""视情况而定"。
4. action 是一个今天就能执行的具体动作，不要写"加强学习"。
5. tags 3–6 个，用用户真会搜的口语词（例：砍价、涨价、留人），不要用学科术语。
6. 不确定的不写；严禁编造数字、人名、页码、引文。
7. 一段材料最多提炼 2 张卡；宁可少，不要重复。
只输出 JSON。"""

USER = """资料：{doc} · {title}

{text}

可用问题域（domain_id 必须取自这里）：
{doms}

可用卡片类型（type 必须取自这里）：
{types}

输出 JSON：{{"cards":[{{"title":"≤40字，能当索引看","claim":"一句可复用的判断",
"basis":"依据/关键概念（来自材料）","conditions":"适用条件","limits":"失效边界或反例",
"action":"可以怎么用","tags":["..."],"type":"D","domain_id":"D1"}}]}}
没有值得提炼的判断就返回 {{"cards":[]}}。"""

SYN_SYS = """你是知识库主编。要基于一批已有知识卡，写出「跨资料综合卡」：直接回答用户会问的一类问题。
综合卡不是摘要，而是把多份材料的判断合成为一个更可用的结论（可包含取舍条件与例外）。
只输出 JSON。"""

SYN_USER = """问题域：{name}
用户在这个域里会问的问题：
{qs}

已有卡片（来自多份资料）：
{cards}

请写 2–4 张综合卡，要求：
- 每张卡回答上面某一类问题，claim 是明确结论（允许"分情况"但要说清分几种情况）
- limits 必须写清什么情况下这个结论不成立
- basis 注明综合了哪些资料的哪几个观点（用资料名，不要编造）
- layer 固定为 "综合"

输出 JSON：{{"cards":[{{"title":"...","claim":"...","basis":"...","conditions":"...","limits":"...","action":"...","tags":["..."],"type":"D"}}]}}"""


PUNCT = " \t\n，。！？、；：\"'“”‘’（）《》-—·,.;:!?()"


def bigrams(s: str) -> set:
    s = (s or "").translate({ord(c): None for c in PUNCT})
    return {s[i:i + 2] for i in range(len(s) - 1)} or {s}


def jac(a: str, b: str) -> float:
    A, B = bigrams(a), bigrams(b)
    return len(A & B) / max(1, len(A | B))


def load_tax(project: Path) -> dict:
    return json.loads((project / "data" / "taxonomy.json").read_text(encoding="utf-8"))


def clean_card(c: dict, tax: dict, doc: str, layer: str) -> dict | None:
    claim = str(c.get("claim") or "").strip()
    if len(claim) < 8:
        return None
    lim = str(c.get("limits") or "").strip()
    if lim.lower() in BAD_LIMITS or len(lim) < 4:
        return None
    doms = {d["id"] for d in tax["domains"]}
    types = {t["id"] for t in tax["card_types"]}
    dom = str(c.get("domain_id") or "").strip()
    if dom not in doms:
        dom = tax["domains"][0]["id"]
    typ = str(c.get("type") or "D").strip().upper()
    if typ not in types:
        typ = "D"
    tags = c.get("tags") or []
    if not isinstance(tags, list):
        tags = re.split(r"[、,，\s]+", str(tags))
    tags = [str(t).strip() for t in tags if str(t).strip()][:6]
    return {
        "title": (str(c.get("title") or claim).strip())[:60],
        "claim": claim[:300],
        "basis": str(c.get("basis") or "").strip()[:400],
        "conditions": str(c.get("conditions") or "").strip()[:300],
        "limits": lim[:300],
        "action": str(c.get("action") or "").strip()[:300],
        "tags": tags,
        "type": typ,
        "domain": dom,
        "book": doc,
        "layer": layer,
        "source_confidence": "model_extracted",
    }


def dedupe(cards: list[dict]) -> list[dict]:
    kept: list[dict] = []
    for c in sorted(cards, key=lambda x: 0 if x["layer"] == "综合" else 1):
        if any(jac(c["claim"], k["claim"]) > 0.82 for k in kept):
            continue
        kept.append(c)
    return kept


def run(project: Path, max_chunks: int = 0, synth: bool = True, sleep: float = 0.0) -> list[dict]:
    conf = llm.load_conf(project)
    if not llm.ready(conf):
        raise SystemExit("没有可用的模型：请设置 SBS_BASE / SBS_MODEL / SBS_KEY（或写进 brain.json 的 llm）")
    tax = load_tax(project)
    chunks = [json.loads(l) for l in
              (project / "data" / "chunks.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    if max_chunks:
        chunks = chunks[:max_chunks]

    raw_path = project / "data" / "cards.raw.jsonl"
    done = set()
    if raw_path.exists():
        for l in raw_path.read_text(encoding="utf-8").splitlines():
            if l.strip():
                try:
                    done.add(json.loads(l)["chunk"])
                except Exception:
                    pass
    todo = [c for c in chunks if c["id"] not in done]
    print(f"待处理 {len(todo)} 块（已完成 {len(done)}，可断点续跑）")

    doms = "\n".join(f"- {d['id']} = {d['name']}（{('、'.join(d['keywords'][:8]))}）" for d in tax["domains"])
    types = " / ".join(f"{t['id']} = {t['name']}" for t in tax["card_types"])

    with raw_path.open("a", encoding="utf-8") as f:
        for i, c in enumerate(todo, 1):
            try:
                raw = llm.chat(conf, SYS, USER.format(doc=c["doc"], title=c["title"],
                                                      text=c["text"], doms=doms, types=types),
                               json_mode=True, temperature=0.2)
                data = llm.parse_json(raw)
                cards = data.get("cards") if isinstance(data, dict) else data
                cards = cards or []
            except Exception as e:  # noqa: BLE001
                print(f"  ! {c['id']} 失败：{e}")
                cards = []
            f.write(json.dumps({"chunk": c["id"], "doc": c["doc"], "cards": cards},
                               ensure_ascii=False) + "\n")
            f.flush()
            print(f"  [{i}/{len(todo)}] {c['doc']} · {c['title'][:24]}  → {len(cards)} 张")
            if sleep:
                time.sleep(sleep)

    # 汇总 + 清洗
    out: list[dict] = []
    seen_chunks = set()
    for l in raw_path.read_text(encoding="utf-8").splitlines():
        if not l.strip():
            continue
        rec = json.loads(l)
        if rec["chunk"] in seen_chunks:      # 续跑会重复追加，取最后一次
            out = [c for c in out if c.get("_chunk") != rec["chunk"]]
        seen_chunks.add(rec["chunk"])
        for c in rec["cards"]:
            cc = clean_card(c, tax, rec["doc"], "要点")
            if cc:
                cc["_chunk"] = rec["chunk"]
                out.append(cc)

    # 第二遍：跨资料综合卡
    if synth:
        by_dom: dict[str, list[dict]] = {}
        for c in out:
            by_dom.setdefault(c["domain"], []).append(c)
        for d in tax["domains"]:
            group = by_dom.get(d["id"], [])
            docs = {c["book"] for c in group}
            if len(group) < 4 or len(docs) < 2:
                continue
            picks = group[:28]
            payload = "\n".join(
                f"- [{c['book']}] {c['claim']}（条件：{c['conditions']}；边界：{c['limits']}）"
                for c in picks)
            try:
                raw = llm.chat(conf, SYN_SYS,
                               SYN_USER.format(name=d["name"],
                                               qs="\n".join("- " + q for q in d["typical_questions"]),
                                               cards=payload),
                               json_mode=True, temperature=0.35)
                data = llm.parse_json(raw)
                cs = data.get("cards") if isinstance(data, dict) else data
                for c in (cs or []):
                    c["type"] = c.get("type") or "D"
                    cc = clean_card(dict(c, domain_id=d["id"]), tax, "跨资料综合", "综合")
                    if cc:
                        out.append(cc)
                print(f"  · 综合 {d['name']}：+{len(cs or [])} 张")
            except Exception as e:  # noqa: BLE001
                print(f"  ! 综合 {d['name']} 失败：{e}")

    out = dedupe(out)
    for i, c in enumerate(out, 1):
        c.pop("_chunk", None)
        c["id"] = f"K{i:03d}"

    (project / "data" / "cards.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    src = len({c["book"] for c in out})
    print(f"✓ {len(out)} 张卡（综合 {sum(1 for c in out if c['layer'] == '综合')} 张，"
          f"覆盖 {src} 份资料）→ data/cards.json")
    return out


if __name__ == "__main__":
    import sys
    run(Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve())
