"""鉅亨網 cnyes.com 新聞爬蟲 — 透過公開 JSON API。"""
from __future__ import annotations

import html
import sys
import time
from typing import Iterable

try:
    from .common import html_to_text, request_get, to_taipei_iso
except ImportError:
    from common import html_to_text, request_get, to_taipei_iso

BASE = "https://api.cnyes.com/media/api/v1/newslist/category/{}"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Origin": "https://news.cnyes.com",
    "Referer": "https://news.cnyes.com/",
}

CATEGORIES = {
    "headline": "頭條",
    "wd_stock": "國際股市",
    "tw_stock": "台股",
    "forex": "外匯",
    "future": "期貨",
}


def _get(category: str, limit: int = 30, page: int = 1) -> list[dict]:
    resp = request_get(
        BASE.format(category),
        params={"limit": limit, "page": page},
        headers=HEADERS,
    )
    return resp.json()["items"]["data"]


def _stock_codes(item: dict) -> list[str]:
    """出版商已標好的個股代號(權威 entity-linking):item.stock=['8046'] + market[].code。
    撿回來給配對直接用,免脆弱的股名字串比對。"""
    codes: list[str] = []
    for c in (item.get("stock") or []):
        s = str(c).strip()
        if s and s not in codes:
            codes.append(s)
    for m in (item.get("market") or []):
        s = str((m or {}).get("code", "")).strip()
        if s and s not in codes:
            codes.append(s)
    return codes


def fetch(categories: Iterable[str] | None = None, limit: int = 20) -> list[dict]:
    """抓取鉅亨網新聞，回傳標準化欄位。"""
    cats = list(categories) if categories else list(CATEGORIES.keys())
    out: list[dict] = []
    for cat in cats:
        try:
            for item in _get(cat, limit=limit):
                out.append(
                    {
                        "source": "cnyes",
                        "category": CATEGORIES.get(cat, cat),
                        "title": item.get("title"),
                        "author": (item.get("author") or "").strip(),
                        "summary": item.get("summary"),
                        # cnyes 列表 API 已內含全文 HTML，無需再抓內頁；內文是實體編碼(&lt;p&gt;)，先還原再轉文字
                        "content": html_to_text(html.unescape(item.get("content") or "")),
                        "url": f"https://news.cnyes.com/news/id/{item.get('newsId')}",
                        "published_at": to_taipei_iso(item.get("publishAt")),
                        "keywords": item.get("keyword", ""),
                        "stock_codes": _stock_codes(item),   # 出版商標的代號
                    }
                )
        except Exception as e:
            print(f"[cnyes] {cat} 抓取失敗: {e}", file=sys.stderr)
        time.sleep(1)
    return out


if __name__ == "__main__":
    for n in fetch(limit=5):
        print(n["published_at"], n["category"], n["title"])
        print("  ", n["url"])
