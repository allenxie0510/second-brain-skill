# 云端模式：笔记跨设备 + Key 不落浏览器

本地模式（默认）已经够用：笔记存 localStorage，模型 Key 存访客自己的浏览器。
只有这两种情况值得上后端：

1. 用户要在手机、电脑看到同一批笔记；
2. 知识库公开分享，但不想把模型 Key 交给访客。

## 最小后端（两个函数）

部署到 Vercel（`api/` 目录自动成为 Serverless 函数）：

```
api/proxy.js   # POST /v1/chat/completions -> 转发到真实模型，Key 在环境变量里
api/notes.js   # GET/POST/DELETE /api/notes，笔记存 Vercel Blob
```

前端只要把 `brain.json` 的 `cloud` 设为 `true`，页面就会自动改用这两条接口
（`build_site.py` 里的 `BRAND.cloud` 分支），其余 UX 完全一致。

### proxy.js 要点

- 从 `process.env.LLM_API_KEY` 取 Key，浏览器永远拿不到。
- 校验 `X-SBS-Token`（口令），否则任何拿到地址的人都能消耗你的额度。
- 校验 `Origin`，只允许自己的域名。
- 加 `AbortSignal.timeout(9000)`，避免上游卡死把函数拖到超时。
- `vercel.json` 里给这两个函数配 `maxDuration: 60`（默认 10s 会掐断流式响应）。

### notes.js 要点（三条硬约束，实测踩过）

1. `@vercel/blob` 的 `put()` 同路径必须传 `allowOverwrite: true`，否则第二次写入报 "blob already exists"。
2. 读改写**不能用固定 key 的公开 URL**——CDN 会返回写前的缓存值，导致丢数据。用版本化 key
   （`notes-<ts>-<rand>.json`），读时取 `uploadedAt` 最新的那个。
3. 加密用 AES-256-GCM，密钥放环境变量（与访问口令分开）。口令泄露时不至于连内容一起泄露。

## 什么时候不要上后端

- 只有一个用户、只在一台设备用 → 本地模式更快更省。
- 笔记里会写客户名、报价、私人判断 → 本地模式天然合规，云端要想清楚谁能读。

## 迁移路径

本地笔记可以直接导出 JSON（「我的笔记 → 导出备份」），后端上线后写一个一次性导入脚本，
把 `notes` 数组逐条 POST 到 `/api/notes` 即可。两边数据结构一致，不需要转换。
