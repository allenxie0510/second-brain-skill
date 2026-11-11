# 示例：阿岚的接单手册（迷你项目）

一个只有 4 份资料的小知识库，用来验证安装和看产出长什么样。

```bash
cp -r examples/demo ~/sbs-试跑
export SBS_BASE=https://api.deepseek.com SBS_MODEL=deepseek-chat SBS_KEY=sk-xxx
python3 engine/sbs.py ingest ~/sbs-试跑
python3 engine/sbs.py plan   ~/sbs-试跑     # brain.json 里已有人工写好的问题域，会被保留
python3 engine/sbs.py cards  ~/sbs-试跑
python3 engine/sbs.py build  ~/sbs-试跑
python3 engine/sbs.py verify ~/sbs-试跑
open ~/sbs-试跑/dist/index.html
```

内容为虚构示例。产出约 15–20 张卡，页面约 100 KB，成本几分钱以内。
