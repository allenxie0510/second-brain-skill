#!/usr/bin/env python3
"""把一堆原始资料切成可喂给模型的语义块（chunks）。

支持：md / markdown / txt / html / htm / csv / tsv / json / docx / epub / pdf
设计原则：
- 结构优先：Markdown 按标题切、保留层级路径；其它格式按段落合并。
- 块要能独立成立：带上「文档名 · 章节」，模型才知道这段话从哪来。
- 不做过早的摘要：这一层只负责"切"，判断和归纳交给下一步。
"""
from __future__ import annotations

import json
import re
import subprocess
import zipfile
from pathlib import Path

TEXT_EXT = {".md", ".markdown", ".txt", ".csv", ".tsv", ".json", ".html", ".htm",
            ".docx", ".epub", ".pdf", ".log", ".rst"}
MIN_CHUNK, TARGET, MAX_CHUNK = 80, 700, 1500


def html_to_text(h: str) -> str:
    h = re.sub(r"(?is)<(script|style|nav|footer|header)[^>]*>.*?</\1>", " ", h)
    h = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</h[1-6]>", "\n", h)
    h = re.sub(r"<[^>]+>", " ", h)
    h = (h.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<")
          .replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'"))
    return re.sub(r"[ \t]+", " ", h)


def read_pdf(p: Path) -> str:
    # 1) 系统自带 pdftotext（最快最稳）
    try:
        r = subprocess.run(["pdftotext", "-layout", str(p), "-"],
                           capture_output=True, text=True, timeout=120)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout
    except Exception:
        pass
    # 2) pypdf（用户在项目 venv 里装了就可用）
    try:
        from pypdf import PdfReader  # type: ignore
        return "\n\n".join((pg.extract_text() or "") for pg in PdfReader(str(p)).pages)
    except Exception:
        pass
    raise RuntimeError(f"读不了 PDF：{p.name}（装 poppler 的 pdftotext 或 pip install pypdf）")


def read_docx(p: Path) -> str:
    with zipfile.ZipFile(p) as z:
        xml = z.read("word/document.xml").decode("utf-8", "ignore")
    xml = re.sub(r"</w:p>", "\n", xml)
    return html_to_text(xml)


def read_epub(p: Path) -> str:
    out = []
    with zipfile.ZipFile(p) as z:
        for n in sorted(z.namelist()):
            if n.lower().endswith((".xhtml", ".html", ".htm")):
                out.append(html_to_text(z.read(n).decode("utf-8", "ignore")))
    return "\n\n".join(out)


def read_any(p: Path) -> str:
    ext = p.suffix.lower()
    if ext == ".pdf":
        return read_pdf(p)
    if ext == ".docx":
        return read_docx(p)
    if ext == ".epub":
        return read_epub(p)
    raw = p.read_text(encoding="utf-8", errors="ignore")
    if ext in (".html", ".htm"):
        return html_to_text(raw)
    if ext == ".json":
        try:
            obj = json.loads(raw)
            return json.dumps(obj, ensure_ascii=False, indent=1)
        except Exception:
            return raw
    return raw


def split_md(text: str, doc: str):
    """按 Markdown 标题切，返回 [(标题路径, 正文)]"""
    parts, buf, crumb = [], [], []
    for line in text.splitlines():
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            if buf:
                parts.append((" / ".join(crumb) or doc, "\n".join(buf)))
                buf = []
            level, title = len(m.group(1)), m.group(2).strip()
            crumb = crumb[: level - 1] + [title]
        else:
            buf.append(line)
    if buf:
        parts.append((" / ".join(crumb) or doc, "\n".join(buf)))
    return parts


def pack(paras, doc, title):
    """把段落合并成 350~MAX 的块，尽量不切断段落。"""
    out, cur = [], ""
    for para in paras:
        para = para.strip()
        if not para:
            continue
        if not cur:
            cur = para
        elif len(cur) + len(para) + 2 <= TARGET:
            cur = cur + "\n" + para
        else:
            out.append(cur)
            cur = para
        while len(cur) > MAX_CHUNK:
            out.append(cur[:MAX_CHUNK])
            cur = cur[MAX_CHUNK:]
    if cur:
        out.append(cur)
    return [(title, c) for c in out if len(c) >= MIN_CHUNK]


def chunks_for(p: Path):
    text = read_any(p)
    doc = p.stem
    if p.suffix.lower() in (".md", ".markdown"):
        res = []
        for title, body in split_md(text, doc):
            res.extend(pack(body.split("\n\n"), doc, title))
        if not res:
            res = pack(text.split("\n\n"), doc, doc)
        return res
    paras = re.split(r"\n\s*\n", text)
    return pack(paras, doc, doc)


def run(project: Path, src_dir: Path | None = None, limit_docs: int = 0) -> list[dict]:
    src = src_dir or (project / "sources")
    if not src.exists():
        raise SystemExit(f"没有资料目录：{src}（把 md/txt/pdf/docx 放进去）")
    files = [p for p in sorted(src.rglob("*")) if p.is_file() and p.suffix.lower() in TEXT_EXT
             and not p.name.startswith(".") and p.name.lower() != "readme.md"]
    if not files:
        raise SystemExit(f"{src} 里没有可读的资料（支持 {' '.join(sorted(TEXT_EXT))}）")
    if limit_docs:
        files = files[:limit_docs]

    chunks, docs, skipped = [], [], []
    n = 0
    for p in files:
        try:
            cs = chunks_for(p)
        except Exception as e:  # noqa: BLE001
            skipped.append(f"{p.name}: {e}")
            continue
        if not cs:
            skipped.append(f"{p.name}: 没有可用文本")
            continue
        docs.append({"id": f"S{len(docs) + 1:03d}", "name": p.stem,
                     "path": str(p.relative_to(src)), "chunks": len(cs),
                     "bytes": p.stat().st_size})
        for title, text in cs:
            n += 1
            chunks.append({"id": f"c{n:04d}", "doc": p.stem, "doc_id": docs[-1]["id"],
                           "title": title, "text": text})

    (project / "data").mkdir(exist_ok=True)
    with (project / "data" / "chunks.jsonl").open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    (project / "data" / "sources.json").write_text(
        json.dumps(docs, ensure_ascii=False, indent=1), encoding="utf-8")

    chars = sum(len(c["text"]) for c in chunks)
    print(f"✓ 读入 {len(docs)} 份资料 → {len(chunks)} 个语义块（约 {chars / 1000:.0f}k 字）")
    print(f"  data/chunks.jsonl  data/sources.json")
    for s in skipped:
        print("  ! 跳过", s)
    return chunks


if __name__ == "__main__":
    import sys
    run(Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve())
