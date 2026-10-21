"""日終 ETL — 將當日 raw JSON + 盤中 stream JSONL 整理成 processed Parquet。

補齊資料管線「抓取層 → PIT 儲存層」的缺口：
  - 來源：data/raw/{source}/{date}.json（main.py / backfill 寫入）
          data/stream/{date}.jsonl（watch_intraday 寫入）
  - 輸出：data/processed/date={date}/data.parquet（PIT 三時間戳齊備）
  - 去重：兩層——Tier 1 標題正規化相同、Tier 2 內文指紋相同的改寫轉載，
          皆保留最早 publish_ts 一筆，被併來源彙整於 also_reported_by

用法：
  python scripts/process_day.py              # 處理今天（台北時間）
  python scripts/process_day.py 2026-06-12   # 處理指定日期
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from dateutil import parser as dtparser  # type: ignore

try:
    from .common import TAIPEI, norm_title
    from . import storage
    from .watch_intraday import classify, load_alias_index, match_tickers
except ImportError:
    from common import TAIPEI, norm_title
    import storage
    from watch_intraday import classify, load_alias_index, match_tickers

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
STREAM = ROOT / "data" / "stream"


def _to_naive_taipei(value) -> datetime | None:
    """任意時間值 -> 台北時間 naive datetime（processed 層慣例）；失敗回 None。"""
    if not value:
        return None
    try:
        dt = dtparser.parse(str(value))
    except (ValueError, OverflowError):
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(TAIPEI).replace(tzinfo=None)
    return dt


def _record_id(item: dict) -> str:
    key = f"{norm_title(item.get('title', ''))}|{item.get('url', '')}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


# Tier 2 去重：標題經改寫但全文/摘要相同（如 yahoo 引用其他來源全文）的轉載
FINGERPRINT_LEN = 60  # 內文正規化後取前 N 字作指紋；過短視為無法判定，不參與比對
DEDUP_WINDOW = timedelta(hours=48)  # 超出時間窗視為各自獨立事件（如舊聞重炒），不合併


def _content_fingerprint(text: str) -> str:
    """內文正規化後取前 FINGERPRINT_LEN 字；過短（含空字串）回空字串。"""
    norm = norm_title(text)
    return norm[:FINGERPRINT_LEN] if len(norm) >= FINGERPRINT_LEN else ""


def _merge_exact_dupes(groups: list[list[dict]]) -> list[dict]:
    """Tier 1 去重：標題正規化後完全相同者保留最早 publish 一筆。

    其餘來源記於 also_reported_by（與 Tier 2 共用欄位，_merge_reprints 會再合併）。
    """
    out: list[dict] = []
    for group in groups:
        group.sort(key=lambda r: r["publish_ts"] or datetime.max)
        primary, *dups = group
        # 排除主筆自身來源（同來源同標題重抓不算「其他來源也報」）
        primary["also_reported_by"] = sorted(
            {d["source"] for d in dups if d["source"]} - {primary["source"]}
        )
        out.append(primary)
    return out


def _merge_reprints(records: list[dict]) -> list[dict]:
    """Tier 2 去重：依內文指紋合併「標題改寫但全文相同」的轉載（如 yahoo 引用其他來源全文）。

    同指紋且 publish_ts 落在 DEDUP_WINDOW 內者視為同一事件，保留最早一筆，
    其餘來源（含其 Tier 1 也帶來的 also_reported_by）併入 also_reported_by；
    指紋不同、無指紋或超出時間窗者各自保留。
    """
    groups: dict[str, list[dict]] = {}
    out: list[dict] = []
    for rec in records:
        fp = _content_fingerprint(rec["content"] or rec["summary"])
        if fp:
            groups.setdefault(fp, []).append(rec)
        else:
            out.append(rec)

    for group in groups.values():
        group.sort(key=lambda r: r["publish_ts"] or datetime.max)
        clusters: list[list[dict]] = []
        for rec in group:
            for cluster in clusters:
                last_pub, cur_pub = cluster[-1]["publish_ts"], rec["publish_ts"]
                if (last_pub is not None and cur_pub is not None
                        and cur_pub - last_pub <= DEDUP_WINDOW):
                    cluster.append(rec)
                    break
            else:
                clusters.append([rec])
        for primary, *dups in clusters:
            extra = {d["source"] for d in dups if d["source"]}
            for d in dups:
                extra.update(d["also_reported_by"])
            primary["also_reported_by"] = sorted(
                (set(primary["also_reported_by"]) | extra) - {primary["source"]}
            )
            out.append(primary)

    return out


def load_day_items(date: str) -> list[dict]:
    """收集當日所有 raw JSON 與 stream JSONL 項目（欄位名就地統一）。"""
    items: list[dict] = []
    for raw_file in sorted(RAW.glob(f"*/{date}.json")):
        for it in json.loads(raw_file.read_text(encoding="utf-8")):
            items.append(it)
    stream_file = STREAM / f"{date}.jsonl"
    if stream_file.exists():
        for line in stream_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            ev = json.loads(line)
            # stream 事件 schema 的時間欄位叫 publish_ts；raw 層一律叫 published_at，
            # 此處橋接讓 build_records 只需認得 published_at 一個名字
            ev.setdefault("published_at", ev.get("publish_ts", ""))
            items.append(ev)
    return items


def build_records(
    items: list[dict],
    default_ingestion: datetime,
    alias_index: list[tuple[str, str]] | None = None,
) -> pd.DataFrame:
    """純函式：項目清單 -> processed schema DataFrame（含去重與 PIT 時間戳）。"""
    if alias_index is None:
        alias_index = load_alias_index()

    by_title: dict[str, list[dict]] = {}
    for item in items:
        title = item.get("title") or ""
        if not title:
            continue
        tkey = norm_title(title)
        publish = _to_naive_taipei(item.get("published_at"))
        ingestion = _to_naive_taipei(item.get("ingestion_ts")) or default_ingestion
        # 來源時鐘誤差可能讓 publish 晚於我們的抓取時間；PIT 不變量要求
        # ingestion >= publish，以 publish 為下限校正
        if publish is not None and ingestion < publish:
            ingestion = publish

        if "tickers" in item:
            tickers = list(item["tickers"])
        else:
            text = f"{title} {item.get('summary', '')}"
            tickers = match_tickers(text, alias_index)
        tags = list(item["tags"]) if "tags" in item else classify(title)

        rec = {
            "id": _record_id(item),
            "source": item.get("source", ""),
            "category": item.get("category", ""),
            "title": title,
            "author": item.get("author", ""),
            "summary": item.get("summary", ""),
            # 相容舊鍵 body；統一輸出 content
            "content": item.get("content", item.get("body", "")),
            "url": item.get("url", ""),
            "publish_ts": publish,
            "ingestion_ts": ingestion,
            "actionable_ts": storage.compute_actionable_ts(publish)
            if publish is not None
            else None,
            "tickers": tickers,
            "tags": tags,
        }

        by_title.setdefault(tkey, []).append(rec)

    primaries = _merge_exact_dupes(list(by_title.values()))
    df = pd.DataFrame(_merge_reprints(primaries))
    if df.empty:
        return pd.DataFrame(columns=storage.PROCESSED_REQUIRED)
    for col in ("publish_ts", "ingestion_ts", "actionable_ts"):
        df[col] = pd.to_datetime(df[col])
    return df


def main(date: str | None = None) -> None:
    date = date or datetime.now(TAIPEI).strftime("%Y-%m-%d")
    items = load_day_items(date)
    if not items:
        print(f"[process_day] {date} 無 raw/stream 資料，跳過")
        return
    df = build_records(items, default_ingestion=datetime.now(TAIPEI).replace(tzinfo=None))
    out = storage.save_processed(date, df)
    n_pub = int(df["publish_ts"].notna().sum())
    print(f"[process_day] {date}: {len(items)} 項 -> 去重後 {len(df)} 筆"
          f"（含 publish_ts {n_pub} 筆）-> {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
