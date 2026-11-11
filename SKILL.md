---
name: second-brain-skill
description: 把任意语料（笔记/文档/PDF/书单/课程/访谈/聊天记录）编译成一个自包含的"第二大脑"单页应用：原子知识卡 + 问题域路由 + 零依赖离线检索 + 可接任意大模型。当用户说「把这些资料做成知识库」「建我自己的第二大脑」「做一个像 ChatGPT 但只懂我资料的应用」「把文档变成能问答的网站」「打包成本地应用」时使用。
---

# Second Brain Skill —— 给 AI Agent 的执行手册

本文件面向 AI Agent（Claude / GPT / WorkBuddy / 任何能执行 shell 的模型）。
你的任务：引导用户或代用户执行管线，把 `sources/` 里的语料编译成一个单文件知识库应用。
完整产品说明见 `README.md`，本文只讲「Agent 该怎么做」。

## 铁律（先读，违反任何一条都会做出不可用的东西）

1. **不做文档问答机器人，做判断库。** 检索粒度是「一条可判断、可反驳的主张」，不是文档。
2. **每张卡必须有适用条件和失效边界。** 没有边界的知识检索出来只是正确的废话。
3. **问题域决定检索质量。** 数量 6–9 个；域名说人话（「定价与报价」而不是「市场营销」）；
   keywords 用口语词；typical_questions 用带情境的真实问题。
4. **产物必须是零外部依赖的单文件。** `build_site.py` 自带校验，出现外链会直接报错退出。
5. **不确定的不写。** 管线 prompt 已禁止编造数字、页码、引文；你人工补卡片时同样遵守。

## 执行流程

### 第 0 步：确认环境

```bash
python3 --version          # ≥ 3.10
ls <仓库路径>/engine/sbs.py
```

- 模型配置三选一：环境变量 `SBS_BASE/SBS_MODEL/SBS_KEY`、项目 `brain.json` 的 `llm` 字段、
  `~/.config/second-brain/config.json`。任何 OpenAI 兼容端点都可以。
- 用户没配模型时：仍可执行 `new`、`ingest`、`plan --no-llm`，把项目骨架搭好，然后明确告诉用户
  「配好 Key 后跑 sbs.py cards 即可续跑」，不要替用户编卡片充数。
- 用户只有 URL 没有文件：引擎不抓网页。让用户 `curl -sL 网址 > sources/标题.html` 或浏览器另存，
  再继续。扫描版 PDF（无文字层）先让用户 OCR。

### 第 1 步：建项目

```bash
python3 engine/sbs.py new <项目目录> --title "..." --sub "垂类 · 主题" --hero "三行|大字|文案"
```

然后让用户把资料放进 `sources/`（一份资料一个文件，文件名即出处名）。
检查：`ls <项目>/sources/` 确认格式在支持列表内（md/txt/pdf/docx/epub/html/csv/json）。

### 第 2 步：切块 + 设计问题域

```bash
python3 engine/sbs.py ingest <项目>
python3 engine/sbs.py plan   <项目>
```

**plan 之后必须人工审一遍 `data/taxonomy.json`**（这是 Agent 的核心增值步骤）：
- 域名是否说人话？keywords 是否都是用户真会打的口语词？
- 模型给的词往往太书面——把「采购流程优化」改成「砍价」「拖款」「来不及」。
- 每个域 10–14 个 keywords、3–5 个 typical_questions，不足就补。
- 用户行业特有的「看起来像但库里没有」的词，写进 `brain.json` 的 `offtopic`。

### 第 3 步：生成知识卡（省钱策略）

```bash
python3 engine/sbs.py cards <项目> --max-chunks 10   # 先试 10 块
```

看 `data/cards.json` 质量再全量：`python3 engine/sbs.py cards <项目>`。
- `cards.raw.jsonl` 支持断点续跑，**不要删**（删了会重新花钱）。
- 每 50 张扫一次标题，语义重复（bigram 相似度 > 0.82 只能抓字面重复）交给人工判断。

### 第 4 步：构建 + 自检

```bash
python3 engine/sbs.py build  <项目>
python3 engine/sbs.py verify <项目>
```

verify 输出逐题命中报告，按此修：
- **命中率 < 80%** → 补该域 keywords / typical_questions（不是调权重）。
- **Top1 落错域** → 给正确卡补口语检索标签（`data/cards.json` 的 tags 最前面），重跑 build + verify。
- **离题题推了卡** → 补 `brain.json.offtopic`。
- 每次修复后必须重跑 build + verify，对比「原来对的题有没有被改坏」。

### 第 5 步：交付

- 本地：`dist/` 整个目录给用户，双击 `index.html`。
- 托管：`dist/index.html` 传任意静态托管。
- 用户要云端模式（笔记同步 / Key 不落浏览器）：按 `docs/cloud-mode.md` 部署 Vercel API 后，
  `brain.json` 设 `"cloud": true`，再重跑 `build`。

## 已知坑（Agent 不要踩）

- **单域语料会让意图护栏失效**：检索代码已用未归一化的 `routeRaw()` 修复，改引擎时别改回去。
- **系统代理会拦本机模型服务**（HTTP_PROXY 指向 127.0.0.1 时）：`llm.py` 已对 localhost 关代理。
- **流式期间不要重绘 DOM**：页面有 `streamingNow` 守卫，改前端时别在流式回调里调 `renderMsgs()`。
- **改了卡片必须重跑 build**：`dist/index.html` 是快照，不实时读数据。
- **成本**：≈ 1 次调用 / 语义块。先 `--max-chunks 10` 试跑再全量。

## 交付标准（完成前自查）

- [ ] `verify` 命中率 ≥ 80%，离题题 0 误推
- [ ] 产物 `dist/index.html` 单文件、无外链（build 自带校验）
- [ ] `brain.json` 的 title/hero/persona/scope 已按用户领域定制，不是默认值
- [ ] 卡片抽样 10 张：claim 可反驳、conditions 具体、limits 是真实反例
- [ ] 告知用户：模型在页面「设置」里用他们自己的 Key；笔记存本机浏览器
