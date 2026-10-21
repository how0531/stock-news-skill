"""鉅亨網 5 個月歷史新聞回抓腳本。

回抓 2025-12-16 ~ 2026-05-15 所有財經新聞（5 分類），
依日期分檔存於 data/raw/cnyes/YYYY-MM-DD.json。

設計重點:
- PIT 時間戳分離（published_at / ingestion_ts）
- 完整保留 raw_api_response
- 斷點續抓（日檔存在即跳過）
- rate limit + 指數退避 retry
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

# ---- 設定 ----
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

TZ_TAIPEI = timezone(timedelta(hours=8))

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "cnyes"

REQUEST_INTERVAL = 1.1  # 每次 API 呼叫間隔（秒）
MAX_RETRIES = 3
PAGE_LIMIT = 100  # 每頁筆數


def _request_with_retry(url: str, params: dict) -> dict:
    """帶指數退避的 GET。"""
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=15)
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = (2 ** attempt) * 2
                print(f"  [retry] HTTP {resp.status_code} — wait {wait}s", flush=True)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            wait = (2 ** attempt) * 2
            print(f"  [retry] {e} — wait {wait}s", flush=True)
            time.sleep(wait)
    raise RuntimeError(f"Failed after {MAX_RETRIES} retries: {url} {params}")


def _fetch_range(category: str, start_ts: int, end_ts: int) -> list[dict]:
    """抓取一個分類在 [start_ts, end_ts] 範圍內的所有新聞（含分頁）。"""
    items: list[dict] = []
    page = 1
    url = BASE.format(category)
    while True:
        params = {
            "startAt": start_ts,
            "endAt": end_ts,
            "limit": PAGE_LIMIT,
            "page": page,
        }
        data = _request_with_retry(url, params)
        block = data.get("items", {})
        page_items = block.get("data", []) or []
        items.extend(page_items)
        last_page = block.get("last_page") or 1
        if page >= last_page or not page_items:
            break
        page += 1
        time.sleep(REQUEST_INTERVAL)
    return items


def _normalize(item: dict, category_id: str, ingestion_iso: str) -> dict:
    publish_at_ts = item.get("publishAt", 0)
    published_at = (
        datetime.fromtimestamp(publish_at_ts, tz=TZ_TAIPEI).isoformat()
        if publish_at_ts
        else None
    )
    news_id = item.get("newsId")
    return {
        "source": "cnyes",
        "source_news_id": str(news_id) if news_id is not None else None,
        "title": item.get("title"),
        "summary": item.get("summary"),
        "url": f"https://news.cnyes.com/news/id/{news_id}" if news_id else None,
        "category": CATEGORIES.get(category_id, category_id),
        "category_id": category_id,
        "published_at": published_at,
        "ingestion_ts": ingestion_iso,
        "keywords": item.get("keyword", ""),
        "stock_codes_from_api": item.get("market") or item.get("stock") or [],
        "raw_api_response": item,
    }


def _day_bounds(day: datetime) -> tuple[int, int]:
    """回傳該日 [00:00:00, 23:59:59] 的台北時區 Unix 時間戳。"""
    start = day.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=TZ_TAIPEI)
    end = day.replace(hour=23, minute=59, second=59, microsecond=0, tzinfo=TZ_TAIPEI)
    return int(start.timestamp()), int(end.timestamp())


def backfill_day(day: datetime) -> int:
    """抓取單一日期的新聞並寫檔，回傳筆數。已存在則跳過。"""
    date_str = day.strftime("%Y-%m-%d")
    out_file = RAW_DIR / f"{date_str}.json"
    if out_file.exists():
        print(f"[{date_str}] cnyes: skip (file exists)", flush=True)
        return 0

    start_ts, end_ts = _day_bounds(day)
    ingestion_iso = datetime.now(tz=TZ_TAIPEI).isoformat()

    all_records: list[dict] = []
    seen_ids: set[str] = set()  # 跨分類去重
    per_cat_count: dict[str, int] = defaultdict(int)

    for cat_id in CATEGORIES:
        try:
            raw_items = _fetch_range(cat_id, start_ts, end_ts)
        except Exception as e:
            print(f"  [{date_str}] {cat_id} failed: {e}", flush=True)
            time.sleep(REQUEST_INTERVAL)
            continue
        for item in raw_items:
            nid = str(item.get("newsId"))
            if nid in seen_ids:
                continue
            seen_ids.add(nid)
            all_records.append(_normalize(item, cat_id, ingestion_iso))
            per_cat_count[cat_id] += 1
        time.sleep(REQUEST_INTERVAL)

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    tmp_file = out_file.with_suffix(".json.tmp")
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(all_records, f, ensure_ascii=False, indent=2)
    os.replace(tmp_file, out_file)

    breakdown = ", ".join(f"{k}={v}" for k, v in per_cat_count.items())
    print(
        f"[{date_str}] cnyes: {len(all_records)} articles saved ({breakdown})",
        flush=True,
    )
    return len(all_records)


def daterange(start: datetime, end: datetime):
    """yield 每一天（含 start, end）。"""
    cur = start
    while cur <= end:
        yield cur
        cur = cur + timedelta(days=1)


def main():
    parser = argparse.ArgumentParser(description="Cnyes backfill")
    parser.add_argument("--start", default="2025-12-16", help="起始日 YYYY-MM-DD")
    parser.add_argument("--end", default="2026-05-15", help="結束日 YYYY-MM-DD")
    parser.add_argument("--days", type=int, default=None,
                        help="僅抓最近 N 天（覆蓋 start/end，用於試跑）")
    args = parser.parse_args()

    if args.days is not None:
        end = datetime.now(tz=TZ_TAIPEI).replace(tzinfo=None) - timedelta(days=1)
        start = end - timedelta(days=args.days - 1)
    else:
        start = datetime.strptime(args.start, "%Y-%m-%d")
        end = datetime.strptime(args.end, "%Y-%m-%d")

    print(f"Backfill {start.date()} -> {end.date()}", flush=True)
    total = 0
    t0 = time.time()
    for day in daterange(start, end):
        try:
            total += backfill_day(day)
        except Exception as e:
            print(f"[{day.date()}] FATAL: {e}", flush=True)
    elapsed = time.time() - t0
    print(f"Done. total={total} elapsed={elapsed:.1f}s", flush=True)


if __name__ == "__main__":
    sys.exit(main())
