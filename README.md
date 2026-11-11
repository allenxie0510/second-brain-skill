# Second Brain Studio

把一堆原始资料（笔记 / 文档 / PDF / 书单 / 课程 / 访谈 / 聊天记录）编译成一个**自包含的"第二大脑"单页应用**：

- **单文件产物**：`dist/index.html`，数据内联、零外部依赖，双击即用，断网可用
- **以问题为索引的知识卡**：不是"文档问答机器人"，每张卡是一个可判断、可反驳的主张，带适用条件、失效边界和落地动作
- **检索在浏览器里完成**：字符 n-gram TF-IDF + 问题域路由，无向量库、无后端、语料不出本机
- **接任意大模型**：任何 OpenAI 兼容端点（DeepSeek / Kimi / 智谱 / 通义 / OpenAI / 本地 vLLM），Key 由用户自配

```
原始语料 ──切块──▶ 语义块 ──LLM──▶ 原子知识卡 ──▶ 单文件站点（检索内联 + 模型直连）
```

## 快速开始

```bash
git clone https://github.com/allenxie0510/second-brain-skill.git
cd second-brain-skill

# 1. 新建一个知识库项目
python3 engine/sbs.py new ~/我的第二大脑 --title "我的第二大脑" --sub "垂类 · 知识库"

# 2. 把资料丢进 ~/我的第二大脑/sources/
#    支持 .md .txt .pdf .docx .epub .html .csv .json

# 3. 配置任意 OpenAI 兼容模型
export SBS_BASE=https://api.deepseek.com SBS_MODEL=deepseek-chat SBS_KEY=sk-xxx

# 4. 一条龙：切块 → 设计问题域 → 生成知识卡 → 构建单页 → 自检
python3 engine/sbs.py all ~/我的第二大脑

# 5. 打开
open ~/我的第二大脑/dist/index.html
```

想接自己的模型又不想每次 export？写进 `brain.json` 的 `"llm": {"base":..., "model":..., "key":...}`，或放 `~/.config/second-brain/config.json`（优先级：环境变量 > 项目 > 全局）。

想看效果？`examples/demo/` 是一个现成的迷你项目（自由职业接单手册，4 篇笔记），把它拷出来直接跑第 3 步即可。

## 命令一览

| 命令 | 作用 | 备注 |
|---|---|---|
| `sbs.py new <dir>` | 新建项目骨架 | `--title --sub --hero "三行字用\|分隔"` |
| `sbs.py ingest <dir>` | 读资料、切语义块 | 支持 `--limit-docs N` 先试几份 |
| `sbs.py plan <dir>` | 设计问题域（检索路由） | `--no-llm` 用文件名兜底；结果可人工改 |
| `sbs.py cards <dir>` | 逐块生成知识卡 + 跨资料综合卡 | **断点续跑**；`--max-chunks` / `--no-synth` / `--sleep` |
| `sbs.py build <dir>` | 构建单文件站点 | 改了 `brain.json` 文案后重跑即可，不用重新生成卡片 |
| `sbs.py verify <dir>` | 自检：结构 + 检索命中报告 | 命中率 < 80% 先补问题域关键词，别急着调权重 |
| `sbs.py all <dir>` | 上面全部 | |

零第三方依赖（纯 Python 标准库）。PDF 例外：需要 `pdftotext`（poppler）或 `pip install pypdf`。

## 边界条件（使用前必读）

### 资料格式

| 格式 | 支持情况 |
|---|---|
| `.md` `.markdown` | ✅ 最佳。按标题层级切块，语义块最准 |
| `.txt` `.csv` `.tsv` `.json` `.log` `.rst` | ✅ 按段落合并切块 |
| `.html` `.htm` | ✅ 自动剥掉 script/style/nav |
| `.docx` `.epub` | ✅ 纯标准库解析 |
| `.pdf` | ⚠️ 需要文字层。**扫描版 PDF 不支持**（无 OCR），先自行 OCR |
| 图片 / 音频 / 视频 | ❌ 不支持，先转文字 |
| **网址（URL）** | ❌ 不内置抓取。见下 |

### 关于"给个网址就能总结吗"

不内置。这是刻意取舍：抓网页需要处理反爬、正文抽取、动态渲染，会引入一堆依赖，破坏"零依赖单脚本"的约束。**变通做法（都很好用）**：

```bash
# 静态页 / 文章：直接存成 html，引擎能解析
curl -sL "https://example.com/article" > sources/文章标题.html
# 或用浏览器"另存为 / 复制为 Markdown"存进 sources/
```

批量抓站建议配合 `wget --mirror` 或现成的 readability 工具，抓完按普通资料跑管线。

### 资料数量与规模

没有硬性上限，但实际约束来自三处：

| 维度 | 舒适区 | 边界 | 超出的后果 |
|---|---|---|---|
| 单个语义块 | 350–700 字 | 80–1500 字硬切 | 过长被硬切，卡面变碎 |
| 原始语料 | 3 万–30 万字 | < 1 万字不建议 | 太少 → 问题域过拟合，检索互相干扰 |
| 知识卡数量 | 50–500 张 | 1000 张以内都很流畅 | 卡片 JSON 内联进单页，页面体积线性增长；检索是线性扫描，数千张仍毫秒级但页载变慢 |
| 问题域 | **6–9 个** | 4 个起（示例就是 4 个） | 少了互相干扰，多了每个域样本不足 |
| 产物体积 | < 2 MB | ≈ 5 MB | 双击打开仍可用，但首屏变慢 |

**成本估算**：约 1 次模型调用 / 语义块。1 万字 ≈ 15 块 ≈ 15 次调用；10 万字 ≈ 150 次。建议先 `--max-chunks 10` 看产出质量再全量跑。

### 模型要求

- 任何 OpenAI 兼容 `/v1/chat/completions` 端点，支持 `response_format: json_object` 更稳（不支持也能跑，`parse_json` 有容错）
- 生成卡片要求**指令遵循较好**的模型；Ultra-cheap 模型容易产出"XX 很重要"这种空话卡（会被自动丢弃，但浪费调用）

### 隐私模型

- **构建期**：语料以语义块形式发给**你自己配置的**模型端点。用本地 vLLM/Ollama 则完全不出本机
- **使用期**：`dist/index.html` 是纯静态页，检索全在浏览器；只有你主动提问时，问题 + 检索到的卡片会发给你在「设置」里填的模型端点
- 笔记、用户新增卡片默认存本机浏览器 localStorage，可导出 JSON 备份

## 做一个垂类知识库的推荐流程

1. **选料**：挑"带判断"的资料（复盘、案例、方法论），删掉寒暄、时间戳、纯事实流水账——管线提炼的是可反驳的主张，原材料没有判断，卡片就没有。
2. **试跑**：`ingest --limit-docs 3` + `cards --max-chunks 10`，看卡片质量。质量不对先调模型或资料，别全量烧钱。
3. **改问题域**：`plan` 生成后**人工过一遍**——把模型给的书面词换成用户真会打的口语词（"砍价""太贵""拖款"），补 3–5 个带情境的典型问题。这是检索质量的第一决定因素，比调任何权重都有效。
4. **全量生成**：`cards`（断了直接重跑，自动续）。
5. **自检调优**：`verify` 看逐题命中。哪道题 Top1 错了就给正确卡补口语检索标签（加在 `tags` 最前面），重跑 `build + verify`。真实用户问过的问题都加进 `tests/questions.json`，它就是你的回归测试。
6. **品牌化**：`brain.json` 里的 `persona`（模型人设）、`hero`（首页三行大字）、`scope`（覆盖范围）、`offtopic`（本行业特有的"看起来像但库里没有"的词）。
7. **分发**：整个 `dist/` 打包发人，或传到 Vercel / Cloudflare Pages / 对象存储。

## 让 AI Agent 替你执行

本仓库自带 `SKILL.md`（AI Agent 执行手册）。任何能执行 shell 的模型助手
（Claude Code / WorkBuddy / Cursor / GPT + 终端）读到本仓库后，都能按手册自动完成：
建项目 → 审查并优化问题域 → 试跑卡片 → 构建自检 → 按命中报告迭代。
直接把这个仓库喂给你的 Agent，说「把 sources 里的资料做成第二大脑」即可；
手册里还包含「用户没配 Key 时如何搭好骨架等人续跑」的降级路径。

## 云端模式（可选）

默认是纯本地模式。如果你想把知识库挂到公网域名、笔记跨设备同步、模型 Key 不落在访客浏览器里，参考 `docs/cloud-mode.md`：在 Vercel 上补 `api/proxy`（模型代理）与 `api/notes`（加密笔记存储），然后 `brain.json` 设 `"cloud": true`。

## 架构与设计取舍

- **为什么不用向量库 / embedding？** 几百张卡的规模下，字符 n-gram TF-IDF + 意图路由足够准，且换来四个性质：零成本、零延迟、断网可用、语料不出本机。语义索引在构建期已经完成——卡片本身（tags / keywords / typical_questions）就是索引。语料到数千卡以上时再考虑本地 embedding。
- **为什么是"知识卡"不是"文档块"？** 以文档为检索粒度永远召回一整段模糊摘要；以"一条可判断的主张"为粒度才能真正回答"这单该不该接"式的问题。
- **回写闭环**：页面内置「＋ 新增知识」——对话中发现库里没有的判断，直接让 AI 整理成一张卡写回本地（云端模式写回 Blob）。

## License

MIT
