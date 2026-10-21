# -*- coding: utf-8 -*-
"""
test_query_news_internals.py — query_news() keyword 分支內部邏輯測試。

用 monkeypatch 把 news_providers.fetch_sanbao 換成回傳「固定假新聞清單」,
再以 source="sanbao"(完全不碰 Metabase、不打網路)呼叫
news_core.query_news(keyword=..., source="sanbao", tag_sentiment=False),
驗證 keyword_hits 的四項內部邏輯:

  1) 去重    : 重複標題只留一則(且留 body 較豐富者)
  2) 排序    : 依 time 倒序(新→舊),無時間者排最後
  3) 時間過濾: 超出 cutoff(now - max(days,10) 日)的假新聞被濾掉
  4) individual_only=True: 泛大盤標題(三大法人/台股/收盤…)被濾掉,個股保留

設計鐵則:
  - 完全不觸網:fetch_sanbao 被 patch 成回固定 dict;attach_bodies 也 pat 成
    no-op(雙保險,即使 fetch_body 被打開也不會上網)。
  - tag_sentiment=False:不依賴 news_sentiment 詞庫(它正被另一 agent 改)。
  - 每個 case 用「不同 keyword」,規避另一 agent 正在加的 TTL 記憶體快取。
  - 每個 case 開頭嘗試呼叫 clear_news_cache()(若存在);用 try/except 包,
    目前 news_core 尚無此函式 → 靜默略過,不報錯。
  - monkeypatch 用完一律在 finally 還原原始函式。

退出碼: 全 OK → 0;任一 FAIL → 1。
"""
import sys
import datetime
import pathlib

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "scripts"))

import news_core as NC          # noqa: E402
import news_providers as NP     # noqa: E402

results = []  # (name, ok, msg)


def record(name, ok, msg=""):
    tag = "OK  " if ok else "FAIL"
    print(f"  [{tag}] {name}" + (f" — {msg}" if msg else ""))
    results.append((name, ok, msg))


def check(name, cond, msg=""):
    record(name, bool(cond), msg)
    return bool(cond)


def _iso(days_ago, hour=9):
    """回 N 天前的 ISO 時間字串(帶本地時區)。"""
    dt = (datetime.datetime.now().astimezone()
          - datetime.timedelta(days=days_ago)).replace(
              hour=hour, minute=0, second=0, microsecond=0)
    return dt.isoformat()


def _try_clear_cache():
    """另一 agent 正在加 TTL 快取。若有清快取函式就呼叫,沒有則靜默略過。"""
    for fname in ("clear_news_cache", "_clear_news_cache",
                  "clear_cache", "reset_cache"):
        fn = getattr(NC, fname, None)
        if callable(fn):
            try:
                fn()
            except Exception:
                pass
            return


def make_fake_items(kw):
    """產一組精心設計的假新聞(news_providers 共通格式)。

    kw 會被嵌進標題,確保 query_news 的 keyword 比對命中。
    包含:
      - 重複標題(body 一長一短)→ 驗去重 + 留長 body
      - 不同 published_at → 驗排序
      - 一筆超出時間範圍(40 天前)→ 驗時間過濾
      - 泛大盤標題(台股收盤 / 三大法人)→ 驗 individual_only 過濾
      - 有些有 body 有些沒有
    """
    return [
        # --- 重複標題:同一則「{kw}訂單滿手」出現兩次,body 一短一長 ---
        {"source": "cnyes", "title": f"{kw}訂單滿手出貨暢旺",
         "summary": "", "body": "短內文",
         "url": "http://fake/dup-short",
         "published_at": _iso(2), "keywords": []},
        {"source": "udn", "title": f"{kw}訂單滿手出貨暢旺",   # 同標題,body 較長
         "summary": "", "body": "這是比較長的內文" * 5,
         "url": "http://fake/dup-long",
         "published_at": _iso(2), "keywords": []},

        # --- 不同時間的個股新聞(驗排序:新→舊) ---
        {"source": "ctee", "title": f"{kw}法說會今登場",
         "summary": "摘要", "body": "",
         "url": "http://fake/newest",
         "published_at": _iso(1), "keywords": []},        # 最新(1 天前)
        {"source": "cnyes", "title": f"{kw}獲利成長動能強",
         "summary": "", "body": "內文",
         "url": "http://fake/middle",
         "published_at": _iso(5), "keywords": []},        # 中間(5 天前)

        # --- 超出時間範圍(40 天前,遠超 max(days,10))→ 應被濾掉 ---
        {"source": "udn", "title": f"{kw}去年舊聞不該出現",
         "summary": "", "body": "",
         "url": "http://fake/too-old",
         "published_at": _iso(40), "keywords": []},

        # --- 泛大盤新聞(含 GENERIC_NEWS 詞),內文含 kw 以便命中 ---
        {"source": "cnyes", "title": "台股收盤跌200點 量能萎縮",
         "summary": f"{kw}權值股走弱", "body": "",
         "url": "http://fake/generic-1",
         "published_at": _iso(1), "keywords": []},
        {"source": "udn", "title": "三大法人賣超百億 外資賣超居多",
         "summary": "", "body": f"{kw}遭提款",
         "url": "http://fake/generic-2",
         "published_at": _iso(2), "keywords": []},
    ]


# --------------------------------------------------------------------------- #
# 測試案例 — 每個用不同 keyword(規避 TTL 快取)
# --------------------------------------------------------------------------- #

def run_with_patch(kw, items=None, search_items=None, **query_kwargs):
    """patch fetch_sanbao(回 make_fake_items 或指定 items)+ attach_bodies(no-op)
    + search_cnyes_news(關鍵字模式的 cnyes 搜尋腿,預設回 []),
    跑 query_news(source='sanbao'),回 keyword_hits。finally 還原。"""
    _try_clear_cache()
    orig_fetch = NP.fetch_sanbao
    orig_attach = NP.attach_bodies
    orig_search = getattr(NP, "search_cnyes_news", None)

    def fake_fetch_sanbao(news_cfg):
        return items if items is not None else make_fake_items(kw)

    def fake_attach_bodies(by_code, *a, **k):
        return 0  # no-op,絕不上網

    def fake_search(keyword, *a, **k):
        return list(search_items or [])  # 絕不上網

    NP.fetch_sanbao = fake_fetch_sanbao
    NP.attach_bodies = fake_attach_bodies
    NP.search_cnyes_news = fake_search
    try:
        res = NC.query_news(keyword=kw, source="sanbao",
                            tag_sentiment=False, **query_kwargs)
    finally:
        NP.fetch_sanbao = orig_fetch
        NP.attach_bodies = orig_attach
        if orig_search is not None:
            NP.search_cnyes_news = orig_search
    return res


def test_dedup():
    kw = "甲積電"   # 專屬 keyword
    res = run_with_patch(kw, days=3, fetch_body=False)
    hits = res["keyword_hits"]
    titles = [h["title"] for h in hits]
    dup_title = f"{kw}訂單滿手出貨暢旺"
    cnt = titles.count(dup_title)
    check("dedup:重複標題只留一則", cnt == 1,
          f"'{dup_title}' 出現 {cnt} 次")
    # 留下的應是 body 較長那筆(去重邏輯保留 body 較豐富者)
    kept = next((h for h in hits if h["title"] == dup_title), None)
    check("dedup:留 body 較長者",
          kept is not None and len(kept.get("body") or "") > len("短內文"),
          f"kept body len={len(kept.get('body') or '') if kept else 'NA'}")


def test_sort_desc():
    kw = "乙積電"
    res = run_with_patch(kw, days=3, fetch_body=False)
    hits = res["keyword_hits"]

    def _dt(s):
        try:
            d = datetime.datetime.fromisoformat((s or "").strip())
            return d if d.tzinfo else d.astimezone()
        except Exception:
            return None
    times = [_dt(h.get("time")) for h in hits if _dt(h.get("time"))]
    desc = all(times[i] >= times[i + 1] for i in range(len(times) - 1))
    check("sort:依時間倒序(新→舊)", desc,
          f"times={[str(t)[:10] for t in times]}")
    # 最新那筆(法說會,1 天前)在個股新聞裡應排前面
    # (此 case 未開 individual_only,泛大盤也在,但「法說會」是最新個股聞)
    if hits:
        newest = hits[0]
        check("sort:首則為最新時間",
              _dt(newest.get("time")) == max(times) if times else False,
              f"first time={str(newest.get('time'))[:16]}")


def test_time_filter():
    kw = "丙積電"
    res = run_with_patch(kw, days=3, fetch_body=False)
    titles = [h["title"] for h in res["keyword_hits"]]
    # 40 天前那筆,遠超 cutoff(now - max(3,10)=10 日),應被濾掉
    old_title = f"{kw}去年舊聞不該出現"
    check("time_filter:超範圍舊聞被濾掉", old_title not in titles,
          f"titles={titles}")
    # 而近期的個股新聞(1/2/5 天前)應留著
    check("time_filter:近期新聞保留",
          f"{kw}法說會今登場" in titles
          and f"{kw}獲利成長動能強" in titles,
          f"titles={titles}")


def test_individual_only():
    kw = "丁積電"
    # 開 individual_only:泛大盤標題應被濾掉
    res = run_with_patch(kw, days=3, fetch_body=False, individual_only=True)
    titles = [h["title"] for h in res["keyword_hits"]]
    check("individual_only:台股收盤被濾掉",
          "台股收盤跌200點 量能萎縮" not in titles, f"titles={titles}")
    check("individual_only:三大法人賣超被濾掉",
          "三大法人賣超百億 外資賣超居多" not in titles, f"titles={titles}")
    # 個股新聞應保留
    check("individual_only:個股新聞保留",
          f"{kw}法說會今登場" in titles, f"titles={titles}")

    # 對照組:不開 individual_only → 泛大盤新聞應出現(命中 kw 在 summary/body)
    kw2 = "戊積電"
    res2 = run_with_patch(kw2, days=3, fetch_body=False)
    titles2 = [h["title"] for h in res2["keyword_hits"]]
    check("individual_only=False:泛大盤新聞保留",
          "台股收盤跌200點 量能萎縮" in titles2
          or "三大法人賣超百億 外資賣超居多" in titles2,
          f"titles2={titles2}")


def test_no_network_isolation():
    """確認 source='sanbao' + patch 後,by_code 為空(沒去碰 metabase),
    且回傳結構合法。"""
    kw = "己積電"
    res = run_with_patch(kw, days=3, fetch_body=False)
    check("isolation:回傳是 dict 且含兩鍵",
          isinstance(res, dict)
          and "by_code" in res and "keyword_hits" in res,
          f"keys={sorted(res.keys()) if isinstance(res, dict) else res}")
    check("isolation:by_code 空(未碰 metabase)",
          res["by_code"] == {}, f"by_code={res['by_code']}")
    check("isolation:keyword_hits 非空(假資料有命中)",
          len(res["keyword_hits"]) > 0,
          f"len={len(res['keyword_hits'])}")
    # 每則 schema 應含契約 6 鍵
    NEWS_KEYS = {"time", "title", "source", "url", "summary", "body"}
    bad = [h for h in res["keyword_hits"]
           if not NEWS_KEYS <= set(h.keys())]
    check("isolation:每則含契約 6 鍵", not bad,
          f"違反 {len(bad)} 則" if bad else "")


def test_patch_restored():
    """測完後 fetch_sanbao / attach_bodies 應還原為原始函式。"""
    check("restore:fetch_sanbao 已還原",
          NP.fetch_sanbao.__name__ == "fetch_sanbao",
          f"got {NP.fetch_sanbao.__name__}")
    check("restore:attach_bodies 已還原",
          NP.attach_bodies.__name__ == "attach_bodies",
          f"got {NP.attach_bodies.__name__}")
    check("restore:search_cnyes_news 已還原",
          NP.search_cnyes_news.__name__ == "search_cnyes_news",
          f"got {NP.search_cnyes_news.__name__}")


# --------------------------------------------------------------------------- #
# 2026-10-09 新增:快取時間戳/磁碟快取、AND、snippets、--intl、cnyes 搜尋腿、時間正確性
# --------------------------------------------------------------------------- #

def _item(title, body="", category="", days_ago=1, source="cnyes", url=None):
    return {"source": source, "title": title, "summary": "", "body": body,
            "url": url or f"http://fake/{abs(hash(title))}",
            "published_at": _iso(days_ago), "keywords": [], "category": category}


def test_match_all_and_snippets():
    kw1, kw2 = "庚積電", "產能極限"
    long_body = ("前言" * 300) + f"{kw1}執行長示警{kw2}恐延續到明年" + ("結語" * 50)
    items = [
        _item(f"{kw1}談{kw2}", body=long_body),          # 兩個都有
        _item(f"{kw1}月營收創高", body="與產能無關"),      # 只有 kw1
    ]
    res_or = run_with_patch(f"{kw1},{kw2}", items=items, days=3, fetch_body=False)
    res_and = run_with_patch(f"{kw1},{kw2}", items=items, days=3, fetch_body=False,
                             match_all=True)
    check("match_all:OR 預設兩則都命中", len(res_or["keyword_hits"]) == 2,
          f"got {len(res_or['keyword_hits'])}")
    titles_and = [h["title"] for h in res_and["keyword_hits"]]
    check("match_all:AND 只留兩詞都出現者", titles_and == [f"{kw1}談{kw2}"],
          f"got {titles_and}")
    hit = res_and["keyword_hits"][0] if res_and["keyword_hits"] else {}
    sn = hit.get("snippets") or []
    check("snippets:內文第 600 字後的命中也抓得到",
          bool(sn) and any(kw2 in s for s in sn) and len(sn) <= 3,
          f"snippets={sn}")
    check("snippets:片段長度受控(前後 60 字)",
          all(len(s) <= 60 * 2 + len(kw1) + len(kw2) + 20 for s in sn),
          f"lens={[len(s) for s in sn]}")
    check("契約:新增欄位不影響原 6 鍵 + code/name",
          {"time", "title", "source", "url", "summary", "body", "code", "name"}
          <= set(hit.keys()), f"keys={sorted(hit.keys())}")


def test_intl_and_cnyes_search_leg():
    kw = "辛非農"
    items = [
        _item(f"{kw}就業數據優於預期", category="國際焦點"),
        _item(f"{kw}概念股走強", category="台股"),
    ]
    search = [{"source": "cnyes-search", "title": f"聯準會會議紀要提到{kw}",
               "summary": "", "body": f"…{kw}就業…", "url": "http://fake/cs1",
               "published_at": _iso(1), "category": "美股雷達", "keywords": []},
              {"source": "cnyes-search", "title": "完全無關的標題",
               "summary": "", "body": "沒有關鍵字", "url": "http://fake/cs2",
               "published_at": _iso(1), "category": "美股雷達", "keywords": []}]
    res = run_with_patch(kw, items=items, search_items=search, days=3, fetch_body=False)
    srcs = sorted(h["source"] for h in res["keyword_hits"])
    check("cnyes 搜尋腿:命中者併入、未含關鍵字者濾掉",
          srcs.count("cnyes-search") == 1 and len(srcs) == 3, f"srcs={srcs}")
    res_i = run_with_patch(kw, items=items, search_items=search, days=3,
                           fetch_body=False, intl=True)
    cats = sorted(h.get("category") for h in res_i["keyword_hits"])
    check("intl:只留國際/總經分類", cats == ["國際焦點", "美股雷達"], f"cats={cats}")


def test_mb_time():
    check("_mb_time:假 Z 改 +08:00",
          NC._mb_time("2026-10-09T18:21:19Z") == "2026-10-09T18:21:19+08:00",
          NC._mb_time("2026-10-09T18:21:19Z"))
    check("_mb_time:已帶時區不動",
          NC._mb_time("2026-10-09T18:21:19+08:00") == "2026-10-09T18:21:19+08:00")
    d = datetime.datetime.fromisoformat(NC._mb_time("2026-10-09T18:21:19Z"))
    check("_mb_time:解析後是台北 18:21 而非隔天 02:21",
          d.astimezone(NC.TAIPEI).strftime("%m-%d %H:%M") == "10-09 18:21",
          d.isoformat())


def test_prev_business_day_holiday():
    D = datetime.date
    check("前一交易日:10/12(一)跳過 10/09 補假與週末 → 10/08",
          NC._prev_business_day(D(2026, 10, 12)) == D(2026, 10, 8),
          str(NC._prev_business_day(D(2026, 10, 12))))
    check("前一交易日:10/13(二) → 10/12",
          NC._prev_business_day(D(2026, 10, 13)) == D(2026, 10, 12))
    now = datetime.datetime(2026, 10, 12, 7, 40, tzinfo=NC.TAIPEI)
    cutoff, prev = NC.market_session_cutoff(now)
    check("盤前窗下界:10/12 07:40 → 10/08 14:00 台北",
          cutoff.isoformat() == "2026-10-08T14:00:00+08:00" and prev == D(2026, 10, 8),
          cutoff.isoformat())


def test_sanbao_cache_timestamp_and_disk():
    """回歸:時間戳要記在抓完之後(抓取 > TTL 時舊版快取一出生就過期);
    磁碟快取跨進程共用;被 monkeypatch 的假抓取不碰磁碟。"""
    import types
    import tempfile
    import time as _time
    tmpdir = pathlib.Path(tempfile.mkdtemp())
    orig_disk, orig_ttl = NC._SB_DISK, NC._cache_ttl
    calls = {"n": 0}

    def slow_fetch(n):
        calls["n"] += 1
        _time.sleep(1.5)
        return [{"source": "cnyes", "title": "快取測試", "url": "http://fake/c"}]
    slow_fetch.__module__ = "fake_np"
    fake_np = types.SimpleNamespace(__name__="fake_np", fetch_sanbao=slow_fetch)
    n = NC.news_cfg()
    try:
        NC._SB_DISK = tmpdir / ".sanbao_cache.json"
        NC._cache_ttl = lambda: 1                      # TTL 1 秒 < 抓取 1.5 秒
        with NC._SB_LOCK:
            NC._SB_CACHE.clear()
        NC._fetch_sanbao_cached(fake_np, n)
        NC._fetch_sanbao_cached(fake_np, n)            # 抓完立刻再查,應命中記憶體
        check("cache:抓取比 TTL 久時,抓完立即再查仍命中(時間戳記在抓完後)",
              calls["n"] == 1, f"fetch 次數={calls['n']}")
        check("cache:磁碟快取檔已寫出", NC._SB_DISK.exists())
        with NC._SB_LOCK:
            NC._SB_CACHE.clear()                       # 模擬另一個進程(記憶體空)
        got = NC._fetch_sanbao_cached(fake_np, n)
        check("cache:記憶體空時讀磁碟快取,不重抓",
              calls["n"] == 1 and got and got[0]["title"] == "快取測試",
              f"fetch 次數={calls['n']}")
        _time.sleep(1.1)                               # 過期
        with NC._SB_LOCK:
            NC._SB_CACHE.clear()
        NC._fetch_sanbao_cached(fake_np, n)
        check("cache:過期後重抓", calls["n"] == 2, f"fetch 次數={calls['n']}")
        NC.clear_news_cache()
        check("cache:clear_news_cache() 預設不刪磁碟(單元測試不清正式快取)",
              NC._SB_DISK.exists())
        NC.clear_news_cache(disk=True)
        check("cache:clear_news_cache(disk=True) 連磁碟一起清", not NC._SB_DISK.exists())
        # 被 patch 的假抓取(__module__ 不同)不讀不寫磁碟

        def patched(n):
            return [{"source": "x", "title": "假資料", "url": "http://fake/p"}]
        fake_np2 = types.SimpleNamespace(__name__="fake_np", fetch_sanbao=patched)
        with NC._SB_LOCK:
            NC._SB_CACHE.clear()
        NC._fetch_sanbao_cached(fake_np2, n)
        check("cache:monkeypatch 的假抓取不寫磁碟", not NC._SB_DISK.exists())
        # 抓取整批失敗回空清單時不落磁碟(避免 15 分鐘內別的進程都拿到 0 則)

        def empty_fetch(n):
            return []
        empty_fetch.__module__ = "fake_np"
        fake_np3 = types.SimpleNamespace(__name__="fake_np", fetch_sanbao=empty_fetch)
        with NC._SB_LOCK:
            NC._SB_CACHE.clear()
        NC._fetch_sanbao_cached(fake_np3, n)
        check("cache:空結果不寫磁碟", not NC._SB_DISK.exists())
    finally:
        NC._SB_DISK, NC._cache_ttl = orig_disk, orig_ttl
        with NC._SB_LOCK:
            NC._SB_CACHE.clear()


def test_codes_without_metabase():
    """沒有 Metabase 的使用者:source=both 自動退成即時流,代號查詢不靠 Metabase 也比對得到
    (離線字典股名、代號字串、出版商標的代號),沒有股名的代號改用代號直取。"""
    _try_clear_cache()
    items = [
        _item("台積電法說會釋利多", body="先進製程需求強"),
        _item("某公司(9999)接獲大單", body="訂單能見度到明年"),
        {**_item("出版商標代號的新聞", body="內文沒寫代號"), "stock_codes": ["9998"]},
        _item("完全無關的新聞", body="沒有代號"),
    ]
    calls = {"metabase": 0, "direct": []}

    def no_metabase(*a, **k):
        calls["metabase"] += 1
        raise RuntimeError("不該呼叫 Metabase")

    def fake_direct(code, name, **k):
        calls["direct"].append((str(code), name))
        return []

    orig = (NP.fetch_sanbao, NP.attach_bodies, NP.prefetch_candidate_bodies,
            NP.fetch_stock_news, NC.get_stock_names, NC.get_news_metabase, NC._MB_OK)
    NP.fetch_sanbao = lambda n: items
    NP.attach_bodies = lambda *a, **k: 0
    NP.prefetch_candidate_bodies = lambda *a, **k: 0
    NP.fetch_stock_news = fake_direct
    NC.get_stock_names = no_metabase
    NC.get_news_metabase = no_metabase
    NC._MB_OK = False                      # 模擬沒有權限或連不上
    try:
        res = NC.query_news(codes=["2330", "9999", "9998"], source="both", days=3,
                            fetch_body=False, tag_sentiment=False)
    finally:
        (NP.fetch_sanbao, NP.attach_bodies, NP.prefetch_candidate_bodies,
         NP.fetch_stock_news, NC.get_stock_names, NC.get_news_metabase, NC._MB_OK) = orig
    bc = res["by_code"]

    def titles(code):
        return [h["title"] for h in bc.get(code, [])]
    check("無 Metabase:source=both 自動退成即時流,沒有呼叫 Metabase",
          calls["metabase"] == 0, f"Metabase 呼叫 {calls['metabase']} 次")
    check("無 Metabase:離線字典股名命中(2330 台積電)",
          titles("2330") == ["台積電法說會釋利多"], f"got {titles('2330')}")
    check("無 Metabase:只有代號字串也命中(9999)",
          titles("9999") == ["某公司(9999)接獲大單"], f"got {titles('9999')}")
    check("無 Metabase:出版商標的代號命中(9998)",
          titles("9998") == ["出版商標代號的新聞"], f"got {titles('9998')}")
    check("無 Metabase:有股名用股名直取,沒有股名改用代號直取",
          ("2330", "台積電") in calls["direct"] and ("9999", "9999") in calls["direct"],
          f"direct={calls['direct']}")


def test_fetch_lock_and_codes_merge():
    """跨進程抓取鎖:別人持鎖時等它寫好磁碟快取直接沿用;代號去重:全文版取代只有標題的 Metabase 版。"""
    import tempfile
    import threading
    import time as _time
    tmpdir = pathlib.Path(tempfile.mkdtemp())
    orig = (NC._SB_DISK, NC._SB_LOCKFILE)
    try:
        NC._SB_DISK = tmpdir / ".sanbao_cache.json"
        NC._SB_LOCKFILE = tmpdir / ".sanbao_fetch.lock"
        got = NC._wait_fetch_lock("k", 60, wait=10)
        check("lock:沒人持鎖時自己拿到鎖", got == (True, None) and NC._SB_LOCKFILE.exists(), str(got))
        threading.Timer(1.2, lambda: NC._disk_cache_save("k", _time.time(), [{"title": "別人抓的"}])).start()
        owned, disk = NC._wait_fetch_lock("k", 60, wait=10)          # 鎖還在 → 等磁碟快取
        check("lock:別人持鎖時等它寫好快取並沿用",
              not owned and disk and disk[1][0]["title"] == "別人抓的", f"owned={owned} disk={disk}")
    finally:
        NC._SB_DISK, NC._SB_LOCKFILE = orig

    title = "台積電法說會登場 重點整理"
    origs = (NC.get_news_metabase, NP.fetch_stock_news)
    NC.get_news_metabase = lambda codes, days: {"2330": [
        {"time": _iso(1), "title": title, "source": "metabase", "url": "", "summary": "", "body": ""}]}
    NP.fetch_stock_news = lambda code, name, **k: [
        {"time": _iso(1), "title": title, "source": "cnyes-search", "url": "http://fake/full",
         "summary": "", "body": "全文內容"}]
    try:
        res = NC.query_news(codes=["2330"], names={"2330": "台積電"}, source="metabase",
                            days=3, fetch_body=False, tag_sentiment=False)
    finally:
        NC.get_news_metabase, NP.fetch_stock_news = origs
    lst = res["by_code"].get("2330", [])
    check("codes 去重:同標題時全文版取代只有標題的 Metabase 版",
          len(lst) == 1 and lst[0]["body"] == "全文內容" and lst[0]["url"], f"got {lst}")


def test_local_stock_name_fallback():
    """離線股名:官方全市場 tw_names.json 優先,其次策展字典,都沒有回空字串。"""
    NP.local_stock_name("2330")                     # 先觸發載入,再換成假清單
    orig = NP._FULL_NAMES
    NP._FULL_NAMES = {"5555": "測試股", "2330": "官方新名"}
    try:
        check("離線股名:全市場清單優先", NP.local_stock_name("2330") == "官方新名",
              NP.local_stock_name("2330"))
        check("離線股名:全市場沒有時查策展字典", NP.local_stock_name("0050") == "元大台灣50",
              NP.local_stock_name("0050"))
        check("離線股名:全市場清單命中", NP.local_stock_name("5555") == "測試股",
              NP.local_stock_name("5555"))
        check("離線股名:都沒有回空字串", NP.local_stock_name("0000") == "",
              repr(NP.local_stock_name("0000")))
    finally:
        NP._FULL_NAMES = orig


def main():
    print("\n=== query_news keyword 分支內部邏輯測試(monkeypatch,不觸網) ===")
    has_clear = any(callable(getattr(NC, n, None))
                    for n in ("clear_news_cache", "_clear_news_cache",
                              "clear_cache", "reset_cache"))
    print(f"  [info] news_core 清快取函式存在: {has_clear} "
          f"(不存在則靠『每 case 不同 keyword』規避快取)")

    print("\n--- 1) 去重 ---")
    test_dedup()
    print("\n--- 2) 排序(時間倒序) ---")
    test_sort_desc()
    print("\n--- 3) 時間過濾 ---")
    test_time_filter()
    print("\n--- 4) individual_only 泛大盤過濾 ---")
    test_individual_only()
    print("\n--- 5) 來源隔離(不碰 metabase / 結構契約) ---")
    test_no_network_isolation()
    print("\n--- 6) AND / snippets ---")
    test_match_all_and_snippets()
    print("\n--- 7) --intl / cnyes 搜尋腿 ---")
    test_intl_and_cnyes_search_leg()
    print("\n--- 8) 時間正確性(Metabase 假 Z / 連假前一交易日) ---")
    test_mb_time()
    test_prev_business_day_holiday()
    print("\n--- 9) 快取時間戳 + 磁碟快取 ---")
    test_sanbao_cache_timestamp_and_disk()
    print("\n--- 10) 沒有 Metabase 的代號查詢 ---")
    test_codes_without_metabase()
    test_local_stock_name_fallback()
    test_fetch_lock_and_codes_merge()
    print("\n--- 11) monkeypatch 還原 ---")
    test_patch_restored()

    ok = sum(1 for _, p, _ in results if p)
    fail = sum(1 for _, p, _ in results if not p)
    print(f"\n=== 結果: {ok}/{len(results)} pass, {fail} fail ===")
    sys.exit(0 if fail == 0 else 1)


if __name__ == "__main__":
    main()
