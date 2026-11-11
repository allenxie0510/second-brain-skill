#!/usr/bin/env python3
"""OpenAI 兼容的最小客户端：只用标准库，支持自定义 Base URL / 模型 / Key。

配置优先级（先到先得）：
1. 环境变量 SBS_BASE / SBS_MODEL / SBS_KEY
2. <项目>/brain.json 的 "llm": {"base":..., "model":..., "key":...}
3. ~/.config/second-brain/config.json 同名结构
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

HOME_CFG = Path.home() / ".config" / "second-brain" / "config.json"


class LLMError(RuntimeError):
    pass


def load_conf(project: Path | None = None) -> dict:
    conf = {}
    if HOME_CFG.exists():
        try:
            conf.update(json.loads(HOME_CFG.read_text(encoding="utf-8")))
        except Exception:
            pass
    if project and (project / "brain.json").exists():
        try:
            b = json.loads((project / "brain.json").read_text(encoding="utf-8"))
            conf.update(b.get("llm") or {})
        except Exception:
            pass
    conf["base"] = os.environ.get("SBS_BASE") or conf.get("base") or ""
    conf["model"] = os.environ.get("SBS_MODEL") or conf.get("model") or ""
    conf["key"] = os.environ.get("SBS_KEY") or conf.get("key") or ""
    return conf


def ready(conf: dict) -> bool:
    return bool(conf.get("base") and conf.get("model"))


def chat(conf: dict, system: str, user: str, *, json_mode: bool = False,
         temperature: float = 0.2, retries: int = 3, timeout: int = 120) -> str:
    if not ready(conf):
        raise LLMError("未配置模型：设置 SBS_BASE / SBS_MODEL / SBS_KEY，"
                       "或写进 brain.json 的 llm 字段")
    base = conf["base"].rstrip("/")
    if not base.endswith("/v1") and "/v1" not in base:
        base += "/v1"
    url = base + "/chat/completions"
    payload = {
        "model": conf["model"],
        "temperature": temperature,
        "stream": False,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if conf.get("key"):
        headers["Authorization"] = "Bearer " + conf["key"]

    last = ""
    for i in range(retries):
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            # 本机 mock / 内网模型服务不走系统代理（否则会被 127.0.0.1:9090 之类拦成 501）
            opener = (urllib.request.build_opener(urllib.request.ProxyHandler({}))
                      if conf.get("no_proxy") or "127.0.0.1" in url or "localhost" in url
                      else urllib.request.build_opener())
            with opener.open(req, timeout=timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
            return (data["choices"][0]["message"]["content"] or "").strip()
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "ignore")[:300]
            last = f"HTTP {e.code} {detail}"
            if e.code in (400, 401, 403, 404):
                break
        except Exception as e:  # noqa: BLE001 - 网络类错误统一重试
            last = str(e)
        if i < retries - 1:
            time.sleep(1.5 * (i + 1))
    raise LLMError(last or "调用模型失败")


def parse_json(text: str) -> object:
    """模型偶尔会包 ```json 或加解释，这里做最大努力解析。"""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1]
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    t = t.strip()
    try:
        return json.loads(t)
    except Exception:
        pass
    for a, b in (("{", "}"), ("[", "]")):
        i, j = t.find(a), t.rfind(b)
        if i >= 0 and j > i:
            try:
                return json.loads(t[i:j + 1])
            except Exception:
                continue
    raise LLMError("模型返回的不是合法 JSON：" + text[:200])
