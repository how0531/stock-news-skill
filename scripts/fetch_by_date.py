"""抓取指定日期的新聞（含日期過濾邏輯）。"""
from __future__ import annotations

import sys
from datetime import datetime

from dateutil import parser as dtparser  # type: ignore

try:
    from .cnyes import CATEGORIES as CNYES_CATS
    from .common import request_get, to_taipei_iso
    from .udn import FEEDS as UDN_FEEDS
except ImportError:  # 直接以 python scripts/fetch_by_date.py 執行
    from cnyes import CATEGORIES as CNYES_CATS
    from common import request_get, to_taipei_iso
    from udn import FEEDS as UDN_FEEDS
import feedparser


CNYES_BASE = "https://api.cnyes.com/media/api/v1/newslist/category/{}"
CNYES_HEAD = {
    "User-Agent": "Mozilla/5.0",
    "Origin": "https://news.cnyes.com",
    "Referer": "https://news.cnyes.com/",
}


def fetch_cnyes_by_date(target: datetime.date) -> list[dict]:
    """cnyes 支援 startAt/endAt timestamp 過濾"""
    start_ts = int(datetime.combine(target, datetime.min.time()).timestamp())
    end_ts = int(datetime.combine(target, datetime.max.time()).timestamp())
    out: list[dict] = []
    for cat, cname in CNYES_CATS.items():
        try:
            r = request_get(
                CNYES_BASE.format(cat),
                params={"limit": 30, "startAt": start_ts, "endAt": end_ts},
                headers=CNYES_HEAD,
            )
            for item in r.json()["items"]["data"]:
                out.append(
                    {
                        "source": "cnyes",
                        "category": cname,
                        "title": item.get("title"),
                        "url": f"https://news.cnyes.com/news/id/{item.get('newsId')}",
                        # epoch -> Asia/Taipei ISO（原本用 naive fromtimestamp，UTC 主機會錯 8 小時）
                        "published_at": to_taipei_iso(item.get("publishAt")),
                    }
                )
        except Exception as e:
            print(f"[cnyes] {cat} 失敗: {e}", file=sys.stderr)
    return out


def fetch_udn_by_date(target: datetime.date) -> list[dict]:
    out: list[dict] = []
    for name, url in UDN_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                pub = entry.get("published") or entry.get("updated") or ""
                if not pub:
                    continue
                try:
                    pub_dt = dtparser.parse(pub).date()
                except Exception:
                    continue
                if pub_dt == target:
                    out.append(
                        {
                            "source": "udn",
                            "category": name,
                            "title": entry.get("title"),
                            "url": entry.get("link"),
                            "published_at": pub,
                        }
                    )
        except Exception as e:
            print(f"[udn] {name} 失敗: {e}", file=sys.stderr)
    return out


def main(date_str: str) -> None:
    target = dtparser.parse(date_str).date()
    print(f"抓取 {target.isoformat()} 的新聞...\n")

    items = fetch_cnyes_by_date(target) + fetch_udn_by_date(target)
    # 去重
    seen, deduped = set(), []
    for n in items:
        if n["url"] and n["url"] not in seen:
            seen.add(n["url"])
            deduped.append(n)

    # 排序：時間倒序
    deduped.sort(key=lambda x: x.get("published_at", ""), reverse=True)

    print(f"=== {target.isoformat()} 共 {len(deduped)} 則 ===\n")
    by_source: dict[str, list[dict]] = {}
    for n in deduped:
        by_source.setdefault(n["source"], []).append(n)

    for src, lst in by_source.items():
        print(f"\n--- [{src.upper()}] {len(lst)} 則 ---")
        for n in lst:
            print(f"  ({n['category']}) {n['title']}")
            print(f"    {n['url']}")


if __name__ == "__main__":
    date_arg = sys.argv[1] if len(sys.argv) > 1 else "2026-05-13"
    main(date_arg)
