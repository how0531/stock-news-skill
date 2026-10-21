"""來源健檢 — 一條指令探測所有新聞來源，回報存活狀態與樣本。

取代「本機逐一驗證五六個端點」的手動流程：列出每個來源是否回得了資料、
抓到幾筆、幾筆帶得到 publish_ts、耗時、以及一則樣本標題（失敗則顯示錯誤）。
網路受限環境（如雲端 sandbox）會全部標記失敗，屬預期。

用法：
  python scripts/healthcheck.py             # 全部來源(中時已移出主路徑,預設不測)
  python scripts/healthcheck.py cnyes ctee  # 只測指定來源
  python scripts/healthcheck.py chinatimes  # 點名才測中時

離開碼：全部存活回 0，有任一來源失敗回 1（方便接 cron 告警）。
"""
from __future__ import annotations

import sys
import time
from typing import Callable

try:
    from .cnyes import fetch as fetch_cnyes
    from .udn import fetch as fetch_udn
    from .ctee import fetch as fetch_ctee
    from .chinatimes import fetch as fetch_chinatimes
    from .rss_sources import SOURCES as RSS_SOURCES, fetch_source as fetch_rss
    from .twse_announce import fetch as fetch_announce
except ImportError:  # 直接以 python scripts/healthcheck.py 執行
    from cnyes import fetch as fetch_cnyes
    from udn import fetch as fetch_udn
    from ctee import fetch as fetch_ctee
    from chinatimes import fetch as fetch_chinatimes
    from rss_sources import SOURCES as RSS_SOURCES, fetch_source as fetch_rss
    from twse_announce import fetch as fetch_announce


def probe(label: str, fn: Callable[[], list[dict]]) -> dict:
    """執行一個抓取函式並彙整結果；任何例外都收斂成失敗結果，不外拋。"""
    start = time.time()
    try:
        items = fn() or []
        sample = next((it.get("title", "") for it in items if it.get("title")), "")
        return {
            "source": label,
            "ok": len(items) > 0,
            "count": len(items),
            "with_ts": sum(1 for it in items if it.get("published_at")),
            "elapsed": time.time() - start,
            "detail": sample[:44],
        }
    except Exception as e:
        return {
            "source": label,
            "ok": False,
            "count": 0,
            "with_ts": 0,
            "elapsed": time.time() - start,
            "detail": f"ERROR: {str(e)[:50]}",
        }


def build_probes(selected: set[str]) -> list[tuple[str, Callable[[], list[dict]]]]:
    """組出 (label, fn) 清單；selected 為空代表全選。"""
    def want(name: str) -> bool:
        return not selected or name in selected

    probes: list[tuple[str, Callable[[], list[dict]]]] = []
    if want("cnyes"):
        probes.append(("cnyes", lambda: fetch_cnyes(limit=3)))
    if want("udn"):
        probes.append(("udn", lambda: fetch_udn(limit_per_feed=3)))
    if want("ctee"):
        probes.append(("ctee", lambda: fetch_ctee(limit_per_cat=3)))
    if "chinatimes" in selected:  # 2026-10-05 起 403、已移出主路徑;要確認恢復時再點名測
        probes.append(("chinatimes", lambda: fetch_chinatimes(limit_per_cat=3)))
    if want("announce"):
        probes.append(("announce", lambda: fetch_announce()))
    for sid in RSS_SOURCES:
        if want(sid):
            probes.append((sid, lambda s=sid: fetch_rss(s, limit_per_feed=3)))
    return probes


def main(argv: list[str]) -> int:
    probes = build_probes(set(argv))
    print(f"{'SOURCE':<14}{'OK':<5}{'N':>4}{'TS':>5}{'SEC':>7}  SAMPLE / ERROR")
    print("-" * 80)
    results = []
    for label, fn in probes:
        r = probe(label, fn)
        results.append(r)
        print(f"{r['source']:<14}{'✓' if r['ok'] else '✗':<5}{r['count']:>4}"
              f"{r['with_ts']:>5}{r['elapsed']:>7.1f}  {r['detail']}")
    alive = sum(1 for r in results if r["ok"])
    print("-" * 80)
    print(f"存活 {alive}/{len(results)} 來源")
    return 0 if alive == len(results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
