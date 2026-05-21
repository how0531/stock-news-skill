# -*- coding: utf-8 -*-
"""
news_formatters.py — stock-news-skill 輸出層。

把 query_news() 的結果(by_code / keyword_hits)轉成三種輸出格式:
  console: 主控台對齊文字(維持原 news.py 行為)
  md:      Markdown(H2 / list / blockquote / table),可貼 Notion/Slack/郵件
  json:    乾淨 JSON dict(由 CLI 端決定 dump 到 stdout / 寫檔)

另含「個股深度報告(report)」的純資料計算函式 build_report(),
以及對應的三種 render: render_report_console/md/json。

設計重點:
  - 純函式、可單元測試,不直接吃 sys.argv / 不直接寫檔
  - 三 format 共用一份 helper(_sent_count / _event_count / _source_count / _top_n)
  - 中文寬度對齊用 unicodedata.east_asian_width 算寬度,console 才會整齊
"""
from __future__ import annotations

import datetime
import unicodedata
from collections import Counter
from typing import Dict, List, Any, Iterable

_SENT_ZH = {"bullish": "利多", "bearish": "利空", "neutral": "中性"}


# --------------------------------------------------------------------------- #
# 共用 helper
# --------------------------------------------------------------------------- #

def _vis_width(s: str) -> int:
    """中文/全形佔 2 寬,其他佔 1。給 console 對齊用。"""
    w = 0
    for ch in s or "":
        w += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return w


def _pad(s: str, width: int) -> str:
    s = s or ""
    pad = width - _vis_width(s)
    return s + " " * max(pad, 0)


def _sent_tag_console(nws: dict) -> str:
    """組出 |利多 0.80| 之類的標籤;無 sentiment 欄位則回空字串。"""
    s = nws.get("sentiment")
    if not s:
        return ""
    zh = _SENT_ZH.get(s, s)
    return f"|{zh} {nws.get('confidence', 0):.2f}"


def _sent_tag_md(nws: dict) -> str:
    """Markdown 用的 inline sentiment 標籤,反引號包起來。"""
    s = nws.get("sentiment")
    if not s:
        return ""
    zh = _SENT_ZH.get(s, s)
    return f"`{zh} {nws.get('confidence', 0):.2f}`"


def _parse_dt(s: str):
    try:
        d = datetime.datetime.fromisoformat((s or "").strip())
        return d if d.tzinfo else d.astimezone()
    except Exception:
        return None


def _sent_count(items: Iterable[dict]) -> Dict[str, int]:
    """回 {'bullish':x,'bearish':y,'neutral':z};沒 sentiment 算 neutral。"""
    c = Counter()
    for it in items:
        c[it.get("sentiment") or "neutral"] += 1
    return {"bullish": c.get("bullish", 0),
            "bearish": c.get("bearish", 0),
            "neutral": c.get("neutral", 0)}


def _event_count(items: Iterable[dict]) -> List[tuple]:
    """回 [(event, count), ...] 按出現次數降序。"""
    c = Counter()
    for it in items:
        for e in (it.get("events") or []):
            c[e] += 1
    return c.most_common()


def _source_count(items: Iterable[dict]) -> List[tuple]:
    """回 [(source, count), ...] 按則數降序。"""
    c = Counter()
    for it in items:
        c[it.get("source") or "unknown"] += 1
    return c.most_common()


def _top_n(items: List[dict], n: int = 5) -> List[dict]:
    """挑 abs(confidence) 最高的 N 則,平手用時間最近。
       無 sentiment / confidence 視為 0;無時間排最後。"""
    _MIN = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)

    def keyfn(it):
        try:
            conf = abs(float(it.get("confidence") or 0))
        except (TypeError, ValueError):
            conf = 0.0
        dt = _parse_dt(it.get("time")) or _MIN
        return (conf, dt)
    return sorted(items, key=keyfn, reverse=True)[:n]


# --------------------------------------------------------------------------- #
# 一般查詢(非 report)— Console / Markdown
# --------------------------------------------------------------------------- #

def render_console(res: dict, code_to_name: Dict[str, str] = None) -> str:
    """非 report 模式的 console 文字。維持與原 news.py 一致格式。"""
    code_to_name = code_to_name or {}
    out = []
    if res.get("by_code"):
        out.append("\n== 個股新聞 ==")
        for code, lst in res["by_code"].items():
            name = code_to_name.get(code, "")
            head = f"{code} {name}".strip()
            out.append(f"\n— {head}（{len(lst)} 則）")
            for nws in lst[:6]:
                out.append(f"  [{nws.get('source','')}|{str(nws.get('time'))[:16]}"
                           f"{_sent_tag_console(nws)}] {nws.get('title','')}")
                evs = nws.get("events") or []
                if evs:
                    out.append(f"     事件: {', '.join(evs)}")
                b = (nws.get("body") or nws.get("summary") or "").strip()
                if b:
                    out.append(f"     → {b[:220]}")
    if res.get("keyword_hits"):
        out.append(f"\n== 關鍵字命中（{len(res['keyword_hits'])} 則）==")
        for h in res["keyword_hits"]:
            tag = f"{h.get('code', '')} {h.get('name', '')}".strip()
            out.append(f"  [{h.get('source','')}|{str(h.get('time'))[:16]}"
                       f"{_sent_tag_console(h)}]"
                       f"{(' '+tag) if tag else ''} {h.get('title','')}")
            evs = h.get("events") or []
            if evs:
                out.append(f"     事件: {', '.join(evs)}")
            b = (h.get("body") or h.get("summary") or "").strip()
            if b:
                out.append(f"     → {b[:260]}")
    return "\n".join(out)


def render_markdown(res: dict, code_to_name: Dict[str, str] = None) -> str:
    """非 report 模式的 Markdown。每檔 H2,每則一個 list item + 引用塊。"""
    code_to_name = code_to_name or {}
    out = []
    by_code = res.get("by_code") or {}
    if by_code:
        for code, lst in by_code.items():
            name = code_to_name.get(code, "")
            head = f"{code}" + (f"（{name}）" if name else "")
            out.append(f"## 個股新聞 — {head}（{len(lst)} 則）\n")
            for nws in lst:
                out.append(_md_news_line(nws))
                b = (nws.get("body") or nws.get("summary") or "").strip()
                if b:
                    out.append(f"  > {b[:300]}")
                out.append("")
    kw = res.get("keyword_hits") or []
    if kw:
        out.append(f"## 關鍵字命中（{len(kw)} 則）\n")
        for h in kw:
            tag = ""
            if h.get("code") or h.get("name"):
                tag = f" `{(h.get('code') or '').strip()} {(h.get('name') or '').strip()}`".rstrip()
            out.append(_md_news_line(h, extra_tag=tag))
            b = (h.get("body") or h.get("summary") or "").strip()
            if b:
                out.append(f"  > {b[:300]}")
            out.append("")
    return "\n".join(out).rstrip() + "\n"


def _md_news_line(nws: dict, extra_tag: str = "") -> str:
    """單則新聞的 markdown list item。"""
    title = (nws.get("title") or "").replace("[", "［").replace("]", "］")
    url = (nws.get("url") or "").replace("(", "%28").replace(")", "%29")
    if url:
        link = f"[{title}]({url})"
    else:
        link = title
    src = nws.get("source") or ""
    t = str(nws.get("time") or "")[:16]
    parts = [link, "— `" + src + "`", "· " + t]
    sent = _sent_tag_md(nws)
    if sent:
        parts.append("· " + sent)
    evs = nws.get("events") or []
    if evs:
        parts.append("· 事件:" + ",".join(evs))
    line = "- " + " ".join(parts)
    if extra_tag:
        line += extra_tag
    return line


# --------------------------------------------------------------------------- #
# 個股深度報告(report)
# --------------------------------------------------------------------------- #

def build_report(code: str, name: str, items: List[dict],
                 days: int) -> dict:
    """純資料層:把單一個股的新聞清單算成 report dict。

    回傳 schema:
      {
        "code": str, "name": str, "days": int, "total": int,
        "sentiment": {"bullish":x,"bearish":y,"neutral":z},
        "events": [(event,count), ...],
        "sources": [(source,count), ...],
        "top": [news...],          # 最重要 N 則(預設 5)
        "timeline": [news...],     # 只挑有 events,依時間倒序
      }
    """
    items = items or []
    timeline = [it for it in items if it.get("events")]
    _MIN = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)
    timeline.sort(key=lambda h: _parse_dt(h.get("time")) or _MIN, reverse=True)
    return {
        "code": code,
        "name": name,
        "days": days,
        "total": len(items),
        "sentiment": _sent_count(items),
        "events": _event_count(items),
        "sources": _source_count(items),
        "top": _top_n(items, 5),
        "timeline": timeline,
    }


def render_report_console(reports: List[dict]) -> str:
    """純文字、對齊 — 適合 terminal 直接讀。"""
    out = []
    for rp in reports:
        head = f"{rp['code']}" + (f" ({rp['name']})" if rp.get("name") else "")
        out.append(f"\n== 個股深度報告 — {head} 近 {rp['days']} 日 "
                   f"{rp['total']} 則新聞 ==")

        # Sentiment 分布
        s = rp["sentiment"]
        total = rp["total"]
        out.append(f"\n[Sentiment 分布]")
        out.append(f"  利多: {s['bullish']:>3} 則"
                   f"   利空: {s['bearish']:>3} 則"
                   f"   中性: {s['neutral']:>3} 則"
                   f"   合計: {total} 則")

        # 事件統計
        out.append(f"\n[事件統計]")
        if rp["events"]:
            for ev, c in rp["events"]:
                out.append(f"  {_pad(ev, 12)} {c:>3} 則")
        else:
            out.append("  (無事件命中)")

        # 來源分布
        out.append(f"\n[來源分布]")
        if rp["sources"]:
            for src, c in rp["sources"]:
                out.append(f"  {_pad(src, 12)} {c:>3} 則")
        else:
            out.append("  (無資料)")

        # Top 5
        out.append(f"\n[Top {len(rp['top'])} 重要新聞]")
        if not rp["top"]:
            out.append("  (無資料)")
        for i, nws in enumerate(rp["top"], 1):
            t = str(nws.get("time") or "")[:16]
            out.append(f"  {i}. [{nws.get('source','')}|{t}"
                       f"{_sent_tag_console(nws)}] {nws.get('title','')}")
            if nws.get("url"):
                out.append(f"     {nws['url']}")
            evs = nws.get("events") or []
            if evs:
                out.append(f"     事件: {', '.join(evs)}")
            b = (nws.get("body") or nws.get("summary") or "").strip()
            if b:
                out.append(f"     → {b[:200]}")

        # 時序事件流
        out.append(f"\n[時序事件流] {len(rp['timeline'])} 則(僅含 events)")
        for nws in rp["timeline"]:
            t = str(nws.get("time") or "")[:16]
            evs = ",".join(nws.get("events") or [])
            out.append(f"  [{t}] [{nws.get('source','')}] [{evs}] "
                       f"{nws.get('title','')}")
    return "\n".join(out)


def render_report_md(reports: List[dict]) -> str:
    """乾淨可貼 Markdown — H2 / 表格 / 引用塊。"""
    out = []
    for rp in reports:
        head = f"{rp['code']}" + (f" ({rp['name']})" if rp.get("name") else "")
        out.append(f"## 個股深度報告 — {head} 近 {rp['days']} 日 "
                   f"{rp['total']} 則新聞\n")

        # Sentiment 表格
        s = rp["sentiment"]
        total = rp["total"]
        out.append("### Sentiment 分布\n")
        out.append("| 利多 | 利空 | 中性 | 合計 |")
        out.append("| ---: | ---: | ---: | ---: |")
        out.append(f"| {s['bullish']} | {s['bearish']} | "
                   f"{s['neutral']} | {total} |\n")

        # 事件
        out.append("### 事件統計\n")
        if rp["events"]:
            for ev, c in rp["events"]:
                out.append(f"- `{ev}`: {c} 則")
        else:
            out.append("- (無事件命中)")
        out.append("")

        # 來源
        out.append("### 來源分布\n")
        if rp["sources"]:
            parts = [f"`{src}`: {c}" for src, c in rp["sources"]]
            out.append(" / ".join(parts))
        else:
            out.append("(無資料)")
        out.append("")

        # Top 5
        out.append(f"### Top {len(rp['top'])} 重要新聞\n")
        if not rp["top"]:
            out.append("(無資料)\n")
        for i, nws in enumerate(rp["top"], 1):
            out.append(f"{i}. " + _md_news_line(nws).lstrip("- "))
            b = (nws.get("body") or nws.get("summary") or "").strip()
            if b:
                out.append(f"   > {b[:200]}")
            out.append("")

        # 時序
        out.append(f"### 時序事件流（{len(rp['timeline'])} 則）\n")
        if not rp["timeline"]:
            out.append("(無事件命中)\n")
        for nws in rp["timeline"]:
            t = str(nws.get("time") or "")[:16]
            evs = ",".join(nws.get("events") or [])
            title = (nws.get("title") or "").replace("[", "［").replace("]", "］")
            url = (nws.get("url") or "").replace("(", "%28").replace(")", "%29")
            link = f"[{title}]({url})" if url else title
            out.append(f"- `[{t}]` `{nws.get('source','')}` "
                       f"`{evs}` {link}")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def render_report_json(reports: List[dict]) -> List[dict]:
    """JSON 版:就是 build_report 出來的 list,events/sources 轉成 dict 友善些。"""
    out = []
    for rp in reports:
        out.append({
            "code": rp["code"],
            "name": rp["name"],
            "days": rp["days"],
            "total": rp["total"],
            "sentiment": rp["sentiment"],
            "events": [{"event": e, "count": c} for e, c in rp["events"]],
            "sources": [{"source": s, "count": c} for s, c in rp["sources"]],
            "top": rp["top"],
            "timeline": rp["timeline"],
        })
    return out
