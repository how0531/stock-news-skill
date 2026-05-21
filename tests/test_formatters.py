# -*- coding: utf-8 -*-
"""
test_formatters.py — news_formatters 純函式測試(餵假資料,不打網路)。

涵蓋函式:
  helper:  _sent_count / _event_count / _source_count / _top_n
  report:  build_report
  render:  render_console / render_markdown
           render_report_console / render_report_md / render_report_json

驗證重點:
  - 計數正確(_sent_count 把無 sentiment 算 neutral;_event_count/_source_count
    依次數降序)
  - _top_n 排序契約:依 abs(confidence) 由大到小,平手用時間較新者在前;
    無 confidence 視為 0、無時間排最後;且只取 N 筆
  - build_report 回傳 schema 完整且各欄位型別/內容正確
  - 各 render 不崩、回傳 str(json render 回 list),且含關鍵字串

退出碼: 全 OK → 0;任一 FAIL → 1。
"""
import sys
import pathlib

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "scripts"))

import news_formatters as F  # noqa: E402

results = []  # (name, ok, msg)


def record(name, ok, msg=""):
    tag = "OK  " if ok else "FAIL"
    print(f"  [{tag}] {name}" + (f" — {msg}" if msg else ""))
    results.append((name, ok, msg))


def check(name, cond, msg=""):
    record(name, bool(cond), msg)
    return bool(cond)


# --------------------------------------------------------------------------- #
# 假資料 — 固定、可預測,覆蓋各種欄位齊全度
# --------------------------------------------------------------------------- #
# 時間用 ISO,刻意讓 confidence 有平手以驗時間 tie-break。
def make_items():
    return [
        {  # 0: bullish 高信心,較舊
            "time": "2026-05-10T09:00:00+08:00",
            "title": "甲公司訂單滿手 獲利大增",
            "source": "cnyes", "url": "http://x/1",
            "summary": "", "body": "內文甲",
            "sentiment": "bullish", "confidence": 0.9,
            "events": ["訂單"],
        },
        {  # 1: bearish 高信心,較新(與 #0 不同信心)
            "time": "2026-05-20T09:00:00+08:00",
            "title": "乙公司踩雷 認列損失",
            "source": "udn", "url": "http://x/2",
            "summary": "", "body": "內文乙較長一點點",
            "sentiment": "bearish", "confidence": 0.8,
            "events": ["踩雷"],
        },
        {  # 2: neutral,confidence 與 #3 平手(0.5),時間較新 → 排在 #3 前
            "time": "2026-05-19T09:00:00+08:00",
            "title": "丙公司召開法說會",
            "source": "ctee", "url": "http://x/3",
            "summary": "摘要丙", "body": "",
            "sentiment": "neutral", "confidence": 0.5,
            "events": ["法說"],
        },
        {  # 3: 與 #2 同 confidence 0.5,時間較舊 → 排在 #2 後
            "time": "2026-05-15T09:00:00+08:00",
            "title": "丁公司股利政策",
            "source": "cnyes", "url": "http://x/4",
            "summary": "", "body": "",
            "sentiment": "bullish", "confidence": 0.5,
            "events": ["股利"],
        },
        {  # 4: 無 sentiment / 無 confidence / 無 time → neutral、conf=0、排最後
            "title": "戊公司無標記新聞",
            "source": "udn", "url": "http://x/5",
            "summary": "", "body": "",
            "events": [],
        },
    ]


def test_sent_count():
    items = make_items()
    sc = F._sent_count(items)
    # bullish: #0,#3 = 2;bearish: #1 = 1;neutral: #2 + #4(無 sentiment)= 2
    check("_sent_count:bullish", sc["bullish"] == 2, f"got {sc['bullish']}")
    check("_sent_count:bearish", sc["bearish"] == 1, f"got {sc['bearish']}")
    check("_sent_count:neutral", sc["neutral"] == 2,
          f"got {sc['neutral']} (含無 sentiment 的 #4)")
    check("_sent_count:keys",
          set(sc.keys()) == {"bullish", "bearish", "neutral"},
          f"keys={sorted(sc.keys())}")


def test_event_count():
    items = make_items()
    # 額外塞一筆讓「訂單」出現 2 次,驗降序
    items.append({"title": "再一筆訂單新聞", "source": "cnyes",
                  "events": ["訂單"], "confidence": 0.1,
                  "time": "2026-05-01T09:00:00+08:00"})
    ec = F._event_count(items)
    d = dict(ec)
    check("_event_count:訂單=2", d.get("訂單") == 2, f"got {d.get('訂單')}")
    check("_event_count:踩雷=1", d.get("踩雷") == 1, f"got {d.get('踩雷')}")
    # 降序:第一個元素 count 應 >= 最後一個
    desc = all(ec[i][1] >= ec[i + 1][1] for i in range(len(ec) - 1))
    check("_event_count:降序", desc, f"counts={[c for _, c in ec]}")
    # 訂單(2)應排在最前
    check("_event_count:top-is-訂單", ec and ec[0][0] == "訂單",
          f"top={ec[0] if ec else None}")


def test_source_count():
    items = make_items()
    sc = F._source_count(items)
    d = dict(sc)
    # cnyes: #0,#3 = 2;udn: #1,#4 = 2;ctee: #2 = 1
    check("_source_count:cnyes=2", d.get("cnyes") == 2, f"got {d.get('cnyes')}")
    check("_source_count:udn=2", d.get("udn") == 2, f"got {d.get('udn')}")
    check("_source_count:ctee=1", d.get("ctee") == 1, f"got {d.get('ctee')}")
    desc = all(sc[i][1] >= sc[i + 1][1] for i in range(len(sc) - 1))
    check("_source_count:降序", desc, f"counts={[c for _, c in sc]}")


def test_top_n():
    items = make_items()
    top = F._top_n(items, n=5)
    check("_top_n:長度<=5", len(top) == 5, f"got {len(top)}")
    confs = [abs(float(it.get("confidence") or 0)) for it in top]
    # 1) 整體 abs(confidence) 非遞增
    nonincr = all(confs[i] >= confs[i + 1] for i in range(len(confs) - 1))
    check("_top_n:confidence 降序", nonincr, f"confs={confs}")
    # 2) 第一名應是 conf 0.9(甲)
    check("_top_n:首位最高信心",
          top[0].get("title", "").startswith("甲"),
          f"top0={top[0].get('title')!r} conf={top[0].get('confidence')}")
    # 3) 末位應是無 confidence 的戊(conf=0)
    check("_top_n:末位最低信心",
          top[-1].get("title", "").startswith("戊"),
          f"last={top[-1].get('title')!r}")
    # 4) tie-break:#2(丙 0.5 新)應排在 #3(丁 0.5 舊)之前
    titles = [it.get("title", "") for it in top]
    i_bing = next(i for i, t in enumerate(titles) if t.startswith("丙"))
    i_ding = next(i for i, t in enumerate(titles) if t.startswith("丁"))
    check("_top_n:平手用時間(新在前)", i_bing < i_ding,
          f"丙 idx={i_bing}, 丁 idx={i_ding} (丙較新應在前)")
    # 5) n 參數生效
    top2 = F._top_n(items, n=2)
    check("_top_n:n=2 截斷", len(top2) == 2, f"got {len(top2)}")


def test_build_report():
    items = make_items()
    rp = F.build_report("2330", "台積電", items, days=7)
    expect_keys = {"code", "name", "days", "total", "sentiment",
                   "events", "sources", "top", "timeline"}
    check("build_report:keys", set(rp.keys()) == expect_keys,
          f"keys={sorted(rp.keys())}")
    check("build_report:code/name/days",
          rp["code"] == "2330" and rp["name"] == "台積電" and rp["days"] == 7,
          f"code={rp['code']} name={rp['name']} days={rp['days']}")
    check("build_report:total", rp["total"] == len(items),
          f"got {rp['total']}")
    check("build_report:sentiment-是dict",
          isinstance(rp["sentiment"], dict)
          and set(rp["sentiment"]) == {"bullish", "bearish", "neutral"},
          f"got {rp['sentiment']}")
    check("build_report:events-是list-of-tuple",
          isinstance(rp["events"], list)
          and all(isinstance(x, tuple) and len(x) == 2 for x in rp["events"]),
          f"got {rp['events']}")
    check("build_report:sources-是list-of-tuple",
          isinstance(rp["sources"], list)
          and all(isinstance(x, tuple) and len(x) == 2 for x in rp["sources"]),
          f"got {rp['sources']}")
    check("build_report:top<=5",
          isinstance(rp["top"], list) and len(rp["top"]) <= 5,
          f"len={len(rp['top'])}")
    # timeline:只含有 events 的(#0-#3 有 events,#4 無)→ 4 筆,且依時間倒序
    tl = rp["timeline"]
    check("build_report:timeline 只含有事件者",
          all(it.get("events") for it in tl) and len(tl) == 4,
          f"len={len(tl)}")
    tl_times = [it.get("time", "") for it in tl]
    desc = all(tl_times[i] >= tl_times[i + 1] for i in range(len(tl_times) - 1))
    check("build_report:timeline 時間倒序", desc, f"times={tl_times}")


def test_build_report_empty():
    """空清單也要回完整 schema,不可崩。"""
    rp = F.build_report("9999", "", [], days=3)
    check("build_report:empty-total0", rp["total"] == 0, f"got {rp['total']}")
    check("build_report:empty-sentiment",
          rp["sentiment"] == {"bullish": 0, "bearish": 0, "neutral": 0},
          f"got {rp['sentiment']}")
    check("build_report:empty-top空", rp["top"] == [], f"got {rp['top']}")
    check("build_report:empty-timeline空",
          rp["timeline"] == [], f"got {rp['timeline']}")


def test_render_console():
    items = make_items()
    res = {"by_code": {"2330": items}, "keyword_hits": []}
    out = F.render_console(res, {"2330": "台積電"})
    check("render_console:是str", isinstance(out, str) and len(out) > 0)
    check("render_console:含個股新聞標題", "個股新聞" in out)
    check("render_console:含代號名稱", "2330" in out and "台積電" in out)
    check("render_console:含新聞標題", "甲公司訂單滿手 獲利大增" in out)
    check("render_console:含事件字串", "事件:" in out)

    # keyword_hits 分支
    kw = {"by_code": {}, "keyword_hits": [
        {"time": "2026-05-20T09:00", "title": "關鍵字命中新聞",
         "source": "cnyes", "url": "http://x/9", "summary": "", "body": "",
         "code": "2330", "name": "台積電",
         "sentiment": "bullish", "confidence": 0.7, "events": ["訂單"]},
    ]}
    out2 = F.render_console(kw)
    check("render_console:含關鍵字命中標頭", "關鍵字命中" in out2)
    check("render_console:含命中標題", "關鍵字命中新聞" in out2)


def test_render_markdown():
    items = make_items()
    res = {"by_code": {"2330": items},
           "keyword_hits": [
               {"time": "2026-05-20T09:00", "title": "命中[含括號]標題",
                "source": "cnyes", "url": "http://x/9", "summary": "",
                "body": "body", "code": "2330", "name": "台積電",
                "sentiment": "bullish", "confidence": 0.7, "events": ["訂單"]},
           ]}
    out = F.render_markdown(res, {"2330": "台積電"})
    check("render_markdown:是str", isinstance(out, str) and len(out) > 0)
    check("render_markdown:含H2", "## " in out)
    check("render_markdown:含個股新聞", "個股新聞" in out)
    check("render_markdown:含關鍵字命中", "關鍵字命中" in out)
    # _md_news_line 會把標題的 [ ] 轉成全形,避免破壞 markdown 連結
    check("render_markdown:中括號被轉全形",
          "命中［含括號］標題" in out,
          "標題的半形[]應被替換為全形［］")
    # 有 url → 應產生 markdown 連結語法
    check("render_markdown:含連結語法", "](http" in out)


def test_render_report_console():
    items = make_items()
    rp = F.build_report("2330", "台積電", items, days=7)
    out = F.render_report_console([rp])
    check("render_report_console:是str", isinstance(out, str) and len(out) > 0)
    check("render_report_console:含報告標題", "個股深度報告" in out)
    check("render_report_console:含Sentiment分布", "Sentiment 分布" in out)
    check("render_report_console:含事件統計", "事件統計" in out)
    check("render_report_console:含來源分布", "來源分布" in out)
    check("render_report_console:含Top", "重要新聞" in out)
    check("render_report_console:含時序事件流", "時序事件流" in out)
    # 空 report 不崩
    empty = F.build_report("9999", "", [], days=3)
    out_e = F.render_report_console([empty])
    check("render_report_console:空report不崩",
          isinstance(out_e, str) and "個股深度報告" in out_e)


def test_render_report_md():
    items = make_items()
    rp = F.build_report("2330", "台積電", items, days=7)
    out = F.render_report_md([rp])
    check("render_report_md:是str", isinstance(out, str) and len(out) > 0)
    check("render_report_md:含H2報告標題", "## 個股深度報告" in out)
    check("render_report_md:含Sentiment分布H3", "### Sentiment 分布" in out)
    check("render_report_md:含表格分隔", "---:" in out)
    check("render_report_md:含事件統計H3", "### 事件統計" in out)
    check("render_report_md:含時序事件流H3", "時序事件流" in out)


def test_render_report_json():
    items = make_items()
    rp = F.build_report("2330", "台積電", items, days=7)
    out = F.render_report_json([rp])
    check("render_report_json:是list", isinstance(out, list) and len(out) == 1)
    j = out[0]
    expect_keys = {"code", "name", "days", "total", "sentiment",
                   "events", "sources", "top", "timeline"}
    check("render_report_json:keys", set(j.keys()) == expect_keys,
          f"keys={sorted(j.keys())}")
    # events / sources 應被轉成 list[dict]
    check("render_report_json:events 轉 dict",
          isinstance(j["events"], list)
          and all(isinstance(x, dict) and {"event", "count"} <= set(x)
                  for x in j["events"]),
          f"got {j['events']}")
    check("render_report_json:sources 轉 dict",
          isinstance(j["sources"], list)
          and all(isinstance(x, dict) and {"source", "count"} <= set(x)
                  for x in j["sources"]),
          f"got {j['sources']}")
    # 可被 json 序列化(timeline/top 都是純 dict)
    import json
    try:
        json.dumps(out, ensure_ascii=False)
        check("render_report_json:可json序列化", True)
    except Exception as e:
        check("render_report_json:可json序列化", False, f"{e!r}")


def main():
    print("\n=== news_formatters 純函式測試 ===")
    print("\n--- helper: _sent_count / _event_count / _source_count ---")
    test_sent_count()
    test_event_count()
    test_source_count()
    print("\n--- helper: _top_n(排序契約) ---")
    test_top_n()
    print("\n--- build_report ---")
    test_build_report()
    test_build_report_empty()
    print("\n--- render: console / markdown ---")
    test_render_console()
    test_render_markdown()
    print("\n--- render: report console / md / json ---")
    test_render_report_console()
    test_render_report_md()
    test_render_report_json()

    ok = sum(1 for _, p, _ in results if p)
    fail = sum(1 for _, p, _ in results if not p)
    print(f"\n=== 結果: {ok}/{len(results)} pass, {fail} fail ===")
    sys.exit(0 if fail == 0 else 1)


if __name__ == "__main__":
    main()
