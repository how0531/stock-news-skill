# -*- coding: utf-8 -*-
"""
test_bullish.py, 新聞利多自選股清單的離線測試。

目前涵蓋:
  1) stock_mentions: 全市場股名反查(標題級 / 內文級、常用詞與主題詞剔除、最長匹配、英數邊界)
  2) news_bullish: 計票、混合排除與排序(vote / score_news)
  3) news_bullish: 組檔、codes 欄位、寫檔、run()(含預設抓取參數)與 news.py --bullish 旗標、結束碼

設計鐵則: 完全不觸網。匯入 news_core 時會讀 config.json(沒有這個檔會直接報錯), 測試本身不依賴它的內容。
退出碼: 全 OK → 0;任一 FAIL → 1。
"""
import sys
import json
import shutil
import pathlib
import tempfile
import datetime

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "scripts"))

import news_core as NC  # noqa: E402
import stock_mentions as SM  # noqa: E402
import news_bullish as NB  # noqa: E402
import storage  # noqa: E402
import update_holidays as UH  # noqa: E402

results = []  # (name, ok, msg)


def record(name, ok, msg=""):
    tag = "OK  " if ok else "FAIL"
    print(f"  [{tag}] {name}" + (f" | {msg}" if msg else ""))
    results.append((name, ok, msg))


def check(name, cond, msg=""):
    record(name, bool(cond), msg)
    return bool(cond)


LEX = SM.build_lexicon(
    {"2408": "南亞科", "1303": "南亞", "2027": "大成鋼", "5347": "世界", "6643": "M31",
     "2330": "台積電", "1459": "聯發", "2454": "聯發科", "5203": "訊連", "8069": "元太"},
    {"2330.TW": {"name_zh": "台積電", "aliases": ["台積電", "TSMC", "2330.TW", "2330"]},
     "2330.TWO": {"name_zh": "台積電", "aliases": ["台積", "護國神山"]},
     "2408.TW": {"name_zh": "南亞科", "aliases": ["DRAM"]},
     "2454.TW": {"name_zh": "聯發科", "aliases": ["聯發", "MTK"]}})


def test_mentions_title_and_body():
    check("標題點名算 title,只在內文算 body",
          SM.find_mentions("南亞科報價調漲", "台積電也受惠", [], LEX) == {"2408": "title", "2330": "body"})


def test_mentions_filters():
    f = SM.find_mentions
    check("最長匹配:聯發科不連帶聯發", f("聯發科法說", "", [], LEX) == {"2454": "title"})
    check("主題詞 DRAM 不算點名", f("DRAM 報價大漲", "", [], LEX) == {})
    check("常用詞股名不算", f("世界經濟展望", "", [], LEX) == {})
    check("常用詞股名靠代號仍命中", f("世界(5347)營收創高", "", [], LEX) == {"5347": "title"})
    check("代號後接年不算", f("2027年展望", "預估 2027 年", [], LEX) == {})
    check("網址裡的括號代號不算", f("", "見 https://x.com/q?c=(2027) 說明", [], LEX) == {})
    check("英數邊界", f("M310 晶片", "", [], LEX) == {} and f("M31 營收", "", [], LEX) == {"6643": "title"})
    check(".TW 與 .TWO 的別名合併", f("台積拿下大單", "", [], LEX) == {"2330": "title"})
    check("英文別名", f("TSMC capex", "", [], LEX) == {"2330": "title"})
    check("別名是他檔簡稱就丟別名", f("聯發公告", "", [], LEX) == {"1459": "title"})
    shared = SM.build_lexicon(
        {"1111": "甲公司", "2222": "乙公司"},
        {"1111.TW": {"name_zh": "甲公司", "aliases": ["共用名"]},
         "2222.TW": {"name_zh": "乙公司", "aliases": ["共用名"]}})
    check("同一別名在兩檔以上全部丟", f("共用名大漲", "", [], shared) == {}
          and f("甲公司大漲", "", [], shared) == {"1111": "title"})


def test_mentions_code_rule():
    f = SM.find_mentions
    # 裸數字不算代號(年度、數量、金額都會長得像)
    check("明（2027）年度不算", f("證交所對明（2027）年度公告", "", [], LEX) == {})
    check("括號代號後接月日也不算", f("（2027）月營收", "", [], LEX) == {} and f("(2027) 日", "", [], LEX) == {})
    check("2027會計年度不算", f("2027會計年度", "", [], LEX) == {})
    check("2027/28年度不算", f("2027/28年度預算", "", [], LEX) == {})
    check("於2027下半年通過不算", f("", "計畫於2027下半年通過", [], LEX) == {})
    check("7萬2027人不算", f("", "約7萬2027人受惠", [], LEX) == {})
    check("數字加空白加元不算", f("", "價格 2027 元", [], LEX) == {})
    check("2027戶不算", f("", "開戶 2027戶", [], LEX) == {})
    # 括號或 -TW 類後綴才算代號
    check("括號代號:半形", f("世界(5347)營收創高", "", [], LEX) == {"5347": "title"})
    check("括號代號:全形", f("大成鋼（2027）", "", [], LEX) == {"2027": "title"})
    check("括號代號:沒有股名也算", f("（2027）漲停", "", [], LEX) == {"2027": "title"})
    check("括號代號:後綴 -TW / .TW / -TWO", f("(2027-TW)", "", [], LEX) == {"2027": "title"}
          and f("(2027.TW)", "", [], LEX) == {"2027": "title"} and f("（2027-TWO）", "", [], LEX) == {"2027": "title"})
    check("後綴代號:大小寫不拘", f("2027-TW 大漲", "", [], LEX) == {"2027": "title"}
          and f("2027.tw 大漲", "", [], LEX) == {"2027": "title"} and f("2027-Two 大漲", "", [], LEX) == {"2027": "title"})
    check("後綴後面不能再黏英數", f("2027-TWD 報價", "", [], LEX) == {})
    check("括號內代號必須在字典裡", f("(9999)", "", [], LEX) == {})
    check("內文括號代號算 body", f("盤勢", "世界(5347)走強", [], LEX) == {"5347": "body"})


def test_mentions_block_terms():
    f = SM.find_mentions
    check("簡訊連結不算訊連", f("簡訊連結勿點", "", [], LEX) == {})
    check("東南亞科技不算南亞科", f("東南亞科技業擴產", "", [], LEX) == {})
    check("元太外匯不算元太", f("元太外匯保證金", "", [], LEX) == {})
    check("訊連科技照常命中", f("訊連科技發表", "", [], LEX) == {"5203": "title"})
    check("元太營收照常命中", f("元太營收創高", "", [], LEX) == {"8069": "title"})
    check("阻擋詞不影響前後文的其他股名", f("簡訊連結 台積電法說", "", [], LEX) == {"2330": "title"})


def test_mentions_publisher_codes():
    f = SM.find_mentions
    check("出版商代號算 body,美股代號忽略", f("盤勢", "", ["2408", "US-NVDA", "NVDA"], LEX) == {"2408": "body"})
    check("出版商代號加標題股名算 title", f("南亞科大漲", "", ["2408"], LEX) == {"2408": "title"})


def test_mentions_missing_fields():
    check("欄位 None 不當掉", SM.find_mentions(None, None, None, LEX) == {})


def test_real_lexicon():
    import json
    lex = SM.load_lexicon()
    names = set(json.loads((BASE / "data/stocks/tw_names.json").read_text(encoding="utf-8")).values())
    curated = json.loads((BASE / "data/stocks/tw_stocks.json").read_text(encoding="utf-8"))
    names |= {v["name_zh"] for v in curated.values()}
    aliases = {a for v in curated.values() for a in v["aliases"]}
    check("常用詞清單每個都是真股名", SM.COMMON_WORD_NAMES <= names, str(SM.COMMON_WORD_NAMES - names))
    check("主題詞清單每個都在別名裡", SM.THEME_ALIASES <= aliases, str(SM.THEME_ALIASES - aliases))
    check("真實字典:南亞科、台積、聯發", lex["terms"].get("南亞科") == "2408"
          and lex["terms"].get("台積") == "2330" and lex["terms"].get("聯發") == "1459")
    check("真實字典:常用詞與主題詞已剔除", "世界" not in lex["terms"] and "DRAM" not in lex["terms"])
    check("真實字典:阻擋詞不對應任何股票", all(lex["terms"].get(t, 1) is None for t in SM.BLOCK_TERMS))


def test_mentions_speed():
    import time
    lex = SM.load_lexicon()
    body = ("台股今日中小型股大漲,華碩與台積電領軍,大立光、中華電走穩。" * 70)[:2000]
    t0 = time.perf_counter()
    for _ in range(200):
        SM.find_mentions("南亞科法說會", body, ["2408"], lex)
    dt = time.perf_counter() - t0
    check("效能:200 則 x 2,000 字 < 3 秒", dt < 3, f"{dt:.2f}s")


def N(title, body="", codes=(), s="bullish", c=0.667, t="2026-10-22T07:00:00+08:00", ev=()):
    return {"time": t, "title": title, "source": "ctee", "url": f"http://x/{title}", "summary": "",
            "body": body, "sentiment": s, "confidence": c, "events": list(ev), "stock_codes": list(codes)}


def test_vote():
    check("利多過門檻", NB.vote(N("a", c=0.5)) == "bull")
    check("利多不過門檻", NB.vote(N("a", c=0.25)) is None)
    check("利空過門檻", NB.vote(N("a", s="bearish")) == "bear")
    check("中性與缺鍵", NB.vote(N("a", s="neutral")) is None and NB.vote({"title": "a"}) is None)


def test_score_basic():
    r = NB.score_news([N("南亞科報價調漲", ev=["訂單"]), N("市場觀察", body="台積電受惠")], LEX)
    codes = [i["code"] for i in r["items"]]
    check("標題級在前", codes == ["2408", "2330"], str(codes))
    top = r["items"][0]
    check("分數與票數", (top["score"], top["title_votes"], top["body_votes"]) == (3, 1, 0), str(top))
    check("reason", top["reason"] == "標題點名 1 則利多（訂單）", top["reason"])


def test_body_cap():
    r = NB.score_news([N("聯發科大漲", body="南亞科、台積電、大成鋼、M31 同步走高")], LEX)
    check("內文超過 3 檔不計票,標題級照算", [i["code"] for i in r["items"]] == ["2454"], str(r["items"]))
    capped = [e for c in r["candidates"] for e in c["evidence"] if c["code"] == "2408"]
    check("被擋的仍在 candidates 且 counted=False", capped and capped[0]["counted"] is False)


def test_body_cap_boundary():
    three = NB.score_news([N("盤勢觀察", body="南亞科、台積電、大成鋼同步走高")], LEX)
    check("內文剛好 3 檔仍計票", sorted(i["code"] for i in three["items"]) == ["2027", "2330", "2408"],
          str(three["items"]))
    four = NB.score_news([N("盤勢觀察", body="南亞科、台積電、大成鋼、M31 同步走高")], LEX)
    check("內文 4 檔不計票", four["items"] == [] and len(four["candidates"]) == 4, str(four["items"]))


def test_mixed_excluded():
    r = NB.score_news([N("南亞科報價調漲"), N("南亞科遭降評", s="bearish")], LEX)
    check("利多利空並存:不列", r["items"] == [] and r["excluded"] == [{"code": "2408", "name": "南亞科", "why": "mixed"}])
    check("並存的仍在 candidates", [c["code"] for c in r["candidates"]] == ["2408"])


def test_rank_title_first():
    news = [N("聯發科報喜")] + [N(f"盤勢{i}", body="台積電受惠") for i in range(4)]
    r = NB.score_news(news, LEX)
    check("標題 1 票(3 分)排在內文 4 票(4 分)前", [i["code"] for i in r["items"]] == ["2454", "2330"])


def test_rank_tie_latest():
    r = NB.score_news([N("南亞科報喜", t="2026-10-22T06:00:00+08:00"),
                       N("聯發科報喜", t="2026-10-22T07:00:00+08:00")], LEX)
    check("同分較新的在前", [i["code"] for i in r["items"]] == ["2454", "2408"])


def test_one_vote_per_article():
    r = NB.score_news([N("南亞科南亞科", body="南亞科再提南亞科"), N("南亞科法說")], LEX)
    top = r["items"][0]
    check("每則只算一票一筆", top["title_votes"] == 2 and len(top["evidence"]) == 2, str(top))


def test_score_missing_fields():
    r = NB.score_news([{"title": None, "body": None}, {"time": None, "title": "南亞科報喜",
                      "sentiment": "bullish", "confidence": 0.667, "stock_codes": ["US-NVDA"]}], LEX)
    check("缺欄位不當掉", [i["code"] for i in r["items"]] == ["2408"], str(r))


def test_snippet():
    r = NB.score_news([N("市場觀察", body="法人指出南亞科第四季報價續漲", s="neutral", c=0.0)], LEX)
    ev = r["candidates"][0]["evidence"][0]
    check("候選附個股片段", "南亞科" in ev["snippet"] and ev["match"] == "body", str(ev))


D = lambda *a: datetime.datetime(*a, tzinfo=NC.TAIPEI)
KEYS = {"schema_version", "status", "trade_date", "next_trade_date", "codes", "generated_at", "window",
        "method", "rule", "items", "excluded", "candidates"}


def test_payload_ok_shape():
    p = NB.make_payload([N("南亞科報價調漲")], D(2026, 10, 22, 7, 50), LEX)
    check("欄位齊全", set(p) == KEYS, str(set(p) ^ KEYS))
    check("狀態與日期", (p["status"], p["trade_date"], p["next_trade_date"]) == ("ok", "2026-10-22", "2026-10-23"))
    check("時間窗", p["window"]["from"] == "2026-10-21T14:00:00+08:00", str(p["window"]))


def test_payload_codes():
    p = NB.make_payload([N("南亞科報價調漲"), N("聯發科報喜", t="2026-10-22T06:00:00+08:00")],
                        D(2026, 10, 22, 7, 50), LEX)
    keys = list(p)
    check("ok 的 codes 等於 items 的代號與順序",
          p["status"] == "ok" and len(p["items"]) == 2 and p["codes"] == [i["code"] for i in p["items"]], str(p["codes"]))
    check("codes 緊接在 next_trade_date 後面", keys.index("codes") == keys.index("next_trade_date") + 1, str(keys))
    empty = NB.make_payload([N("南亞科法說", s="neutral", c=0.0)], D(2026, 10, 22, 7, 50), LEX)
    check("empty 的 codes 是空陣列", empty["status"] == "empty" and empty["codes"] == [])
    zero = NB.make_payload([], D(2026, 10, 22, 7, 50), LEX)
    raw = [{k: v for k, v in N("南亞科報喜").items() if k not in ("sentiment", "confidence", "events")}]
    nosent = NB.make_payload(raw, D(2026, 10, 22, 7, 50), LEX)
    check("error 的 codes 是空陣列", zero["status"] == nosent["status"] == "error" and zero["codes"] == nosent["codes"] == [])


def test_payload_next_trade_date_holiday():
    p = NB.make_payload([N("南亞科報喜")], D(2026, 10, 23, 7, 50), LEX)
    check("週五的下一交易日跳過 10/26 休市", p["next_trade_date"] == "2026-10-27", p["next_trade_date"])


def test_payload_year_rollover():
    saved = (storage._HOLIDAYS, set(storage._HOLIDAY_YEARS), set(storage._MISSING_YEAR_HANDLED), UH.update)
    UH.update = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("離線測試不連網"))
    try:
        p = NB.make_payload([N("南亞科報喜")], D(2026, 12, 31, 7, 50), LEX)
    finally:
        storage._HOLIDAYS, storage._HOLIDAY_YEARS = saved[0], saved[1]
        storage._MISSING_YEAR_HANDLED.clear()
        storage._MISSING_YEAR_HANDLED.update(saved[2])
        UH.update = saved[3]
    check("跨年離線也算得出", p["next_trade_date"] == "2027-01-04", p["next_trade_date"])


def test_payload_empty():
    p = NB.make_payload([N("南亞科法說", s="neutral", c=0.0)], D(2026, 10, 22, 7, 50), LEX)
    check("沒有利多是 empty", p["status"] == "empty" and p["items"] == [])


def test_payload_zero_news():
    p = NB.make_payload([], D(2026, 10, 22, 7, 50), LEX)
    check("零則新聞是 error", p["status"] == "error" and "沒有抓到任何新聞" in p["error"], str(p))


def test_payload_no_sentiment():
    raw = [{k: v for k, v in N("南亞科報喜").items() if k not in ("sentiment", "confidence", "events")}]
    p = NB.make_payload(raw, D(2026, 10, 22, 7, 50), LEX)
    check("沒有情緒標籤是 error", p["status"] == "error", str(p))


def test_run_writes_files():
    tmp = pathlib.Path(tempfile.mkdtemp())
    shared = NC.BASE / "out" / "news_result.json"
    before = shared.stat().st_mtime_ns if shared.exists() else None
    try:
        rc = NB.run(now=D(2026, 10, 22, 7, 50), out_dir=tmp, fetch=lambda: [N("南亞科報價調漲")])
        dated, latest = tmp / "bullish_20261022.json", tmp / "latest.json"
        check("run 回 0 並寫兩個檔", rc == 0 and dated.exists() and latest.exists())
        check("兩檔內容相同", dated.read_bytes() == latest.read_bytes())
        check("清單內容", json.loads(latest.read_text(encoding="utf-8"))["items"][0]["code"] == "2408")
        check("沒動到 news_result.json", (shared.stat().st_mtime_ns if shared.exists() else None) == before)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_run_closed_day():
    tmp = pathlib.Path(tempfile.mkdtemp())
    try:
        rc = NB.run(now=D(2026, 10, 24, 7, 50), out_dir=tmp, fetch=lambda: [N("南亞科報喜")])
        check("休市日回 0 且不寫檔", rc == 0 and not any(tmp.iterdir()))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_run_fetch_error():
    tmp = pathlib.Path(tempfile.mkdtemp())

    def boom():
        raise RuntimeError("缺套件")
    try:
        rc = NB.run(now=D(2026, 10, 22, 7, 50), out_dir=tmp, fetch=boom)
        p = json.loads((tmp / "latest.json").read_text(encoding="utf-8"))
        check("抓取失敗回 1 並寫 error 檔", rc == 1 and p["status"] == "error" and "缺套件" in p["error"], str(p))
        check("error 檔的 codes 是空陣列", p["codes"] == [])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_run_default_fetch_args():
    tmp = pathlib.Path(tempfile.mkdtemp())
    seen = {}

    def fake_fetch(*a, **kw):
        seen["args"], seen["kw"] = a, kw
        return [N("南亞科報價調漲")]
    orig = NC.fetch_market_news
    NC.fetch_market_news = fake_fetch
    try:
        rc = NB.run(now=D(2026, 10, 22, 7, 50), out_dir=tmp)
    finally:
        NC.fetch_market_news = orig
        shutil.rmtree(tmp, ignore_errors=True)
    kw = seen.get("kw", {})
    check("預設抓取明確帶 keep_codes 與 tag_sentiment", rc == 0 and kw.get("keep_codes") is True
          and kw.get("tag_sentiment") is True and kw.get("since") == "last_close", str(seen))


def test_cli_flag():
    import news
    check("--bullish 旗標", news.parse_args(["--bullish"])["bullish"] is True)


def test_cli_exit_code():
    import news
    saved_run, saved_argv = NB.run, sys.argv
    got = {}
    try:
        for rc in (0, 1):
            NB.run = lambda rc=rc: rc
            sys.argv = ["news.py", "--bullish"]
            try:
                news.main()
                got[rc] = "no exit"
            except SystemExit as e:
                got[rc] = e.code
    finally:
        NB.run, sys.argv = saved_run, saved_argv
    check("news.main 的結束碼等於 run() 的回傳", got == {0: 0, 1: 1}, str(got))


def main():
    test_mentions_title_and_body()
    test_mentions_filters()
    test_mentions_code_rule()
    test_mentions_block_terms()
    test_mentions_publisher_codes()
    test_mentions_missing_fields()
    test_real_lexicon()
    test_mentions_speed()
    test_vote()
    test_score_basic()
    test_body_cap()
    test_body_cap_boundary()
    test_mixed_excluded()
    test_rank_title_first()
    test_rank_tie_latest()
    test_one_vote_per_article()
    test_score_missing_fields()
    test_snippet()
    test_payload_ok_shape()
    test_payload_codes()
    test_payload_next_trade_date_holiday()
    test_payload_year_rollover()
    test_payload_empty()
    test_payload_zero_news()
    test_payload_no_sentiment()
    test_run_writes_files()
    test_run_closed_day()
    test_run_fetch_error()
    test_run_default_fetch_args()
    test_cli_flag()
    test_cli_exit_code()
    ok = sum(1 for _, o, _ in results if o)
    fail = len(results) - ok
    print(f"\n=== 結果: {ok}/{len(results)} pass, {fail} fail ===")
    sys.exit(0 if fail == 0 else 1)


if __name__ == "__main__":
    main()
