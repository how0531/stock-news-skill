"""盤中快訊監看 — 輪詢低延遲來源，去重後比對個股、寫入事件串流。

本 skill 只負責前端資料搜集：產出事件串流即為終點。
每則新事件 append 至 data/stream/YYYY-MM-DD.jsonl，下游 skill
（股市資訊大腦、快訊推播）自行 tail 讀取，每行 schema 見下方 build_event()。

用法：
  python scripts/watch_intraday.py --once                # 單次輪詢（測試）
  python scripts/watch_intraday.py --interval 60         # 持續監看
  python scripts/watch_intraday.py --sources cnyes,cna,announce --market-hours-only
"""
from __future__ import annotations

import argparse
import json
import time as time_mod
from datetime import datetime, time
from pathlib import Path

try:
    from .common import TAIPEI, fetch_article, norm_title
    from .cnyes import fetch as fetch_cnyes
    from .rss_sources import SOURCES as RSS_SOURCES, fetch_source as fetch_rss
    from .twse_announce import fetch as fetch_announce
except ImportError:  # 直接以 python scripts/watch_intraday.py 執行
    from common import TAIPEI, fetch_article, norm_title
    from cnyes import fetch as fetch_cnyes
    from rss_sources import SOURCES as RSS_SOURCES, fetch_source as fetch_rss
    from twse_announce import fetch as fetch_announce

LOG_FILE: Path | None = None


def log(msg: str) -> None:
    print(msg)
    if LOG_FILE is not None:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now(TAIPEI):%Y-%m-%d %H:%M:%S} {msg}\n")

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "data" / "state" / "seen_keys.json"
STREAM_DIR = ROOT / "data" / "stream"
STOCKS_DIR = ROOT / "data" / "stocks"

SEEN_CAP = 8000  # 去重 key 上限，超過砍最舊的

MARKET_OPEN = time(8, 30)   # 提早半小時涵蓋開盤前快訊
MARKET_CLOSE = time(13, 45)

DEFAULT_SOURCES = ["cnyes", "cna", "moneydj", "announce"]

# 已知雜訊只打 tag 不丟棄（下游自行決定要不要濾）
TAG_RULES = [
    ("盤中速報", "noise_intraday_tick"),
    ("鉅亨速報 - Factset", "signal_target_price"),
    ("營收速報", "signal_revenue"),
    ("[重大訊息]", "signal_announcement"),
]


# --------------------------------------------------------------------------- #
# 去重狀態
# --------------------------------------------------------------------------- #

def load_seen() -> list[str]:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return []


def save_seen(seen: list[str]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(seen[-SEEN_CAP:]), encoding="utf-8")


def item_keys(item: dict) -> list[str]:
    """兩把去重 key：URL+標題（重大訊息共用查詢頁 URL，需加標題才唯一）、
    正規化標題（跨來源轉載 URL 不同、內文相同）。"""
    keys = [f"url:{item.get('url', '')}|{item.get('title', '')}"]
    tkey = norm_title(item.get("title") or "")
    if tkey:
        keys.append(f"title:{tkey}")
    return keys


# --------------------------------------------------------------------------- #
# 個股比對（L1 regex + L2 字典，與 quick_heat 同邏輯的輕量版）
# --------------------------------------------------------------------------- #

def load_alias_index() -> list[tuple[str, str]]:
    """回傳 [(alias, ticker)]，別名長度倒序，先匹配長的避免 partial match。"""
    pairs: list[tuple[str, str]] = []
    for f in ("tw_stocks.json", "us_stocks.json", "jp_stocks.json"):
        path = STOCKS_DIR / f
        if not path.exists():
            continue
        for ticker, info in json.loads(path.read_text(encoding="utf-8")).items():
            for alias in info.get("aliases", []):
                pairs.append((alias, ticker))
    pairs.sort(key=lambda p: len(p[0]), reverse=True)
    return pairs


def match_tickers(text: str, alias_index: list[tuple[str, str]]) -> list[str]:
    found: list[str] = []
    for alias, ticker in alias_index:
        if alias in text and ticker not in found:
            found.append(ticker)
    return found


def classify(title: str) -> list[str]:
    return [tag for prefix, tag in TAG_RULES if title.startswith(prefix)]


# --------------------------------------------------------------------------- #
# 輪詢
# --------------------------------------------------------------------------- #

def poll_sources(sources: list[str]) -> list[dict]:
    items: list[dict] = []
    for sid in sources:
        try:
            if sid == "cnyes":
                items.extend(fetch_cnyes(limit=20))
            elif sid == "announce":
                items.extend(fetch_announce())
            elif sid in RSS_SOURCES:
                items.extend(fetch_rss(sid, limit_per_feed=15))
            else:
                print(f"[watch] 未知來源: {sid}")
        except Exception as e:
            print(f"[watch] {sid} 輪詢失敗: {e}")
    return items


def enrich_content(item: dict) -> None:
    """就地補抓 RSS 來源新項目的內頁全文（cnyes/announce 已含全文者略過）。

    僅對通過去重的新項目呼叫，避免每輪對同一批列表重複抓內頁而被擋。
    內文容器選擇器取自 RSS_SOURCES[sid]['body_selectors']。
    """
    if item.get("content"):
        return
    conf = RSS_SOURCES.get(item.get("source", ""))
    url = item.get("url")
    if not conf or not url:
        return
    art = fetch_article(url, body_selectors=conf.get("body_selectors"))
    if art["content"]:
        item["content"] = art["content"]
    if not item.get("summary"):
        item["summary"] = art["summary"]
    if not item.get("author"):
        item["author"] = art["author"]
    time_mod.sleep(1)  # 禮貌性間隔，避免內頁抓取過快被擋


def poll_once(
    sources: list[str],
    seen: list[str],
    alias_index: list[tuple[str, str]],
    fetch_content: bool = True,
) -> int:
    seen_set = set(seen)
    new_count = 0
    now = datetime.now(TAIPEI)
    stream_file = STREAM_DIR / f"{now:%Y-%m-%d}.jsonl"
    STREAM_DIR.mkdir(parents=True, exist_ok=True)

    for item in poll_sources(sources):
        keys = item_keys(item)
        if not item.get("title") or any(k in seen_set for k in keys):
            continue
        seen_set.update(keys)
        seen.extend(keys)
        new_count += 1

        if fetch_content:
            enrich_content(item)

        tags = classify(item["title"])
        text = f"{item.get('title', '')} {item.get('summary', '')}"
        tickers = match_tickers(text, alias_index)
        if item.get("ticker_hint") and item["ticker_hint"] not in tickers:
            tickers.insert(0, item["ticker_hint"])

        event = build_event(
            item,
            event_id=f"{now:%Y%m%d%H%M%S}-{new_count:04d}",
            ingestion_iso=now.isoformat(),
            tickers=tickers,
            tags=tags,
        )
        with open(stream_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

        log(f"  + [{item['source']}] {item['title']}  tickers={tickers} tags={tags}")

    return new_count


def build_event(item: dict, event_id: str, ingestion_iso: str,
                tickers: list[str], tags: list[str]) -> dict:
    """組事件串流記錄（純函式，可離線測試）。

    與日終 processed 的統一格式對齊：帶 author/summary/content，
    讓官方公告全文與 fetch_content 抓到的內文不會在串流路徑被丟棄。
    """
    return {
        "event_id": event_id,
        "source": item["source"],
        "category": item.get("category", ""),
        "title": item["title"],
        "author": item.get("author", ""),
        "summary": item.get("summary", ""),
        "content": item.get("content", ""),
        "url": item.get("url", ""),
        "publish_ts": item.get("published_at", ""),
        "ingestion_ts": ingestion_iso,
        "tickers": tickers,
        "tags": tags,
    }


def in_market_hours(now: datetime | None = None) -> bool:
    """以台北時區判斷，主機系統時區是 UTC 也不會誤判。"""
    now = now or datetime.now(TAIPEI)
    return now.weekday() < 5 and MARKET_OPEN <= now.time() <= MARKET_CLOSE


def main() -> None:
    ap = argparse.ArgumentParser(description="盤中快訊監看（只搜集，不推播）")
    ap.add_argument("--sources", default=",".join(DEFAULT_SOURCES),
                    help=f"逗號分隔來源（預設 {','.join(DEFAULT_SOURCES)}；"
                         f"可用 cnyes,announce,{','.join(RSS_SOURCES)}）")
    ap.add_argument("--interval", type=int, default=60, help="輪詢間隔秒數（預設 60）")
    ap.add_argument("--once", action="store_true", help="只輪詢一次後結束（測試用）")
    ap.add_argument("--market-hours-only", action="store_true",
                    help="僅在台股盤中時段（08:30-13:45）輪詢")
    ap.add_argument("--no-content", action="store_true",
                    help="新項目不進內頁補抓全文（較快、較不易被擋）")
    ap.add_argument("--log-file", default=None,
                    help="同步寫入 log 檔（長時運行建議開啟，例如 data/state/watch.log）")
    args = ap.parse_args()

    global LOG_FILE
    if args.log_file:
        LOG_FILE = Path(args.log_file)
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    alias_index = load_alias_index()
    seen = load_seen()

    log(f"[watch] 來源: {sources}，間隔 {args.interval}s，字典 {len(alias_index)} 別名，"
        f"全文補抓: {'關' if args.no_content else '開'}")
    while True:
        if args.market_hours_only and not in_market_hours():
            log(f"[watch] {datetime.now(TAIPEI):%H:%M} 非盤中時段，待命中...")
        else:
            n = poll_once(sources, seen, alias_index, fetch_content=not args.no_content)
            # 記憶體去重表與磁碟同步維持上限，長時運行（--interval）才不會無上限成長
            del seen[:-SEEN_CAP]
            save_seen(seen)
            log(f"[watch] {datetime.now(TAIPEI):%H:%M:%S} 本輪新增 {n} 則")
        if args.once:
            break
        time_mod.sleep(args.interval)


if __name__ == "__main__":
    main()
