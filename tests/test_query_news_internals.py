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

def run_with_patch(kw, **query_kwargs):
    """patch fetch_sanbao(回 make_fake_items)+ attach_bodies(no-op),
    跑 query_news(source='sanbao'),回 keyword_hits。finally 還原。"""
    _try_clear_cache()
    orig_fetch = NP.fetch_sanbao
    orig_attach = NP.attach_bodies

    def fake_fetch_sanbao(news_cfg):
        return make_fake_items(kw)

    def fake_attach_bodies(by_code, *a, **k):
        return 0  # no-op,絕不上網

    NP.fetch_sanbao = fake_fetch_sanbao
    NP.attach_bodies = fake_attach_bodies
    try:
        res = NC.query_news(keyword=kw, source="sanbao",
                            tag_sentiment=False, **query_kwargs)
    finally:
        NP.fetch_sanbao = orig_fetch
        NP.attach_bodies = orig_attach
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
    print("\n--- 6) monkeypatch 還原 ---")
    test_patch_restored()

    ok = sum(1 for _, p, _ in results if p)
    fail = sum(1 for _, p, _ in results if not p)
    print(f"\n=== 結果: {ok}/{len(results)} pass, {fail} fail ===")
    sys.exit(0 if fail == 0 else 1)


if __name__ == "__main__":
    main()
