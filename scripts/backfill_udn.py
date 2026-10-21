"""UDN 經濟日報歷史新聞回補 (Backfill).

策略：透過 money.udn.com 的靜態 sitemap (weekly partitions) 取得歷史文章索引：
    https://money.udn.com/sitemap/staticmap/1001T{YYYYMM}W{1..5}

每個 sitemap 內含當週所有文章 URL 以及 <!-- YYYY-MM-DD HH:MM:SS --> 發佈時間註解。
我們依照 URL path 中的「子分類 ID」過濾出與美 / 日 / 台股相關的類別：

    5591   要聞
    5599   國際焦點
    11074  美股雷達
    10511  美國新聞
    122381 外媒解析
    120769 日經中文網
    122979 日經TRENDY
    123398 美股動態

對每篇文章發 HTTP 取回 raw HTML，解析 title / publish_ts / category / body
並以 PIT 設計分離 published_at (新聞時間) 與 ingestion_ts (抓取時間)。
按日存檔至 data/raw/udn/YYYY-MM-DD.json，已抓過的 URL 寫入 checkpoint 以便續抓。

Usage:
    PYTHONUTF8=1 python scripts/backfill_udn.py --start 2025-12-16 --end 2026-05-15
    PYTHONUTF8=1 python scripts/backfill_udn.py --start 2026-05-13 --end 2026-05-15  # 試跑
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw" / "udn"
CHECKPOINT = ROOT / "data" / "raw" / "udn_checkpoint.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
}

# URL category ID -> human-readable category name
TARGET_CATEGORIES: dict[str, str] = {
    "5591":   "要聞",
    "5599":   "國際焦點",
    "11074":  "美股雷達",
    "10511":  "美國新聞",
    "122381": "外媒解析",
    "120769": "日經中文網",
    "122979": "日經TRENDY",
    "123398": "美股動態",
}

SITEMAP_TMPL = "https://money.udn.com/sitemap/staticmap/1001T{ym}W{w}"

RATE_LIMIT_SEC = 2.1       # >= 1 req / 2 sec
RETRY_MAX = 3
RETRY_BACKOFF = 5.0
TPE = timezone(timedelta(hours=8))

# Pattern: each <url> block embeds a comment with publish timestamp
URL_BLOCK_RE = re.compile(
    r"<loc>(https://money\.udn\.com/money/story/(\d+)/(\d+))</loc>.*?"
    r"<!--\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s*-->",
    re.DOTALL,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_dirs() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)


def _load_checkpoint() -> set[str]:
    if not CHECKPOINT.exists():
        return set()
    try:
        return set(json.loads(CHECKPOINT.read_text(encoding="utf-8")))
    except Exception:
        return set()


def _save_checkpoint(seen: set[str]) -> None:
    CHECKPOINT.write_text(
        json.dumps(sorted(seen), ensure_ascii=False), encoding="utf-8"
    )


def _http_get(url: str, *, timeout: int = 15) -> requests.Response | None:
    for attempt in range(RETRY_MAX):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=timeout)
            if resp.status_code == 200:
                return resp
            if resp.status_code == 404:
                return None
            print(f"  [warn] {url} -> {resp.status_code}")
        except requests.RequestException as e:
            print(f"  [warn] {url} -> {e}")
        time.sleep(RETRY_BACKOFF * (attempt + 1))
    return None


def _iter_target_months(start: datetime, end: datetime):
    """Yield 'YYYYMM' strings spanning start..end inclusive."""
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield f"{y:04d}{m:02d}"
        m += 1
        if m == 13:
            m = 1
            y += 1


# ---------------------------------------------------------------------------
# Sitemap collection
# ---------------------------------------------------------------------------

def collect_index(start: datetime, end: datetime) -> list[dict]:
    """Walk weekly sitemaps and return [{url, story_cat, article_id, publish_ts}].

    Filters: publish in [start, end] AND story_cat in TARGET_CATEGORIES.
    """
    out: list[dict] = []
    seen_urls: set[str] = set()
    for ym in _iter_target_months(start, end):
        for w in range(1, 6):
            url = SITEMAP_TMPL.format(ym=ym, w=w)
            print(f"[sitemap] {url}")
            resp = _http_get(url)
            time.sleep(RATE_LIMIT_SEC)
            if resp is None:
                continue
            for match in URL_BLOCK_RE.finditer(resp.text):
                article_url, story_cat, article_id, ts_str = match.groups()
                if story_cat not in TARGET_CATEGORIES:
                    continue
                try:
                    publish_dt = datetime.strptime(
                        ts_str, "%Y-%m-%d %H:%M:%S"
                    ).replace(tzinfo=TPE)
                except ValueError:
                    continue
                if not (start <= publish_dt <= end):
                    continue
                if article_url in seen_urls:
                    continue
                seen_urls.add(article_url)
                out.append({
                    "url": article_url,
                    "story_cat_id": story_cat,
                    "category": TARGET_CATEGORIES[story_cat],
                    "article_id": article_id,
                    "publish_ts": publish_dt.isoformat(),
                })
    out.sort(key=lambda r: r["publish_ts"])
    return out


# ---------------------------------------------------------------------------
# Article parsing
# ---------------------------------------------------------------------------

def parse_article(html: str, fallback_category: str) -> dict:
    soup = BeautifulSoup(html, "lxml")

    # title
    title = ""
    h1 = soup.select_one("#story_art_title, h1.article-content__title, h1")
    if h1:
        title = h1.get_text(strip=True)
    if not title:
        og = soup.find("meta", attrs={"property": "og:title"})
        if og and og.get("content"):
            title = og["content"].split(" | ")[0].strip()

    # publish time
    publish_meta = soup.find("meta", attrs={"name": "date"})
    publish_str = publish_meta["content"].strip() if publish_meta and publish_meta.get("content") else ""

    # category from title tail
    category = fallback_category
    title_tag = soup.find("title")
    if title_tag and title_tag.string and " | " in title_tag.string:
        parts = [p.strip() for p in title_tag.string.split(" | ")]
        # e.g. "標題 | 國際焦點 | 國際 | 經濟日報"
        if len(parts) >= 2:
            category = parts[1]

    # body
    body_el = soup.select_one(
        "section.article-body__editor, div#article_body, "
        "section.article-content__editor"
    )
    body = ""
    if body_el:
        body = "\n".join(
            p.get_text(strip=True) for p in body_el.find_all("p") if p.get_text(strip=True)
        )

    return {
        "title": title,
        "publish_str": publish_str,
        "category": category,
        "body": body,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(start: datetime, end: datetime, *, max_articles: int | None = None) -> None:
    _ensure_dirs()
    print(f"[backfill_udn] window: {start.isoformat()} -> {end.isoformat()}")

    seen = _load_checkpoint()
    index = collect_index(start, end)
    print(f"[backfill_udn] {len(index)} target articles from sitemaps")

    by_day: dict[str, list[dict]] = defaultdict(list)
    # preload existing day files so we can append without losing prior runs
    fetched = 0
    for entry in index:
        if max_articles is not None and fetched >= max_articles:
            break
        url = entry["url"]
        if url in seen:
            continue

        resp = _http_get(url)
        ingestion_ts = datetime.now(tz=TPE).isoformat()
        time.sleep(RATE_LIMIT_SEC)
        if resp is None:
            seen.add(url)  # avoid infinite retry on permanent 404
            continue

        try:
            parsed = parse_article(resp.text, entry["category"])
        except Exception as e:
            print(f"  [parse error] {url}: {e}")
            continue

        day_key = entry["publish_ts"][:10]
        record = {
            "source": "udn",
            "url": url,
            "article_id": entry["article_id"],
            "story_cat_id": entry["story_cat_id"],
            "category": parsed["category"] or entry["category"],
            "title": parsed["title"],
            "body": parsed["body"],
            "published_at": entry["publish_ts"],         # PIT publish time
            "publish_str_meta": parsed["publish_str"],   # raw <meta name="date"> value
            "ingestion_ts": ingestion_ts,                # PIT ingestion time
            "raw_html": resp.text,
        }
        by_day[day_key].append(record)
        seen.add(url)
        fetched += 1

        # flush every 25 articles
        if fetched % 25 == 0:
            _flush(by_day)
            by_day.clear()
            _save_checkpoint(seen)
            print(f"  [progress] fetched={fetched} / {len(index)}")

    _flush(by_day)
    _save_checkpoint(seen)
    print(f"[backfill_udn] done. fetched={fetched} new articles")


def _flush(by_day: dict[str, list[dict]]) -> None:
    """Append day buckets to existing JSON files."""
    for day_key, items in by_day.items():
        path = RAW_DIR / f"{day_key}.json"
        existing: list[dict] = []
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                existing = []
        existing.extend(items)
        path.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def _parse_date(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=TPE)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, help="YYYY-MM-DD inclusive")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD inclusive")
    ap.add_argument(
        "--max-articles", type=int, default=None, help="Optional cap for smoke tests"
    )
    args = ap.parse_args()

    start = _parse_date(args.start)
    end = _parse_date(args.end) + timedelta(hours=23, minutes=59, seconds=59)
    run(start, end, max_articles=args.max_articles)


if __name__ == "__main__":
    main()
