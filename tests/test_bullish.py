# -*- coding: utf-8 -*-
"""
test_bullish.py, 新聞利多自選股清單的離線測試。

目前涵蓋:
  1) stock_mentions: 全市場股名反查(標題級 / 內文級、常用詞與主題詞剔除、最長匹配、英數邊界)
  2) news_bullish: 計票、混合排除與排序(vote / score_news)

設計鐵則: 完全不觸網, 不讀 config.json。
退出碼: 全 OK → 0;任一 FAIL → 1。
"""
import sys
import pathlib

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "scripts"))

import stock_mentions as SM  # noqa: E402
import news_bullish as NB  # noqa: E402

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
     "2330": "台積電", "1459": "聯發", "2454": "聯發科"},
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
    check("網址裡的數字不算", f("", "見 https://x.com/a?id=2027 說明", [], LEX) == {})
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


def main():
    test_mentions_title_and_body()
    test_mentions_filters()
    test_mentions_publisher_codes()
    test_mentions_missing_fields()
    test_real_lexicon()
    test_mentions_speed()
    test_vote()
    test_score_basic()
    test_body_cap()
    test_mixed_excluded()
    test_rank_title_first()
    test_rank_tie_latest()
    test_one_vote_per_article()
    test_score_missing_fields()
    test_snippet()
    ok = sum(1 for _, o, _ in results if o)
    fail = len(results) - ok
    print(f"\n=== 結果: {ok}/{len(results)} pass, {fail} fail ===")
    sys.exit(0 if fail == 0 else 1)


if __name__ == "__main__":
    main()
