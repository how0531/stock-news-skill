"""中時新聞網 chinatimes.com 財經即時爬蟲 — HTML 列表解析。

由於官方 RSS 404 停用，此模組改以爬取網頁 HTML 列表進行解析。
發布日期直接從 URL 內嵌的 8 碼取得（/realtimenews/{YYYYMMDD}...），免額外請求即可得到日粒度 publish_ts。
"""
from __future__ import annotations

import re
import sys
import time
from typing import Iterable

from bs4 import BeautifulSoup

try:
    from .common import parse_article_fields, request_get, to_taipei_iso, UA
except ImportError:
    from common import parse_article_fields, request_get, to_taipei_iso, UA

HEADERS = {"User-Agent": UA}
URL_DATE_RE = re.compile(r"/realtimenews/(\d{8})")


def _url_date_iso(url: str) -> str:
    """從文章 URL 內嵌的 8 碼日期取台北時間 ISO（日粒度）；無法解析回空字串。"""
    m = URL_DATE_RE.search(url)
    if not m:
        return ""
    ymd = m.group(1)
    return to_taipei_iso(f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}")


def _detail_fields(url: str) -> dict:
    """抓文章頁取得精確發布時間、作者、摘要與全文。"""
    try:
        html = request_get(url, headers=HEADERS).text
    except Exception:
        return {"publish": "", "author": "", "summary": "", "content": ""}
    af = parse_article_fields(html, body_selectors=["div.article-body", "article", "main"])
    
    # 抽取時間 (中時的文章頁通常有 <meta property="article:published_time" content="...">)
    soup = BeautifulSoup(html, "html.parser")
    time_meta = (
        soup.find("meta", attrs={"property": "article:published_time"})
        or soup.find("meta", attrs={"name": "pubdate"})
    )
    publish_time = ""
    if time_meta and time_meta.get("content"):
        publish_time = to_taipei_iso(time_meta["content"].strip())
        
    return {
        "publish": publish_time,
        "author": af["author"],
        "summary": af["summary"],
        "content": af["content"],
    }


def _parse_list(url: str, limit: int) -> list[dict]:
    resp = request_get(url, headers=HEADERS)
    soup = BeautifulSoup(resp.text, "lxml")

    # 尋找 h3.title a 與包含 realtimenews 的 a
    anchors = soup.select("h3.title a") or soup.select(".title a")
    items: list[dict] = []
    for a in anchors:
        href = a.get("href", "")
        title = a.get_text(strip=True)
        if href and title:
            # 正規化 URL
            if not href.startswith("http"):
                href = "https://www.chinatimes.com" + href
            if "/realtimenews/" in href:
                items.append({"title": title, "url": href})
                if len(items) >= limit:
                    break
    return items


def fetch(
    categories: Iterable[str] | None = None,
    limit_per_cat: int = 15,
    fetch_content: bool = False,
) -> list[dict]:
    """抓取中時新聞網財經新聞列表。"""
    url = "https://www.chinatimes.com/money/?chdtv"
    out: list[dict] = []
    try:
        for item in _parse_list(url, limit_per_cat):
            pub = _url_date_iso(item["url"])
            author = summary = content = ""
            if fetch_content:
                det = _detail_fields(item["url"])
                if det["publish"]:
                    pub = det["publish"]
                author, summary, content = det["author"], det["summary"], det["content"]
                time.sleep(1)
            out.append(
                {
                    "source": "chinatimes",
                    "category": "財經即時",
                    "title": item["title"],
                    "author": author,
                    "url": item["url"],
                    "summary": summary,
                    "content": content,
                    "published_at": pub,
                }
            )
    except Exception as e:
        print(f"[chinatimes] 抓取失敗: {e}", file=sys.stderr)
    return out


if __name__ == "__main__":
    for n in fetch(limit_per_cat=5):
        print(n["published_at"], n["category"], n["title"])
        print("  ", n["url"])
