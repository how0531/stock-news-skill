"""Finance-NEWS 統一彙整入口 — 抓最新並寫入 data/raw/（依來源、日期分檔）。"""
from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

try:
    from .cnyes import fetch as fetch_cnyes
    from .ctee import fetch as fetch_ctee
    from .udn import fetch as fetch_udn
    from .rss_sources import SOURCES as RSS_SOURCES, fetch_source as fetch_rss_source
    from .common import TAIPEI, norm_title
    from . import storage
except ImportError:  # 直接以 python scripts/main.py 執行
    from cnyes import fetch as fetch_cnyes
    from ctee import fetch as fetch_ctee
    from udn import fetch as fetch_udn
    from rss_sources import SOURCES as RSS_SOURCES, fetch_source as fetch_rss_source
    from common import TAIPEI, norm_title
    import storage

# 中時(chinatimes)自 2026-10-05 起列表頁回 403,每次白耗約 8 秒且 0 則,暫時移出主路徑。
# 恢復方式:兩段 import 加回 fetch_chinatimes,並在 aggregate() 的 tasks 加回
# ("chinatimes", lambda: fetch_chinatimes(limit_per_cat=10, fetch_content=fetch_content)),
# 位置放在 ctee 之後(維持原本去重先後順序)。可先跑 python scripts/healthcheck.py chinatimes 確認。


def aggregate(fetch_content: bool = True) -> list[dict]:
    """彙整各來源最新新聞。fetch_content=True（預設）逐篇進內頁補全文；
    日終批次跑一次、延遲不敏感，故預設抓全文，--no-content 可關閉。
    cnyes（API 內含全文）與重大訊息（說明即全文）本就帶 content。

    各來源(不同網域)以 ThreadPoolExecutor 並行;同一來源內維持序列 + 禮貌間隔,
    結果依固定來源順序攤平後再去重,去重結果與序列版一致。"""
    # 進度訊息一律走 stderr —— 被 news.py --format=json 當函式呼叫時,
    # stdout 必須是純 JSON,bare print 會污染下游解析(eval 實測兩個 agent 都踩到)。
    tasks = [
        ("cnyes", lambda: fetch_cnyes(limit=15)),
        ("udn", lambda: fetch_udn(limit_per_feed=10, fetch_content=fetch_content)),
        ("ctee", lambda: fetch_ctee(limit_per_cat=10, fetch_content=fetch_content)),
    ] + [
        (sid, lambda s=sid: fetch_rss_source(s, 10, fetch_content=fetch_content))
        for sid in RSS_SOURCES     # 中央社/自由/科技新報/ETtoday/MoneyDJ/Yahoo股市,各一工
    ]

    def _run(name, fn):
        t0 = time.time()
        print(f"[{name}] 抓取中...", file=sys.stderr)
        try:
            got = fn() or []
        except Exception as e:      # 單一來源掛掉不拖累其他來源
            print(f"[{name}] 抓取失敗: {e!r}", file=sys.stderr)
            got = []
        print(f"[{name}] 完成 {len(got)} 則 ({time.time() - t0:.1f}s)", file=sys.stderr)
        return got

    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = [ex.submit(_run, name, fn) for name, fn in tasks]
        news: list[dict] = []
        for f in futs:              # 依 tasks 固定順序收結果,去重先後與序列版相同
            news.extend(f.result())

    # 以 url + 正規化標題去重（跨來源轉載 URL 不同、標題相同）
    seen: set[str] = set()
    deduped: list[dict] = []
    for n in news:
        url = n.get("url") or ""
        tkey = norm_title(n.get("title") or "")
        if not url or url in seen or (tkey and tkey in seen):
            continue
        seen.add(url)
        if tkey:
            seen.add(tkey)
        deduped.append(n)
    return deduped


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Finance-NEWS 統一彙整入口")
    ap.add_argument("--no-content", action="store_true",
                    help="不進內頁抓全文（較快，僅留標題/摘要）")
    args = ap.parse_args()

    items = aggregate(fetch_content=not args.no_content)
    print(f"\n總共 {len(items)} 則新聞")

    # 依來源寫入 raw 層，供日終 process_day.py 轉 processed parquet
    date = datetime.now(TAIPEI).strftime("%Y-%m-%d")
    by_source: dict[str, list[dict]] = {}
    for n in items:
        by_source.setdefault(n.get("source", "unknown"), []).append(n)
    for src, lst in by_source.items():
        merged = {  # 與當日既有 raw 合併（同日多次執行不互相覆蓋）
            f"{i.get('url', '')}|{i.get('title', '')}": i
            for i in storage.load_raw(src, date) + lst
        }
        path = storage.save_raw(src, date, list(merged.values()))
        print(f"  [{src}] {len(lst)} 則 -> {path}")
