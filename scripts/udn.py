"""經濟日報 money.udn.com 新聞爬蟲 — 透過 RSS Feed + 內頁解析。"""
from __future__ import annotations

import sys
import time
from typing import Iterable

import feedparser
from bs4 import BeautifulSoup

try:
    from .common import extract_author_from_entry, request_get, to_taipei_iso
except ImportError:
    from common import extract_author_from_entry, request_get, to_taipei_iso

HEADERS = {"User-Agent": "Mozilla/5.0"}

FEEDS = {
    "國際焦點": "https://money.udn.com/rssfeed/news/1001/5588/9286",
    "國際綜合": "https://money.udn.com/rssfeed/news/1001/5588/11091",
    "美股雷達": "https://money.udn.com/rssfeed/news/1001/5599/11074",
    "全球財經": "https://money.udn.com/rssfeed/news/1001/5588",
    "要聞": "https://money.udn.com/rssfeed/news/1001/5589/5591",
    # 證券/個股版(補個股漲因:目標價/外資調升/個股盤後都在這,實測可用)
    "證券": "https://money.udn.com/rssfeed/news/1001/5590",
    "證券要聞": "https://money.udn.com/rssfeed/news/1001/5590/5710",
    "股市": "https://money.udn.com/rssfeed/news/1001/5590/5607",
}


def _parse_article(url: str) -> str:
    try:
        resp = request_get(url, headers=HEADERS)
        soup = BeautifulSoup(resp.text, "lxml")
        body = soup.select_one("section.article-body__editor") or soup.select_one(
            "div#article_body"
        )
        if not body:
            return ""
        return "\n".join(p.get_text(strip=True) for p in body.select("p"))
    except Exception:
        return ""


def fetch(
    feeds: Iterable[str] | None = None, limit_per_feed: int = 10, fetch_content: bool = False
) -> list[dict]:
    """抓取 UDN 經濟日報新聞。fetch_content=True 時逐篇進內頁抽全文。"""
    chosen = {k: FEEDS[k] for k in feeds} if feeds else FEEDS
    out: list[dict] = []
    for name, url in chosen.items():
        try:
            resp = request_get(url, headers=HEADERS)
            feed = feedparser.parse(resp.content)
            for entry in feed.entries[:limit_per_feed]:
                item = {
                    "source": "udn",
                    "category": name,
                    "title": entry.get("title"),
                    "author": extract_author_from_entry(entry),
                    "summary": entry.get("summary", ""),
                    "content": "",
                    "url": entry.get("link"),
                    "published_at": to_taipei_iso(
                        entry.get("published") or entry.get("updated")
                    ),
                }
                if fetch_content:
                    item["content"] = _parse_article(entry.link)
                    time.sleep(0.3)  # 同網域禮貌間隔(來源間已並行,見 main.aggregate)
                out.append(item)
        except Exception as e:
            print(f"[udn] {name} 抓取失敗: {e}", file=sys.stderr)
    return out


if __name__ == "__main__":
    for n in fetch(limit_per_feed=3):
        print(n["published_at"], n["category"], n["title"])
        print("  ", n["url"])
