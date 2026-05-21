# -*- coding: utf-8 -*-
"""
test_health.py — stock-news-skill 來源可達性健康檢查。

對 cnyes / udn / ctee(+ 可選 Metabase)各端點發單一 GET,印 OK/FAIL +
回應大小,失敗不中斷,只計分。沿用 news_providers._get() 的設計:
SSL 失敗 fallback 到未驗證 context(永豐 TLS 攔截相容)。

退出碼: 全部 OK → 0;有任何 FAIL → 1。
"""
import os
import ssl
import sys
import time
import json
import urllib.request
import urllib.error

TIMEOUT = 12
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
_UNVERIFIED = ssl._create_unverified_context()

# 取小流量 — 加 Range header(支援的伺服器會回 206 + 1KB,否則正常 200)
RANGE_HEADER = {"Range": "bytes=0-1023"}


def probe(name, url, expect_json=False, with_range=True):
    """回 (ok: bool, msg: str)。失敗包成 FAIL,不丟例外。"""
    headers = dict(UA)
    if with_range:
        headers.update(RANGE_HEADER)
    req = urllib.request.Request(url, headers=headers)
    t0 = time.time()
    try:
        try:
            r = urllib.request.urlopen(req, timeout=TIMEOUT)
        except ssl.SSLError:
            r = urllib.request.urlopen(req, timeout=TIMEOUT,
                                       context=_UNVERIFIED)
        raw = r.read()
        elapsed = (time.time() - t0) * 1000
        size = len(raw)
        status = r.getcode()
        if expect_json:
            try:
                json.loads(raw.decode("utf-8", "replace"))
            except Exception as e:
                return False, (f"HTTP {status} 但 JSON parse 失敗: {e!r} "
                               f"({size}B / {elapsed:.0f}ms)")
        return True, f"HTTP {status} ({size}B / {elapsed:.0f}ms)"
    except urllib.error.HTTPError as e:
        elapsed = (time.time() - t0) * 1000
        # 部分內容/重導向都算正常活著
        if e.code in (200, 206, 301, 302, 304):
            return True, f"HTTP {e.code} ({elapsed:.0f}ms)"
        return False, f"HTTPError {e.code} ({elapsed:.0f}ms)"
    except Exception as e:
        elapsed = (time.time() - t0) * 1000
        return False, f"{type(e).__name__}: {e} ({elapsed:.0f}ms)"


def main():
    targets = [
        ("cnyes API tw_stock",
         "https://api.cnyes.com/media/api/v1/newslist/category/"
         "tw_stock?limit=1&page=1", True),
        ("udn RSS 5590",
         "https://money.udn.com/rssfeed/news/1001/5590?ch=money", False),
        ("udn RSS 5591",
         "https://money.udn.com/rssfeed/news/1001/5591?ch=money", False),
        ("udn RSS 12017",
         "https://money.udn.com/rssfeed/news/1001/12017?ch=money", False),
        ("ctee livenews/stock",
         "https://www.ctee.com.tw/livenews/stock", False),
        ("ctee livenews/finance",
         "https://www.ctee.com.tw/livenews/finance", False),
        ("ctee livenews/tech",
         "https://www.ctee.com.tw/livenews/tech", False),
    ]

    # Metabase 可選
    mb_url = os.environ.get("METABASE_URL")
    if mb_url:
        targets.append(("Metabase (env)", mb_url.rstrip("/") + "/api/health",
                        False))
    else:
        print("[skip] Metabase: METABASE_URL 未設,略過")

    print(f"\n=== stock-news-skill 健康檢查 ({len(targets)} 個端點) ===")
    ok = fail = 0
    for name, url, expect_json in targets:
        passed, msg = probe(name, url, expect_json=expect_json)
        tag = "OK  " if passed else "FAIL"
        print(f"  [{tag}] {name:30s} → {msg}")
        if passed:
            ok += 1
        else:
            fail += 1

    total = ok + fail
    print(f"\n=== 結果: {ok}/{total} pass, {fail} fail ===")
    sys.exit(0 if fail == 0 else 1)


if __name__ == "__main__":
    main()
