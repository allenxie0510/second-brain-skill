#!/usr/bin/env python3
"""Second Brain Studio — 一行命令把资料编译成一个属于自己的第二大脑。

    python3 engine/sbs.py new  ~/我的第二大脑 --title "我的第二大脑"
    （把 md / txt / pdf / docx 丢进 ~/我的第二大脑/sources/）
    export SBS_BASE=https://api.deepseek.com  SBS_MODEL=deepseek-chat  SBS_KEY=sk-...
    python3 engine/sbs.py all  ~/我的第二大脑

产物：<项目>/dist/index.html —— 双击就能用，也能直接静态托管。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_site  # noqa: E402
import cards as cards_mod  # noqa: E402
import extract  # noqa: E402
import llm  # noqa: E402
import plan as plan_mod  # noqa: E402
import verify  # noqa: E402

TEMPLATE = {
    "title": "我的第二大脑",
    "sub": "个人知识库",
    "kicker": "个人知识库",
    "hero": ["先把问题", "— 说清楚", "再翻你的卡片"],
    "tip": "带着真实问题来。只有真正对得上的材料才会出现，沾边的不会推给你。",
    "persona": "你是一位严谨、克制的知识顾问",
    "action_label": "可以怎么用",
    "source_unit": "份资料",
    "cloud": False,
    "storage_prefix": "sb_",
    "domains": [],
    "llm": {"base": "", "model": "", "key": ""},
}


def cmd_new(args) -> None:
    root = Path(args.dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    (root / "sources").mkdir(exist_ok=True)
    (root / "data").mkdir(exist_ok=True)
    cfg_path = root / "brain.json"
    if cfg_path.exists() and not args.force:
        print(f"已存在 {cfg_path}，未覆盖（加 --force 可重建）")
    else:
        cfg = dict(TEMPLATE)
        if args.title:
            cfg["title"] = args.title
        if args.sub:
            cfg["sub"] = args.sub
        if args.hero:
            parts = [x.strip() for x in args.hero.split("|")]
            if len(parts) == 3:
                cfg["hero"] = parts
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"✓ 建好 {root}")
    note = root / "sources" / "README.md"
    if not note.exists():
        note.write_text(
            "把要沉淀的资料直接放进这个目录（支持子目录，本文件不会被读入）：\n"
            ".md  .txt  .pdf  .docx  .epub  .html  .csv  .json\n\n"
            "建议：一份资料一个文件，文件名就是它的出处名（会显示在卡片上）。\n"
            "Markdown 的小标题会被当作章节，切块更准。\n", encoding="utf-8")
    print(f"  下一步：把资料放进 {root / 'sources'}，再跑 sbs.py ingest")


def cmd_ingest(args) -> None:
    root = Path(args.dir).expanduser().resolve()
    extract.run(root, limit_docs=args.limit_docs)


def cmd_plan(args) -> None:
    root = Path(args.dir).expanduser().resolve()
    plan_mod.run(root, use_llm=not args.no_llm)


def cmd_cards(args) -> None:
    root = Path(args.dir).expanduser().resolve()
    cards_mod.run(root, max_chunks=args.max_chunks, synth=not args.no_synth, sleep=args.sleep)


def cmd_build(args) -> None:
    root = Path(args.dir).expanduser().resolve()
    sys.argv = ["build_site.py", str(root)]
    build_site.main()


def cmd_verify(args) -> None:
    root = Path(args.dir).expanduser().resolve()
    sys.exit(verify.run(root))


def cmd_all(args) -> None:
    root = Path(args.dir).expanduser().resolve()
    conf = llm.load_conf(root)
    print("① 切块")
    extract.run(root, limit_docs=args.limit_docs)
    print("\n② 设计问题域")
    plan_mod.run(root, use_llm=llm.ready(conf))
    if not llm.ready(conf):
        print("\n! 没检测到模型配置，跳过知识卡生成。")
        print("  设置后再跑：export SBS_BASE=... SBS_MODEL=... SBS_KEY=... 然后 sbs.py cards")
    else:
        print("\n③ 生成知识卡")
        cards_mod.run(root, max_chunks=args.max_chunks, synth=not args.no_synth)
    if (root / "data" / "cards.json").exists():
        print("\n④ 构建单页")
        sys.argv = ["build_site.py", str(root)]
        build_site.main()
        print("\n⑤ 自检")
        verify.run(root)
    out = root / 'dist' / 'index.html'
    if out.exists():
        print(f"\n完成。产物：{out}")
    else:
        print("\n还没生成页面：先补上模型配置，再跑 sbs.py cards（会接着生成卡片）")


def main() -> None:
    ap = argparse.ArgumentParser(prog="sbs", description="Second Brain Studio")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("new", help="新建一个知识库项目")
    p.add_argument("dir")
    p.add_argument("--title")
    p.add_argument("--sub")
    p.add_argument("--hero", help='头图三行字，用 | 分隔："先把问题|— 说清楚|再翻你的卡片"')
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_new)

    p = sub.add_parser("ingest", help="读资料、切块")
    p.add_argument("dir")
    p.add_argument("--limit-docs", type=int, default=0)
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("plan", help="设计问题域（检索路由）")
    p.add_argument("dir")
    p.add_argument("--no-llm", action="store_true")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("cards", help="生成知识卡（可断点续跑）")
    p.add_argument("dir")
    p.add_argument("--max-chunks", type=int, default=0)
    p.add_argument("--no-synth", action="store_true")
    p.add_argument("--sleep", type=float, default=0.0)
    p.set_defaults(func=cmd_cards)

    p = sub.add_parser("build", help="构建单文件站点")
    p.add_argument("dir")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("verify", help="自检：结构 + 检索命中")
    p.add_argument("dir")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("all", help="一条龙：切块 → 域 → 卡 → 构建 → 自检")
    p.add_argument("dir")
    p.add_argument("--max-chunks", type=int, default=0)
    p.add_argument("--limit-docs", type=int, default=0)
    p.add_argument("--no-synth", action="store_true")
    p.set_defaults(func=cmd_all)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
