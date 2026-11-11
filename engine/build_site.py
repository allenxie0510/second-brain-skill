#!/usr/bin/env python3
"""Second Brain Studio —— 把一份语料编译成一个自包含的对话式知识库单页。

用法：python3 engine/build_site.py <项目目录>
读取：brain.json（品牌与配置）、data/cards.json（知识卡）、data/taxonomy.json（问题域/分类）
输出：dist/index.html（单文件、数据内联、零外部依赖、双击即用或直接静态托管）

输出：site/index.html（单文件，数据内联，零外部依赖，可直接静态托管）
设计前提：知识库只是「信息来源之一」，不是答案本身。页面先做意图判定与相关性过滤，
只有真正对得上的知识卡才会进入回答，且以可展开的参考材料形式呈现，默认不铺开。
两种模式：
  - 检索模式（默认，无后端）：理解意图 → 判断能否用库回答 → 严格过滤 → 克制呈现；
    问题超出范围、过于模糊或库内无可用材料时，明确说明并不推任何卡片。
  - 模型模式（可选 API 接入）：由 LLM 直接针对问题作答，知识卡作为 RAG 候选材料，
    prompt 明确要求忽略无关卡片；失败自动回退检索模式。
  另有「复制为 Prompt」作为零风险桥梁（粘贴到 ima / 任意大模型）。
"""
import base64
import json
import re
from pathlib import Path

import sys
from collections import Counter

ENGINE = Path(__file__).resolve().parent

TPL = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>__TITLE__</title>
<meta name="description" content="__DESC__">
<meta property="og:title" content="__TITLE__">
<meta property="og:description" content="__OGDESC__">
<link rel="icon" href="__FAV__">
<style>
:root{
--ink:#101010;--body:#2B2B2B;--muted:#626262;--hint:#949494;
--line:rgba(16,16,16,.12);--line2:rgba(16,16,16,.22);
--paper:#F1F1F1;--side:#E9E9E9;--surf:#FFFFFF;--wash:#FAFAFA;
--blue:#101010;--blue-d:#000000;--blue-bg:#EAEAEA;
--teal:#4A4A4A;--teal-bg:#EFEFEF;
--coral:#333333;--coral-bg:#F0F0F0;
--amber:#555555;--amber-bg:#F2F2F2;
--purple:#4A4A4A;--purple-bg:#EFEFEF;
--r:14px;--sans:-apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",Inter,system-ui,sans-serif;
/* 字号：对齐主流对话产品（正文 16 / 侧栏 14），移动端输入框 >=16px 防 iOS 缩放 */
--fs-body:16px;--lh-body:1.75;--fs-user:15px;--fs-side:14px;--fs-meta:12px;--fs-small:13.5px;
--fs-input:15px;--lh-input:24px;--h-input:34px;
}
*{box-sizing:border-box}
html,body{margin:0;height:100%;overflow:hidden}
body{font-family:var(--sans);background:var(--paper);color:var(--ink);font-size:15px;line-height:1.68;-webkit-font-smoothing:antialiased}
button,textarea{font:inherit;color:inherit}
button{cursor:pointer}
::selection{background:#D5D5D5}
.app{display:flex;height:100vh;height:100dvh}
/* ---------- sidebar ---------- */
/* 侧栏三段式：顶部品牌/新对话固定，中间两个分组在独立滚动区，底部统计+入口常驻。
   中间区不参与挤压（flex:1 + min-height:0），底部就不会被溢出内容盖住。 */
.side{width:252px;flex:none;background:var(--side);border-right:1px solid var(--line);display:flex;flex-direction:column;padding:18px 14px 12px;overflow:hidden}
.sidebody>.brand,.sidebody>.newbtn,.sidebody>.sfoot{flex:none}
.side-scroll{flex:1;min-height:0;overflow:auto;overscroll-behavior:contain;scrollbar-width:thin}
/* 纵向滚动仍交给浏览器，横向位移留给 JS 的侧滑关闭；标签条保留横向滚动 */
.side,.drawer{touch-action:pan-y}
.dtabs{touch-action:pan-x}
.brand{display:flex;gap:10px;align-items:center;padding:2px 6px 16px;cursor:pointer;border-radius:10px;transition:opacity .15s}
.brand:hover{opacity:.78}
.brand:focus-visible{outline:2px solid var(--blue);outline-offset:2px}
.logo{width:34px;height:34px;flex:none;border-radius:10px;background:var(--blue);display:grid;place-items:center;color:#fff}
.logo .ic{width:21px;height:21px}
.logo svg{width:19px;height:19px}
.bname{font-size:14.5px;font-weight:650;letter-spacing:.1px;line-height:1.3}
.bsub{font-size:12px;color:var(--hint);margin-top:1px}
.newbtn{display:flex;align-items:center;justify-content:center;gap:7px;width:100%;padding:9px 12px;border:1px solid var(--line2);border-radius:10px;background:var(--surf);font-size:14px;font-weight:550;margin-bottom:20px}
.newbtn:hover{border-color:var(--blue);color:var(--blue)}
.slabel{font-size:12px;font-weight:650;letter-spacing:1.3px;color:var(--hint);text-transform:uppercase;margin:0 8px 8px}
/* 分组标题可折叠：收起=右尖括号，展开=下尖括号（对齐参考图的 Projects > / Projects ⌄） */
/* 分组自身按内容高度排，不允许被压缩到内容以下（否则子项会溢出盖住底部卡片） */
.sec{display:flex;flex-direction:column;flex:none}
#sec-hist{flex:none}
.stoggle{display:flex;align-items:center;gap:6px;width:100%;flex:none;text-align:left;border:none;background:none;cursor:pointer;
  font:inherit;font-size:12px;font-weight:650;letter-spacing:1.3px;color:var(--hint);text-transform:uppercase;
  padding:0 8px;margin:0 0 8px;border-radius:6px;transition:color .15s}
.stoggle:hover{color:var(--muted)}
.stoggle:focus-visible{outline:2px solid var(--blue);outline-offset:2px}
.stoggle .chev{width:13px;height:13px;flex:none;opacity:.7;transition:transform .18s ease}
.sec.open .stoggle .chev{transform:rotate(90deg)}
.sec:not(.open) .dnav,.sec:not(.open) .hlist,.sec:not(.open) .hio{display:none}
.sec:not(.open) .stoggle{margin-bottom:14px}
.dnav{display:flex;flex-direction:column;gap:1px;margin-bottom:20px}
.ditem{display:flex;align-items:center;gap:9px;width:100%;text-align:left;border:none;background:none;padding:6px 9px;border-radius:8px;font-size:var(--fs-side);color:var(--body)}
.ditem:hover{background:rgba(255,255,255,.75);color:var(--blue)}
.dcode{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11.5px;color:var(--hint);width:20px;flex:none}
.ditem:hover .dcode{color:var(--blue)}
.hlist{display:flex;flex-direction:column;gap:1px;flex:none;min-height:60px}
.hitem{display:flex;flex-direction:column;gap:2px;width:100%;border:none;background:none;text-align:left;padding:7px 9px;border-radius:8px;font-size:var(--fs-side);color:var(--muted)}
.hitem .hq{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--body)}
.hitem .hm{font-size:var(--fs-meta);color:var(--hint);white-space:nowrap}
.hitem:hover{background:rgba(255,255,255,.75)}
.hitem.on{background:var(--blue-bg)}
.hitem.on .hq{color:var(--ink);font-weight:600}
.viewbar{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;background:var(--wash);border:1px solid var(--line);border-radius:10px;padding:9px 13px;margin:0 0 18px;font-size:13px;color:var(--muted)}
.viewbar b{color:var(--ink);font-weight:600}
.viewbar button{border:none;background:none;color:var(--ink);font-size:13px;padding:2px 0;cursor:pointer;text-decoration:underline;text-underline-offset:3px}
.hempty{font-size:13px;color:var(--hint);padding:6px 9px;line-height:1.7}
.sfoot{border-top:1px solid var(--line);padding-top:12px;margin-top:12px}
.sstat{display:flex;gap:12px;padding:0 8px 10px;color:var(--muted);font-size:12px;flex-wrap:wrap}
.sstat b{color:var(--ink);font-weight:650;font-size:13.5px}
.slinks{display:flex;gap:3px}
.slinks .slink{white-space:nowrap;font-size:12px;padding:6px 2px}
.slink{flex:1;border:none;background:none;padding:6px 4px;border-radius:7px;font-size:12.5px;color:var(--muted)}
.slink:hover{background:rgba(255,255,255,.8);color:var(--blue)}
.hio{display:flex;gap:5px;flex:none;margin:8px 0 2px;border-top:1px solid var(--line);padding-top:9px}
.hio .slink{border:1px solid var(--line);font-size:12.5px;padding:5px 4px}
/* ---------- main ---------- */
.main{flex:1;min-width:0;display:flex;flex-direction:column}
.top{flex:none;height:56px;border-bottom:1px solid var(--line);background:rgba(251,250,247,.9);backdrop-filter:blur(8px);display:flex;align-items:center;gap:12px;padding:0 22px}
.hamb{display:none;border:none;background:none;border-radius:8px;width:34px;height:34px;flex:none;padding:0;color:var(--muted);place-items:center}
.hamb svg{display:block}
.hamb:hover{background:var(--surf);color:var(--ink)}
.ic{display:block;fill:currentColor}
.badge{display:inline-flex;align-items:center;gap:5px;font-size:12px;color:var(--teal);background:var(--teal-bg);border-radius:20px;padding:3px 10px}
.dot{width:5px;height:5px;border-radius:50%;background:var(--teal)}
.topright{margin-left:auto;display:flex;align-items:center;gap:6px}
.iconbtn{border:1px solid transparent;background:none;border-radius:8px;padding:6px 9px;font-size:13px;color:var(--muted)}
.iconbtn:hover{background:var(--surf);border-color:var(--line);color:var(--ink)}
.scrollwrap{position:relative;flex:1;min-height:0;display:flex}
.scroll{flex:1;min-width:0;overflow:auto}
/* 单一圆形结构：白底 + 外缘浅灰描边 + 阴影。
   加载弧用 CSS 伪元素沿边框转，不再叠 SVG 圆环（避免多层圆错位）。 */
.scrolldown{position:absolute;left:50%;bottom:16px;transform:translateX(-50%);width:44px;height:44px;border:1px solid var(--line2);border-radius:50%;background:#fff;color:var(--ink);display:none;place-items:center;cursor:pointer;z-index:12;box-shadow:0 2px 10px rgba(0,0,0,.10)}
.scrolldown.on{display:grid}
.scrolldown::before{content:'';position:absolute;inset:-1px;border-radius:50%;border:2px solid transparent;border-top-color:var(--ink);animation:sdspin .95s linear infinite}
.scrolldown.done::before{display:none}
@keyframes sdspin{to{transform:rotate(360deg)}}
.sdarrow{width:18px;height:18px;display:block;position:relative;z-index:1}
.scrolldown:hover{background:var(--wash)}
.wrap{max-width:780px;margin:0 auto;padding:0 24px}
/* ---------- welcome ---------- */
.welcome{padding:0 0 28px}
.wmark{width:44px;height:44px;border-radius:13px;background:var(--blue);display:grid;place-items:center;margin-bottom:20px;color:#fff}
.wmark .ic{width:26px;height:26px}
.wmark svg{width:24px;height:24px}
.wtitle{font-size:30px;font-weight:650;letter-spacing:-.4px;margin:0 0 8px;line-height:1.35}
.wdesc{font-size:15px;color:var(--muted);margin:0 0 6px;max-width:600px}
.wtip{font-size:14px;color:var(--blue-d);background:var(--blue-bg);border-radius:9px;padding:9px 13px;margin:18px 0 24px;display:inline-block}
.wguide{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px}
.wguide h2{font-size:12px;font-weight:650;letter-spacing:1.2px;color:var(--hint);text-transform:uppercase;margin:0}
.swap{border:none;background:none;font-size:13px;color:var(--blue);padding:4px 6px}
.swap:hover{text-decoration:underline}
.guides{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}
.guide{position:relative;text-align:left;background:var(--surf);border:1px solid var(--line);border-radius:12px;padding:13px 15px 12px;min-height:92px;display:flex;flex-direction:column;transition:border .14s,transform .14s}
.guide:hover{border-color:var(--blue);transform:translateY(-1px)}
.gcode{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11.5px;color:var(--blue);letter-spacing:.5px}
.gtext{font-size:15px;font-weight:550;margin-top:6px;line-height:1.55;flex:1}
.gsub{font-size:12.5px;color:var(--hint);margin-top:7px}
.garrow{position:absolute;right:13px;top:12px;color:var(--hint);font-size:13px}
.wnote{margin-top:26px;border-top:1px solid var(--line);padding-top:16px;color:var(--hint);font-size:13px;line-height:1.8}
.wnote b{color:var(--muted);font-weight:600}
/* ---------- 首页头图：大字排版 + 几何构件 + 连线（纯 CSS/SVG，零外部资源） ---------- */
.hero{--h-green:#2FBF71;--h-blue:#2F6BFF;--h-yellow:#F5B93B;--h-violet:#8B5CF6;--h-sky:#5BA8FF;
 position:relative;padding:clamp(24px,4.4vh,50px) 0 clamp(20px,3.4vh,36px);
 font-size:clamp(30px,5.6vw,68px);isolation:isolate}
.hero-kicker{display:flex;align-items:center;gap:9px;font-size:11.5px;font-weight:650;letter-spacing:1.5px;
 color:var(--hint);margin-bottom:clamp(18px,3vh,32px);text-transform:uppercase}
.hero-kdot{width:8px;height:8px;border-radius:50%;background:var(--h-blue);flex:none}
.hero-kline{flex:1;height:1px;background:var(--line);max-width:110px}
.hero-kv{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:1px;font-weight:400}
.hero-type{position:relative;display:flex;flex-direction:column;align-items:flex-start;gap:.02em}
.hero-line{display:flex;align-items:center;gap:.17em;white-space:nowrap}
.hero-line:nth-child(2){padding-left:.26em}
.hw{font-weight:800;letter-spacing:-.035em;line-height:1.14;color:var(--ink)}
/* 绿色圆 + 箭头 */
.hgo{width:1.05em;height:1.05em;border-radius:50%;background:var(--h-green);display:grid;place-items:center;flex:none}
.hgo svg{width:.56em;height:.56em;stroke:var(--ink);stroke-width:2.4;fill:none;stroke-linecap:round;stroke-linejoin:round}
/* 蓝色开关 */
.htoggle{width:2.55em;height:1.05em;border-radius:.6em;background:#E6E6E7;position:relative;flex:none;overflow:hidden}
.htoggle::before{content:'';position:absolute;left:0;top:0;bottom:0;width:62%;border-radius:.6em;background:var(--h-blue)}
.htoggle i{position:absolute;left:calc(62% - .46em);top:50%;transform:translateY(-50%);width:.92em;height:.92em;border-radius:50%;background:#fff;box-shadow:0 1px 5px rgba(0,0,0,.13)}
.htoggle b{position:absolute;left:.40em;top:50%;transform:translateY(-50%);width:.1em;height:.1em;border-radius:50%;background:var(--h-blue)}
/* 黄色圆 + 垂线与箭头 */
.hsun{width:1.05em;height:1.05em;border-radius:50%;background:var(--h-yellow);position:relative;flex:none}
.hsun i{position:absolute;left:26%;top:50%;transform:translate(-50%,-50%);width:.13em;height:.13em;border-radius:50%;background:var(--h-blue)}
.hsun::after{content:'';position:absolute;left:26%;top:100%;width:1.5px;height:.58em;background:var(--ink)}
.hsun::before{content:'';position:absolute;left:calc(26% + 6px);top:calc(100% + .55em);width:0;height:0;
 border-left:5px solid var(--ink);border-top:3px solid transparent;border-bottom:3px solid transparent}
/* 白底描边胶囊 */
.hpill{width:1.9em;height:.62em;border:1.6px solid var(--ink);border-radius:.4em;background:var(--surf);
 display:flex;align-items:center;justify-content:center;gap:.16em;position:relative;flex:none}
.hpill i{width:.3em;height:2px;background:var(--ink);border-radius:2px}
.hpill b{width:.12em;height:.12em;border-radius:50%;background:var(--h-green)}
.hpill::before,.hpill::after{content:'';position:absolute;top:50%;transform:translateY(-50%);width:.1em;height:.1em;border-radius:50%;background:var(--h-blue)}
.hpill::before{left:-.06em}.hpill::after{right:-.06em}
/* 紫蓝叠圆 + 脑图标胶囊 */
.horbs{width:1.62em;height:1.05em;position:relative;flex:none}
.horbs .o1,.horbs .o2{position:absolute;top:0;width:1.05em;height:1.05em;border-radius:50%}
.horbs .o1{left:0;background:var(--h-violet)}
.horbs .o2{left:.55em;background:var(--h-sky);opacity:.88}
.horbicon{position:absolute;left:.3em;top:50%;transform:translateY(-50%);width:.92em;height:.5em;border-radius:.3em;
 background:#fff;display:grid;place-items:center;z-index:2;box-shadow:0 2px 9px rgba(0,0,0,.12)}
.horbicon svg{width:.32em;height:.32em;fill:var(--ink)}
/* 右侧细连线与端点 */
.hwire{position:absolute;right:-2%;top:34%;width:19%;height:50%;overflow:visible;pointer-events:none;z-index:-1}
.hwire path{fill:none;stroke:var(--ink);stroke-width:1.6;stroke-linecap:round}
.hwire circle{fill:var(--h-blue)}
.hero-sub{font-size:15px;line-height:1.85;color:var(--muted);margin:clamp(20px,3.2vh,34px) 0 0;max-width:580px}
.hero-sub b{color:var(--ink);font-weight:650}
.hero-cta{margin-top:18px;border:none;background:var(--ink);color:#fff;border-radius:999px;padding:11px 20px;
 font-size:13.5px;font-weight:600;display:inline-flex;align-items:center;gap:9px;transition:transform .16s,opacity .16s}
.hero-cta:hover{transform:translateY(-2px);opacity:.88}
.hero-cta svg{width:14px;height:14px;stroke:currentColor;stroke-width:2;fill:none;stroke-linecap:round;stroke-linejoin:round}
.hero-tip{font-size:13.5px;color:var(--hint);margin:16px 0 0;line-height:1.7}
/* ---------- 侧栏收起为图标导轨 ---------- */
.sidebody{display:flex;flex-direction:column;flex:1;min-height:0}
.rail{display:none;flex-direction:column;align-items:center;gap:3px;width:100%;flex:1;min-height:0}
.railbtn{width:40px;height:40px;flex:none;border:none;background:transparent;border-radius:10px;display:grid;place-items:center;color:var(--muted);position:relative;padding:0}
.railbtn:hover{background:rgba(255,255,255,.85);color:var(--ink)}
.railbtn svg{width:19px;height:19px;stroke:currentColor;fill:none;stroke-width:1.9;stroke-linecap:round;stroke-linejoin:round}
.railbtn.rb-brand{background:var(--ink);color:#fff;border-radius:11px}
.railbtn.rb-brand:hover{background:var(--ink);opacity:.86;color:#fff}
.railbtn.rb-brand svg{width:21px;height:21px;fill:currentColor;stroke:none}
.railsep{width:24px;height:1px;background:var(--line);margin:7px 0;flex:none}
.railsp{flex:1;min-height:0}
.railcnt{position:absolute;top:1px;right:1px;min-width:14px;height:14px;line-height:14px;padding:0 3px;border-radius:8px;background:var(--ink);color:#fff;font-size:9px;text-align:center}
@media(min-width:901px){
 .app.side-collapsed .side{width:62px;padding:14px 6px 10px}
 .app.side-collapsed .sidebody{display:none}
 .app.side-collapsed .rail{display:flex}
}
/* ---------- 顶栏收敛 ---------- */
.sidetoggle{border:none;background:none;border-radius:8px;width:34px;height:34px;flex:none;
 display:grid;place-items:center;color:var(--muted);padding:0}
.sidetoggle:hover{background:var(--surf);color:var(--ink)}
.sidetoggle svg{width:19px;height:19px;display:block}
/* 移动端抽屉内的收起按钮（展开靠左上角菜单，收起靠这里 / 左划 / 点遮罩） */
.sideclose{display:none;margin-left:auto;border:none;background:none;border-radius:8px;width:30px;height:30px;
 flex:none;place-items:center;color:var(--hint);padding:0}
.sideclose:hover{background:var(--surf);color:var(--ink)}
.sideclose svg{width:16px;height:16px;display:block}
.abstatus{display:inline-flex;align-items:center;gap:7px;font-size:12.5px;color:var(--teal);background:var(--teal-bg);border-radius:20px;padding:5px 12px;margin-bottom:10px}
.absetdesc{font-size:13px;color:var(--muted);margin:0 0 12px}
/* ---------- messages ---------- */
.msgs{padding:26px 0 12px}
.msg{margin-bottom:26px;opacity:1;animation:fade .28s ease both}
@keyframes fade{from{opacity:.82;transform:translateY(4px)}to{opacity:1;transform:none}}
@media(prefers-reduced-motion:reduce){.msg{animation:none}}
.urow{display:flex;justify-content:flex-end}
.ububble{background:var(--blue-bg);color:var(--blue-d);border-radius:14px 14px 4px 14px;padding:10px 15px;max-width:82%;font-size:var(--fs-user);line-height:1.65;white-space:pre-wrap;word-break:break-word}
.arow{display:flex;gap:11px;align-items:flex-start}
.avatar{width:27px;height:27px;flex:none;border-radius:8px;background:var(--blue);display:grid;place-items:center;margin-top:2px;color:#fff}
.avatar .ic{width:16px;height:16px}
.avatar svg{width:15px;height:15px}
.abody{flex:1;min-width:0}
.ameta{font-size:var(--fs-meta);color:var(--hint);margin:2px 0 9px;display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.ans{background:var(--surf);border:1px solid var(--line);border-radius:var(--r);padding:17px 19px 14px}
.alead{display:flex;gap:11px;align-items:flex-start;padding-bottom:14px;border-bottom:1px solid var(--line)}
.atag{flex:none;font-size:11.5px;font-weight:650;color:var(--blue);background:var(--blue-bg);border-radius:5px;padding:3px 7px;margin-top:2px;white-space:nowrap}
.alead p{margin:0;font-size:var(--fs-body);font-weight:600;line-height:var(--lh-body)}
.agrid{display:grid;grid-template-columns:1fr 1fr;gap:14px;padding:14px 0}
.acell h5,.awarn h5,.aact h5{font-size:11.5px;font-weight:650;letter-spacing:.6px;color:var(--hint);margin:0 0 4px}
.acell p,.awarn p,.aact p{margin:0;font-size:14.5px;line-height:1.75;color:var(--body)}
.awarn{background:var(--coral-bg);border-radius:9px;padding:10px 12px;margin-bottom:9px}
.awarn h5{color:var(--coral)}
.aact{background:var(--teal-bg);border-radius:9px;padding:10px 12px}
.aact h5{color:var(--teal)}
.aanother{border-left:2px solid var(--line2);padding:2px 0 2px 11px;margin:13px 0 0;font-size:14px;color:var(--muted);line-height:1.7}
.aanother b{color:var(--body);font-weight:600}
.arefs{display:flex;gap:6px;flex-wrap:wrap;margin-top:14px;padding-top:12px;border-top:1px solid var(--line)}
.ref{border:1px solid var(--line);background:var(--paper);border-radius:7px;padding:4px 9px;font-size:12px;color:var(--muted)}
.ref:hover{border-color:var(--blue);color:var(--blue)}
.badge-s{padding:1px 6px;border-radius:4px;font-size:11px;font-weight:650;margin-right:5px}
.b-M{background:var(--purple-bg);color:var(--purple)}.b-D{background:var(--blue-bg);color:var(--blue)}.b-S{background:var(--teal-bg);color:var(--teal)}.b-T{background:var(--amber-bg);color:var(--amber)}.b-C{background:var(--wash);color:var(--muted)}.b-W{background:var(--coral-bg);color:var(--coral)}
.afollow{display:flex;gap:6px;flex-wrap:wrap;margin-top:11px}
.fchip{border:1px solid var(--line);background:var(--surf);border-radius:20px;padding:4px 11px;font-size:12.5px;color:var(--muted)}
.fchip:hover{border-color:var(--blue);color:var(--blue);background:var(--blue-bg)}
.atools{display:flex;gap:5px;flex-wrap:wrap;margin-top:13px;padding-top:11px;border-top:1px solid var(--line)}
.tool{border:none;background:none;padding:4px 8px;border-radius:6px;font-size:12px;color:var(--hint)}
.tool:hover{background:var(--wash);color:var(--blue)}
.thinking{display:flex;gap:4px;align-items:center;color:var(--hint);font-size:13.5px;padding:8px 0}
.thinking i{width:5px;height:5px;border-radius:50%;background:var(--hint);animation:blink 1.1s infinite}
.thinking i:nth-child(2){animation-delay:.2s}.thinking i:nth-child(3){animation-delay:.4s}
@keyframes blink{0%,60%,100%{opacity:.25}30%{opacity:1}}
.spin{color:var(--blue);flex:none;animation:spin .85s linear infinite;transform-origin:50% 50%}
@keyframes spin{to{transform:rotate(360deg)}}
.genline{display:flex;align-items:center;gap:9px;color:var(--hint);font-size:14.5px;padding:12px 0}
.direct.gen{display:flex;align-items:center;gap:9px}
.md.streaming>*:last-child::after{content:'';display:inline-block;width:2px;height:1.05em;background:var(--blue);margin-left:3px;vertical-align:-2px;animation:blink 1s step-end infinite}
.md.streaming:empty::after{content:'';display:inline-block;width:2px;height:1.05em;background:var(--blue);animation:blink 1s step-end infinite}
.ansbody{}
.copybtn{position:absolute;left:19px;bottom:9px;width:30px;height:30px;border:none;border-radius:8px;background:transparent;color:var(--ink);display:grid;place-items:center;cursor:pointer;padding:0;opacity:.5;transition:opacity .15s,background .15s}
.ans:hover .copybtn{opacity:1}
.copybtn:hover{background:var(--blue-bg);opacity:1;color:var(--ink)}
.copybtn svg{width:16px;height:16px;display:block}
.copybtn.inline{position:static;opacity:.55}
/* --- 回答旁笔记（私人数据，云端保存） --- */
.notebar{margin-top:10px;display:flex;justify-content:flex-end}
.notebtn{display:inline-flex;align-items:center;gap:5px;border:none;background:transparent;color:var(--muted);font-size:12px;padding:4px 9px;border-radius:7px;cursor:pointer;opacity:.5;transition:opacity .15s,background .15s}
.ans:hover .notebtn,.notebtn:focus-visible,.notesview .notebtn{opacity:1}
.notebtn:hover{background:var(--blue-bg);opacity:1;color:var(--ink)}
.notebtn svg{width:13px;height:13px}
.noteblk{margin-top:12px;border:1px solid var(--line);border-left:3px solid var(--line2);border-radius:9px;background:var(--wash);padding:9px 12px 10px}
.nhead{display:flex;align-items:center;gap:8px;margin-bottom:5px}
.nmark{display:inline-flex;align-items:center;gap:4px;font-size:11.5px;color:var(--hint);font-weight:600}
.nmark svg{width:12px;height:12px}
.ntime{font-size:11px;color:var(--hint)}
.nops{margin-left:auto;display:flex;gap:2px}
.nbtn{border:none;background:transparent;color:var(--muted);font-size:11.5px;padding:3px 7px;border-radius:6px;cursor:pointer}
.nbtn:hover{background:var(--blue-bg);color:var(--ink)}
/* 笔记正文与对话正文同字号（--fs-body 16px / --lh-body 1.75），所见即所得 */
.nbody{font-size:var(--fs-body);line-height:var(--lh-body);color:var(--body);white-space:pre-wrap;overflow-wrap:anywhere}
.nedit{margin-top:8px;border:1px solid var(--line2);border-radius:9px;background:var(--surf);padding:8px}
.nedit textarea{width:100%;box-sizing:border-box;border:none;resize:none;outline:none;background:transparent;font:inherit;font-size:var(--fs-body);line-height:var(--lh-body);color:var(--ink);min-height:52px}
.nedops{display:flex;align-items:center;gap:4px;margin-top:6px}
.nedops .ns{border:1px solid var(--ink);color:var(--ink);font-weight:600}
.nerr{font-size:11.5px;color:#B3261E;margin-left:6px}
.ncnt{color:var(--hint);font-size:11px;margin-left:2px}
.notesview{max-width:760px;margin:0 auto;padding:26px 8px 60px}
.nvtop{display:flex;align-items:center;gap:12px;margin-bottom:14px}
.nvtop b{font-size:15px}
.nsearch{width:100%;box-sizing:border-box;border:1px solid var(--line2);border-radius:9px;background:var(--surf);padding:9px 13px;font:inherit;font-size:var(--fs-input);color:var(--ink);outline:none;margin-bottom:16px}
.nsearch:focus{border-color:var(--ink)}
.nday{font-size:11.5px;color:var(--hint);margin:16px 0 8px;font-weight:600}
.ncard{background:var(--surf);border:1px solid var(--line);border-radius:10px;padding:13px 15px;margin-bottom:9px}
/* 问题行 = 可折叠披露按钮：右尖括号收起 / 下尖括号展开，点击就地展开上下文 */
.ncq{display:flex;align-items:flex-start;gap:7px;width:100%;text-align:left;border:none;background:none;cursor:pointer;
  padding:0;margin:0 0 9px;font-size:13.5px;line-height:1.65;color:var(--muted);font-weight:550}
.ncq:hover{color:var(--blue)}
.ncq:focus-visible{outline:2px solid var(--blue);outline-offset:3px;border-radius:4px}
.ncq .chev{width:13px;height:13px;flex:none;margin-top:4px;opacity:.7;transition:transform .18s ease}
.ncq[aria-expanded="true"] .chev{transform:rotate(90deg)}
.ncqtext{flex:1;min-width:0;overflow-wrap:anywhere}
.ncq .nqpre{color:var(--hint);font-weight:400}
.ncqhint{flex:none;font-size:11.5px;font-weight:400;color:var(--hint);white-space:nowrap;margin-top:3px}
.ncq[aria-expanded="true"] .ncqhint{display:none}
/* 上下文：引用过去的问答，视觉上弱于用户自己的笔记，保持层级 */
.nctx{margin:0 0 12px;padding:10px 12px;border-left:2px solid var(--line2);background:var(--wash);border-radius:0 8px 8px 0}
.nctx[hidden]{display:none}
.nctxq{font-size:13px;line-height:1.7;color:var(--muted);overflow-wrap:anywhere}
.nctxq b{color:var(--hint);font-weight:600;margin-right:6px}
.nctxlab{font-size:11.5px;color:var(--hint);font-weight:600;margin:10px 0 5px;letter-spacing:.4px}
.nctxa{font-size:14px;line-height:var(--lh-body);color:var(--muted);max-height:300px;overflow:auto;overflow-wrap:anywhere}
.nctxa.md p{margin:0 0 9px}
.nctxa.md ul,.nctxa.md ol{margin:0 0 9px;padding-left:19px}
.nctxa.md li{font-size:14px;line-height:var(--lh-body);margin:3px 0}
.nctxa.md h3,.nctxa.md h4{font-size:14px;color:var(--body);margin:9px 0 5px}
.nctxa.md strong{color:var(--body)}
.nctxa.md blockquote{border-left:2px solid var(--line2);padding-left:10px;margin:0 0 9px;color:var(--hint)}
.nctxfoot{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:10px;padding-top:9px;border-top:1px solid var(--line)}
.njump{font-size:12px;padding:3px 0;color:var(--blue);font-weight:600;text-decoration:underline;text-underline-offset:3px}
.njump:hover{background:none;color:var(--ink)}
.nctxhint{font-size:11.5px;color:var(--hint);line-height:1.6}
.ncb{font-size:var(--fs-body);line-height:var(--lh-body);color:var(--body);white-space:pre-wrap;overflow-wrap:anywhere}
.nct{margin-top:8px;display:flex;gap:5px;flex-wrap:wrap}
.ncm{margin-top:10px;font-size:11.5px;color:var(--hint);display:flex;align-items:center;gap:8px}
.ncm .nops{margin-left:auto}
.nempty{color:var(--muted);font-size:15px;line-height:1.9;padding:26px 4px}
@media (prefers-reduced-motion: reduce){.spin{animation-duration:2.6s}.md.streaming>*:last-child::after,.md.streaming:empty::after{animation:none}}
.noresult{background:var(--surf);border:1px solid var(--line);border-radius:var(--r);padding:18px 20px;color:var(--muted);font-size:15px;line-height:1.9}
.ans,.ububble,.alead p,.acell p,.awarn p,.aact p,.aanother{max-width:100%;overflow-wrap:anywhere;word-break:break-word}
/* --- 意图层与「知识库只是来源之一」 --- */
.intentline{display:flex;gap:8px;align-items:center;font-size:12.5px;color:var(--hint);margin:0 0 10px;flex-wrap:wrap}
.intentline b{color:var(--muted);font-weight:600}
/* 复制按钮锚在回复框左下角，脱离正文流，不压任何文字 */
.ans{position:relative;padding:17px 19px 15px}
.ans:has(.refbox){padding-bottom:48px}
.ans:has(.ansbody):not(:has(.refbox)){padding-bottom:42px}
.direct{font-size:var(--fs-body);line-height:var(--lh-body);font-weight:550;margin:0 0 12px;white-space:pre-wrap}
.direct.plain{font-weight:400}

/* 模型回答的结构化排版：黑白灰体系内做层次，不用彩色强调 */
.direct.plain.md{white-space:normal}
.md p{margin:0 0 12px;line-height:var(--lh-body)}
.md h3,.md h4{font-size:15px;font-weight:650;line-height:1.5;color:var(--ink);margin:20px 0 8px}
.md h4{font-size:14px}
.md ul,.md ol{margin:0 0 12px;padding-left:21px}
.md li{margin:5px 0;line-height:var(--lh-body)}
.md li::marker{color:var(--hint)}
.md strong{font-weight:700;color:var(--ink)}
.md em{font-style:normal;color:var(--muted)}
.md blockquote{margin:0 0 12px;padding:2px 0 2px 12px;border-left:2px solid var(--line2);color:var(--muted)}
.md hr{border:none;border-top:1px solid var(--line);margin:18px 0}
.md code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.88em;background:var(--wash);border:1px solid var(--line);border-radius:4px;padding:1px 5px}
.md pre{background:var(--wash);border:1px solid var(--line);border-radius:8px;padding:10px 12px;margin:0 0 12px;overflow-x:auto;white-space:pre;font-size:13px;line-height:1.65;color:var(--body)}
.md pre code{background:none;border:none;padding:0;font-size:inherit}
.md .mtable{list-style:none;padding-left:0;border:1px solid var(--line);border-radius:9px;overflow:hidden;margin:0 0 12px}
.md .mtable li{padding:9px 12px;margin:0;border-top:1px solid var(--line)}
.md .mtable li:first-child{border-top:none}
.md .mtable b{display:block;font-weight:700;color:var(--ink);margin-bottom:2px}
.md .mtable span{display:block;font-size:12.5px;color:var(--muted);line-height:1.7}
.md>*:last-child{margin-bottom:0}
.scope{display:flex;gap:9px;flex-wrap:wrap;margin:0 0 13px}
.scope span{font-size:12.5px;color:var(--muted);background:var(--wash);border-radius:6px;padding:4px 9px}
.scope span.no{background:var(--amber-bg);color:#4A4A4A}
.refbox{border:1px solid var(--line);border-radius:10px;overflow:hidden;margin-top:12px}
.refhead{display:flex;align-items:center;gap:8px;padding:9px 12px;background:var(--wash);font-size:12.5px;color:var(--muted)}
.refhead b{color:var(--ink);font-weight:600}
.refhead .cnt{margin-left:auto;color:var(--hint)}
.refrow{display:flex;align-items:flex-start;gap:9px;width:100%;text-align:left;border:none;border-top:1px solid var(--line);background:var(--surf);padding:10px 12px;font-size:var(--fs-small);color:var(--body)}
.refrow:hover{background:var(--blue-bg)}
.refrow .rmeta{flex:none;color:var(--hint);font-size:11.5px;font-family:ui-monospace,monospace;margin-top:2px;width:56px}
.refrow .rtext{flex:1;line-height:1.6}
.refrow .rtext em{display:block;font-style:normal;color:var(--hint);font-size:12px;margin-top:3px}
.refrow .ropen{flex:none;color:var(--blue);font-size:12.5px;margin-top:1px}
.clarify{display:flex;flex-direction:column;gap:7px;margin-top:10px}
.clarify button{text-align:left;border:1px solid var(--line);background:var(--surf);border-radius:9px;padding:9px 12px;font-size:14px;color:var(--body)}
.clarify button:hover{border-color:var(--blue);color:var(--blue);background:var(--blue-bg)}
.nocard{background:var(--surf);border:1px solid var(--line);border-radius:var(--r);padding:16px 19px;font-size:15px;line-height:1.85;color:var(--body)}
.nocard strong{color:var(--ink);font-weight:600}
.upcard{display:flex;align-items:center;gap:12px;width:100%;text-align:left;margin:0 0 22px;padding:12px 15px;border:1px solid var(--blue);border-radius:12px;background:var(--blue-bg)}
.upcard:hover{filter:brightness(.985)}
.upcard .ut{flex:1;font-size:14px;color:var(--blue-d);line-height:1.6}
.upcard .ut b{display:block;font-weight:650;font-size:15px}
.upcard .ua{color:var(--blue);font-size:16px}
.modehint{font-size:12px;color:var(--hint)}
.qmark{font-size:12.5px;color:var(--hint);margin:0 0 8px}
.preset{width:100%;padding:9px 11px;border:1px solid var(--line2);border-radius:9px;outline:none;font-size:14px;background:var(--paper);margin-bottom:13px}
.preset:focus{border-color:var(--blue);background:#fff}
.lock{position:fixed;inset:0;z-index:70;background:var(--paper);display:none;place-items:center;padding:20px}
.lock.on{display:grid}
.lockbox{width:min(360px,100%);background:var(--surf);border:1px solid var(--line);border-radius:16px;padding:26px 24px;text-align:center}
.lockmark{width:40px;height:40px;border-radius:12px;background:var(--blue);display:grid;place-items:center;margin:0 auto 14px;color:#fff}
.lockmark .ic{width:23px;height:23px}
.lockmark svg{width:21px;height:21px}
.lockbox h3{font-size:15px;margin:0 0 6px;font-weight:650}
.lockbox p{font-size:12px;color:var(--muted);margin:0 0 16px}
.lockbox input{width:100%;padding:10px 12px;border:1px solid var(--line2);border-radius:9px;outline:none;font-size:13px;margin-bottom:10px;text-align:center;letter-spacing:2px}
.lockbox input:focus{border-color:var(--blue)}
.lockbox .mbtn{width:100%}
/* ---------- composer ---------- */
.composer{flex:none;border-top:1px solid var(--line);background:var(--paper);padding:12px 24px 10px}
.cbox{max-width:780px;margin:0 auto}
.cinput{display:flex;align-items:flex-end;gap:9px;background:var(--surf);border:1px solid var(--line2);border-radius:14px;padding:9px 10px 9px 15px;transition:border .14s}
.cinput:focus-within{border-color:var(--blue)}
/* 单行时 textarea 高 32px = 发送按钮高，两者在 flex-end 下顶部也齐平；
   文字靠 padding 5px + line-height 22px 在自身盒内居中，不会因按钮更高而被压低 */
#q{flex:1;border:none;outline:none;resize:none;background:none;font-size:var(--fs-input);line-height:var(--lh-input);max-height:140px;min-height:var(--h-input);padding:5px 0}
#q::placeholder{color:var(--hint)}
/* 正圆提交按钮：与主流对话产品一致，降低认知成本；宽高由 --h-input 保证相等 */
.send{width:var(--h-input);height:var(--h-input);flex:none;border:none;border-radius:50%;background:var(--blue);display:grid;place-items:center;color:#fff}
.send:hover{filter:brightness(1.1)}
.send:disabled{opacity:.4;cursor:default}
.cfg_status{font-size:12.5px;color:var(--muted);background:var(--wash);border:1px solid var(--line);border-radius:9px;padding:9px 11px;margin:-6px 0 16px;line-height:1.65}
/* ---------- overlays ---------- */
.overlay{position:fixed;inset:0;background:rgba(30,30,26,.32);z-index:40;display:none}
.overlay.on{display:block}
.modal{position:fixed;z-index:50;top:50%;left:50%;transform:translate(-50%,-50%);width:min(480px,calc(100vw - 32px));max-height:84vh;overflow:auto;background:var(--surf);border-radius:16px;padding:24px 26px;display:none;box-shadow:0 12px 48px rgba(0,0,0,.13)}
.modal.on{display:block}
.modal h2{font-size:18px;margin:0 0 6px;font-weight:650}
.modal .mdesc{font-size:13.5px;color:var(--muted);margin:0 0 18px;line-height:1.75}
.field{margin-bottom:13px}
.field label{display:block;font-size:12.5px;color:var(--muted);margin-bottom:5px;font-weight:550}
.field input{width:100%;padding:9px 11px;border:1px solid var(--line2);border-radius:9px;outline:none;font-size:14px;background:var(--paper)}
.field input:focus{border-color:var(--blue);background:#fff}
.field textarea{width:100%;padding:9px 11px;border:1px solid var(--line2);border-radius:9px;outline:none;font-size:14px;background:var(--paper);resize:vertical;line-height:1.7;font-family:inherit;box-sizing:border-box}
.field textarea:focus{border-color:var(--blue);background:#fff}
.pvcard{border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin:10px 0;background:var(--paper)}
.pvcard h4{margin:0 0 10px;font-size:14.5px;line-height:1.55;color:var(--ink)}
.pvsec{font-size:12.5px;color:var(--muted);margin:0 0 10px}
.pvsec b{color:var(--ink);font-weight:600}
.pvsec .lb{display:block;font-size:11px;letter-spacing:.8px;color:var(--hint);margin:8px 0 3px;text-transform:uppercase}
.simwarn{background:var(--wash);border:1px solid var(--line);border-radius:9px;padding:9px 12px;font-size:12.5px;color:var(--body);margin:8px 0;line-height:1.7}
.pvq{background:var(--blue-bg);border-radius:9px;padding:9px 12px;font-size:12.5px;color:var(--blue-d);margin:8px 0;line-height:1.7}
.warnbox{background:var(--amber-bg);border-radius:9px;padding:10px 12px;font-size:13px;color:#4A4A4A;line-height:1.75;margin:14px 0}
.mbtns{display:flex;gap:8px;justify-content:flex-end;margin-top:18px}
.mbtn{padding:8px 15px;border-radius:9px;border:1px solid var(--line2);background:var(--surf);font-size:13.5px}
.mbtn:hover{background:var(--wash)}
.mbtn.pri{background:var(--blue);border-color:var(--blue);color:#fff}
.mbtn.pri:hover{filter:brightness(1.08)}
.aboutsec{margin-bottom:16px}
.aboutsec h3{font-size:12px;letter-spacing:.8px;color:var(--hint);margin:0 0 6px;text-transform:uppercase}
.aboutsec p{font-size:14px;color:var(--body);margin:0;line-height:1.85}
.kv{display:flex;gap:8px;font-size:13px;padding:4px 0;color:var(--muted)}
.kv b{color:var(--ink);font-weight:600;min-width:78px}
/* ---------- card drawer ---------- */
.drawer{position:fixed;z-index:50;top:0;right:0;width:min(430px,100vw);height:100vh;height:100dvh;background:var(--surf);border-left:1px solid var(--line);transform:translateX(102%);transition:transform .24s ease;display:flex;flex-direction:column;box-shadow:-8px 0 32px rgba(0,0,0,.08)}
.drawer.on{transform:none}
.dhead{flex:none;padding:17px 20px;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:10px}
.dhead h3{font-size:15px;margin:0;font-weight:650}
.dclose{margin-left:auto;border:none;background:none;color:var(--hint);font-size:19px;line-height:1;padding:3px 7px}
.dtabs{display:flex;gap:4px;padding:10px 14px;border-bottom:1px solid var(--line);overflow:auto;flex:none}
.dtab{border:1px solid var(--line);background:var(--paper);border-radius:7px;padding:5px 10px;font-size:12px;white-space:nowrap;color:var(--muted)}
.dtab.on{background:var(--blue-bg);border-color:var(--blue);color:var(--blue);font-weight:600}
.dbody{flex:1;overflow:auto;padding:18px 20px 30px}
.dcard{padding-bottom:20px;margin-bottom:20px;border-bottom:1px solid var(--line)}
.dcard:last-child{border:none}
.dcid{font-family:ui-monospace,monospace;font-size:11.5px;color:var(--hint)}
.dct{font-size:16px;font-weight:650;line-height:1.5;margin:6px 0 9px}
.dcm{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px}
.pill{border:1px solid var(--line);border-radius:20px;padding:2px 9px;font-size:11.5px;color:var(--muted)}
.dsec{margin-bottom:11px}
.dsec h5{font-size:11.5px;letter-spacing:.6px;color:var(--hint);margin:0 0 3px;font-weight:650}
.dsec p{margin:0;font-size:14px;line-height:1.75;color:var(--body)}
.dsec.w p{color:var(--coral)}
.toast{position:fixed;bottom:88px;left:50%;transform:translateX(-50%) translateY(8px);background:var(--ink);color:#fff;font-size:13px;padding:8px 15px;border-radius:9px;opacity:0;pointer-events:none;transition:.2s;z-index:60}
.toast.on{opacity:1;transform:translateX(-50%)}
@media(max-width:900px){
 :root{--fs-body:16px;--lh-body:1.78;--fs-user:16px;--fs-side:14px;--fs-meta:12px;--fs-small:13.5px;
  --fs-input:16px;--lh-input:25px;--h-input:35px}
 .side{position:fixed;z-index:45;left:0;top:0;bottom:0;transform:translateX(-102%);transition:transform .22s ease;box-shadow:8px 0 28px rgba(0,0,0,.1)}
 .side.on{transform:none}
 .hamb{display:grid}
 .sideclose{display:grid}
 .sidetoggle{display:none}
 .top{padding:0 10px;gap:6px;height:52px}
 .wrap{padding:0 16px}
 .composer{padding:10px 14px 8px}
 .guides{grid-template-columns:1fr}
 .agrid{grid-template-columns:1fr;gap:10px}
 .welcome{padding:0 0 20px}
 .hero{font-size:clamp(29px,7.6vw,44px)}
 .hwire{display:none}
 .hero-kicker{font-size:10.5px;letter-spacing:1.2px}
 .hero-sub{font-size:14px}
 .hero-cta{font-size:13px;padding:10px 17px}
 .ans{padding:15px}
 .scrolldown{width:46px;height:46px;bottom:12px}
}
@media(max-width:380px){.hero{font-size:27px}}
/* 正文上滑 → 头部与输入框一起滑出并把空间让给正文；下滑 → 平滑恢复。
   用负 margin 而非仅 transform，才能真正回收 56px / 输入框高度。 */
@media(max-width:900px){
 .main{overflow:hidden}
 .top{transition:margin-top .3s cubic-bezier(.22,.61,.36,1),opacity .24s ease}
 .composer{transition:margin-bottom .3s cubic-bezier(.22,.61,.36,1),opacity .24s ease}
 .top.chrome-hide{margin-top:calc(-1 * var(--top-h,56px));opacity:0;pointer-events:none}
 .composer.chrome-hide{margin-bottom:calc(-1 * var(--comp-h,72px));opacity:0;pointer-events:none}
 /* 编辑笔记时彻底移走问答输入框，避免移动端误触把心得打进提问框 */
 .composer.note-editing{display:none}
}
@media (prefers-reduced-motion:reduce){
 .top,.composer{transition-duration:.01ms}
 .scrolldown::before{animation-duration:2.4s}
}
</style>
</head>
<body>
<svg width="0" height="0" style="position:absolute" aria-hidden="true"><symbol id="brain" viewBox="__BRAINVB__">__BRAINPATH__</symbol></svg>
<div class="app">
  <aside class="side" id="side">
    <div class="sidebody">
    <div class="brand" id="brandbtn" role="button" tabindex="0" title="关于这个页面" aria-label="关于这个页面">
      <div class="logo"><svg class="ic"><use href="#brain"/></svg></div>
      <div><div class="bname">__SHORT__</div><div class="bsub">__SUB__</div></div>
      <button class="sideclose" id="sideclose" aria-label="收起菜单" title="收起菜单"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg></button>
    </div>
    <button class="newbtn" id="newchat"><span style="font-size:15px;line-height:1">+</span> 新对话</button>
    <div class="side-scroll" id="sidescroll">
    <div class="sec" id="sec-dom">
      <button class="slabel stoggle" data-sec="dom" aria-expanded="true" aria-controls="dnav">按场景提问<svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6l6 6-6 6"/></svg></button>
      <div class="dnav" id="dnav"></div>
    </div>
    <div class="sec" id="sec-hist">
      <button class="slabel stoggle" data-sec="hist" aria-expanded="true" aria-controls="hlist">最近提问<svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6l6 6-6 6"/></svg></button>
      <div class="hlist" id="hlist"></div>
      <div class="hio">
        <button class="slink" id="hexport" title="把全部历史保存为 JSON 文件">导出历史</button>
        <button class="slink" id="himport" title="从 JSON 文件恢复历史（按记录 ID 去重合并）">导入历史</button>
        <input type="file" id="hfile" accept=".json,application/json" hidden>
      </div>
    </div>
    </div>
    <div class="sfoot">
      <div class="sstat" id="sstat"></div>
      <div class="slinks">
        <button class="slink" id="openadd" title="粘贴内容，AI 按卡片规范整理后入库">＋ 新增知识</button>
        <button class="slink" id="openmap">随手一张</button>
        <button class="slink" id="opennotes" title="__NOTETIP__">我的笔记<span class="ncnt" id="notecnt"></span></button>
      </div>
    </div>
    </div>
    <div class="rail" id="rail">
      <button class="railbtn rb-brand" id="railbrand" title="关于 / 设置" aria-label="关于 / 设置"><svg class="ic"><use href="#brain"/></svg></button>
      <button class="railbtn" id="railexpand" title="展开侧栏" aria-label="展开侧栏"><svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16M14.5 9.5l3 2.5-3 2.5"/></svg></button>
      <button class="railbtn" id="railnew" title="新对话" aria-label="新对话"><svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg></button>
      <div class="railsep"></div>
      <button class="railbtn" id="raildom" title="按场景提问" aria-label="按场景提问"><svg viewBox="0 0 24 24"><rect x="3.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="3.5" y="13.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.5"/></svg></button>
      <button class="railbtn" id="railhist" title="最近提问" aria-label="最近提问"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.5 2"/></svg></button>
      <div class="railsp"></div>
      <button class="railbtn" id="railadd" title="新增知识" aria-label="新增知识"><svg viewBox="0 0 24 24"><rect x="3.5" y="3.5" width="17" height="17" rx="4"/><path d="M12 8v8M8 12h8"/></svg></button>
      <button class="railbtn" id="railmap" title="随手一张" aria-label="随手一张"><svg viewBox="0 0 24 24"><rect x="4" y="5" width="11" height="14" rx="2"/><path d="M8 3h9a2 2 0 0 1 2 2v11"/></svg></button>
      <button class="railbtn" id="railnotes" title="我的笔记" aria-label="我的笔记"><svg viewBox="0 0 24 24"><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg><span class="railcnt" id="railcnt" style="display:none"></span></button>
    </div>
  </aside>

  <main class="main">
    <div class="top">
      <button class="hamb" id="hamb" aria-label="菜单"><svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 7h16M4 12h16M4 17h16"/></svg></button>
      <button class="sidetoggle" id="sidetoggle" aria-label="收起侧栏" title="收起侧栏"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/></svg></button>
    </div>

    <div class="scrollwrap">
      <div class="scroll" id="scroll"><div class="wrap" id="content"></div></div>
      <button class="scrolldown" id="scrolldown" aria-label="滚动到最新内容" title="滚动到最新内容">
        <svg class="sdarrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v13M5.5 11.5l6.5 6.5 6.5-6.5"/></svg>
      </button>
    </div>

    <div class="composer">
      <div class="cbox">
        <div class="cinput">
          <textarea id="q" rows="1" placeholder="问一个你此刻真正要做的决定…"></textarea>
          <button class="send" id="send" aria-label="发送"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5M5 12l7-7 7 7"/></svg></button>
        </div>
      </div>
    </div>
  </main>
</div>

<div class="overlay" id="overlay"></div>

<div class="lock" id="lock"><div class="lockbox">
  <div class="lockmark"><svg class="ic"><use href="#brain"/></svg></div>
  <h3 id="locktitle">需要访问口令</h3>
  <p id="locksub">这个第二大脑是私有的。输入口令进入。</p>
  <input id="lockin" type="password" placeholder="访问口令" autocomplete="off">
  <button class="mbtn pri" id="lockgo">进入</button>
  <div class="modehint" id="lockerr" style="margin-top:10px;color:var(--coral)"></div>
</div></div>

<div class="modal" id="setmodal">
  <h2>接入生成式大模型（可选）</h2>
  <p class="mdesc">接入后，大模型会先理解你的问题，再把知识卡当作其中一路参考材料来组织回答；与问题无关的卡片会被直接忽略。未接入时页面只做克制的检索与呈现，不会生成针对性回答。接口不可用时自动回退。</p>
  <div class="cfg_status" id="cfg_status"></div>
  <select class="preset" id="cfg_preset">
    <option value="">选择服务商预设（或手动填写）</option>
    <option value="deepseek">DeepSeek</option>
    <option value="moonshot">月之暗面 Kimi</option>
    <option value="zhipu">智谱 GLM</option>
    <option value="dashscope">阿里通义千问</option>
    <option value="openai">OpenAI</option>
    <option value="custom">自定义 OpenAI 兼容端点</option>
  </select>
  <div class="field"><label>API Base URL</label><input id="cfg_base" placeholder="https://api.deepseek.com/v1"></div>
  <div class="field"><label>模型名</label><input id="cfg_model" placeholder="gpt-4o-mini"></div>
  <div class="field"><label>API Key</label><input id="cfg_key" type="password" placeholder="sk-..."></div>
  <div class="field"><label>调用方式</label>
    <select class="preset" id="cfg_mode">
      <option value="direct">浏览器直连 — Key 存在本机浏览器</option>
      <option value="proxy">走我的代理 — Key 在服务端，浏览器不存 Key</option>
      <option value="none">不使用模型 — 纯本地检索，卡片只当参考</option>
    </select>
  </div>
  <div class="field"><label>访问口令（可选）</label><input id="cfg_pass" type="password" placeholder="留空则不启用；子域名公开时建议设置"></div>
  <div class="warnbox" id="cfg_warn" style="display:none">代理模式下 <strong>Key 不在浏览器</strong>，但任何拿到这个代理地址的人都能消耗你的额度。请设置访问口令，并把它同步到代理服务端的 <code>PROXY_TOKEN</code>。</div>
  <div class="warnbox">浏览器直连：Key 存在本机 localStorage，页面本身拿不到它，但<strong>任何打开这个页面的人打开开发者工具都能看到</strong>——只适合页面不对外公开的场景。走代理：Key 放在服务器，浏览器不存，配合访问口令最安全。</div>
  <div class="warnbox" style="background:var(--teal-bg);color:#2B2B2B">已实测 DeepSeek 官方 API 支持浏览器跨域直连（预检会放行 authorization 头），不需要额外搭代理即可用。</div>
  <div class="mbtns"><button class="mbtn" id="cfg_clear">清除配置</button><button class="mbtn" id="cfg_cancel">取消</button><button class="mbtn pri" id="cfg_save">保存</button></div>
</div>

<div class="modal" id="addmodal">
  <h2>＋ 新增知识</h2>
  <p class="mdesc">粘贴一段有价值的内容（书籍要点、文章观点、个人思考），AI 会按现有知识体系的卡片规范整理成一张知识卡。<b>整理结果需经你确认，未确认不写入任何存储。</b></p>
  <div id="add_step1">
    <div class="field"><label>内容（粘贴正文或要点，支持 Markdown）</label><textarea id="add_content" rows="8" placeholder="粘贴要入库的内容…"></textarea></div>
    <div class="field"><label>知识来源（书籍 / 作者 / 文章 / 网址 / 个人经验）</label><input id="add_source" placeholder="例：《掌控习惯》James Clear；或「个人经验」"></div>
    <div class="field"><label>知识性质</label>
      <select class="preset" id="add_kind">
        <option value="external">外部知识 — 来自书籍、文章或课程</option>
        <option value="personal">个人原创思考 — 自己的判断与实践</option>
      </select>
    </div>
    <div class="warnbox" id="add_err" style="display:none"></div>
    <div class="mbtns"><button class="mbtn" id="add_cancel">取消</button><button class="mbtn pri" id="add_ai">AI 整理</button></div>
  </div>
  <div id="add_step2" style="display:none"></div>
</div>

<div class="modal" id="aboutmodal">
  <h2>关于这个页面</h2>
  <p class="mdesc">__ABOUT__</p>
  <div class="aboutsec"><h3>运行状态与设置</h3>
    <div class="abstatus"><span class="dot"></span><span id="status">离线可用</span></div>
    <p class="absetdesc">模型接入、调用方式与访问口令都在这里配置。入口收敛到此处，顶栏只保留侧栏控制。</p>
    <button class="mbtn" id="about_set">打开设置</button>
  </div>
  <div class="aboutsec"><h3>知识库只是来源之一</h3><p><b id="about_books">0</b> <span id="about_unit">份资料</span> 沉淀为 <b id="about_cards">0</b> 张知识卡（含你在站内新增的卡片），但它们不是答案本身。页面先判断你的问题是什么类型、能不能用这些材料回答，只有真正对得上的卡片才会进入回答区，并默认折叠为可展开的参考材料。</p></div>
  <div class="aboutsec"><h3>不会硬凑答案</h3><p>问题超出范围、太模糊，或库里没有对得上的判断时，会直接说明并<b>不推任何卡片</b>。相关性用向量相似度、主张重合、意图与卡型匹配多路信号判定，宁可少给，不给沾边的。</p></div>
  <div class="aboutsec"><h3>两种模式</h3><p><b>检索模式</b>（默认）：呈现最贴近的材料并说明局限，不针对你的具体情境下结论。<b>模型模式</b>：接入大模型后由它理解问题并作答，知识卡作为参考来源之一，无关卡片会被忽略；接口失败自动回退。</p></div>
  <div class="aboutsec"><h3>怎么问才准</h3><p id="about_asktip"></p></div>
  <div class="aboutsec"><h3>怎么用</h3><p>双击 index.html 就能用：单文件、零依赖、数据全内联，断网也能检索。想多设备访问就把它丢到任意静态托管（对象存储 / CDN / Nginx / Vercel / Cloudflare Pages）。模型在「设置」里用自己的 Key 接入，不接也能用纯检索模式。笔记原地保存在本机浏览器里，可随时导出备份。</p></div>
  <div class="aboutsec"><h3>知识库规模</h3><div id="aboutstat"></div></div>
  <div class="mbtns"><button class="mbtn pri" id="about_close">知道了</button></div>
</div>

<div class="drawer" id="drawer">
  <div class="dhead"><h3>参考卡片</h3><button class="dclose" id="dclose">&times;</button></div>
  <div class="dtabs" id="dtabs"></div>
  <div class="dbody" id="dbody"></div>
</div>
<div class="toast" id="toast"></div>

<script>
const DB = __DATA__;
const TAX = __TAX__;
const META = __META__;
const BRAND = __BRAND__;

/* ========== 检索核心：字符 n-gram TF-IDF 稀疏向量 + 混合召回 ========== */
/* 层级语义由数据配置：综合卡（跨资料归纳）加权、速览卡（单条资料摘要）降权 */
const SYNTH_LAYER=BRAND.synth_layer||'综合', SPEED_LAYER=BRAND.speed_layer||'速览';
const LATIN=/[a-z0-9]+/g, CJK=/[\u4e00-\u9fff]+/g;
function toks(s){s=(s||'').toLowerCase();const out=[];
  (s.match(LATIN)||[]).forEach(x=>out.push(x));
  (s.match(CJK)||[]).forEach(seg=>{for(const c of seg)out.push(c);
    for(let i=0;i<seg.length-1;i++)out.push(seg.slice(i,i+2));
    for(let i=0;i<seg.length-2;i++)out.push(seg.slice(i,i+3));});
  return out;}
function cardText(c){return [c.title,c.title,c.book,c.category_name,c.domain_name,c.subcategory,
  (c.tags||[]).join(' '),c.claim,c.basis,c.conditions,c.limits,c.action].join(' ');}
const DF=new Map(),IDF=new Map(),VEC=new Map();let N=DB.length;
function vec(s){const tf=new Map();toks(s).forEach(t=>tf.set(t,(tf.get(t)||0)+1));
  const v=new Map();let norm=0;tf.forEach((k,t)=>{if(IDF.has(t)){const x=(1+Math.log(k))*IDF.get(t);v.set(t,x);norm+=x*x;}});
  norm=Math.sqrt(norm)||1;v.forEach((x,t)=>v.set(t,x/norm));return v;}
function rebuildIndex(){DF.clear();IDF.clear();VEC.clear();N=DB.length;
  DB.forEach(c=>{new Set(toks(cardText(c))).forEach(t=>DF.set(t,(DF.get(t)||0)+1));});
  DF.forEach((d,t)=>IDF.set(t,Math.log((N+1)/(d+1))+1));
  DB.forEach(c=>{VEC.set(c.id,vec(cardText(c)));});}
rebuildIndex();
function cos(a,b){if(a.size>b.size){const t=a;a=b;b=t;}let s=0;a.forEach((x,k)=>s+=x*(b.get(k)||0));return s;}
function bigrams(s){const o=new Set();(s.toLowerCase().match(CJK)||[]).forEach(g=>{
  for(let i=0;i<g.length-1;i++)o.add(g.slice(i,i+2));if(g.length===1)o.add(g);});
  (s.toLowerCase().match(LATIN)||[]).forEach(x=>o.add(x));return o;}
function sim(a,b){const A=bigrams(a),B=bigrams(b);if(!A.size||!B.size)return 0;
  let n=0;A.forEach(x=>{if(B.has(x))n++;});return n/Math.sqrt(A.size*B.size);}
function route(q){q=q.toLowerCase();const sc={};
  TAX.domains.forEach(d=>{let s=0;d.keywords.forEach(k=>{if(q.includes(k.toLowerCase()))s+=1;});
    (d.typical_questions||[]).forEach(t=>{const v=sim(q,t);if(v>=.25)s+=2*v;});
    if(s>0)sc[d.id]=s;});
  if(!Object.keys(sc).length){TAX.domains.forEach(d=>{
    const v=sim(q,d.name+' '+d.keywords.join(' ')+' '+(d.typical_questions||[]).join(' '));
    if(v>.06)sc[d.id]=v;});}
  const m=Math.max(...Object.values(sc),0)||1;Object.keys(sc).forEach(k=>sc[k]/=m);return sc;}
function kwHit(q,c){const surface=[c.title,c.book,(c.tags||[]).join(' ')].join(' ').toLowerCase();
  const g=bigrams(q);if(!g.size)return 0;let n=0;g.forEach(x=>{if(surface.includes(x))n++;});
  return Math.min(1,n/Math.max(2,Math.sqrt(g.size)));}
/* 意图层：先判断「这是什么类型的问题、值不值得查库」 */
const DEF_OFFTOPIC='天气|气温|下雨|菜谱|做饭|食谱|翻译|星座|算命|电影|歌曲|游戏攻略|比分|笑话|讲个|写诗|新闻|汇率换算|数学题|旅游|去哪里玩|宠物|养猫|养狗';
const DEF_FACTOID='几点|多少天|几天|哪个软件|什么软件|工具推荐|天气预报|手机号|电话号码|具体地址|在哪里买|多少钱';
function reEsc(x){return String(x).replace(/[.*+?^${}()|[\]\\]/g,'\\$&');}
function vagueRe(){
  const words=TAX.domains.map(d=>String(d.name||'').split(/[\s\/·、—]/)[0]).filter(x=>x&&x.length>1);
  return new RegExp('^('+words.map(reEsc).join('|')+'|怎么弄|怎么办|不知道|随便|都行)$');
}
/* 路由很强时，护栏让位：专业语料里"翻译/价格/代码"这类词很常见。
   注意不能用归一化后的 route()——只有一个域时它恒为 1，会把任何句子都判成"强路由"，
   护栏就形同虚设（实测：单域语料里"今天天气怎么样"也推了 2 张卡）。 */
function routeRaw(str){
  const q=str.toLowerCase();let best=0;
  TAX.domains.forEach(d=>{let sc=0;
    d.keywords.forEach(k=>{if(q.includes(String(k).toLowerCase()))sc+=1;});
    (d.typical_questions||[]).forEach(t=>{const v=sim(q,t);if(v>=.25)sc+=2*v;});
    if(sc>best)best=sc;});
  return best;
}
function strongDomain(str){return routeRaw(str)>=1;}
/* 意图护栏：默认词表刻意保守，只挡与任何专业资料都无关的生活闲聊；
   本行业的词由 brain.json 的 offtopic / factoid 追加，避免把本行问题误判成"超纲"。
   另外：命中护栏词但问题域路由很强时，以路由为准（专业语料里常有字面撞车的词）。 */
const OFFTOPIC=new RegExp(BRAND.offtopic||DEF_OFFTOPIC,'i');
const FACTOID=new RegExp(BRAND.factoid||DEF_FACTOID,'i');
const METAQ=/你是谁|你能做什么|能干什么|怎么用|使用说明|这是什么|多少份资料|多少张卡|多少条|知识库里有|介绍一下你自己|帮助|help/i;
const GREET=/^(你好|hi|hello|嗨|在吗|谢谢|thanks|多谢|辛苦了|好的|ok|嗯|哈喽|早上好|晚安)[\s!！。,.，~]*$/i;
const VAGUE_ONLY=vagueRe();
/* 澄清选项：直接用问题域的典型问题，换语料不用改代码 */
const CLARIFY=TAX.domains.map(d=>({k:new RegExp((d.keywords||[]).slice(0,8).map(reEsc).join('|')||'$^'),
  o:(d.typical_questions||[]).slice(0,3)})).filter(x=>x.o.length);
const FALLBACK_CLARIFY=TAX.domains.map(d=>(d.typical_questions||[])[0]).filter(Boolean).slice(0,3);
function clarifyFor(raw){const c=CLARIFY.find(x=>x.k.test(raw));return c?c.o:FALLBACK_CLARIFY;}
function parseIntent(q,lastQ){
  const raw=q.trim();
  if(GREET.test(raw))return {kind:'greet',label:'打招呼',clarify:[],effective:raw};
  if(METAQ.test(raw))return {kind:'meta',label:'了解这个页面',clarify:[],effective:raw};
  if(OFFTOPIC.test(raw)&&!strongDomain(raw))return {kind:'offtopic',label:'超出知识范围',clarify:[],effective:raw};
  if(FACTOID.test(raw))return {kind:'factoid',label:'一个具体事实或操作信息',clarify:[],effective:raw};
  const bare=raw.replace(/[？?。！!，,\s]/g,'');
  if(bare.length<5||VAGUE_ONLY.test(raw))return {kind:'vague',label:'需要澄清',clarify:clarifyFor(raw),effective:raw};
  let kind='decide';
  if(/怎么做|如何|步骤|流程|怎么开始|从哪|几步|怎么验证|怎么设计|怎么搭|具体做法/.test(raw))kind='howto';
  else if(/为什么|原因|出问题|没效果|下降|卡住|诊断|出了|失败|没转化/.test(raw))kind='diagnose';
  else if(/是什么|本质|区别|含义|定义|原理|机制|什么叫/.test(raw))kind='concept';
  const labels={decide:'一个取舍决策',howto:'一套可执行做法',diagnose:'一次问题诊断',concept:'一个概念澄清'};
  const effective=(lastQ&&raw.length<16)?lastQ+' '+raw:raw;
  return {kind,label:labels[kind],clarify:[],effective};
}
/* ---------- 相关性：多信号判定，宁可不推，也不推无关卡 ---------- */
const AFF={decide:{D:1,W:.7,M:.5,S:.35,T:.3,C:.4},
           howto:{S:1,T:.9,D:.6,W:.4,M:.35,C:.3},
           diagnose:{W:.95,D:.8,M:.6,S:.45,C:.6,T:.3},
           concept:{M:1,D:.55,C:.45,S:.3,T:.25,W:.35}};
const REL_MIN=0.235, REL_RATIO=0.84;
const STOPWORDS=new Set(['怎么','什么','哪个','哪些','如何','为什么','是否','可以','应该','一个','一下','现在','我们','我的','比较','最好','还是','多少','哪里','给我','帮我','请问','有没有','能不能','怎样','这个','那个','对于','关于','时候','以及','进行','需要','通过','之后','之前','一些','这样','那样','到底','真正','具体','问题','办法','然后','其实','到底']);
/* 卡片词表里的概念词 + taxonomy 里人工整理的口语化主题词（账上 / 撑几个月 / 第一批客户…） */
const EXTRA_CONCEPTS=new Set();
TAX.domains.forEach(d=>d.keywords.forEach(k=>{if(k.length>=2)EXTRA_CONCEPTS.add(k.toLowerCase());}));
function keyTokens(q){
  const tf=new Map();toks(q).forEach(t=>tf.set(t,(tf.get(t)||0)+1));
  const s=q.toLowerCase();
  const out=[...EXTRA_CONCEPTS].filter(k=>s.includes(k)).slice(0,6);
  [...tf.keys()].filter(t=>t.length>=2&&!STOPWORDS.has(t)&&IDF.has(t)&&!out.includes(t))
    .sort((a,b)=>IDF.get(b)-IDF.get(a)).forEach(t=>{if(out.length<14)out.push(t);});
  return out;
}
function cardSurface(c){return (c.title+' '+c.claim+' '+c.basis+' '+c.conditions+' '+(c.tags||[]).join(' ')).toLowerCase();}
function conceptHits(keys,c){const s=cardSurface(c);let n=0;keys.forEach(k=>{if(s.includes(k))n++;});return n;}
function coverage(keys,c){return keys.length?conceptHits(keys,c)/keys.length:0;}
function relevance(q,r,it,keys){
  const c=r.c, claimSim=sim(q,c.title+' '+c.claim);
  const aff=(AFF[it.kind]||{})[c.type]||.3;
  const synth=c.layer===SYNTH_LAYER?1:0, book=c.layer===SPEED_LAYER?1:0;
  return .24*r.cv+.28*claimSim+.20*coverage(keys,c)+.08*aff+.16*(r.rtWeight||0)+.07*synth-.05*book;
}
function retrieve(q,it,ctxDomain){
  const eq=it.effective||q, qv=vec(eq), rt=route(eq), keys=keyTokens(q);
  const all=DB.map(c=>{
    const cv=cos(qv,VEC.get(c.id)||new Map());
    const layer=c.layer===SYNTH_LAYER?1:0;
    const ctx=(ctxDomain&&c.domain===ctxDomain&&q.length<16)?.03:0;
    return {c,cv,rtWeight:rt[c.domain]||0,
      score:.66*cv+.12*kwHit(eq,c)+.16*(rt[c.domain]||0)+.06*layer+ctx};});
  all.sort((a,b)=>b.score-a.score);
  const cand=new Map();
  all.slice(0,14).forEach(r=>cand.set(r.c.id,r));
  /* 概念补充召回：主张里真的出现关键概念的卡，即使向量初排靠后也要进候选 */
  DB.map(c=>({c,h:conceptHits(keys,c)})).sort((a,b)=>b.h-a.h).slice(0,6).forEach(x=>{
    if(x.h>0&&!cand.has(x.c.id))cand.set(x.c.id,{c:x.c,cv:cos(qv,VEC.get(x.c.id)||new Map()),
      rtWeight:rt[x.c.domain]||0,score:0});});
  const pool=[...cand.values()].map(r=>({...r,hits:conceptHits(keys,r.c),rel:relevance(q,r,it,keys)}));
  pool.sort((a,b)=>b.rel-a.rel);
  /* 门槛：要么主张里真的出现关键概念，要么这个问题明确路由到了该卡所属的域 */
  const eligible=pool.filter(r=>r.hits>=1||(r.rtWeight||0)>=0.75);
  const lead=eligible.length?eligible[0].rel:0;
  /* 强路由（明确命中某问题域）时放宽绝对线：抽象主题的口语提问与卡片词面重合度天然偏低，
     0.235 是按旧创业域调的，会误杀新域的第 1 名目标卡 */
  const strongRoute=pool.some(r=>(r.rtWeight||0)>=0.75);
  const cut=Math.max(strongRoute?0.19:REL_MIN,lead*REL_RATIO);
  const picked=eligible.filter(r=>r.rel>=cut).slice(0,2);
  const dom=Object.keys(rt).sort((a,b)=>rt[b]-rt[a])[0]||null;
  return {picked,pool,rt,dom,lead,cut,keys};
}

/* ========== 状态 ========== */
/* 首页引导问题：从各问题域的 typical_questions 自动拼两页，数据驱动 */
const GUIDES=(function(){
  const pool=[];
  TAX.domains.forEach(d=>(d.typical_questions||[]).forEach(t=>pool.push({d:d.id,t:t,s:d.name})));
  DB.slice(0,0);
  if(!pool.length)return [[{d:'',t:'',s:''}]];
  const pages=[];for(let i=0;i<pool.length;i+=6)pages.push(pool.slice(i,i+6));
  return pages;
})();
let guideIdx=0, msgs=[], lastDomain=null, lastQ=null, busy=false, drawerCards=[], drawerSel=0;
let streamingNow=false;
let cfg=loadCfg(), hist=loadHist();
let viewMsgs=null, viewMeta=null;
const $=id=>document.getElementById(id);
const esc=s=>String(s==null?'':s).replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
function loadCfg(){try{return JSON.parse(localStorage.getItem('sbs_llm')||'null')||null}catch(e){return null}}
function loadHist(){try{const a=JSON.parse(localStorage.getItem('sbs_hist')||'[]');return Array.isArray(a)?a.filter(h=>h&&h.q):[]}catch(e){return []}}
function saveHist(){
  const data=hist.slice(0,30);
  try{localStorage.setItem('sbs_hist',JSON.stringify(data));return;}catch(e){}
  try{const half=data.slice(0,15);localStorage.setItem('sbs_hist',JSON.stringify(half));hist=half;return;}catch(e){}
  toast('浏览器存储空间不足，历史未能保存');
}
function activeMsgs(){return viewMsgs||msgs;}
function exitView(){viewMsgs=null;viewMeta=null;notesView=false;noteJump=false;renderMsgs();renderNav();}
function nextN(){let n=0;hist.forEach(h=>{if((h.n||0)>n)n=h.n});return n+1;}
function fmtTime(ts){if(!ts)return '时间未记录';const d=new Date(ts),p=x=>String(x).padStart(2,'0');
  return d.getFullYear()+'-'+p(d.getMonth()+1)+'-'+p(d.getDate())+' '+p(d.getHours())+':'+p(d.getMinutes());}
function snap(m){return {q:m.q,pending:false,html:m.html,plain:m.plain,cards:m.cards||[],dom:m.dom,
  source:m.source,localHtml:m.localHtml,localPlain:m.localPlain,prompt:m.prompt};}

/* ---- 零后端备份：导出 / 导入历史（纯前端，不依赖任何服务） ---- */
function exportPayload(){
  return JSON.stringify({app:'sbs-second-brain',version:1,exportedAt:new Date().toISOString(),
    count:hist.length,history:hist},null,2);
}
function downloadHist(){
  if(!hist.length){toast('还没有历史记录可导出');return;}
  const blob=new Blob([exportPayload()],{type:'application/json'});
  const url=URL.createObjectURL(blob);
  const a=document.createElement('a');a.href=url;
  const d=new Date(),p=x=>String(x).padStart(2,'0');
  a.download='sbs-history-'+d.getFullYear()+p(d.getMonth()+1)+p(d.getDate())+'-'+p(d.getHours())+p(d.getMinutes())+'.json';
  document.body.appendChild(a);a.click();a.remove();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
  toast('已导出 '+hist.length+' 条提问');
}
function cleanHtml(s){
  s=String(s||'');
  s=s.replace(/<script\b[\s\S]*?<\/script>/gi,'').replace(/<\/(script|iframe|object|embed)>/gi,'');
  s=s.replace(/<(script|iframe|object|embed)\b/gi,'&lt;$1');
  s=s.replace(/\son\w+\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)/gi,'');
  s=s.replace(/srcdoc\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)/gi,'');
  s=s.replace(/\s(href|src)\s*=\s*(["']?)\s*(javascript|data|vbscript):[^"'\s>]*\2/gi,'');
  s=s.replace(/\sstyle\s*=\s*("[^"]*"|'[^']*')/gi,function(m,v){
    return /expression|javascript:|url\s*\(\s*['"]?\s*javascript:/i.test(v)?'':m;});
  s=s.replace(/javascript\s*:/gi,'');
  return s;
}
function cleanCard(c){
  const keys=['id','title','category_name','book','type','layer','domain_name','claim','basis','conditions','limits','action'];
  const o={};keys.forEach(k=>{o[k]=String(c[k]==null?'':c[k]).slice(0,2000)});
  o.tags=Array.isArray(c.tags)?c.tags.map(String).slice(0,12):[];
  return o;
}
function cleanSnap(m){
  return {q:String(m.q||'').slice(0,500),pending:false,html:cleanHtml(m.html||''),
    plain:String(m.plain||'').slice(0,50000),
    cards:Array.isArray(m.cards)?m.cards.filter(r=>r&&r.c).slice(0,6).map(r=>({c:cleanCard(r.c),rel:Number(r.rel)||0})):[],
    dom:m.dom||null,source:String(m.source||'历史记录').slice(0,120),
    localHtml:'',localPlain:'',prompt:String(m.prompt||'').slice(0,20000)};
}
function importText(txt){
  let d;try{d=JSON.parse(txt)}catch(e){return {ok:false,msg:'不是有效的 JSON 文件'};}
  let arr=null;
  if(d&&d.app==='sbs-second-brain'&&Array.isArray(d.history))arr=d.history;
  else if(Array.isArray(d))arr=d;
  else return {ok:false,msg:'不是本工具导出的历史文件'};
  const valid=arr.filter(h=>h&&typeof h.q==='string'&&h.q.trim());
  if(!valid.length)return {ok:false,msg:'文件里没有可用的提问记录'};
  const seen={};hist.forEach(h=>{if(h.id)seen[h.id]=1});
  const add=[];
  let maxN=0;hist.forEach(h=>{if((h.n||0)>maxN)maxN=h.n});
  valid.forEach(h=>{
    const id=h.id||('imp'+Math.random().toString(36).slice(2,10));
    if(seen[id])return;seen[id]=1;
    const n=(h.n||0)>maxN?(h.n||0):0;
    add.push({id:id,q:h.q.slice(0,500),ts:h.ts||Date.now(),n:n||++maxN,
      msgs:Array.isArray(h.msgs)?h.msgs.map(cleanSnap):[]});
  });
  hist=add.concat(hist).sort((a,b)=>(b.n||0)-(a.n||0)).slice(0,30);
  saveHist();renderNav();
  return {ok:true,added:add.length,total:hist.length};
}
function toast(t,ms){const e=$('toast');e.textContent=t;e.classList.add('on');clearTimeout(e._t);e._t=setTimeout(()=>e.classList.remove('on'),ms||1900);}
function copy(t){if(navigator.clipboard&&window.isSecureContext){navigator.clipboard.writeText(t).then(()=>toast('已复制')).catch(()=>fallbackCopy(t));}else fallbackCopy(t);}
function fallbackCopy(t){const a=document.createElement('textarea');a.value=t;a.style.position='absolute';a.style.left='-9999px';document.body.appendChild(a);a.select();try{document.execCommand('copy');toast('已复制')}catch(e){toast('复制失败')}a.remove();}
const tname={M:'心智模型',D:'决策规则',S:'操作流程',T:'工具模板',C:'案例证据',W:'反模式'};
const domName={};TAX.domains.forEach(d=>domName[d.id]=d.name);

/* ========== Markdown 白名单渲染 ==========
   模型文本一律先 esc，再按固定标签集合生成结构；绝不把原文直接塞进 innerHTML。
   只支持 问答用得到的语法：段落 / 小标题 / 列表 / 加粗 / 斜体 / 引用 / 分隔线 / 行内代码；
   表格降级成列表，代码块降级成等宽块。 */
function mdInline(s){
 s=esc(s);
 const codes=[];
 s=s.replace(/`([^`]+)`/g,function(m,c){codes.push('<code>'+c+'</code>');return '\u0001'+(codes.length-1)+'\u0001';});
 s=s.replace(/\*\*([^*\n]+)\*\*/g,'<strong>$1</strong>');
 s=s.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g,'$1<em>$2</em>');
 s=s.replace(/\u0001(\d+)\u0001/g,function(m,i){return codes[+i]||'';});
 return s;
}
function mdTableSep(line){return /^\s*\|?[\s:\-|]+\|?\s*$/.test(line)&&line.indexOf('---')>=0;}
function renderMd(src){
 const lines=String(src==null?'':src).replace(/\r\n?/g,'\n').split('\n');
 let out=[],para=[],list=null,quote=[],table=null,inCode=false,codeBuf=[];
 function flushPara(){if(para.length){out.push('<p>'+mdInline(para.join(' '))+'</p>');para=[];}}
 function flushList(){if(list){out.push('<'+list.tag+'>'+list.items.map(function(t){return '<li>'+mdInline(t)+'</li>';}).join('')+'</'+list.tag+'>');list=null;}}
 function flushQuote(){if(quote.length){out.push('<blockquote>'+mdInline(quote.join(' '))+'</blockquote>');quote=[];}}
 function flushTable(){
  if(table&&table.rows.length){
   out.push('<ul class="mtable">'+table.rows.map(function(r){
    const head=mdInline(r[0]||''),rest=[];
    for(let j=1;j<r.length;j++){
     const k=table.head[j]||'';
     if(r[j])rest.push(mdInline((k?k+'：':'')+r[j]));
    }
    return '<li>'+(head?'<b>'+head+'</b>':'')+(rest.length?'<span>'+rest.join(' · ')+'</span>':'')+'</li>';
   }).join('')+'</ul>');
  }
  else if(table&&table.head&&table.head.length){
   out.push('<p>'+mdInline(table.head.filter(Boolean).join(' · '))+'</p>');
  }
  table=null;
 }
 function flushAll(){flushPara();flushList();flushQuote();flushTable();}
 for(let i=0;i<lines.length;i++){
  const line=lines[i];
  if(/^\s*```/.test(line)){
   if(inCode){out.push('<pre>'+esc(codeBuf.join('\n'))+'</pre>');codeBuf=[];inCode=false;}
   else{flushAll();inCode=true;}
   continue;
  }
  if(inCode){codeBuf.push(line);continue;}
  if(!line.trim()){flushAll();continue;}
  if(/^\s*\|.*\|\s*$/.test(line)){
   flushPara();flushList();flushQuote();
   const cells=line.trim().replace(/^\|/,'').replace(/\|$/,'').split('|').map(function(x){return x.trim();});
   if(!table)table={head:cells,rows:[]};
   else if(mdTableSep(line)){/* 对齐行，忽略 */}
   else table.rows.push(cells);
   continue;
  }else if(table)flushTable();
  if(quote.length&&!/^\s*>/.test(line))flushQuote();
  let m=line.match(/^\s*(#{2,4})\s+(.+)$/);
  if(m){flushAll();const tag=m[1].length>=3?'h4':'h3';out.push('<'+tag+'>'+mdInline(m[2])+'</'+tag+'>');continue;}
  if(/^\s*(---+|\*\*\*+|___+)\s*$/.test(line)){flushAll();out.push('<hr>');continue;}
  m=line.match(/^\s*>\s?(.*)$/);
  if(m){flushPara();flushList();quote.push(m[1]);continue;}
  m=line.match(/^\s*(\d+)[.)]\s+(.*)$/);
  if(m){flushPara();if(!list||list.tag!=='ol'){flushList();list={tag:'ol',items:[]};}list.items.push(m[2].replace(/^[-*+]\s+\[[ xX]\]\s*/,''));continue;}
  m=line.match(/^\s*[-*+]\s+(?:\[[ xX]\]\s*)?(.*)$/);
  if(m){flushPara();if(!list||list.tag!=='ul'){flushList();list={tag:'ul',items:[]};}list.items.push(m[1]);continue;}
  flushList();para.push(line.trim());
 }
 flushAll();
 if(inCode&&codeBuf.length)out.push('<pre>'+esc(codeBuf.join('\n'))+'</pre>');
 return out.join('');
}
/* 流式清洗：delta 可能停在行内标记中间，临时去掉最后一行未闭合的标记，
   使流式期间也不出现半截 ** 或反引号；文本本身不动（下一个 chunk 会补回） */
function mdStreamClean(s){
 const lines=String(s==null?'':s).split('\n');
 let t=lines[lines.length-1]||'';
 /* 星号按「未配对计数」整行剥离：覆盖 **未闭合、末尾多一个孤立 * 等情况；
    只影响当前这一帧，下一个 chunk 会用完整文本重新渲染 */
 const dstar=(t.match(/\*\*/g)||[]).length,star=(t.match(/\*/g)||[]).length;
 if(dstar%2||star%2)t=t.replace(/\*/g,'');
 if((t.match(/`/g)||[]).length%2)t=t.replace(/`/g,'');
 if(/^\s*#{1,6}\s*$/.test(t))t='';                       /* 只有井号、标题尚未成形 */
 if(/^\s*\|/.test(t)&&!/\|\s*$/.test(t))t=t.replace(/^\s*\|\s*/,'').replace(/\s*\|\s*/g,' · ');
 lines[lines.length-1]=t;
 return lines.join('\n');
}
/* 复制用：去掉 Markdown 标记，保留段落、列表编号与换行，粘到任何地方都干净 */
function toPlain(src){
 const lines=String(src==null?'':src).replace(/\r\n?/g,'\n').split('\n');
 const out=[];let inCode=false,tableHead=null;
 for(let i=0;i<lines.length;i++){
  let l=lines[i];
  if(/^\s*```/.test(l)){inCode=!inCode;continue;}
  if(inCode){out.push(l);continue;}
  if(/^\s*\|.*\|\s*$/.test(l)){
   const cells=l.trim().replace(/^\|/,'').replace(/\|$/,'').split('|').map(function(x){return x.trim();});
   if(!tableHead){tableHead=cells;continue;}
   if(mdTableSep(l))continue;
   const head=cells[0]||'',rest=[];
   for(let j=1;j<cells.length;j++)if(cells[j])rest.push((tableHead[j]?tableHead[j]+'：':'')+cells[j]);
   out.push(head+(rest.length?'：'+rest.join(' · '):''));
   continue;
  }else tableHead=null;
  l=l.replace(/^\s{0,3}#{1,6}\s+/,'')
     .replace(/^\s*>\s?/,'')
     .replace(/^\s*(\d+\.\s*)[-*+]\s+\[[ xX]\]\s*/,'$1')
     .replace(/^\s*[-*+]\s+\[[ xX]\]\s*/,'- ')
     .replace(/^\s*(\d+)[.)]\s+/,'$1. ')
     .replace(/^\s*(---+|\*\*\*+|___+)\s*$/,'')
     .replace(/\*\*([^*]+)\*\*/g,'$1')
     .replace(/(^|[^*])\*([^*]+)\*(?!\*)/g,'$1$2')
     .replace(/`([^`]+)`/g,'$1');
  out.push(l);
 }
 return out.join('\n').replace(/\n{3,}/g,'\n\n').trim();
}

/* ========== 回答组装 ========== */
function buildPrompt(q,cards,it){
 let s=(BRAND.persona||'你是一位严谨、克制的知识顾问')+'。用户这次的问题属于【'+it.label+'】类型。知识卡只是参考来源之一，不是答案本身。\n'+
 '规则：\n1) 先直接、具体地回答问题本身，不要复述问题、不要泛泛而谈、不要开场白；\n'+
 '2) 逐张判断下面的材料是否真的与这个问题相关，只使用相关的；完全无关的不要提及、不要罗列、不要硬套；\n'+
 '3) 材料只覆盖部分问题时，说清哪部分能用、哪部分帮不上，并用你的经营常识补全，且标明这是推断；\n'+
 '4) 只输出给用户看的话。不要出现卡片 ID、出处、书名、类别名，不要写「根据知识卡」「如 K019 所示」这类措辞——来源由界面单独呈现，你不需要标注；\n'+
 '5) 不编造材料之外的案例、数据、页码或引文；\n'+
 '6) 若所有材料都不足以回答，直接说「知识库里没有能回答这个的材料」，再给出你自己的判断。\n'+
 '7) 输出格式：先给一段直接结论，再用 ## 小标题分点，需要步骤时用 1. 或 - 列表，'+
 '关键判断用 **加粗** 强调。标题最多一层，列表每项一句话，整体不超过 400 字。'+
 '不要用表格、代码块、HTML、emoji、脚注、多级标题，也不要在行首堆多余符号。\n\n'+
 '【我的问题】\n'+q+'\n\n【内部参考材料（可能全部无关，不要向用户提及它们的存在）】\n';
 if(!cards.length)s+='（本次没有检索到相关材料，请直接凭常识回答，并说明知识库这次帮不上忙）\n';
 cards.forEach((r,i)=>{const c=r.c;s+='\n【材料 '+(i+1)+'｜'+c.id+'｜'+(tname[c.type]||c.type)+'｜出处：'+c.book+'】\n'+
 '主张：'+c.claim+'\n依据：'+c.basis+'\n适用条件：'+c.conditions+'\n失效边界：'+c.limits+'\n落地动作：'+c.action+'\n';});
 return s;}
function shorten(s,n){s=String(s||'');return s.length>n?s.slice(0,n)+'…':s;}
function refHtml(cards){
 if(!cards.length)return '';
  return '<div class="refbox"><div class="refhead"><b>参考材料</b><span>点击卡片在右侧展开完整内容</span><span class="cnt">'+cards.length+' 条</span></div>'+
  cards.map(r=>'<button class="refrow" data-ref="'+esc(r.c.id)+'">'+
   '<span class="rmeta">'+esc(r.c.id)+'</span>'+
   '<span class="rtext">'+esc(r.c.title)+'<em>'+esc(r.c.category_name)+' · '+esc(shorten(r.c.book,30))+' · 相关度 '+r.rel.toFixed(2)+'</em></span>'+
   '<span class="ropen">查看 →</span></button>').join('')+'</div>';
}
function copyIcon(){
 return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="11" height="11" rx="2.2"/><path d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1"/></svg>';}
function spinSvg(){
 return '<svg class="spin" viewBox="0 0 24 24" width="15" height="15" aria-hidden="true"><circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2.6" opacity=".2"/><path d="M21 12a9 9 0 0 0-9-9" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"/></svg>';}
/* 模型回答区：正文 + 参考材料 + 一个复制图标。刻意不放来源标注与多余按钮。 */
function llmHtml(txt,picked,streaming){
 const inner=streaming
  ? '<div class="genline">'+spinSvg()+'<span>正在思考…</span></div><div class="direct plain md" id="llmout"></div>'
  : '<div class="direct plain md" id="llmout">'+renderMd(txt||'')+'</div>';
 return '<div class="ans"><div class="ansbody">'+inner+'</div>'+refHtml(picked)+
  '<button class="copybtn" data-act="copyans" title="复制回答" aria-label="复制回答">'+copyIcon()+'</button></div>';
}
function toolsHtml(cards,hasUpgrade){
 return '<div class="ansbody" style="margin-top:10px"><button class="copybtn inline" data-act="copyans" title="复制" aria-label="复制">'+copyIcon()+'</button></div>';
}
function intentLine(it,dom){
 return '<div class="intentline"><b>我理解你在问</b><span>'+esc(it.label)+'</span>'+
  (dom?'<span>· '+esc(domName[dom]||dom)+'</span>':'')+'</div>';
}
function compose(q,pack,it){
 const picked=pack.picked||[], prompt=buildPrompt(q,picked,it), hasUpgrade=!(cfg&&cfg.key);
 const meta={cards:picked,prompt,useLLM:['decide','howto','diagnose','concept','factoid'].includes(it.kind),followups:[]};
 if(it.kind==='greet'){
  return {...meta,source:'对话',plain:'你好。带一个你正在面对的问题来，我从知识库里找能用得上的判断；用不上的不会硬塞给你。',
   html:'<div class="nocard">你好。带一个你正在面对的问题来，我从知识库里找能用得上的判断；用不上的不会硬塞给你。<br><span class="modehint">例如「合伙人要 30% 股份该不该给」「账上只够撑 4 个月该砍什么」。</span></div>'};
 }
 if(it.kind==='meta'){
  return {...meta,source:'对话',plain:'我是'+BRAND.title+'，覆盖 '+Object.keys(META.domains||{}).length+' 类问题。知识卡是参考来源，不是答案本身。',
   html:'<div class="nocard"><strong>我是'+esc(BRAND.title)+'。</strong><br>'+
    '覆盖 '+Object.keys(META.domains||{}).length+' 类问题、'+DB.length+' 张知识卡。知识卡只是参考来源之一——我会先判断你的问题能不能用这些材料回答，用不上的不推给你。'+
    (hasUpgrade?'<br><br>当前是<strong>检索模式</strong>，只能呈现材料，不能针对你的具体情境推理。接入模型后会真正理解问题再作答。':'')+'</div>'+
    '<div class="atools"><button class="tool" data-act="openset">'+(hasUpgrade?'接入模型':'模型设置')+'</button></div>'};
 }
 if(it.kind==='offtopic'){
  return {...meta,source:'超出范围',plain:'这个问题不在我的知识范围内，我不会用沾边的卡片凑一个答案。',
   html:'<div class="nocard"><strong>这个问题不在我的知识范围内。</strong><br>'+
    '我的材料只覆盖'+(BRAND.scope||'这个知识库的主题')+'。我不会拿几张沾边的卡片凑一个答案给你。<br><br>'+
    '这类问题交给通用大模型更合适。'+'</div>'+toolsHtml([],false)};
 }
 if(it.kind==='factoid'){
  return {...meta,source:'知识库不含这类信息',plain:'知识卡是原则与判断，不含这类具体操作或事实信息，我不会用沾边的卡片凑答案。',
   html:'<div class="ans">'+intentLine(it,pack.dom)+
    '<div class="nocard" style="border:none;padding:0"><strong>这是一个具体事实 / 操作信息，知识卡里没有。</strong><br>'+
    '这里存的是原则、判断和适用边界，不是操作手册或实时信息。我不会用几张沾边的卡片凑一个答案给你。<br><br>'+
    '这类问题交给通用大模型更合适，也可以把问题改写成一个判断类问题再问我（例如「我该自建工具还是外包」）。</div>'+
    '<div class="modehint" style="margin-top:12px">'+(hasUpgrade?'接入模型后，这类问题也会得到直接回答。':'已接入模型，正在生成回答…')+'</div>'+
    toolsHtml([],hasUpgrade)+'</div>'};
 }
 if(it.kind==='vague'){
  return {...meta,source:'需要澄清',plain:'我先确认一下你想问的是哪一个：'+it.clarify.join(' / '),
   html:'<div class="nocard"><strong>我想先确认你说的具体是哪一种。</strong><br>选一个，或直接把问题写完整，我再去找材料：</div>'+
    '<div class="clarify">'+it.clarify.map(x=>'<button data-fq="'+esc(x)+'">'+esc(x)+' →</button>').join('')+'</div>'};
 }
 if(!picked.length){
  return {...meta,source:'检索模式 · 无可用材料',plain:'知识库里没有能回答这个问题的材料。',
   html:'<div class="ans">'+intentLine(it,pack.dom)+
    '<div class="nocard" style="border:none;padding:0"><strong>知识库里没有能回答这个问题的材料。</strong><br>'+
    '我没有找到与你这个问题真正对得上的判断，所以不推任何卡片。你可以把问题说得更具体，'+
    '或者直接交给大模型——它会用常识作答，知识库这次帮不上忙。</div>'+
    '<div class="modehint" style="margin-top:12px">'+(hasUpgrade?'接入模型后，即使库里没有材料，也能得到针对问题的回答。':'已接入模型，正在生成回答…')+'</div>'+
    toolsHtml([],hasUpgrade)+'</div>'};
 }
 const a=picked[0], c=a.c;
 const scope='<div class="scope"><span>能成立：'+esc(shorten(c.conditions,44))+'</span>'+
  '<span class="no">不适用：'+esc(shorten(c.limits,44))+'</span></div>';
 const localHtml='<div class="ans">'+intentLine(it,pack.dom)+
  '<div class="direct">你在问的是'+esc(it.label)+'。知识库里与它最贴近的一条判断是：<br><br>「'+esc(c.claim)+'」</div>'+
  scope+
  '<div class="modehint">这是<b>材料</b>，不是对你具体情况的结论。当前为检索模式，我只能呈现材料；接入模型后会先理解问题，再用得上哪些材料就用哪些。</div>'+
  refHtml(picked)+toolsHtml(picked,hasUpgrade)+'</div>';
 const plain='【你的问题】'+q+'\n【我理解的类型】'+it.label+'\n\n【知识库中最贴近的一条判断】'+c.claim+
  '\n\n【能成立】'+c.conditions+'\n【不适用】'+c.limits+'\n【出处】'+c.book+'（'+c.id+'）'+
  (hasUpgrade?'\n\n注：当前为检索模式，以上为材料而非针对性结论。':'');
 const follow=[];
 (c.related||[]).slice(0,1).forEach(id=>{const r=DB.find(x=>x.id===id);if(r)follow.push(r.title);});
 const d=TAX.domains.find(x=>x.id===pack.dom);
 if(d)follow.push(...(d.typical_questions||[]).slice(0,1));
 return {...meta,source:hasUpgrade?'检索模式 · 材料呈现':'检索 + 模型',html:localHtml,plain,followups:[...new Set(follow)].slice(0,2)};
}

/* ========== 回答旁笔记（私人数据 · 云端保存 · 不参与问答检索） ========== */
/* 锚点 = 会话 id（rec.id，历史里持久存在）+ '#0'（一次问答一条笔记，编辑即覆盖）。
   笔记自带问题快照，浏览器历史被清空后仍可在「我的笔记」列表里读回。 */
const NOTES=new Map();let notesView=false,notesQuery='';
/* 存储适配：cloud=true 走 /api/notes（AES 加密落 Blob）；false 走 localStorage。
   UX 完全一致，只是本地模式的"云端"换成本机浏览器，导出仍是一份 JSON。 */
const LSP=BRAND.storage_prefix||'sb_';
const localNotes={
  all(){try{const a=JSON.parse(localStorage.getItem(LSP+'notes')||'[]');return Array.isArray(a)?a:[]}catch(e){return []}},
  save(n){
    const a=this.all(),i=a.findIndex(x=>x.conv===n.conv&&(x.idx||0)===(n.idx||0));
    const now=new Date().toISOString();
    const rec={id:i>=0?a[i].id:LSP+'n'+Date.now().toString(36)+Math.random().toString(36).slice(2,6),
      conv:n.conv,idx:n.idx||0,q:n.q||'',body:n.body||'',answer:n.answer||'',src:n.src||'',
      created:i>=0?a[i].created:now,updated:now,rev:i>=0?((a[i].rev||1)+1):1};
    if(i>=0)a[i]=rec;else a.push(rec);
    localStorage.setItem(LSP+'notes',JSON.stringify(a));return rec;},
  del(id){localStorage.setItem(LSP+'notes',JSON.stringify(this.all().filter(x=>x.id!==id)));}
};
function notesReady(){return BRAND.cloud?(!!(cfg&&cfg.passcode)):true;}
/* 笔记视图状态：已展开的卡片 / 是否从笔记跳去回看 / 跳走前的滚动位置 */
const notesOpen=new Set();let noteJump=false,notesScroll=0;
/* 侧栏分组折叠：默认全展开，选择存 localStorage，刷新不丢 */
function loadSec(){try{const s=JSON.parse(localStorage.getItem('sbs_sec')||'{}');return {dom:s.dom!==false,hist:s.hist!==false};}catch(e){return {dom:true,hist:true};}}
let secOpen=loadSec();
function applySections(){
 for(const k of ['dom','hist']){
  const w=$('sec-'+k);if(!w)continue;
  w.classList.toggle('open',!!secOpen[k]);
  const b=w.querySelector('.stoggle');if(b)b.setAttribute('aria-expanded',secOpen[k]?'true':'false');
 }
}
function noteIcon(){return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>';}
function noteKey(m){const conv=(m&&m.recId)||(viewMeta&&viewMeta.id);return conv?conv+'#0':null;}
function noteHtml(m){
 const key=noteKey(m);if(!key)return '';
 const n=NOTES.get(key);
 if(n){return '<div class="noteblk"><div class="nhead"><span class="nmark">'+noteIcon()+'我的笔记</span>'+
  '<span class="ntime">'+esc(fmtTime(new Date(n.updated||n.created).getTime()))+'</span>'+
  '<span class="nops"><button class="nbtn" data-act="nedit">编辑</button><button class="nbtn" data-act="ndel">删除</button></span></div>'+
  '<div class="nbody">'+esc(n.body)+'</div></div>';}
 return '<div class="notebar"><button class="notebtn" data-act="nopen" title="在这条回答旁写笔记，云端保存">'+noteIcon()+'<span>笔记</span></button></div>';
}
function closeNoteEditor(){
 document.querySelectorAll('.nedit').forEach(x=>x.remove());
 /* 编辑时临时隐藏原笔记块，避免「同一段文字出现两遍」 */
 document.querySelectorAll('.noteblk[data-editing="1"]').forEach(x=>{x.style.display='';x.removeAttribute('data-editing');});
 syncNoteComposer();
}
function openNoteEditor(key,host){
 closeNoteEditor();if(!host)return;
 const n=NOTES.get(key);
 const blk=host.querySelector('.noteblk');
 if(blk){blk.dataset.editing='1';blk.style.display='none';}
 const ed=document.createElement('div');ed.className='nedit';ed.dataset.notekey=key;
 const ph=isMobileUI()?'这次回答里，哪一点对你有用？':'这次回答里，哪一点对你有用？（⌘/Ctrl+Enter 保存 · Esc 收起）';
 ed.innerHTML='<textarea rows="2" maxlength="4000" placeholder="'+ph+'"></textarea>'+
  '<div class="nedops"><button class="nbtn ns" data-act="nsave">保存</button><button class="nbtn" data-act="ncancel">取消</button><span class="nerr"></span></div>';
 host.appendChild(ed);
 const ta=ed.querySelector('textarea');ta.value=n?n.body:'';
 ta.focus();ta.setSelectionRange(ta.value.length,ta.value.length);
 ta.addEventListener('keydown',e=>{
  if((e.metaKey||e.ctrlKey)&&e.key==='Enter'){e.preventDefault();ed.querySelector('[data-act="nsave"]').click();}
  else if(e.key==='Escape'){e.preventDefault();closeNoteEditor();}});
 ta.addEventListener('input',function(){this.style.height='auto';this.style.height=Math.min(this.scrollHeight,180)+'px';});
 syncNoteComposer();
}
/* 取这条回答的上下文：当前对话 > 回看视图 > 本地历史；三者都可能不存在。
   只取纯文本回答（≤2400 字）与来源标签，随笔记一起加密落盘——
   换设备/清缓存后也能在「我的笔记」里就地展开当时的问答。 */
function noteContext(conv){
 let m=msgs.find(x=>x.recId===conv);
 if(!m&&viewMeta&&viewMeta.id===conv)m=(viewMsgs||[])[0];
 const h=hist.find(x=>x.id===conv);
 if(!m&&h)m=(h.msgs||[])[0];
 return {q:(h&&h.q)||(m&&m.q)||'',
  answer:String((m&&m.plain)||'').trim().slice(0,2400),
  src:String((m&&m.source)||'').slice(0,60)};
}
async function saveNote(key,ed){
 const ta=ed.querySelector('textarea'),err=ed.querySelector('.nerr'),btn=ed.querySelector('[data-act="nsave"]');
 const body=ta.value.trim();
 if(!body){err.textContent='写点什么再保存';return;}
 if(!notesReady()){err.textContent='需要访问口令：请在右上角「设置」里填写';return;}
 const conv=key.split('#')[0],ctx=noteContext(conv),old=NOTES.get(key);
 /* 已有云端快照优先保留：本机历史被清掉时，编辑笔记不能把问题/回答擦成空白 */
 const q=ctx.q||(old&&old.q)||'',
       answer=ctx.answer||(old&&old.answer)||'',
       src=ctx.src||(old&&old.src)||'';
 btn.disabled=true;btn.textContent='保存中…';err.textContent='';
 try{
  const payload={conv:conv,idx:0,q:q,body:body,answer:answer,src:src};
  let saved;
  if(BRAND.cloud){
   const r=await fetch('api/notes',{method:'POST',headers:{'Content-Type':'application/json','X-SBS-Token':cfg.passcode},
    body:JSON.stringify({note:payload})});
   const j=await r.json().catch(()=>null);
   if(!r.ok||!j||!j.ok)throw new Error((j&&j.error&&j.error.message)||('HTTP '+r.status));
   saved=j.note;
  }else{
   saved=localNotes.save(payload);
  }
  NOTES.set(key,saved);closeNoteEditor();renderMsgs();renderNav();
  toast(BRAND.cloud?'笔记已保存到云端':'笔记已保存到本机');
 }catch(e){
  btn.disabled=false;btn.textContent='保存';
  err.textContent='未保存：'+e.message+'（内容已保留，可直接重试）';
 }
}
async function delNote(key){
 if(!confirm('删除这条笔记？删除后无法恢复。'))return;
 const n=NOTES.get(key);if(!n)return;
 try{
  if(BRAND.cloud){
   const r=await fetch('api/notes?id='+encodeURIComponent(n.id),{method:'DELETE',headers:{'X-SBS-Token':(cfg&&cfg.passcode)||''}});
   const j=await r.json().catch(()=>null);
   if(!r.ok||!j||!j.ok)throw new Error((j&&j.error&&j.error.message)||('HTTP '+r.status));
  }else{
   localNotes.del(n.id);
  }
  NOTES.delete(key);renderMsgs();renderNav();toast('笔记已删除');
 }catch(e){toast('删除失败：'+e.message);}
}
async function loadNotes(){
 if(!BRAND.cloud){
  NOTES.clear();localNotes.all().forEach(n=>{if(n&&n.conv)NOTES.set(n.conv+'#'+(n.idx||0),n);});
  renderNav();return;
 }
 if(!(cfg&&cfg.passcode))return;
 for(let attempt=0;attempt<2;attempt++){
  try{
   const r=await fetch('api/notes',{headers:{'X-SBS-Token':cfg.passcode},signal:AbortSignal.timeout(9000)});
   if(r.status===503){if(attempt===0){await new Promise(s=>setTimeout(s,1200));continue;}return;}
   if(!r.ok)return;
   const j=await r.json().catch(()=>null);
   if(j&&j.ok&&Array.isArray(j.notes)){
    NOTES.clear();
    j.notes.forEach(n=>{if(n&&n.conv)NOTES.set(n.conv+'#'+(n.idx||0),n);});
    renderNav();
    if(!streamingNow&&!notesView){try{renderMsgs();}catch(e){}}
    return;
   }
   return;
  }catch(e){if(attempt===0){await new Promise(s=>setTimeout(s,1200));continue;}}
  /* 两次都失败：静默降级——问答不受影响，仅笔记暂不可见 */
 }
}
function keyById(id){for(const[k,n]of NOTES)if(n.id===id)return k;return null;}
/* 「回到原对话」：只在本地历史确实还在时可用，进入既有「历史回看」视图。
   笔记本身也贴回当年那条回答下面（noteKey 用 viewMeta.id），上下文连续。 */
function jumpToConv(id){
 const n=[...NOTES.values()].find(x=>x.id===id);if(!n)return;
 const h=hist.find(x=>x.id===n.conv),m=msgs.find(x=>x.recId===n.conv);
 if(!h&&!m){toast('本机已无这条对话，可展开查看云端留存的上下文');return;}
 notesScroll=$('scroll')?$('scroll').scrollTop:0;
 notesView=false;noteJump=true;
 viewMeta={id:n.conv,n:(h&&h.n)||null,ts:(h&&h.ts)||Date.now(),q:n.q||''};
 viewMsgs=(h&&h.msgs&&h.msgs.length)?h.msgs:[m||{q:n.q||'',pending:false,
  html:'<div class="nocard">这条记录没有留存回答，只保留了问题。</div>',plain:'',cards:[],source:'历史记录'}];
 renderMsgs();renderNav();
 $('side').classList.remove('on');$('overlay').classList.remove('on');
 if($('scroll'))$('scroll').scrollTop=0;
}
function chevSvg(){return '<svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6l6 6-6 6"/></svg>';}
/* 上下文面板：优先用本机历史的完整回答，其次用随笔记存在云端的快照。
   两者都没有时明确说明，绝不留一个「点了没反应」的假链接。 */
function noteCtxHtml(n){
 const h=hist.find(x=>x.id===n.conv),hm=h&&h.msgs&&h.msgs[0];
 const answer=String((hm&&hm.plain)||n.answer||'').trim();
 const src=(hm&&hm.source)||n.src||'';
 const local=hist.some(x=>x.id===n.conv)||msgs.some(m=>m.recId===n.conv);
 const open=notesOpen.has(n.id);
 return '<div class="nctx" id="nctx-'+esc(n.id)+'" data-nctx="'+esc(n.id)+'"'+(open?'':' hidden')+'>'+
  '<div class="nctxq"><b>原始提问</b>'+esc(n.q||'（问题快照缺失）')+'</div>'+
  (answer
   ? '<div class="nctxlab">当时的回答'+(src?' · '+esc(src):'')+'</div><div class="nctxa md">'+renderMd(answer)+'</div>'
   : '<div class="nctxlab">当时的回答</div><div class="nctxhint">这条笔记写于旧版本，当时未留存回答快照'+(local?'；可点下方「回到原对话」查看完整问答。':'；本机历史也不在，已无法还原当时的回答。')+'</div>')+
  '<div class="nctxfoot">'+
   (local?'<button class="nbtn njump" data-act="njump" data-nid="'+esc(n.id)+'">回到原对话 ↗</button>':
    answer?'<span class="nctxhint">原对话已不在本机（历史仅保留最近 30 条），以上为云端留存的快照</span>':
           '<span class="nctxhint">原对话已不在本机，这条旧笔记也未留存回答快照；若原设备仍有当时的对话，编辑保存一次即可自动补齐。</span>')+
  '</div></div>';
}
function renderNotesBody(){
 const sc=$('scroll'),keepTop=sc?sc.scrollTop:0;
 const list=[...NOTES.values()].sort((a,b)=>String(b.updated||b.created||'').localeCompare(String(a.updated||a.created||'')));
 const q=notesQuery.trim().toLowerCase();
 const hit=q?list.filter(n=>(n.q+' '+n.body+' '+(n.answer||'')+' '+(n.tags||[]).join(' ')).toLowerCase().includes(q)):list;
 let inner;
 if(!list.length){inner='<div class="nempty">还没有笔记。<br>在任意回答的右下角点「笔记」，写下当时的心得——'+
   (BRAND.cloud?'保存到云端，换设备、清缓存都不会丢。':'保存在本机浏览器里，可随时导出备份。')+'</div>'+
  (!notesReady()?'<div class="nempty">查看与写入都需要访问口令：请在右上角「设置」里填写。</div>':'');}
 else if(!hit.length){inner='<div class="nempty">没有匹配「'+esc(notesQuery)+'」的笔记。</div>';}
 else{
  let lastDay='';
  inner=hit.map(n=>{
   const day=String(n.updated||n.created||'').slice(0,10);
   const head=day!==lastDay?'<div class="nday">'+esc(day)+'</div>':'';lastDay=day;
   const open=notesOpen.has(n.id);
   return head+'<div class="ncard" data-ncard="'+esc(n.id)+'">'+
    '<button class="ncq" data-act="nctx" data-nid="'+esc(n.id)+'" aria-expanded="'+(open?'true':'false')+'" aria-controls="nctx-'+esc(n.id)+'">'+
     chevSvg()+'<span class="ncqtext"><span class="nqpre">问：</span>'+esc(n.q||'（问题快照缺失）')+'</span>'+
     '<span class="ncqhint">查看当时的问答</span></button>'+
    noteCtxHtml(n)+
    '<div class="ncb">'+esc(n.body)+'</div>'+
    ((n.tags&&n.tags.length)?'<div class="nct">'+n.tags.map(t=>'<span class="pill">'+esc(t)+'</span>').join(' ')+'</div>':'')+
    '<div class="ncm">'+esc(String(n.updated||n.created||'').slice(11,16))+' · 第 '+(n.rev||1)+' 次编辑'+
    '<span class="nops"><button class="nbtn" data-act="nedit2" data-nid="'+esc(n.id)+'">编辑</button>'+
    '<button class="nbtn" data-act="ndel2" data-nid="'+esc(n.id)+'">删除</button></span></div></div>';
  }).join('');
 }
 $('content').innerHTML='<div class="notesview"><div class="nvtop"><button class="nbtn" data-act="nback">← 返回对话</button>'+
  '<b>我的笔记'+(NOTES.size?' · '+NOTES.size:'')+'</b><span style="flex:1"></span>'+
  '<button class="nbtn" data-act="nexport">导出备份</button></div>'+
  '<input id="nsearch" class="nsearch" placeholder="搜索问题或内容…" value="'+esc(notesQuery)+'">'+
  '<div class="nlist">'+inner+'</div></div>';
 if(sc)sc.scrollTop=keepTop;
 const si=$('nsearch');
 if(si)si.oninput=function(){notesQuery=this.value;renderNotesBody();
  const s2=$('nsearch');if(s2){s2.focus();s2.setSelectionRange(s2.value.length,s2.value.length);}};
 syncNoteComposer();
}
async function exportNotes(){
 if(!notesReady()){toast('导出需要访问口令：请在右上角「设置」里填写');return;}
 try{
  let b;
  if(BRAND.cloud){
   const r=await fetch('api/notes?export=1',{headers:{'X-SBS-Token':cfg.passcode}});
   if(!r.ok)throw new Error('HTTP '+r.status);
   b=await r.blob();
  }else{
   b=new Blob([JSON.stringify({app:BRAND.title,exportedAt:new Date().toISOString(),count:NOTES.size,
     notes:[...NOTES.values()]},null,2)],{type:'application/json'});
  }
  const u=URL.createObjectURL(b),a=document.createElement('a');
  a.href=u;a.download='sbs-notes-'+new Date().toISOString().slice(0,10)+'.json';a.click();
  setTimeout(()=>URL.revokeObjectURL(u),3000);toast('已导出全部笔记（JSON 备份）');
 }catch(e){toast('导出失败：'+e.message);}
}

/* ========== 渲染 ========== */
function heroLines(){
  const h=(BRAND.hero&&BRAND.hero.length===3)?BRAND.hero:[BRAND.short||'你的第二大脑','— 说出你的问题','再翻你的卡片'];
  return h.map(x=>String(x||''));
}
function renderGuide(){
  const gs=GUIDES[guideIdx];
  /* 头图：把品牌主张拆成三行大字，几何构件穿插在字里；纯 CSS/SVG，无外部图片、响应式按 em 缩放 */
  const hero='<div class="hero">'+
   '<div class="hero-kicker"><span class="hero-kdot"></span>'+esc(BRAND.kicker||BRAND.sub||'')+'<span class="hero-kline"></span><span class="hero-kv">'+esc(BRAND.kickv||'')+'</span></div>'+
   '<div class="hero-type">'+
    '<div class="hero-line"><span class="hw">'+esc(heroLines()[0])+'</span>'+
      '<span class="hgo"><svg viewBox="0 0 24 24"><path d="M5 12h13M13 6l6 6-6 6"/></svg></span>'+
      '<span class="htoggle"><i></i><b></b></span></div>'+
    '<div class="hero-line"><span class="hsun"><i></i></span>'+
      '<span class="hw">'+esc(heroLines()[1])+'</span>'+
      '<span class="hpill"><i></i><b></b><i></i></span></div>'+
    '<div class="hero-line"><span class="horbs"><i class="o1"></i><i class="o2"></i>'+
      '<span class="horbicon"><svg class="ic"><use href="#brain"/></svg></span></span>'+
      '<span class="hw">'+esc(heroLines()[2])+'</span></div>'+
    '<svg class="hwire" viewBox="0 0 120 120" preserveAspectRatio="none" aria-hidden="true">'+
      '<path vector-effect="non-scaling-stroke" d="M2 8 H58 Q70 8 70 22 V86 Q70 100 82 100 H116"/>'+
      '<circle cx="2" cy="8" r="3"/><circle cx="116" cy="100" r="3"/></svg>'+
   '</div>'+
   '<p class="hero-sub"><b>'+META.sources+'</b> '+esc(BRAND.source_unit||'份资料')+' 沉淀为 <b>'+DB.length+'</b> 张知识卡。<br>只有真正对得上的，才会进入回答。</p>'+
   '<button class="hero-cta" data-act="gostart">从这些问题开始 <svg viewBox="0 0 24 24"><path d="M12 5v13M5.5 11.5l6.5 6.5 6.5-6.5"/></svg></button>'+
   '<p class="hero-tip">'+esc(BRAND.tip)+'</p>'+
  '</div>';
  return '<div class="welcome">'+hero+
   (!liveCfg()?'<button class="upcard" data-act="openset"><span class="ut"><b>让它真正理解你的问题 →</b>当前只做检索：会先判断问题能否用知识库回答，用不上的不推。接入模型后，知识卡只作为参考来源之一，由模型针对你的问题作答。</span><span class="ua">→</span></button>':'')+
   '<div class="wguide" id="startguide"><h2>从这些问题开始</h2><button class="swap" id="swap">换一批 →</button></div>'+
   '<div class="guides">'+gs.map(g=>'<button class="guide" data-gq="'+esc(g.t)+'"><span class="garrow">→</span>'+
     '<span class="gcode">'+g.d+'</span><span class="gtext">'+esc(g.t)+'</span><span class="gsub">'+esc(g.s)+'</span></button>').join('')+'</div>'+
   '<div class="wnote"><b>说明：</b>'+esc(BRAND.disclaimer)+'</div></div>';
}
/* 兼容升级：改造前保存的历史记录里 #llmout 是转义纯文本，回看时按需转成结构化排版 */
function normalizeHtml(m){
 let h=String(m.html||'');
 if(h.indexOf('class="direct plain"')>=0&&h.indexOf('class="direct plain md"')<0&&m.plain){
  h=h.replace(/<div class="direct plain" id="llmout">[\s\S]*?<\/div>/,
    '<div class="direct plain md" id="llmout">'+renderMd(m.plain)+'</div>');
 }
 return h;
}
function renderMsgs(scroll){
  /* 流式输出期间禁止任何整体重绘：m.html 此时还是"正在思考"骨架，
     一重建就会把已输出的文字清空，表现为回复窗口不断闪回/跳动 */
  if(streamingNow)return;
  if(notesView){renderNotesBody();return;}
  const AM=activeMsgs();
  const bar=viewMeta
    ? '<div class="viewbar"><span>历史回看 · <b>'+(viewMeta.n?('第 '+esc(viewMeta.n)+' 次提问'):'关联的原始问答')+'</b> · '+esc(fmtTime(viewMeta.ts))+'</span>'+
      '<button data-act="backnow">'+(noteJump?'← 返回我的笔记':'返回当前对话 →')+'</button></div>'
    : '';
  if(!AM.length){$('content').innerHTML=bar?('<div class="msgs">'+bar+'</div>'):renderGuide();return;}
  $('content').innerHTML='<div class="msgs">'+bar+AM.map((m,i)=>{
    let h='<div class="msg"><div class="urow"><div class="ububble">'+esc(m.q)+'</div></div></div>';
    h+='<div class="msg"><div class="arow"><div class="avatar"><svg class="ic"><use href="#brain"/></svg></div>'+
      '<div class="abody"><div class="ameta"><span>'+esc(m.source||'本地知识卡检索')+'</span><span>·</span><span>'+
      (m.dom?esc(domName[m.dom]||m.dom):'未限定')+'</span><span>·</span><span>'+
      (m.cards&&m.cards.length?m.cards.length+' 条参考材料':'未采用知识卡')+'</span></div>'+
      (m.pending?'<div class="genline">'+spinSvg()+'<span>正在检索知识卡…</span></div>':'<div data-mi="'+i+'">'+normalizeHtml(m)+'</div>'+(m.pending?'':noteHtml(m)))+
      '</div></div></div>';
    return h;}).join('')+'</div>';
  const sc=$('scroll');
  if(scroll&&sc){pauseChrome(600);sc.scrollTop=sc.scrollHeight;}   /* 只有提新问题时才滚到底 */
  updateScrollDown();
  syncNoteComposer();
}
/* 长回复：内容溢出且用户不在底部时浮出向下按钮；
   生成中显示旋转进度弧，完成后只留淡圆边框 + 箭头，到底自动隐藏 */
function updateScrollDown(){
  const sc=$('scroll'),b=$('scrolldown');if(!sc||!b)return;
  const overflow=sc.scrollHeight-sc.clientHeight>40;
  const atBottom=(sc.scrollHeight-sc.scrollTop-sc.clientHeight)<28;
  if(overflow&&!atBottom){b.classList.add('on');b.classList.toggle('done',!streamingNow);}
  else b.classList.remove('on','done');
}
function renderStats(){
  const src=META.sources||0,nc=DB.length,unit=BRAND.source_unit||'份资料',
        uc=DB.filter(c=>c.type==='user').length,kz=(META.layers||{})['综合']||0;
  $('sstat').innerHTML='<span><b>'+src+'</b> '+esc(unit)+'</span><span><b>'+nc+'</b> 张卡</span><span><b>'+Object.keys(META.domains||{}).length+'</b> 问题域</span>';
  if($('about_books'))$('about_books').textContent=src;
  if($('about_unit'))$('about_unit').textContent=unit;
  if($('about_cards'))$('about_cards').textContent=nc;
  $('aboutstat').innerHTML='<div class="kv"><b>资料</b>'+src+' '+esc(unit)+'</div>'+
   '<div class="kv"><b>知识卡</b>'+nc+' 张（综合卡 '+kz+' 张'+(uc?' · 站内新增 '+uc+' 张':'')+'）</div>'+
   '<div class="kv"><b>向量词表</b>'+(META.vocab_size||0)+' 维</div>'+
   '<div class="kv"><b>建库</b>'+(META.built||'')+'</div>';
  const ae=$('about_asktip');if(ae)ae.textContent=BRAND.ask_tip||'';
  const ce=$('notecnt');if(ce)ce.textContent=NOTES.size?('+'+NOTES.size):'';
  const rc=$('railcnt');if(rc){rc.textContent=NOTES.size?String(NOTES.size):'';rc.style.display=NOTES.size?'':'none';}
}
function renderNav(){
  $('dnav').innerHTML=TAX.domains.map(d=>'<button class="ditem" data-dom="'+d.id+'"><span class="dcode">'+d.id+'</span>'+esc(d.name)+'</button>').join('');
  $('hlist').innerHTML=hist.length?hist.slice(0,12).map((h,i)=>{
    const on=viewMeta&&viewMeta.id===h.id?' on':'';
    return '<button class="hitem'+on+'" data-hist="'+i+'" title="'+esc(h.q)+'">'+
      '<span class="hq">'+esc(h.q)+'</span>'+
      '<span class="hm">#'+esc(h.n||(i+1))+' · '+esc(fmtTime(h.ts))+(h.msgs&&h.msgs.length?'':' · 仅问题')+'</span></button>';
  }).join(''):
    '<div class="hempty">还没有提问记录。<br>每一次提问都会连同回答与参考材料一起保存在这里。</div>';
  renderStats();
  const live=liveCfg();
  $('status').textContent=needPasscode?'代理就绪 · 待口令':live?('已接入 '+cfg.model+(cfg.proxy?' · 代理':'')):'仅检索';
  /* 原来贴在输入框下方占一整行的提示已移除；当前模式只在「设置」里说明 */
  const cs=$('cfg_status');if(cs)cs.textContent=needPasscode
    ? '当前状态：代理已就绪，等待访问口令。模型作答，知识库为参考来源之一。'
    : live?('当前状态：已接入 '+cfg.model+(cfg.proxy?'（服务端代理）':'（浏览器直连）')+' · 模型作答，知识库为参考来源之一。')
          :'当前状态：仅检索 · 只推真正相关的知识卡，不生成针对性回答。';
}
function openDrawer(cards){
  drawerCards=cards;drawerSel=0;
  $('dtabs').innerHTML=cards.map((r,i)=>'<button class="dtab'+(i===0?' on':'')+'" data-di="'+i+'">'+esc(r.c.id)+' · '+esc(r.c.title.slice(0,12))+'</button>').join('');
  renderDrawer();$('drawer').classList.add('on');$('overlay').classList.add('on');
}
function renderDrawer(){
  const r=drawerCards[drawerSel];if(!r)return;const c=r.c;
  $('dbody').innerHTML='<div class="dcard"><div class="dcid">'+esc(c.id)+' · '+esc(c.layer||'')+'</div>'+
   '<div class="dct">'+esc(c.title)+'</div><div class="dcm">'+
   '<span class="badge-s b-'+c.type+'" style="padding:2px 7px;border-radius:5px">'+(tname[c.type]||'')+'</span>'+
   '<span class="pill">'+esc(c.domain_name)+'</span><span class="pill">'+esc(c.category_name)+'</span>'+
   (r.score!=null?'<span class="pill">相关度 '+r.score.toFixed(3)+'</span>':'<span class="pill">随手抽卡</span>')+'</div>'+
   '<div class="dsec"><h5>出处</h5><p>'+esc(c.book)+'</p></div>'+
   '<div class="dsec"><h5>主张</h5><p>'+esc(c.claim)+'</p></div>'+
   '<div class="dsec"><h5>依据</h5><p>'+esc(c.basis)+'</p></div>'+
   '<div class="dsec"><h5>适用条件</h5><p>'+esc(c.conditions)+'</p></div>'+
   '<div class="dsec w"><h5>失效边界 / 反例</h5><p>'+esc(c.limits)+'</p></div>'+
   '<div class="dsec"><h5>'+esc(BRAND.action_label||'可以怎么用')+'</h5><p>'+esc(c.action)+'</p></div>'+
   '<div class="dsec"><h5>标签</h5><p>'+(c.tags||[]).map(t=>'<span class="pill">'+esc(t)+'</span>').join(' ')+'</p></div></div>';
}

/* ========== 发送 ========== */
async function callLLM(q,cards,it,onDelta){
  if(!cfg||!cfg.base||!cfg.model)return null;
  if(!cfg.proxy&&!cfg.key)return null;
  const h={'Content-Type':'application/json'};
  if(!cfg.proxy)h['Authorization']='Bearer '+cfg.key;
  else if(cfg.passcode)h['X-SBS-Token']=cfg.passcode;
  const payload={model:cfg.model,temperature:.25,stream:!!onDelta,messages:[
    {role:'system',content:(BRAND.persona||'你是一位严谨、克制的知识顾问')+'。先理解并直接回答用户的问题；知识卡只是参考来源之一，用不上的不要提。回答要具体、克制、可执行，不写客套话。只输出给用户看的话——不要出现卡片编号、出处、书名或类别名，也不要写「根据知识卡」「如 K019 所示」这类措辞，来源由界面单独呈现。输出格式：先给结论段，再用 ## 小标题分点与 1./- 列表，关键判断用 **加粗**；标题最多一层、列表每项一句话、整体不超过 400 字；不要用表格、代码块、HTML、emoji、脚注或多级标题。'},
    {role:'user',content:buildPrompt(q,cards,it)}]};
  const r=await fetch(cfg.base.replace(/\/$/,'')+'/chat/completions',{method:'POST',headers:h,body:JSON.stringify(payload)});
  if(!r.ok){let msg='HTTP '+r.status;try{const e=await r.json();if(e&&e.error)msg=e.error.message||msg;}catch(x){}
    throw new Error(msg);}
  const ct=r.headers.get('content-type')||'';
  if(onDelta&&ct.indexOf('text/event-stream')>=0&&r.body){
    const reader=r.body.getReader(),dec=new TextDecoder();
    let buf='',full='';
    while(true){const {done,value}=await reader.read();if(done)break;
      buf+=dec.decode(value,{stream:true});
      const lines=buf.split('\n');buf=lines.pop();
      for(const line of lines){
        if(line.indexOf('data:')!==0)continue;
        const d=line.slice(5).trim();if(!d||d==='[DONE]')continue;
        try{const j=JSON.parse(d);const c=(j.choices&&j.choices[0]&&j.choices[0].delta&&j.choices[0].delta.content)||'';
          if(c){full+=c;onDelta(c,full);}}catch(x){}
      }}
    return full;
  }
  const j=await r.json();
  const txt=(j.choices&&j.choices[0]&&j.choices[0].message&&j.choices[0].message.content)||null;
  if(txt&&onDelta)onDelta(txt,txt);
  return txt;
}
async function send(q){
  q=(q||'').trim();if(!q||busy)return;
  if(needLock())return;
  if(viewMsgs)exitView();
  busy=true;$('send').disabled=true;

  /* 检索是同步的（毫秒级），所以一次性把消息算完整再渲染。
     整个流程只做一次整体重绘；之后流式只替换 #llmout 的内部子节点，外层 DOM 不重建。 */
  const it=parseIntent(q,lastQ);
  const special=['greet','meta','offtopic','factoid','vague'].includes(it.kind);
  const pack=special?{picked:[],pool:[],rt:{},dom:null,lead:0,cut:0}:retrieve(q,it,lastDomain);
  if(!special)lastDomain=pack.dom;
  const built=compose(q,pack,it);
  const useLLM=!!(cfg&&cfg.base&&cfg.model&&(cfg.key||cfg.proxy)&&built.useLLM);
  const m={q,pending:false,cards:pack.picked,prompt:built.prompt,dom:pack.dom,intent:it,
    localHtml:built.html,localPlain:built.plain,plain:built.plain,
    source:useLLM?('生成中 · '+cfg.model):built.source,
    html:useLLM?llmHtml('',pack.picked,true):built.html};
  msgs.push(m);
  const idx=msgs.length-1;
  /* 笔记锚点先建好：这样回答一渲染出来，「笔记」按钮就在（而不是等流式结束后） */
  const rec={id:'h'+Date.now()+Math.random().toString(36).slice(2,6),q,ts:Date.now(),n:nextN(),
    msgs:[Object.assign(snap(m),{html:built.html,plain:built.plain,source:built.source})]};
  m.recId=rec.id;
  renderMsgs(true);

  /* 快照先存检索态：万一中途刷新或生成失败，历史里仍有可读内容 */
  hist=[rec,...hist].slice(0,30);saveHist();renderNav();lastQ=q;

  if(useLLM){
    streamingNow=true;
    const box=document.querySelector('[data-mi="'+idx+'"]');
    const out=box?box.querySelector('#llmout'):null;
    const abody=box?box.parentElement:null;
    const sc=$('scroll');
    let needRebuild=false,finalText=null;

    /* 把回答框顶部对齐到视口上方，长回复从「第一屏」开始读；
       之后生成全程不再自动滚动，未读内容由底部向下按钮提示 */
    if(box&&sc){
      const y=box.getBoundingClientRect().top-sc.getBoundingClientRect().top+sc.scrollTop;
      sc.scrollTop=Math.max(0,y-14);
    }
    updateScrollDown();

    try{
      const txt=await callLLM(q,pack.picked,it,function(delta,full){
        if(!out)return;
        if(out.dataset.started!=='1'){
          out.dataset.started='1';
          out.classList.add('streaming','md');
          const g=abody?abody.querySelector('.genline'):null;if(g)g.remove();
        }
        /* 每个 chunk 都按当前累积文本渲染成结构化样式；
           只替换内部子节点，#llmout 元素本身、滚动位置与外层 DOM 均不变 */
        out.innerHTML=renderMd(mdStreamClean(full||delta));
        updateScrollDown();
      });
      if(txt){
        finalText=txt;
        m.plain=txt;m.source=cfg.model+' · 知识库为参考来源之一';
        m.html=llmHtml(txt,pack.picked,false);   /* 只更新字符串供历史/回看，不碰 DOM */
      }else{
        m.html=m.localHtml;m.plain=m.localPlain;m.source='检索模式 · 模型无返回';needRebuild=true;
      }
    }catch(e){
      m.html=m.localHtml;m.plain=m.localPlain;m.source='检索模式 · 模型不可用';needRebuild=true;
      toast('模型接口不可用：'+(e&&e.message?e.message:'')+'（已回退检索模式）');
    }

    streamingNow=false;
    if(needRebuild)renderMsgs(false);
    else if(out){
      /* 轻量收尾：不重建外层 DOM、不滚动；用最终文本再渲染一次做校准（流式期间已是结构化） */
      out.classList.remove('streaming');
      const g=abody?abody.querySelector('.genline'):null;if(g)g.remove();
      const am=abody?abody.querySelector('.ameta span'):null;if(am)am.textContent=m.source;
      if(finalText){out.innerHTML=renderMd(finalText);out.classList.add('md');}   /* 最终校准：样式与流式期间一致，无突变 */
    }
    updateScrollDown();   /* streamingNow 已归零 → 进度弧消失，只留向下箭头 */
  }
  rec.msgs[0]=snap(m);saveHist();renderNav();
  busy=false;$('send').disabled=false;$('q').value='';$('q').style.height='auto';
}
function newChat(){if(msgs.length&&!confirm('开始新对话？左侧的历史提问会完整保留。'))return;
  msgs=[];lastDomain=null;lastQ=null;exitView();$('side').classList.remove('on');$('overlay').classList.remove('on');}

/* ========== 移动端：侧滑关闭 / 沉浸式头部 / 笔记编辑时收起输入框 ========== */
const MOBILE_MQ=window.matchMedia?window.matchMedia('(max-width:900px)'):{matches:false};
function isMobileUI(){return !!MOBILE_MQ.matches;}
/* 桌面端侧栏收起为图标导轨；移动端仍是抽屉，不参与收起 */
function setSideCollapsed(v){
 const collapsed=!!v&&!isMobileUI();
 document.querySelector('.app').classList.toggle('side-collapsed',collapsed);
 try{localStorage.setItem('sbs_side_collapsed',collapsed?'1':'0');}catch(e){}
 const b=$('sidetoggle');
 if(b){const t=collapsed?'展开侧栏':'收起侧栏';b.title=t;b.setAttribute('aria-label',t);}
 syncChromeHeights();
}
function toggleSideCollapsed(){
 if(isMobileUI()){$('side').classList.toggle('on');$('overlay').classList.toggle('on');return;}
 setSideCollapsed(!document.querySelector('.app').classList.contains('side-collapsed'));
}
let lastCompH=72,noteEditingActive=false,chromeHidden=false,lastScrollY=0,chromePauseUntil=0,chromeSettleUntil=0;
function syncChromeHeights(){
 const t=document.querySelector('.top'),c=document.querySelector('.composer');
 if(t)document.documentElement.style.setProperty('--top-h',t.offsetHeight+'px');
 /* 输入框被 display:none 时取上一次实测值，避免把 --comp-h 写成 0 */
 if(c&&c.offsetHeight>0)lastCompH=c.offsetHeight;
 document.documentElement.style.setProperty('--comp-h',lastCompH+'px');
}
function setChrome(hidden){
 if(!isMobileUI())hidden=false;
 if(hidden===chromeHidden)return;
 chromeHidden=hidden;syncChromeHeights();
 const t=document.querySelector('.top'),c=document.querySelector('.composer');
 if(t)t.classList.toggle('chrome-hide',hidden);
 if(c)c.classList.toggle('chrome-hide',hidden);
 /* 负 margin 过渡（.3s）会改变 scrollHeight：在底部附近浏览器会钳制 scrollTop 并
    发出方向相反的滚动事件，若参与方向判定会立刻反转状态 → 抖动循环。过渡期内只更新基准。 */
 chromeSettleUntil=Date.now()+380;
}
function pauseChrome(ms){chromePauseUntil=Date.now()+(ms||500);}
function onChromeScroll(){
 if(!isMobileUI())return;
 const sc=$('scroll');if(!sc)return;
 const y=sc.scrollTop,dy=y-lastScrollY;lastScrollY=y;
 if(Date.now()<chromePauseUntil)return;                    /* 程序化滚动不触发 */
 if(busy||streamingNow||document.activeElement===$('q')){setChrome(false);return;}  /* 提问/生成/输入中保持可见 */
 if(y<=8||(sc.scrollHeight-sc.clientHeight)<120){setChrome(false);return;}
 /* 已在底部附近：收起看不到更多内容，只会让 scrollTop 被钳制上下弹跳 → 保持显示 */
 if((sc.scrollHeight-sc.clientHeight)-y<140){setChrome(false);return;}
 if(Date.now()<chromeSettleUntil)return;                   /* 状态切换后的过渡期不判定方向 */
 if(Math.abs(dy)<3)return;
 setChrome(dy>0);   /* 手指向上滑（内容上移）→ 收起；向下滑 → 显示 */
}
function syncNoteComposer(){
 const c=document.querySelector('.composer');if(!c)return;
 const editing=isMobileUI()&&!!document.querySelector('.nedit');
 const wasEditing=noteEditingActive;noteEditingActive=editing;
 c.classList.toggle('note-editing',editing);
 if(editing){const q=$('q');if(q&&document.activeElement===q)q.blur();}
 else if(wasEditing)setChrome(false);   /* 保存/取消后完整恢复，别把输入框留在收起态 */
 syncChromeHeights();
}
/* 跟手侧滑关闭：先锁定轴向，纵向滚动完全不受影响；松手按阈值关闭或回弹 */
function bindSwipeClose(el,dir,closeFn,opts){
 if(!el)return;
 const o=opts||{};let x0=0,y0=0,dx=0,axis='',active=false;
 el.addEventListener('touchstart',e=>{
  if(e.touches.length!==1||!el.classList.contains('on'))return;
  if(o.mobileOnly&&!isMobileUI())return;
  if(o.ignore&&e.target.closest&&e.target.closest(o.ignore))return;
  x0=e.touches[0].clientX;y0=e.touches[0].clientY;dx=0;axis='';active=true;
 },{passive:true});
 el.addEventListener('touchmove',e=>{
  if(!active||e.touches.length!==1)return;
  dx=e.touches[0].clientX-x0;
  const dy=e.touches[0].clientY-y0;
  if(!axis&&(Math.abs(dx)>8||Math.abs(dy)>8))axis=Math.abs(dx)>Math.abs(dy)*1.2?'x':'y';
  if(axis!=='x')return;
  el.style.transition='none';
  const d=dir==='left'?Math.min(0,dx):Math.max(0,dx);
  el.style.transform='translateX('+d+'px)';
 },{passive:true});
 function finish(cancel){
  if(!active)return;active=false;
  el.style.transition='';
  const d=dir==='left'?Math.min(0,dx):Math.max(0,dx);
  const threshold=Math.max(56,Math.min(120,el.clientWidth*0.22));
  if(!cancel&&axis==='x'&&Math.abs(d)>threshold)closeFn();
  void el.offsetHeight;          /* 让浏览器以「当前跟手位置」为动画起点 */
  el.style.transform='';
 }
 el.addEventListener('touchend',()=>finish(false),{passive:true});
 el.addEventListener('touchcancel',()=>finish(true),{passive:true});
}

/* ========== 事件 ========== */
$('scrolldown').onclick=()=>{
  const sc=$('scroll');if(!sc)return;
  pauseChrome(600);setChrome(false);
  const target=Math.max(0,sc.scrollHeight-sc.clientHeight),dist=target-sc.scrollTop;
  /* 超长回复直接跳到底；几百像素内才用平滑，避免长时间动画中用户操作被覆盖 */
  if(dist>1500)sc.scrollTop=target;
  else sc.scrollTo({top:target,behavior:'smooth'});
  updateScrollDown();
};
$('scroll').addEventListener('scroll',updateScrollDown,{passive:true});
$('scroll').addEventListener('scroll',onChromeScroll,{passive:true});
window.addEventListener('resize',()=>{syncChromeHeights();syncNoteComposer();});
if(MOBILE_MQ.addEventListener)MOBILE_MQ.addEventListener('change',()=>{
  setSideCollapsed(localStorage.getItem('sbs_side_collapsed')==='1');
  setChrome(false);syncChromeHeights();syncNoteComposer();
});
window.addEventListener('orientationchange',()=>{syncChromeHeights();setChrome(false);});
$('send').onclick=()=>send($('q').value);
$('q').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();send($('q').value);}});
$('q').addEventListener('input',function(){this.style.height='auto';this.style.height=Math.min(this.scrollHeight,140)+'px';syncChromeHeights();});
$('q').addEventListener('focus',()=>setChrome(false));
$('content').onclick=e=>{
  const g=e.target.closest('[data-gq]');if(g){send(g.dataset.gq);return;}
  const f=e.target.closest('[data-fq]');if(f){send(f.dataset.fq);return;}
  const sw=e.target.closest('#swap');if(sw){guideIdx=(guideIdx+1)%GUIDES.length;renderMsgs();return;}
  const rf=e.target.closest('[data-ref]');if(rf){const AM=activeMsgs(),m=AM[AM.length-1];if(!m)return;
    const idx=(m.cards||[]).findIndex(r=>r.c.id===rf.dataset.ref);
    if(idx>=0){openDrawer(m.cards);drawerSel=idx;renderDrawer();
      document.querySelectorAll('.dtab').forEach((t,k)=>t.classList.toggle('on',k===idx));}return;}
  const act=e.target.closest('[data-act]');if(!act)return;
  if(act.dataset.act==='gostart'){const sg=$('startguide');if(sg)sg.scrollIntoView({behavior:'smooth',block:'start'});return;}
  if(act.dataset.act==='backnow'){
   /* 从「我的笔记」跳来 → 原路返回笔记列表，并还原展开状态与滚动位置 */
   if(noteJump){
    noteJump=false;viewMsgs=null;viewMeta=null;notesView=true;
    renderMsgs();renderNav();
    if($('scroll'))$('scroll').scrollTop=notesScroll;
   }else exitView();
   return;
  }
  if(act.dataset.act==='openset'){openSet();return;}
  /* --- 笔记 --- */
  const A=act.dataset.act;
  if(A==='nback'){exitView();return;}
  if(A==='nexport'){exportNotes();return;}
  /* 就地展开：只切换这一张卡，不重建整个列表（不丢滚动、不打断搜索框输入） */
  if(A==='nctx'){
   const id=act.dataset.nid,panel=document.getElementById('nctx-'+id);
   if(panel){
    const wasOpen=!panel.hidden;
    panel.hidden=wasOpen;
    act.setAttribute('aria-expanded',wasOpen?'false':'true');
    if(wasOpen)notesOpen.delete(id);else notesOpen.add(id);
   }
   return;
  }
  if(A==='njump'){jumpToConv(act.dataset.nid);return;}
  if(A==='nsave'){const ed=act.closest('.nedit');if(ed)saveNote(ed.dataset.notekey,ed);return;}
  if(A==='ncancel'){closeNoteEditor();return;}
  if(A==='nedit2'){const key=keyById(act.dataset.nid);if(key)openNoteEditor(key,act.closest('.ncard'));return;}
  if(A==='ndel2'){const key=keyById(act.dataset.nid);if(key)delNote(key);return;}
  if(A==='nopen'||A==='nedit'||A==='ndel'){
    const AM=activeMsgs(),miEl=act.closest('[data-mi]');
    const mi=miEl?+miEl.dataset.mi:AM.length-1,m=AM[mi];
    const key=m&&noteKey(m);
    if(!key)return;
    if(A==='ndel'){delNote(key);return;}
    openNoteEditor(key,act.closest('.abody'));return;
  }
  const mi=act.closest('[data-mi]');const AM=activeMsgs();const m=AM.length?AM[mi?+mi.dataset.mi:AM.length-1]:null;
  if(!m)return;
  if(act.dataset.act==='copyans')copy(toPlain(m.plain||''));   /* 粘出去是去掉 Markdown 标记的干净纯文本 */
};
$('dnav').onclick=e=>{const b=e.target.closest('[data-dom]');if(!b)return;
  const d=TAX.domains.find(x=>x.id===b.dataset.dom);if(!d)return;
  $('q').value=d.typical_questions[0];$('q').focus();$('side').classList.remove('on');};
/* 点击历史 = 回看当时的那一次问答，绝不重新发问、也不写进当前对话 */
$('hlist').onclick=e=>{
  const b=e.target.closest('[data-hist]');if(!b)return;
  const h=hist[+b.dataset.hist];if(!h)return;
  noteJump=false;notesView=false;
  viewMeta={id:h.id,n:h.n||(+b.dataset.hist+1),ts:h.ts,q:h.q};
  viewMsgs=(h.msgs&&h.msgs.length)?h.msgs:[{q:h.q,pending:false,
    html:'<div class="nocard">这条是旧版本留下的记录，当时只保存了问题、没有留存回答。<br>从现在起，每一次提问都会连同回答与参考材料一起完整保存。</div>',
    plain:'',cards:[],source:'历史记录',dom:null,localHtml:'',localPlain:'',prompt:''}];
  renderMsgs();renderNav();
  $('side').classList.remove('on');$('overlay').classList.remove('on');
  const sc=$('scroll');if(sc)sc.scrollTop=0;
};
$('hexport').onclick=downloadHist;
$('himport').onclick=()=>$('hfile').click();
$('hfile').onchange=e=>{
  const f=e.target.files&&e.target.files[0];if(!f)return;
  if(f.size>10*1024*1024){toast('文件超过 10 MB，可能不是历史文件');e.target.value='';return;}
  const rd=new FileReader();
  rd.onload=()=>{
    const r=importText(String(rd.result||''));
    if(!r.ok)toast(r.msg);
    else{if(viewMsgs)exitView();else renderNav();toast('已导入 '+r.added+' 条，共 '+r.total+' 条');}
    e.target.value='';
  };
  rd.onerror=()=>{toast('文件读取失败');e.target.value='';};
  rd.readAsText(f);
};
$('newchat').onclick=newChat;
$('hamb').onclick=()=>{$('side').classList.add('on');$('overlay').classList.add('on');};
$('sidetoggle').onclick=toggleSideCollapsed;
$('railexpand').onclick=()=>setSideCollapsed(false);
$('railnew').onclick=newChat;
$('raildom').onclick=()=>{setSideCollapsed(false);secOpen.dom=true;applySections();
  try{localStorage.setItem('sbs_sec',JSON.stringify(secOpen));}catch(e){}};
$('railhist').onclick=()=>{setSideCollapsed(false);secOpen.hist=true;applySections();
  try{localStorage.setItem('sbs_sec',JSON.stringify(secOpen));}catch(e){}};
$('railadd').onclick=()=>$('openadd').click();
$('railmap').onclick=()=>$('openmap').click();
$('railnotes').onclick=()=>$('opennotes').click();
$('overlay').onclick=()=>{$('side').classList.remove('on');$('drawer').classList.remove('on');
  $('setmodal').classList.remove('on');$('aboutmodal').classList.remove('on');$('addmodal').classList.remove('on');$('overlay').classList.remove('on');};
$('dclose').onclick=()=>{$('drawer').classList.remove('on');$('overlay').classList.remove('on');};
/* 移动端手势：侧栏左划收起、参考卡抽屉右划收起 */
bindSwipeClose($('side'),'left',()=>{$('side').classList.remove('on');$('overlay').classList.remove('on');},{mobileOnly:true});
bindSwipeClose($('drawer'),'right',()=>{$('drawer').classList.remove('on');$('overlay').classList.remove('on');},{ignore:'.dtabs'});
$('dtabs').onclick=e=>{const b=e.target.closest('[data-di]');if(!b)return;drawerSel=+b.dataset.di;
  document.querySelectorAll('.dtab').forEach((t,k)=>t.classList.toggle('on',k===drawerSel));renderDrawer();};
const PRESETS={deepseek:{base:'https://api.deepseek.com/v1',model:'deepseek-chat'},
 moonshot:{base:'https://api.moonshot.cn/v1',model:'moonshot-v1-8k'},
 zhipu:{base:'https://open.bigmodel.cn/api/paas/v4',model:'glm-4-flash'},
 dashscope:{base:'https://dashscope.aliyuncs.com/compatible-mode/v1',model:'qwen-plus'},
 openai:{base:'https://api.openai.com/v1',model:'gpt-4o-mini'},custom:{base:'',model:''}};
$('cfg_preset').onchange=function(){const p=PRESETS[this.value];if(!p)return;
  $('cfg_base').value=p.base;$('cfg_model').value=p.model;};
$('cfg_mode').onchange=function(){$('cfg_warn').style.display=this.value==='proxy'?'block':'none';};
function openSet(){$('cfg_base').value=cfg?cfg.base||'':'';$('cfg_model').value=cfg?cfg.model||'':'';$('cfg_key').value=cfg?cfg.key||'':'';
  let mv='direct';
  if(cfg)mv=cfg.proxy?'proxy':'direct';
  else{try{if(localStorage.getItem('sbs_off')==='1')mv='none';}catch(e){}}
  $('cfg_mode').value=mv;
  $('cfg_pass').value=cfg?(cfg.passcode||''):'';
  $('cfg_warn').style.display=(mv==='proxy'||needPasscode)?'block':'none';
  $('cfg_preset').value='';$('setmodal').classList.add('on');$('overlay').classList.add('on');$('side').classList.remove('on');}
$('about_set').onclick=()=>{$('aboutmodal').classList.remove('on');openSet();};
$('cfg_cancel').onclick=()=>{$('setmodal').classList.remove('on');$('overlay').classList.remove('on');};
$('cfg_clear').onclick=()=>{cfg=null;needPasscode=false;
  try{localStorage.removeItem('sbs_llm');localStorage.removeItem('sbs_off');}catch(e){}
  renderNav();renderMsgs();applyLock();$('setmodal').classList.remove('on');$('overlay').classList.remove('on');
  toast('已清除配置');autoDetect();};
$('cfg_save').onclick=()=>{
  const mode=$('cfg_mode').value;
  const base=$('cfg_base').value.trim(),model=$('cfg_model').value.trim(),key=$('cfg_key').value.trim();
  const passcode=$('cfg_pass').value.trim();
  if(mode==='none'){
    cfg=null;needPasscode=false;
    try{localStorage.setItem('sbs_off','1');localStorage.removeItem('sbs_llm');}catch(e){}
    applyLock();renderNav();renderMsgs();$('setmodal').classList.remove('on');$('overlay').classList.remove('on');
    toast('已切换为纯本地检索');return;
  }
  const proxy=mode==='proxy';
  const complete=proxy?(base&&model):(base&&model&&key);
  cfg=complete?{base,model,key:proxy?'':key,proxy:proxy,passcode:passcode}:null;
  try{cfg?localStorage.setItem('sbs_llm',JSON.stringify(cfg)):localStorage.removeItem('sbs_llm');
       localStorage.removeItem('sbs_off');}catch(e){}
  applyLock();renderNav();renderMsgs();$('setmodal').classList.remove('on');$('overlay').classList.remove('on');
  if(!cfg)toast('未填完整，仍使用检索模式');
  else if(proxy&&!passcode)toast('已接入（代理模式）· 未设访问口令：拿到这个地址的人都能用你的额度');
  else toast(proxy?'已接入（代理模式，Key 不在浏览器）':'已接入 '+model);};
/* 访问口令：子域名公开时防止他人消耗额度 */
let needPasscode=false;
function liveCfg(){return !!(cfg&&cfg.base&&cfg.model&&(cfg.key||cfg.proxy));}
function sessionGet(k){try{return sessionStorage.getItem(k);}catch(e){return null;}}
function sessionSet(k,v){try{sessionStorage.setItem(k,v);return true;}catch(e){return false;}}
function needLock(){
  if(sessionGet('sbs_unlocked')==='1')return false;
  if(needPasscode)return true;
  return !!(cfg&&cfg.passcode);
}
function applyLock(){
  try{
    $('lock').classList.toggle('on',needLock());
    const t=$('locktitle'),s=$('locksub');
    if(t)t.textContent='需要访问口令';
    if(s)s.textContent=needPasscode?'这个代理要求口令才能调用模型。填一次就会记住。':'这个第二大脑是私有的。输入口令进入。';
  }catch(e){}
}
$('lockgo').onclick=()=>{
  const v=$('lockin').value;
  if(needPasscode){
    if(!v){$('lockerr').textContent='请输入口令';return;}
    if(cfg){cfg.passcode=v;try{localStorage.setItem('sbs_llm',JSON.stringify(cfg));}catch(e){}}
    sessionSet('sbs_unlocked','1');needPasscode=false;
    applyLock();renderNav();$('lockin').value='';$('lockerr').textContent='';
    toast('口令已记住，问吧');
    return;
  }
  if(v===(cfg?cfg.passcode:'')){sessionSet('sbs_unlocked','1');applyLock();$('lockin').value='';}
  else{$('lockerr').textContent='口令不对';}
};
$('lockin').addEventListener('keydown',e=>{if(e.key==='Enter')$('lockgo').click();});
/* 自动发现同域代理：Key 在服务端，页面不该要求用户手填地址或密钥 */
async function autoDetect(){
  const probe=document.documentElement;
  try{
    probe.dataset.probe='start';
    try{if(localStorage.getItem('sbs_off')==='1'){probe.dataset.probe='turned-off';return;}}catch(e){}
    if(!/^https?:$/.test(location.protocol)){probe.dataset.probe='no-http';return;}
    const base=location.origin+'/v1';
    probe.dataset.probe='fetch '+base;
    const r=await fetch(base+'/health',{headers:{'Accept':'application/json'},cache:'no-store'});
    probe.dataset.probe='http '+r.status;
    if(!r.ok)return;
    const j=await r.json();
    probe.dataset.probe='json '+JSON.stringify(j).slice(0,90);
    if(!j||!j.ok||!j.keyConfigured)return;
    if(!cfg||!cfg.proxy||!cfg.base){
      cfg={base:base,model:'deepseek-chat',key:'',proxy:true,passcode:(cfg&&cfg.passcode)||''};
      try{localStorage.setItem('sbs_llm',JSON.stringify(cfg));}catch(e){}
    }
    if(j.tokenRequired&&!(cfg&&cfg.passcode))needPasscode=true;
    probe.dataset.probe='ready';
    renderNav();renderMsgs();applyLock();
  }catch(e){try{probe.dataset.probe='err '+(e&&e.message?e.message:e);}catch(x){}}
}
function openAbout(){$('aboutmodal').classList.add('on');$('overlay').classList.add('on');$('side').classList.remove('on');}
$('brandbtn').onclick=openAbout;
$('brandbtn').onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();openAbout();}};
$('sideclose').onclick=function(e){e.stopPropagation();$('side').classList.remove('on');$('overlay').classList.remove('on');};
$('railbrand').onclick=openAbout;
$('about_close').onclick=()=>{$('aboutmodal').classList.remove('on');$('overlay').classList.remove('on');};

/* ========== ＋ 新增知识（AI 整理 + 预览，未确认不写入） ==========
   本地模式直接用你自己配置的模型整理，不依赖任何服务端 */
async function llmOnce(system,user){
  if(!(cfg&&cfg.base&&cfg.model&&(cfg.key||cfg.proxy)))throw new Error('未接入模型：先在「设置」里填写 Base URL / 模型 / Key');
  const h={'Content-Type':'application/json'};
  if(!cfg.proxy)h['Authorization']='Bearer '+cfg.key;
  else if(cfg.passcode)h['X-SBS-Token']=cfg.passcode;
  const r=await fetch(cfg.base.replace(/\/$/,'')+'/chat/completions',{method:'POST',headers:h,
    body:JSON.stringify({model:cfg.model,temperature:.2,stream:false,messages:[
      {role:'system',content:system},{role:'user',content:user}]})});
  if(!r.ok){let m='HTTP '+r.status;try{const e=await r.json();if(e&&e.error)m=e.error.message||m;}catch(x){}throw new Error(m);}
  const j=await r.json();
  const t=(j.choices&&j.choices[0]&&j.choices[0].message&&j.choices[0].message.content)||'';
  if(!t)throw new Error('模型没有返回内容');
  return t;
}
async function localIngest(content,source,kind){
  const doms=TAX.domains.map(d=>d.id+' = '+d.name).join('\n');
  const types=(TAX.card_types||[{id:'D',name:'决策规则'}]).map(t=>t.id+' = '+t.name).join(' / ');
  const sys='你是知识工程师。把用户给的材料整理成一张"原子知识卡"：一张卡只讲一个可判断、可反驳的主张。只输出 JSON，不要解释，不要 Markdown 代码块。';
  const usr='材料：\n'+content+'\n\n出处：'+source+'\n性质：'+(kind==='personal'?'个人原创思考':'外部知识')+
    '\n\n输出 JSON：{"title":"一句话标题（≤40 字）","claim":"可复用的判断（一句话）","basis":"依据 / 关键概念",'+
    '"conditions":"适用条件（什么情况下成立）","limits":"失效边界或反例","action":"可以怎么用（一个具体动作）",'+
    '"tags":["3~6 个检索标签"],"type":"'+types+' 之一","domain_id":"'+doms+' 之一"}'+
    '\n规则：不确定的不写，不编造数据、页码、引文；limits 必须是真实边界，不要写"视情况而定"。';
  const txt=await llmOnce(sys,usr);
  let card;
  try{card=JSON.parse(String(txt).replace(/^```(?:json)?/i,'').replace(/```$/,'').trim());}
  catch(e){throw new Error('模型返回的不是合法 JSON，请重试或换一个模型');}
  if(!card||!card.claim)throw new Error('模型没有给出可用的主张，请补充材料后重试');
  card.title=String(card.title||card.claim).slice(0,80);
  card.tags=Array.isArray(card.tags)?card.tags.slice(0,6):String(card.tags||'').split(/[、,，]/).filter(Boolean).slice(0,6);
  card.kind=kind;
  const dom=TAX.domains.find(d=>d.id===card.domain_id)||TAX.domains[0]||{id:'',name:''};
  card.domain_id=dom.id;card.domain_name=dom.name;
  const cat=(TAX.categories||[]).find(c=>c.id===card.category_id)||(TAX.categories||[])[0]||{id:'',name:''};
  card.category_id=cat.id;card.category_name=cat.name;
  const dup=DB.filter(c=>sim(c.title+' '+c.claim,card.title+' '+card.claim)>=.62).slice(0,2)
    .map(c=>({id:c.id,title:c.title,relation:'相似',reason:'主张重合度较高，建议合并或写成补充条目'}));
  return {ok:true,card,similar:dup};
}
/* ========== ＋ 新增知识（Phase 1：AI 整理 + 预览，未确认不写入） ========== */
let addResult=null;
function addErr(msg){const e=$('add_err');if(!msg){e.style.display='none';e.textContent='';return;}e.style.display='block';e.textContent=msg;}
function openAdd(){addResult=null;addErr('');$('add_content').value='';$('add_source').value='';$('add_kind').value='external';
  $('add_step1').style.display='block';$('add_step2').style.display='none';
  $('addmodal').classList.add('on');$('overlay').classList.add('on');$('side').classList.remove('on');
  setTimeout(()=>$('add_content').focus(),60);}
function closeAdd(){$('addmodal').classList.remove('on');$('overlay').classList.remove('on');}
$('openadd').onclick=openAdd;
$('add_cancel').onclick=closeAdd;
$('add_ai').onclick=async()=>{
  const content=$('add_content').value.trim(), source=$('add_source').value.trim(), kind=$('add_kind').value;
  if(content.length<30){addErr('内容太短（至少 30 字）——只放得下观点的话，AI 没有足够的依据整理出可靠卡片。');return;}
  if(content.length>8000){addErr('内容超过 8000 字，请先精简为要入库的核心部分。');return;}
  if(!source){addErr('请填写知识来源（书籍 / 作者 / 文章 / 个人经验）。来源是防编造的关键字段。');return;}
  addErr('');const btn=$('add_ai');btn.disabled=true;btn.textContent='AI 整理中…';
  try{
    let j;
    if(BRAND.cloud){
      const headers={'Content-Type':'application/json'};
      if(cfg&&cfg.passcode)headers['X-SBS-Token']=cfg.passcode;
      const r=await fetch('api/ingest',{method:'POST',headers,body:JSON.stringify({content,source,kind})});
      j=await r.json().catch(()=>null);
      if(!r.ok||!j||!j.ok)throw new Error((j&&j.error&&j.error.message)||('HTTP '+r.status));
    }else{
      j=await localIngest(content,source,kind);
    }
    addResult=j.card;renderAddPreview(j);
  }catch(e){
    const hint=BRAND.cloud?'（服务端模型未就绪，请联系管理员）':(/设置/.test(e.message)?'':'（检查「设置」里的模型配置）');
    addErr('整理失败：'+e.message+hint);
  }
  btn.disabled=false;btn.textContent='AI 整理';
};
function renderAddPreview(j){
  const c=j.card||{};
  const catOpts=(TAX.categories||[]).map(x=>`<option value="${esc(x.id)}">${esc(x.id)} ${esc(x.name||'')}</option>`).join('');
  const domOpts=(TAX.domains||[]).map(x=>`<option value="${esc(x.id)}">${esc(x.id)} ${esc(x.name||'')}</option>`).join('');
  const sim=(c.similar&&c.similar.length)?c.similar.map(s=>{
    const hit=DB.find(k=>k.id===s.id);
    return `<div class="simwarn">⚠️ 与已有卡 <b>${esc(hit?hit.title:(s.id||''))}</b> ${esc(s.relation||'相似')}${s.reason?'：'+esc(s.reason):''}</div>`;}).join('')
    :'<div class="simwarn" style="color:var(--hint)">未发现明显重复或矛盾的已有卡片。</div>';
  const qs=(c.questions||[]).map(q=>`<div class="pvq">💭 ${esc(q)}</div>`).join('');
  const sec=(lb,val,id,rows)=>`<div class="field"><label>${lb}</label><textarea id="${id}" rows="${rows||2}">${esc(val||'')}</textarea></div>`;
  $('add_step1').style.display='none';
  $('add_step2').style.display='block';
  $('add_step2').innerHTML=`
    <div class="pvcard"><h4>整理结果 · 可直接修改</h4>
      ${sec('标题',c.title,'pv_title',2)}
      ${sec('主张（一句可复用的判断）',c.claim,'pv_claim',2)}
      ${sec('依据（关键概念）',c.basis,'pv_basis',2)}
      ${sec('适用条件',c.conditions,'pv_conditions',2)}
      ${sec('失效边界 / 反例',c.limits,'pv_limits',2)}
      ${sec(BRAND.action_label||'可以怎么用',c.action,'pv_action',2)}
      <div class="field"><label>分类（体系）</label><select class="preset" id="pv_cat">${catOpts}</select></div>
      <div class="field"><label>问题域（检索路由）</label><select class="preset" id="pv_dom">${domOpts}</select></div>
      <div class="field"><label>标签（顿号或逗号分隔，3~6 个）</label><input id="pv_tags" value="${esc((c.tags||[]).join('、'))}"></div>
      <div class="pvsec"><span class="lb">来源（提交后原样保留，AI 不会改写）</span><b>${esc($('add_source').value.trim())}</b> · ${c.kind==='personal'?'个人原创思考':'外部知识'}</div>
      <span class="lb" style="font-size:11px;letter-spacing:.8px;color:var(--hint);display:block;margin-top:6px">查重与关联</span>${sim}
      ${qs?`<span class="lb" style="font-size:11px;letter-spacing:.8px;color:var(--hint);display:block;margin-top:6px">值得思辨的问题</span>${qs}`:''}
      ${j.warn?`<div class="simwarn">ℹ️ ${esc(j.warn)}</div>`:''}
    </div>
    <div class="mbtns">
      <button class="mbtn" id="add_back">返回修改输入</button>
      <button class="mbtn" id="add_re">重新整理</button>
      <button class="mbtn pri" id="add_commit">确认入库</button>
    </div>`;
  if(c.category_id)$('pv_cat').value=c.category_id;
  if(c.domain_id)$('pv_dom').value=c.domain_id;
  $('add_back').onclick=()=>{$('add_step2').style.display='none';$('add_step1').style.display='block';};
  $('add_re').onclick=()=>{$('add_step2').style.display='none';$('add_step1').style.display='block';$('add_ai').onclick();};
  $('add_commit').onclick=async()=>{
    const card=collectAddCard();
    if(!card)return;
    if(!card.category){toast('请先选择体系分类');return;}
    if(!card.domain){toast('请先选择问题域');return;}
    if(BRAND.cloud&&!(cfg&&cfg.passcode)){toast('入库需口令：请在右上角「设置」里填写访问口令');return;}
    const btn=$('add_commit');btn.disabled=true;btn.textContent='入库中…';
    let j;
    try{
      if(BRAND.cloud){
        const headers={'Content-Type':'application/json','X-SBS-Token':cfg.passcode};
        const r=await fetch('api/commit',{method:'POST',headers,body:JSON.stringify({card:card,ima:true})});
        j=await r.json().catch(()=>null);
        if(!r.ok||!j||!j.ok)throw new Error((j&&j.error&&j.error.message)||('HTTP '+r.status));
      }else{
        const rec=Object.assign({},card,{layer:'补充',type:'user',created:new Date().toISOString().slice(0,10)});
        let a=[];try{a=JSON.parse(localStorage.getItem(LSP+'cards')||'[]');}catch(e){a=[];}
        if(!Array.isArray(a))a=[];
        a.push(rec);localStorage.setItem(LSP+'cards',JSON.stringify(a));
        j={ok:true,card:rec,dedupe:{action:'created'}};
      }
      mergeUserCards([j.card||card]);
      const d=j.dedupe||{};
      let msg;
      if(d.action==='noop')msg='✅ '+(d.message||'这张卡已在库，重复提交未写入');
      else if(d.action==='merged')msg='✅ 已合并进同主题卡：'+(d.message||'补充了新信息，未生成重复卡');
      else if(d.action==='updated')msg='✅ 已更新同一张卡：'+(d.message||'');
      else if(d.action==='supplement')msg='✅ 已作为补充并入《'+((d.target_title||'').replace(/^《|》$/g,''))+'》：'+(d.message||'检索仍只有一条');
      else msg='✅ 已入库，立即可被问答检索';
      if(j.ima&&j.ima.written)msg+=' · ima 已同步';
      else if(j.ima&&j.ima.skipped==='duplicate')msg+=' · ima 已有同名内容，跳过重复归档';
      else if(j.ima&&j.ima.skipped==='no-credentials')msg+=' · ima 凭证未配置，暂未归档';
      else if(j.ima&&j.ima.error)msg+=' · ima 归档失败（不影响检索）';
      toast(msg,4600);
      closeAdd();
      $('add_content').value='';$('add_source').value='';
    }catch(e){
      toast('入库失败：'+e.message,4200);
      btn.disabled=false;btn.textContent='确认入库';
    }
  };
}
function collectAddCard(){
  if(!addResult)return null;
  return {id:'U'+Date.now().toString(36),title:$('pv_title').value.trim(),claim:$('pv_claim').value.trim(),
    basis:$('pv_basis').value.trim(),conditions:$('pv_conditions').value.trim(),limits:$('pv_limits').value.trim(),
    action:$('pv_action').value.trim(),category:$('pv_cat').value,domain:$('pv_dom').value,
    tags:$('pv_tags').value.trim().split(/[、,，]/).map(s=>s.trim()).filter(Boolean),
    source:$('add_source').value.trim(),kind:$('add_kind').value,created:new Date().toISOString().slice(0,10),
    similar:(addResult.similar||[]),source_confidence:'user_added'};}
/* ---------- 用户卡合并：启动时拉取云端入库卡，并入检索索引 ---------- */
function mergeUserCards(list){
  let added=0;
  (list||[]).forEach(u=>{
    if(!u||!u.id||!u.title||DB.some(c=>c.id===u.id))return;
    // 补充条目：不新增检索单元，把新增信息并入目标卡（与后端 supplement 语义一致）
    if(u.kind==='supplement'&&u.target_id){
      const t=DB.find(c=>c.id===u.target_id);
      if(t){
        const add=(cur,extra)=>{const e=String(extra||'').trim();if(!e)return String(cur||'').trim();
          const c=String(cur||'').trim();if(!c)return e;return c.includes(e)?c:c+'；补充：'+e;};
        t.basis=add(t.basis,u.basis);t.conditions=add(t.conditions,u.conditions);
        t.limits=add(t.limits,u.limits);t.action=add(t.action,u.action);
        t.tags=Array.from(new Set([...(t.tags||[]),...(u.tags||[])]));
        t.supplements=(t.supplements||[]).concat([{source:u.source,created:u.created,title:u.title,claim:u.claim,basis:u.basis,limits:u.limits,action:u.action}]);
        t.supplement_count=(t.supplement_count||0)+1;
        added++;return;
      }
    }
    const cat=(TAX.categories||[]).find(x=>x.id===u.category)||{};
    const dom=TAX.domains.find(x=>x.id===u.domain)||{};
    DB.push(Object.assign({},u,{book:u.book||'',category_name:cat.name||'',domain_name:dom.name||'',
      layer:u.layer||'补充',type:u.type||'user',card:u.card||u.claim}));
    added++;});
  if(added){rebuildIndex();renderNav();try{renderMsgs();}catch(e){}}
  return added;}
async function loadUserCards(){
  if(!BRAND.cloud){
    try{const a=JSON.parse(localStorage.getItem(LSP+'cards')||'[]');
      if(Array.isArray(a)&&a.length){const n=mergeUserCards(a);if(n)console.log('[第二大脑] 已合并 '+n+' 张本机新增卡片');}}catch(e){}
    return;
  }
  for(let attempt=0;attempt<2;attempt++){
    try{
      const r=await fetch('api/commit',{headers:{'Cache-Control':'no-store'},signal:AbortSignal.timeout(9000)});
      if(r.status===503){if(attempt===0){await new Promise(s=>setTimeout(s,1200));continue;}return;}
      if(!r.ok)return;
      const j=await r.json().catch(()=>null);
      if(j&&j.ok&&Array.isArray(j.cards)){
        const n=mergeUserCards(j.cards);
        if(n)console.log('[第二大脑] 已合并 '+n+' 张自入库卡片');
        return;
      }
      return;
    }catch(e){
      if(attempt===0){await new Promise(s=>setTimeout(s,1200));continue;}
      /* 两次都失败：静默降级，只用内置卡，不影响对话 */
    }
  }
}
loadUserCards();
loadNotes();
$('opennotes').onclick=()=>{
  if(needLock&&needLock())return;
  notesView=true;noteJump=false;viewMsgs=null;viewMeta=null;
  renderMsgs();
  $('side').classList.remove('on');$('overlay').classList.remove('on');
  const sc=$('scroll');if(sc)sc.scrollTop=0;
};
$('openmap').onclick=()=>{const pool=[...DB].sort(()=>Math.random()-.5).slice(0,5).map(c=>({c,score:null}));
  openDrawer(pool);toast('随手抽了 5 张卡');};
document.title=BRAND.title+(BRAND.sub?" · "+BRAND.sub:"");
/* 分组折叠：点标题切换，状态持久化；展开时尖括号向下、收起时向右 */
document.querySelectorAll('.stoggle').forEach(b=>b.onclick=()=>{
  const k=b.dataset.sec;if(!k)return;
  secOpen[k]=!secOpen[k];
  try{localStorage.setItem('sbs_sec',JSON.stringify(secOpen));}catch(e){}
  applySections();
});
try{applySections();renderNav();renderMsgs();applyLock();syncChromeHeights();
  setSideCollapsed(localStorage.getItem('sbs_side_collapsed')==='1');}catch(e){}
try{setTimeout(function(){try{autoDetect();}catch(e){}},0);}catch(e){}
</script>
</body>
</html>
"""



# ============================================================
# 构建：语料 -> 单文件站点
# ============================================================

CARD_KEYS = ("id", "title", "type", "type_name", "domain", "domain_name",
             "category", "category_name", "tags", "layer", "claim", "basis",
             "conditions", "limits", "action", "book", "source", "related")

BRAND_DEFAULTS = {
    "title": "我的第二大脑",
    "sub": "个人知识库",
    "kicker": "个人知识库",
    "kickv": "",
    "hero": ["先把问题", "— 说清楚", "再翻你的卡片"],
    "tip": "带着真实问题来。只有真正对得上的材料才会出现，沾边的不会推给你。",
    "disclaimer": "知识库只是信息来源之一：先判断问题类型与可答性，超过范围或库里没有材料时会直接说明、不推卡片。",
    "scope": "这个知识库的主题",
    "persona": "你是一位严谨、克制的知识顾问",
    "action_label": "可以怎么用",
    "ask_tip": "问判断，别问出处。带着你正在面对的具体问题来，比问「某篇讲了什么」有用得多。",
    "about": "一个自包含的对话式知识库：单文件、零依赖、断网可用。数据内联在页面里，模型在「设置」里用自己的 Key 接入。",
    "source_unit": "份资料",
    "local_note_tip": "回答旁写下的心得，保存在本机浏览器，可导出备份",
    "cloud": False,
    "storage_prefix": "sb_",
    "synth_layer": "综合",
    "speed_layer": "速览",
    "offtopic": "",
    "factoid": "",
}


def tokenize(text: str) -> set:
    """与前端 toks() 同一套规则，用来估算词表规模。"""
    s = (text or "").lower()
    out = set()
    for m in re.finditer(r"[a-z0-9]+", s):
        out.add(m.group(0))
    for m in re.finditer(r"[\u4e00-\u9fff]+", s):
        seg = m.group(0)
        out.update(seg)
        out.update(seg[i:i + 2] for i in range(len(seg) - 1))
        out.update(seg[i:i + 3] for i in range(len(seg) - 2))
    return out


def norm_cards(cards, tax):
    doms = {d["id"]: d.get("name", "") for d in tax.get("domains", [])}
    cats = {c["id"]: c.get("name", "") for c in tax.get("categories", [])}
    types = {t["id"]: t.get("name", "") for t in tax.get("card_types", [])}
    out = []
    for i, c in enumerate(cards):
        d = {k: c.get(k, "") for k in CARD_KEYS}
        d["id"] = str(c.get("id") or f"K{i + 1:03d}")
        d["title"] = str(c.get("title") or c.get("claim") or "")[:200]
        for k in ("claim", "basis", "conditions", "limits", "action"):
            d[k] = str(c.get(k) or "")
        d["tags"] = [str(t) for t in (c.get("tags") or []) if str(t).strip()][:8]
        d["type"] = str(c.get("type") or "D")
        d["type_name"] = d["type_name"] or types.get(d["type"], d["type"])
        d["domain"] = str(c.get("domain") or (tax["domains"][0]["id"] if tax.get("domains") else ""))
        d["domain_name"] = d["domain_name"] or doms.get(d["domain"], "")
        d["category"] = str(c.get("category") or "")
        if not d["category"]:
            d["category"] = next((x.get("category", "") for x in tax.get("domains", [])
                                  if x["id"] == d["domain"]), "")
        d["category_name"] = d["category_name"] or cats.get(d["category"], "")
        d["book"] = str(c.get("book") or c.get("source") or "个人资料")
        d["layer"] = str(c.get("layer") or "速览")
        d["related"] = c.get("related") or []
        out.append(d)
    return out


def esc_html(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def main() -> None:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    cfg_path = root / "brain.json"
    if not cfg_path.exists():
        sys.exit(f"缺少 {cfg_path}：先用 engine/init.py 初始化一个知识库项目")
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cards_raw = json.loads((root / "data" / "cards.json").read_text(encoding="utf-8"))
    tax = json.loads((root / "data" / "taxonomy.json").read_text(encoding="utf-8"))
    if not cards_raw:
        sys.exit("data/cards.json 是空的：至少要有 1 张知识卡")

    cards = norm_cards(cards_raw, tax)
    tax_slim = {
        "domains": [{"id": d["id"], "name": d.get("name", ""),
                     "category": d.get("category", ""),
                     "keywords": d.get("keywords", []),
                     "typical_questions": d.get("typical_questions", [])}
                    for d in tax.get("domains", [])],
        "categories": [{"id": c["id"], "name": c.get("name", "")} for c in tax.get("categories", [])],
        "card_types": [{"id": t["id"], "name": t.get("name", "")} for t in tax.get("card_types", [])],
    }

    src_file = root / "data" / "sources.json"
    if src_file.exists():
        sources = len(json.loads(src_file.read_text(encoding="utf-8")))
    else:
        sources = len({c["book"] for c in cards})

    vocab = set()
    for c in cards:
        vocab |= tokenize(" ".join([c["title"], c["title"], c["book"], c["claim"], c["basis"],
                                    c["conditions"], c["limits"], c["action"], " ".join(c["tags"])]))
    meta = {
        "built": __import__("datetime").date.today().isoformat(),
        "sources": sources,
        "cards": len(cards),
        "card_types": dict(Counter(c["type"] for c in cards)),
        "domains": dict(Counter(c["domain"] for c in cards)),
        "layers": dict(Counter(c["layer"] for c in cards)),
        "vocab_size": len(vocab),
    }

    brand = dict(BRAND_DEFAULTS)
    brand.update({k: v for k, v in cfg.items()
                  if k in BRAND_DEFAULTS or k in ("title", "short", "sub", "kicker", "kickv",
                                                  "hero", "tip", "disclaimer", "scope", "persona",
                                                  "ask_tip", "about", "source_unit", "cloud",
                                                  "offtopic", "factoid")})
    brand["title"] = str(brand["title"])
    brand["short"] = str(cfg.get("short") or brand["title"])
    brand["sub"] = str(brand.get("sub") or "")
    brand["notetip"] = str(brand.get("local_note_tip") or "")

    def js(obj) -> str:
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")

    brain_d = ""
    brain_vb = "0 0 1024 1024"
    svg = (ENGINE / "smart-brain.svg")
    if svg.exists():
        raw = svg.read_text(encoding="utf-8")
        m = re.search(r'\sd="([^"]*)"', raw)
        mv = re.search(r'viewBox="([^"]*)"', raw)
        if m:
            brain_d = m.group(1)
        if mv:
            brain_vb = mv.group(1)
    fav_svg = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='" + brain_vb + "'>"
               "<rect x='-320' y='-320' width='1624' height='1624' rx='280' fill='#101010'/>"
               "<path fill='#ffffff' d='" + brain_d + "'/></svg>")
    fav = "data:image/svg+xml;base64," + base64.b64encode(fav_svg.encode("utf-8")).decode("ascii")

    title = brand["title"] + (f" · {brand['sub']}" if brand["sub"] and brand["sub"] not in brand["title"] else "")
    desc = cfg.get("description") or (
        f"{brand['title']}：{sources} {brand['source_unit']}沉淀为 {len(cards)} 张可检索的知识卡，"
        f"带适用条件与失效边界。")
    ogdesc = cfg.get("og_description") or brand["tip"]

    html = (TPL.replace("__DATA__", js(cards))
               .replace("__TAX__", js(tax_slim))
               .replace("__META__", js(meta))
               .replace("__BRAND__", js(brand))
               .replace("__TITLE__", esc_html(title))
               .replace("__DESC__", esc_html(desc))
               .replace("__OGDESC__", esc_html(ogdesc))
               .replace("__SHORT__", esc_html(brand["short"]))
               .replace("__SUB__", esc_html(brand["sub"]))
               .replace("__NOTETIP__", esc_html(brand["notetip"]))
               .replace("__ABOUT__", esc_html(brand["about"]))
               .replace("__BRAINPATH__", '<path fill="currentColor" d="' + brain_d + '"/>')
               .replace("__BRAINVB__", brain_vb)
               .replace("__FAV__", fav))

    left = re.findall(r"__[A-Z]+__", html)
    if left:
        sys.exit(f"模板占位符没替换完：{set(left)}")
    if re.search(r"<script[^>]+src=|<link[^>]+rel=[\"']stylesheet", html):
        sys.exit("产物里出现了外部资源引用，破坏「零依赖单文件」约束")

    dist = root / "dist"
    dist.mkdir(parents=True, exist_ok=True)
    out = dist / "index.html"
    out.write_text(html, encoding="utf-8")
    (dist / "brain-data.json").write_text(
        json.dumps({"meta": meta, "brand": brand, "taxonomy": tax_slim, "cards": cards},
                   ensure_ascii=False, indent=1), encoding="utf-8")

    launch = dist / "打开知识库.command"
    launch.write_text('#!/bin/bash\ncd "$(dirname "$0")" && open index.html\n', encoding="utf-8")
    launch.chmod(0o755)
    (dist / "怎么用.txt").write_text(
        f"{brand['title']}\n\n"
        "1. 双击 index.html（或双击「打开知识库.command」）即可使用，断网也行。\n"
        "2. 想用大模型作答：右上角头像/标题 -> 关于 -> 打开设置，填 Base URL / 模型 / Key。\n"
        "   不填也能用：纯检索模式会先判断问题能不能用这些卡片回答，用不上就不推。\n"
        "3. 想放到线上给别人用：把 index.html 传到任意静态托管（Vercel / Cloudflare Pages / 对象存储）。\n"
        "   注意：浏览器直连模式下 Key 存在访客自己的浏览器里，页面本身不落 Key。\n"
        "4. 笔记保存在本机浏览器，可在「我的笔记」里导出 JSON 备份。\n",
        encoding="utf-8")

    print(f"✓ {out}  {out.stat().st_size / 1024:.1f} KB")
    print(f"  {len(cards)} 张卡 / {len(tax_slim['domains'])} 个问题域 / {len(vocab)} 维词表 / {sources} {brand['source_unit']}")
    print(f"✓ {(dist / 'brain-data.json')}")
    print(f"✓ {(dist / '打开知识库.command')}")


if __name__ == "__main__":
    main()
