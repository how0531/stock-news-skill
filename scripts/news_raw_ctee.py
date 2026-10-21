"""把工商時報(ctee)新聞寫成 g-brain 的 news-raw schema-v1 JSON。

為什麼存在：daily-run 的 g-brain pipeline 原本用 TS `rss-news-fetch` 抓 ctee
的 Google News RSS，只拿得到 Google redirect URL + RSS 摘要（無全文）。本腳本改走
stock-news-skill 已打通的**解碼管線**(ctee.py：Google News 解碼 → 真實 /news/ URL
→ 抓全文)，輸出與 `rss-news-fetch.ts:buildSchemaV1` 完全相同的 schema-v1 JSON 到
`<brain_dir>/news-raw/<TPE date>/ctee-<slug>.json`，讓下游 `news-ingest` 照常 wikify。

鏈路：news_raw_ctee.py → news-raw/*.json → (adapter) → news-ingest → news/*.md
與 rss-news-fetch 一致；只是 ctee 這一支改吃全文。

用法：
  python -X utf8 news_raw_ctee.py --brain-dir E:\\SinoTrader-data [--date 2026-06-28] [--limit 20]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

try:
    from .ctee import fetch as fetch_ctee, _detail_fields
except ImportError:
    from ctee import fetch as fetch_ctee, _detail_fields

SCHEMA_VERSION = 1
SOURCE_NAME = "ctee"
_SLUG_RE = re.compile(r"/news/([0-9]+-[0-9]+)")


def _slug(url: str) -> str | None:
    """ctee /news/20260628700507-430702 → '20260628700507-430702'（唯一 article id）。"""
    m = _SLUG_RE.search(url or "")
    return m.group(1) if m else None


def _slug_date(slug: str) -> str | None:
    """slug 前 8 碼即文章日期：'20260629700043-...' → '2026-06-29'。"""
    if len(slug) >= 8 and slug[:8].isdigit():
        return f"{slug[:4]}-{slug[4:6]}-{slug[6:8]}"
    return None


def _to_utc_iso(iso_taipei: str) -> str:
    """Taipei ISO(+08:00) → UTC ISO(Z)，對齊 rss-news-fetch.ts 的 published_at 格式。"""
    try:
        dt = datetime.fromisoformat(iso_taipei)
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except Exception:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _tpe_date(iso_taipei: str) -> str:
    """文章的台北日期 YYYY-MM-DD（published_at 已是 +08:00，取前 10 碼即可）。"""
    if iso_taipei and len(iso_taipei) >= 10 and iso_taipei[4] == "-":
        return iso_taipei[:10]
    return datetime.now().astimezone().strftime("%Y-%m-%d")


def _atomic_write(path: str, content: str) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(tmp, path)


def write_news_raw(brain_dir: str, date: str | None, limit: int) -> dict:
    # 先取清單（不抓內文，快）→ 用 slug 日期過濾 → 只對通過的抓全文，
    # 省下非當日文章的 body 請求（daily-run 每天固定帶 --date，避免對 ctee 施壓）。
    items = fetch_ctee(categories=None, limit_per_cat=limit, fetch_content=False)
    written = skipped = no_slug = 0
    dates: set[str] = set()
    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    for it in items:
        url = it.get("url", "")
        slug = _slug(url)
        if not slug:
            no_slug += 1
            continue
        tpe = _slug_date(slug) or _tpe_date(it.get("published_at", ""))
        if date and tpe != date:
            continue  # 日期不符 → 直接跳過，不抓全文

        out_dir = os.path.join(brain_dir, "news-raw", tpe)
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f"{SOURCE_NAME}-{slug}.json")
        if os.path.exists(path):  # 冪等：已抓過就跳過（連全文都省）
            skipped += 1
            continue

        det = _detail_fields(url)  # 只有通過日期過濾＋未抓過的才進文章頁抓全文
        published = det["publish"] or _to_utc_iso(it.get("published_at", "")) or f"{tpe}T00:00:00+08:00"
        record = {
            "schema_version": SCHEMA_VERSION,
            "article_id": slug,
            "source_name": SOURCE_NAME,
            "published_at": _to_utc_iso(published),
            "title": it.get("title", ""),
            "body": det["content"] or it.get("summary") or "",
            "url": url,
            "fetched_at": now_iso,
        }
        _atomic_write(path, json.dumps(record, ensure_ascii=False, indent=2) + "\n")
        written += 1
        dates.add(tpe)

    return {"items": len(items), "written": written, "skipped": skipped,
            "no_slug": no_slug, "dates": sorted(dates)}


def main() -> int:
    ap = argparse.ArgumentParser(description="工商時報 → g-brain news-raw schema-v1")
    ap.add_argument("--brain-dir", required=True, help="g-brain 資料根目錄（含 news-raw/）")
    ap.add_argument("--date", default=None, help="只寫此台北日期(YYYY-MM-DD)的文章；省略=全收")
    ap.add_argument("--limit", type=int, default=20, help="每分類上限（傳給 ctee.fetch）")
    args = ap.parse_args()

    r = write_news_raw(args.brain_dir, args.date, args.limit)
    print(f"[news-raw-ctee] items={r['items']} written={r['written']} "
          f"skipped_existing={r['skipped']} no_slug={r['no_slug']} "
          f"dates={','.join(r['dates']) or '-'}", file=sys.stderr)
    # 寫 0 篇但有抓到資料 → 可能 date 過濾或全 skip，不視為失敗；完全沒抓到才非 0。
    return 0 if r["items"] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
