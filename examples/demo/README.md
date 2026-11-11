# 示例：阿岚的接单手册（迷你项目）

4 份虚构笔记 → 4 个问题域 → 19 张知识卡 → 172 KB 单页。
用来验证安装、看产出质量，也是 CI 的离线夹具（`data/` 里已存好卡片，无需模型即可构建）。

## 直接看成品（不需要模型、不花钱）

```bash
cp -r examples/demo /tmp/demo
python3 engine/sbs.py build  /tmp/demo
python3 engine/sbs.py verify /tmp/demo      # 期望：命中 12/12，离题 0 误推
open /tmp/demo/dist/index.html
```

## 从零跑一遍（需要模型）

```bash
cp -r examples/demo /tmp/demo-from-scratch
rm -rf /tmp/demo-from-scratch/data
export SBS_BASE=https://api.deepseek.com SBS_MODEL=deepseek-chat SBS_KEY=sk-xxx
python3 engine/sbs.py ingest /tmp/demo-from-scratch
python3 engine/sbs.py plan   /tmp/demo-from-scratch
python3 engine/sbs.py cards  /tmp/demo-from-scratch
python3 engine/sbs.py build  /tmp/demo-from-scratch
python3 engine/sbs.py verify /tmp/demo-from-scratch
```

成本几分钱以内。注意：从零生成的卡片与你手改过的 `data/cards.json` 不会完全一致，
`verify` 的命中题也可能变化——这正是「问题域与口语标签决定检索质量」的直观演示。

截图见 `../../docs/screenshots/`。
