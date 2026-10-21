"""工商時報 ctee.com.tw 歷史新聞回補 (Backfill).

策略：透過 ctee.com.tw 的 sitemap 取得歷史文章索引。
robots.txt 公開三個 sitemap，其中 sitemap_news_all_index_0_v2.xml 為 index，
底下有約 100 個 sub-sitemap，每個收 4000~5000 篇文章、時間範圍約 1~3 個月。
WordPress REST API (/wp-json/) 已被關閉 (回 404)，因此走 sitemap + 文章 HTML 解析。

關鍵觀察：
1. 文章 URL 形如  `https://www.ctee.com.tw/news/{YYYYMMDD}{6digit_seq}-{6digit_cat}`
   開頭 8 碼即為發佈日期 (台北時區)。
2. sub-sitemap 內 entry 只有 <loc> + <lastmod>，沒有 publication_date；但 URL 已含日期。
3. 文章 HTML <meta name="pubdate" content="YYYY-MM-DD HH:MM:SS"> 提供精確時間。
4. 末 6 碼為分類代碼：
        430104  要聞
        4302xx  證券
        4303xx  金融
        4305xx  產業
        4307xx  國際       <-- 國際財經 / 美股 / 日股 / 外匯
        430801  兩岸
        431207  商情 / 商品
        431401  生活
        4399xx  日報 (含 即時新聞)
   詳細子類由 HTML <title> 的「- 國際 - 工商時報」尾段提供。

目標分類 (專案需求): 即時新聞 / 國際財經 / 美股 / 日股 / 外匯
   - 國際財經    : cat code 開頭 4307
   - 美股/日股/外匯: 同樣是 4307xx 但用 title 關鍵字補強
   - 即時新聞    : URL 含 `livenews` 或 cat 開頭 4399 (日報即時)

PIT 設計分離 published_at (新聞時間) 與 ingestion_ts (抓取時間)，
按日存檔 data/raw/ctee/YYYY-MM-DD.json，checkpoint 至 ctee_checkpoint.json。

Usage:
    PYTHONUTF8=1 python scripts/backfill_ctee.py --start 2025-12-16 --end 2026-05-15
    PYTHONUTF8=1 python scripts/backfill_ctee.py --start 2026-05-13 --end 2026-05-15
"""
from __future__ import annotations

import argparse
import json
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw" / "ctee"
CHECKPOINT = ROOT / "data" / "raw" / "ctee_checkpoint.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
}

SITEMAP_INDEX = "https://www.ctee.com.tw/sitemaps/sitemap_news_all_index_0_v2.xml"
SITEMAP_NEWSTODAY = "https://www.ctee.com.tw/sitemaps/sitemap_newstoday.xml"

# Category code prefix (first 4 chars of 6-digit suffix) -> coarse category.
# 2026-08-10 以文章頁 articleSection 逐碼實測校正：430201證券 430301金融 430402理財
# 430503產業 430601/430603房市 430702/430704國際 430801兩岸 431206商情。
# 原表 4304 誤標「金融」、4306 誤標「產業」，會讓房市新聞被當產業訊息餵進盤前信。
CAT_PREFIX_MAP: dict[str, str] = {
    "4301": "要聞",
    "4302": "證券",
    "4303": "金融",
    "4304": "理財",
    "4305": "產業",
    "4306": "房市",
    "4307": "國際",     # 國際財經 / 美股 / 日股 / 外匯 都掛在此
    "4308": "兩岸",
    "4312": "商情",
    "4314": "生活",
    "4399": "日報",     # 含即時新聞
}

# Target high-level categories (專案需求)
TARGET_HIGH_LEVEL = {"國際", "日報"}

# Keyword refinement on title (for 美股/日股/外匯/即時)
SUBCAT_KEYWORDS: list[tuple[str, list[str]]] = [
    ("美股", ["美股", "道瓊", "那斯達克", "費半", "S&P", "標普", "輝達", "蘋果"]),
    ("日股", ["日股", "日經", "東證"]),
    ("外匯", ["外匯", "美元", "日圓", "歐元", "人民幣", "新台幣", "匯價", "匯率"]),
    ("國際財經", ["國際", "全球", "歐洲", "美國", "中國"]),
]

RATE_LIMIT_SEC = 2.1
RETRY_MAX = 3
RETRY_BACKOFF = 5.0
TPE = timezone(timedelta(hours=8))

URL_DATE_RE = re.compile(r"/news/(\d{8})(\d{6})-(\d{6})")
LOC_RE = re.compile(r"<loc>([^<]+)</loc>")
SUB_SITEMAP_RE = re.compile(r"<loc>(https://www\.ctee\.com\.tw/sitemaps/sitemap_ctee_news/sitemap_news_\d+_v2\.xml)</loc>")


# ---------------------------------------------------------------------------
# IO helpers
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


def _http_get(url: str, *, timeout: int = 20) -> requests.Response | None:
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


# ---------------------------------------------------------------------------
# Category classification
# ---------------------------------------------------------------------------

def classify(url: str, cat_code: str, title: str) -> tuple[str, bool]:
    """Return (subcategory_label, is_target).

    is_target = True iff article falls into 即時新聞 / 國際財經 / 美股 / 日股 / 外匯.
    """
    # 即時新聞 (livenews URL or 4399 日報)
    if "/livenews" in url or cat_code.startswith("4399"):
        # 日報底下涵蓋多種 — 我們把 4399 視為即時新聞候選
        return ("即時新聞", True)

    prefix = cat_code[:4]
    high = CAT_PREFIX_MAP.get(prefix, "其他")

    if high != "國際":
        return (high, False)

    # 4307xx 國際底下用 title 關鍵字細分
    for sub, keywords in SUBCAT_KEYWORDS:
        if any(k in title for k in keywords):
            return (sub, True)
    # 預設仍歸為國際財經
    return ("國際財經", True)


# ---------------------------------------------------------------------------
# Sitemap collection
# ---------------------------------------------------------------------------

def _list_sub_sitemaps() -> list[str]:
    resp = _http_get(SITEMAP_INDEX)
    if resp is None:
        return []
    return SUB_SITEMAP_RE.findall(resp.text)


def _sitemap_url_to_date(url: str) -> datetime | None:
    m = URL_DATE_RE.search(url)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y%m%d").replace(tzinfo=TPE)
    except ValueError:
        return None


def collect_index(start: datetime, end: datetime) -> list[dict]:
    """Walk sub-sitemaps and collect candidate article URLs whose URL-embedded
    date falls within [start, end]. Category filtering happens later when we
    fetch the article (we only have the cat_code from URL here)."""
    out: list[dict] = []
    seen_urls: set[str] = set()

    sub_sitemaps = _list_sub_sitemaps()
    print(f"[sitemap] index has {len(sub_sitemaps)} sub-sitemaps")
    time.sleep(RATE_LIMIT_SEC)

    # Sub-sitemaps are time-ordered ascending; iterate from newest and stop
    # once we leave the date window on the older side.
    for sm in reversed(sub_sitemaps):
        resp = _http_get(sm)
        time.sleep(RATE_LIMIT_SEC)
        if resp is None:
            continue
        urls = LOC_RE.findall(resp.text)
        in_window = 0
        sm_min_date: datetime | None = None
        sm_max_date: datetime | None = None
        for u in urls:
            m = URL_DATE_RE.search(u)
            if not m:
                continue
            d = _sitemap_url_to_date(u)
            if d is None:
                continue
            if sm_min_date is None or d < sm_min_date:
                sm_min_date = d
            if sm_max_date is None or d > sm_max_date:
                sm_max_date = d
            if not (start <= d <= end):
                continue
            cat_code = m.group(3)
            # coarse filter on category code: only keep 國際/日報 prefixes
            prefix = cat_code[:4]
            if prefix not in ("4307", "4399") and "/livenews" not in u:
                continue
            if u in seen_urls:
                continue
            seen_urls.add(u)
            out.append({
                "url": u,
                "url_date": d.strftime("%Y-%m-%d"),
                "cat_code": cat_code,
            })
            in_window += 1
        print(
            f"[sitemap] {sm.rsplit('/', 1)[-1]}: "
            f"range=[{sm_min_date.date() if sm_min_date else '?'}..{sm_max_date.date() if sm_max_date else '?'}] "
            f"matched={in_window}"
        )
        # Early termination: sitemap entirely older than start
        if sm_max_date is not None and sm_max_date < start:
            print("[sitemap] reached older-than-window sitemap, stopping")
            break

    out.sort(key=lambda r: r["url"])
    return out


# ---------------------------------------------------------------------------
# Article parsing
# ---------------------------------------------------------------------------

def parse_article(html: str) -> dict:
    soup = BeautifulSoup(html, "lxml")

    # title
    title = ""
    og_title = soup.find("meta", attrs={"property": "og:title"})
    if og_title and og_title.get("content"):
        title = og_title["content"].strip()
    if not title:
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(strip=True)

    # publish time
    publish_str = ""
    pub_meta = soup.find("meta", attrs={"property": "article:published_time"})
    if pub_meta and pub_meta.get("content"):
        publish_str = pub_meta["content"].strip()
    else:
        pub_meta2 = soup.find("meta", attrs={"name": "pubdate"})
        if pub_meta2 and pub_meta2.get("content"):
            publish_str = pub_meta2["content"].strip()

    # canonical category from <title> tail "- 國際 - 工商時報"
    canonical_cat = ""
    title_tag = soup.find("title")
    if title_tag and title_tag.string:
        parts = [p.strip() for p in title_tag.string.split(" - ")]
        if len(parts) >= 2:
            canonical_cat = parts[-2]

    # description / summary
    summary = ""
    desc = soup.find("meta", attrs={"property": "og:description"})
    if desc and desc.get("content"):
        summary = desc["content"].strip()

    # body
    body = ""
    body_el = (
        soup.select_one("div.entry-content")
        or soup.select_one("div.article-content")
        or soup.select_one("article")
    )
    if body_el:
        body = "\n".join(
            p.get_text(strip=True) for p in body_el.find_all("p")
            if p.get_text(strip=True)
        )

    return {
        "title": title,
        "publish_str": publish_str,
        "canonical_category": canonical_cat,
        "summary": summary,
        "body": body,
    }


def _publish_str_to_iso(s: str) -> str | None:
    """Convert '2026-05-16 13:29:24' or ISO to ISO-with-TZ string."""
    if not s:
        return None
    s = s.strip()
    try:
        if "T" in s:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        else:
            dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=TPE)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TPE)
        return dt.isoformat()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run(start: datetime, end: datetime, *, max_articles: int | None = None) -> None:
    _ensure_dirs()
    print(f"[backfill_ctee] window: {start.isoformat()} -> {end.isoformat()}")

    seen = _load_checkpoint()
    index = collect_index(start, end)
    print(f"[backfill_ctee] {len(index)} candidate URLs from sitemap")

    by_day: dict[str, list[dict]] = defaultdict(list)
    fetched = 0
    accepted = 0
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
            seen.add(url)
            continue

        try:
            parsed = parse_article(resp.text)
        except Exception as e:
            print(f"  [parse error] {url}: {e}")
            seen.add(url)
            continue

        fetched += 1
        sub_label, is_target = classify(url, entry["cat_code"], parsed["title"])
        if not is_target:
            seen.add(url)
            continue

        publish_iso = _publish_str_to_iso(parsed["publish_str"])
        if not publish_iso:
            # fallback to URL date midnight TPE
            publish_iso = (
                datetime.strptime(entry["url_date"], "%Y-%m-%d")
                .replace(tzinfo=TPE)
                .isoformat()
            )

        # double-check publish_ts within window
        publish_dt = datetime.fromisoformat(publish_iso)
        if not (start <= publish_dt <= end):
            seen.add(url)
            continue

        day_key = publish_iso[:10]
        record = {
            "source": "ctee",
            "url": url,
            "cat_code": entry["cat_code"],
            "category": sub_label,                       # 我們判定的目標子類
            "canonical_category": parsed["canonical_category"],
            "title": parsed["title"],
            "summary": parsed["summary"],
            "body": parsed["body"],
            "published_at": publish_iso,                  # PIT publish time
            "publish_str_meta": parsed["publish_str"],
            "ingestion_ts": ingestion_ts,                 # PIT ingestion time
            "raw_html": resp.text,
        }
        by_day[day_key].append(record)
        seen.add(url)
        accepted += 1

        if fetched % 25 == 0:
            _flush(by_day)
            by_day.clear()
            _save_checkpoint(seen)
            print(
                f"  [progress] fetched={fetched} accepted={accepted} "
                f"/ {len(index)}"
            )

    _flush(by_day)
    _save_checkpoint(seen)
    print(
        f"[backfill_ctee] done. fetched={fetched} accepted={accepted} new articles"
    )


def _flush(by_day: dict[str, list[dict]]) -> None:
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
    ap.add_argument("--start", required=True, help="YYYY-MM-DD inclusive (TPE)")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD inclusive (TPE)")
    ap.add_argument(
        "--max-articles", type=int, default=None, help="Optional cap for smoke tests"
    )
    args = ap.parse_args()

    start = _parse_date(args.start)
    end = _parse_date(args.end) + timedelta(hours=23, minutes=59, seconds=59)
    run(start, end, max_articles=args.max_articles)


if __name__ == "__main__":
    main()
