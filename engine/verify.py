#!/usr/bin/env python3
"""交付前自检：结构 + 检索行为。

检索自检不是"跑通就算过"。要看**具体推荐了哪张卡**：
问题域的问题应该推出该域的卡；离题问题应该 0 卡。
分数看起来合理但推了一张明显无关的卡，是最常见的隐性 bug。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HARNESS = r"""
const fs=require('fs');
const html=fs.readFileSync(process.argv[2],'utf8');
const i=html.indexOf('const DB = ');
const j=html.indexOf('/* ========== 渲染');
if(i<0||j<0){console.error('SLICE_FAIL');process.exit(2);}
const code=html.slice(i,j);
const stub=`
globalThis.localStorage={_d:{},getItem(k){return this._d[k]||null},setItem(k,v){this._d[k]=v},removeItem(k){delete this._d[k]}};
globalThis.document={getElementById(){return null},querySelectorAll(){return []},querySelector(){return null},addEventListener(){},documentElement:{classList:{add(){},remove(){},toggle(){}}},body:{classList:{add(){},remove(){},toggle(){}},appendChild(){}}};
globalThis.window={matchMedia(){return {matches:false,addEventListener(){},addListener(){}}}};
globalThis.location={protocol:'file:',origin:'null',search:''};
globalThis.setTimeout=setTimeout;globalThis.sessionStorage=globalThis.localStorage;
`;
let api;
try{api=new Function(stub+code+'\n;return {retrieve,parseIntent,DB,TAX,META};')();}
catch(e){console.error('EVAL_FAIL '+e.message);process.exit(3);}
const qs=JSON.parse(fs.readFileSync(process.argv[3],'utf8'));
const out=[];
for(const item of qs){
  const it=api.parseIntent(item.q,null);
  let picked=[],dom=null;
  if(!['greet','meta','offtopic','factoid','vague'].includes(it.kind)){
    const p=api.retrieve(item.q,it,null);picked=p.picked.map(r=>({t:r.c.title.slice(0,44),rel:+r.rel.toFixed(2),d:r.c.domain}));dom=p.dom;
  }
  out.push({q:item.q,expect:item.expect||'',kind:it.kind,dom,picked});
}
console.log(JSON.stringify({cards:api.DB.length,domains:api.TAX.domains.length,res:out}));
"""


def extract_questions(tax: dict) -> list[dict]:
    qs = []
    for d in tax["domains"]:
        for q in (d.get("typical_questions") or [])[:3]:
            qs.append({"q": q, "expect": d["id"], "group": d["name"]})
    qs += [
        {"q": "今天天气怎么样，适合出门吗", "expect": "OFF", "group": "离题"},
        {"q": "帮我写一段 Python 爬虫代码", "expect": "OFF", "group": "离题"},
        {"q": "推荐一部好看的电影", "expect": "OFF", "group": "离题"},
    ]
    return qs


def run(project: Path) -> int:
    html_path = project / "dist" / "index.html"
    if not html_path.exists():
        raise SystemExit("还没有产物：先跑 build")
    html = html_path.read_text(encoding="utf-8")
    ok = True

    print("— 结构自检 —")
    size = html_path.stat().st_size / 1024
    print(f"  单文件 {size:.1f} KB")
    if re.search(r"<script[^>]+src=|<link[^>]+rel=[\"']stylesheet", html):
        print("  ✗ 存在外部资源引用")
        ok = False
    else:
        print("  ✓ 零外部依赖")
    for needle, label in (("data:image/svg+xml;base64", "favicon 内联"),
                          ('id="drawer"', "参考卡抽屉"),
                          ("localNotes", "本地笔记适配")):
        print(("  ✓ " if needle in html else "  ✗ ") + label)
        ok = ok and needle in html

    tax = json.loads((project / "data" / "taxonomy.json").read_text(encoding="utf-8"))
    qs = extract_questions(tax)
    qfile = project / "tests" / "questions.json"
    qfile.parent.mkdir(exist_ok=True)
    if not qfile.exists():
        qfile.write_text(json.dumps(qs, ensure_ascii=False, indent=1), encoding="utf-8")
    qs = json.loads(qfile.read_text(encoding="utf-8"))

    with tempfile.NamedTemporaryFile("w", suffix=".cjs", delete=False, encoding="utf-8") as f:
        f.write(HARNESS)
        harness = f.name
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(qs, f, ensure_ascii=False)
        qjson = f.name

    try:
        r = subprocess.run(["node", harness, str(html_path), qjson],
                           capture_output=True, text=True, timeout=180)
    except FileNotFoundError:
        print("  ! 没有 node，跳过检索自检（装 Node 后再跑一次）")
        return 0 if ok else 1
    if r.returncode != 0:
        print("  ✗ 检索自检失败：", (r.stderr or r.stdout)[:500])
        return 1

    data = json.loads(r.stdout)
    print(f"\n— 检索自检（{data['cards']} 张卡 / {data['domains']} 个域）—")
    hit = tot = 0
    bad_off = 0
    for row in data["res"]:
        expected = row["expect"]
        picked = row["picked"]
        top = picked[0] if picked else None
        if expected == "OFF":
            flag = "✓ 0 卡" if not picked else f"✗ 推了 {len(picked)} 张"
            if picked:
                bad_off += 1
                ok = False
            print(f"  {flag}  {row['q'][:26]}")
            continue
        if row["kind"] in ("meta", "greet", "vague"):
            print(f"  · {row['q'][:24]:<26} → 元问题（{row['kind']}），不计入命中率")
            continue
        tot += 1
        if top:
            hit += 1
            mark = "✓" if top["d"] == expected else "△"
            print(f"  {mark} {row['q'][:24]:<26} → [{top['rel']:.2f}] {top['t']}")
        else:
            print(f"  ✗ {row['q'][:24]:<26} → 0 卡（该域应有材料）")
            ok = False
    print(f"\n  命中率 {hit}/{tot}" + (f"，离题误推 {bad_off} 题" if bad_off else "，离题 0 误推"))
    print("  说明：△ 表示推到了别的域但仍在库内——看标题判断是否可接受；"
          "命中率低于 80% 时优先补该域的 keywords / typical_questions。")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run(Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()))
