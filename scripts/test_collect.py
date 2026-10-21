"""搜集層純邏輯測試 — common / twse_announce / watch_intraday / process_day / 假日 PIT。"""
from __future__ import annotations

import inspect
import types
from datetime import datetime

import pandas as pd

import common
import ctee
import healthcheck
import process_day
import rss_sources
import site_map
import storage
import udn
import watch_intraday
from ctee import _url_date_iso
from rss_sources import SOURCES as RSS_SOURCES_KEYS
from twse_announce import _roc_to_iso


# --------------------------------------------------------------------------- #
# common
# --------------------------------------------------------------------------- #

def test_to_taipei_iso():
    # epoch -> 台北時間
    assert common.to_taipei_iso(1781249405) == "2026-06-12T15:30:05+08:00"
    # naive 字串視為台北時間
    assert common.to_taipei_iso("2026-06-12 15:30:05") == "2026-06-12T15:30:05+08:00"
    # aware 字串換算成台北時間（UTC 07:30 = 台北 15:30）
    assert common.to_taipei_iso("2026-06-12T07:30:05+00:00") == "2026-06-12T15:30:05+08:00"
    # 無法解析 / 空值
    assert common.to_taipei_iso("not a date") == ""
    assert common.to_taipei_iso("") == ""
    assert common.to_taipei_iso(None) == ""


def test_html_to_text():
    assert common.html_to_text("<p>第一段</p><p>第二段</p>") == "第一段\n第二段"
    assert common.html_to_text("") == ""


def test_extract_author_from_entry():
    assert common.extract_author_from_entry({"author": " 記者王小明 "}) == "記者王小明"
    assert common.extract_author_from_entry({"authors": [{"name": "李四"}]}) == "李四"
    assert common.extract_author_from_entry({"dc_creator": "張三"}) == "張三"
    assert common.extract_author_from_entry({"title": "無作者"}) == ""


def test_parse_article_fields_meta_and_body():
    html = """
    <html><head>
      <meta name="author" content="陳記者">
      <meta property="og:description" content="這是摘要">
    </head><body>
      <div class="entry-content"><p>內文第一段</p><p>內文第二段</p></div>
    </body></html>
    """
    r = common.parse_article_fields(html)
    assert r["author"] == "陳記者"
    assert r["summary"] == "這是摘要"
    assert r["content"] == "內文第一段\n內文第二段"


def test_parse_article_fields_byline_fallback_and_custom_selector():
    html = """
    <html><body>
      <span class="byline">本報訊</span>
      <div class="article-body"><p>客製選擇器內文</p></div>
    </body></html>
    """
    r = common.parse_article_fields(html, body_selectors=["div.article-body"])
    assert r["author"] == "本報訊"
    assert r["content"] == "客製選擇器內文"


def test_norm_title():
    assert common.norm_title("台積電 法說會！(獨家)") == "台積電法說會獨家"
    assert common.norm_title("TSMC Beats  Estimates") == "tsmcbeatsestimates"
    assert common.norm_title("") == ""
    # 同文轉載：標點/空白差異不影響 key
    a = common.norm_title("〈焦點股〉台積電爆量上攻")
    b = common.norm_title("焦點股：台積電爆量上攻")
    assert a == b


# --------------------------------------------------------------------------- #
# twse_announce
# --------------------------------------------------------------------------- #

def test_roc_to_iso():
    assert _roc_to_iso("1150612", "133005") == "2026-06-12T13:30:05+08:00"
    assert _roc_to_iso("115/06/12", "13:30:05") == "2026-06-12T13:30:05+08:00"
    assert _roc_to_iso("20260612", "") == "2026-06-12T00:00:00+08:00"
    assert _roc_to_iso("", "") == ""
    assert _roc_to_iso("garbage", "12") == ""


# --------------------------------------------------------------------------- #
# watch_intraday
# --------------------------------------------------------------------------- #

def test_classify():
    assert watch_intraday.classify("盤中速報 - 台積電急拉") == ["noise_intraday_tick"]
    assert watch_intraday.classify("鉅亨速報 - Factset 最新調查") == ["signal_target_price"]
    assert watch_intraday.classify("[重大訊息] 台積電(2330) 澄清") == ["signal_announcement"]
    assert watch_intraday.classify("一般新聞標題") == []


def test_match_tickers():
    idx = [("台積電", "2330.TW"), ("台積", "2330.TW"), ("鴻海", "2317.TW")]
    idx.sort(key=lambda p: len(p[0]), reverse=True)
    assert watch_intraday.match_tickers("台積電與鴻海同步上漲", idx) == ["2330.TW", "2317.TW"]
    assert watch_intraday.match_tickers("與個股無關", idx) == []


def test_item_keys_dedupe_reprint():
    a = {"url": "https://a/1", "title": "〈焦點股〉台積電爆量上攻"}
    b = {"url": "https://b/2", "title": "焦點股：台積電爆量上攻"}  # 轉載，URL 不同
    keys_a, keys_b = watch_intraday.item_keys(a), watch_intraday.item_keys(b)
    assert keys_a[0] != keys_b[0]          # URL key 不同
    assert keys_a[1] == keys_b[1]          # 標題 key 相同 -> 會被去重


def test_in_market_hours_taipei():
    assert watch_intraday.in_market_hours(datetime(2026, 6, 12, 10, 0))      # 週五盤中
    assert not watch_intraday.in_market_hours(datetime(2026, 6, 13, 10, 0))  # 週六
    assert not watch_intraday.in_market_hours(datetime(2026, 6, 12, 14, 0))  # 收盤後


def test_build_event_carries_unified_fields():
    """串流事件需帶 author/summary/content，與日終 processed 統一格式對齊。"""
    item = {
        "source": "announce_twse", "category": "上市重大訊息",
        "title": "[重大訊息] 台積電(2330) 澄清", "author": "台積電(2330)",
        "summary": "本公司澄清媒體報導", "content": "本公司澄清媒體報導全文……",
        "url": "https://mops/x", "published_at": "2026-06-12T14:10:00+08:00",
    }
    ev = watch_intraday.build_event(
        item, event_id="20260612141000-0001",
        ingestion_iso="2026-06-12T14:11:00+08:00",
        tickers=["2330.TW"], tags=["signal_announcement"],
    )
    assert ev["author"] == "台積電(2330)"
    assert ev["content"] == "本公司澄清媒體報導全文……"
    assert ev["publish_ts"] == "2026-06-12T14:10:00+08:00"
    assert ev["tickers"] == ["2330.TW"]


# --------------------------------------------------------------------------- #
# storage: 假日感知 actionable_ts
# --------------------------------------------------------------------------- #

def test_actionable_ts_holiday_aware():
    # 2026-01-01（週四，元旦休市）盤中發布 -> 1/2（週五）開盤
    assert storage.compute_actionable_ts(datetime(2026, 1, 1, 10, 0)) == datetime(2026, 1, 2, 9, 0)
    # 春節前最後交易日（2/13 週五）盤後 -> 跳過 2/16-2/20 連假與週末 -> 2/23（週一）開盤
    assert storage.compute_actionable_ts(datetime(2026, 2, 13, 20, 0)) == datetime(2026, 2, 23, 9, 0)
    # 連假中（2/18 週三）發布 -> 2/23（週一）開盤
    assert storage.compute_actionable_ts(datetime(2026, 2, 18, 10, 0)) == datetime(2026, 2, 23, 9, 0)
    # 一般交易日規則不受影響
    assert storage.compute_actionable_ts(datetime(2026, 6, 12, 7, 0)) == datetime(2026, 6, 12, 9, 0)


# --------------------------------------------------------------------------- #
# process_day
# --------------------------------------------------------------------------- #

def test_build_records_dedupe_and_pit():
    idx = [("台積電", "2330.TW")]
    items = [
        {  # raw 項目（無 tickers/tags，現算）；帶 author/content
            "source": "cnyes", "category": "台股",
            "title": "台積電法說會釋出樂觀展望", "author": "鉅亨網記者",
            "summary": "", "content": "台積電今日召開法說會……",
            "url": "https://a/1", "published_at": "2026-06-12T10:00:00+08:00",
        },
        {  # 同文轉載（標題同、URL 不同、發布較晚）-> 應被去重，保留較早那筆
            "source": "yahoo_stock", "category": "台股",
            "title": "台積電法說會釋出樂觀展望！", "summary": "",
            "url": "https://b/2", "published_at": "2026-06-12T10:30:00+08:00",
        },
        {  # stream 事件（已帶 tickers/tags，沿用不重算；經 load_day_items 正規化為 published_at）
            "source": "announce_twse", "category": "上市重大訊息",
            "title": "[重大訊息] 台積電(2330) 澄清", "summary": "",
            "url": "https://mops/x", "published_at": "2026-06-12T14:10:00+08:00",
            "ingestion_ts": "2026-06-12T14:11:00+08:00",
            "tickers": ["2330.TW"], "tags": ["signal_announcement"],
        },
    ]
    df = process_day.build_records(
        items, default_ingestion=datetime(2026, 6, 12, 16, 0), alias_index=idx
    )
    assert len(df) == 2  # 轉載被去重
    for col in storage.PROCESSED_REQUIRED:
        assert col in df.columns

    row_news = df[df["source"] == "cnyes"].iloc[0]
    assert row_news["tickers"] == ["2330.TW"]
    # author/content 透傳至 processed
    assert row_news["author"] == "鉅亨網記者"
    assert row_news["content"] == "台積電今日召開法說會……"
    # Tier 1 去重：同標題轉載的 yahoo_stock 記入 also_reported_by
    assert row_news["also_reported_by"] == ["yahoo_stock"]
    # 盤中發布 -> 當日 13:30 可行動
    assert row_news["actionable_ts"] == pd.Timestamp(2026, 6, 12, 13, 30)

    row_ann = df[df["source"] == "announce_twse"].iloc[0]
    # 盤後發布 -> 次一交易日 09:00（6/12 週五 -> 6/15 週一）
    assert row_ann["actionable_ts"] == pd.Timestamp(2026, 6, 15, 9, 0)
    # PIT 不變量：ingestion >= publish
    assert (df["ingestion_ts"] >= df["publish_ts"]).all()
    # 通過 storage 的 schema/PIT 驗證
    storage.validate_schema(df, "processed")


def test_ctee_url_date_iso():
    # URL 內嵌 8 碼日期 -> 台北時間日粒度 ISO
    url = "https://www.ctee.com.tw/news/20260612123456-430701"
    assert _url_date_iso(url) == "2026-06-12T00:00:00+08:00"
    # 無日期樣式 -> 空字串
    assert _url_date_iso("https://www.ctee.com.tw/livenews") == ""


# --------------------------------------------------------------------------- #
# healthcheck
# --------------------------------------------------------------------------- #

def test_healthcheck_probe_success():
    r = healthcheck.probe(
        "demo",
        lambda: [{"title": "標題A", "published_at": "2026-06-12T10:00:00+08:00"},
                 {"title": "標題B", "published_at": ""}],
    )
    assert r["ok"] and r["count"] == 2 and r["with_ts"] == 1
    assert r["detail"] == "標題A"


def test_healthcheck_probe_handles_exception():
    def boom():
        raise RuntimeError("403 Forbidden")
    r = healthcheck.probe("demo", boom)
    assert not r["ok"] and r["count"] == 0
    assert "403 Forbidden" in r["detail"]


def test_healthcheck_probe_empty_is_not_ok():
    r = healthcheck.probe("demo", lambda: [])
    assert not r["ok"] and r["count"] == 0


def test_healthcheck_build_probes_selection():
    # 指定來源只組出該來源；未指定則涵蓋固定來源 + 所有 RSS
    only = healthcheck.build_probes({"cnyes"})
    assert [label for label, _ in only] == ["cnyes"]
    all_labels = [label for label, _ in healthcheck.build_probes(set())]
    assert {"cnyes", "udn", "ctee", "announce"}.issubset(set(all_labels))
    assert set(RSS_SOURCES_KEYS).issubset(set(all_labels))


# --------------------------------------------------------------------------- #
# site_map: Phase 2 結構地圖
# --------------------------------------------------------------------------- #

def test_rss_body_selectors_wellformed():
    """已登記的 body_selectors 必為非空字串列表（fallback 結尾應含泛用選擇器）。"""
    from rss_sources import SOURCES
    for sid, conf in SOURCES.items():
        sels = conf.get("body_selectors")
        if sels is None:
            continue
        assert isinstance(sels, list) and sels, f"{sid}: body_selectors 應為非空 list"
        assert all(isinstance(s, str) and s.strip() for s in sels), f"{sid}: 選擇器須為非空字串"
        # 結尾保留泛用 fallback，避免站別選擇器失準時抓不到內文
        assert sels[-1] in {"article", "main"}, f"{sid}: 建議以 article/main 收尾作 fallback"


def test_site_maps_all_valid():
    """已交付的 site_maps 全部通過 schema/一致性驗證。"""
    maps = site_map.load_all()
    assert maps, "data/site_maps 應至少有一份地圖"
    problems = site_map.validate(maps)
    assert problems == [], f"site_map 驗證未通過: {problems}"


def test_site_maps_cover_registered_rss_sources():
    """每個 rss_sources 註冊來源都要有對應 site_map。"""
    maps = site_map.load_all()
    assert set(RSS_SOURCES_KEYS).issubset(set(maps)), \
        f"缺少 site_map 的 RSS 來源: {set(RSS_SOURCES_KEYS) - set(maps)}"
    # 固定來源也要在
    assert {"cnyes", "udn", "ctee", "twse"}.issubset(set(maps))


def test_site_map_build_index():
    maps = site_map.load_all()
    index = site_map.build_index(maps)
    assert index["n_sources"] == len(maps)
    assert index["n_verified_live"] == sum(1 for m in maps.values() if m.get("verified_live"))
    assert all("stock_relevant_columns" in s for s in index["sources"])


# --------------------------------------------------------------------------- #
# process_day: Tier 2 去重（內文指紋，標題改寫但同文轉載）
# --------------------------------------------------------------------------- #

_LONG_CONTENT = (
    "台積電法說會釋出樂觀展望，三大法人齊聲喊買，外資加碼力道強勁，"
    "目標價上看千元大關不是夢，市場人士分析後續走勢仍偏多操作為主，後市可期"
)


def test_content_fingerprint_min_length():
    assert process_day._content_fingerprint("太短的內文") == ""
    fp = process_day._content_fingerprint(_LONG_CONTENT)
    assert len(fp) == process_day.FINGERPRINT_LEN


def test_build_records_tier2_dedup_reworded_title_same_content():
    items = [
        {  # 原始報導
            "source": "cna", "category": "財經",
            "title": "台積電法說會展望樂觀", "content": _LONG_CONTENT,
            "summary": "", "url": "https://cna/1",
            "published_at": "2026-06-12T10:00:00+08:00",
        },
        {  # yahoo 引用同篇全文、標題改寫，發布較晚 -> 應依內文指紋合併
            "source": "yahoo_stock", "category": "台股",
            "title": "外資喊買台積電 目標價上看千元", "content": _LONG_CONTENT,
            "summary": "", "url": "https://yahoo/2",
            "published_at": "2026-06-12T11:00:00+08:00",
        },
    ]
    df = process_day.build_records(
        items, default_ingestion=datetime(2026, 6, 12, 12, 0), alias_index=[]
    )
    assert len(df) == 1
    row = df.iloc[0]
    assert row["source"] == "cna"  # 較早發布者為主
    assert row["also_reported_by"] == ["yahoo_stock"]


def test_build_records_tier2_dedup_outside_window_not_merged():
    items = [
        {
            "source": "cna", "category": "財經",
            "title": "台積電法說會展望樂觀", "content": _LONG_CONTENT,
            "summary": "", "url": "https://cna/1",
            "published_at": "2026-06-01T10:00:00+08:00",
        },
        {  # 3 天後舊聞重炒，超出 48 小時去重時間窗 -> 視為各自獨立事件
            "source": "yahoo_stock", "category": "台股",
            "title": "外資喊買台積電 目標價上看千元", "content": _LONG_CONTENT,
            "summary": "", "url": "https://yahoo/2",
            "published_at": "2026-06-04T10:00:00+08:00",
        },
    ]
    df = process_day.build_records(
        items, default_ingestion=datetime(2026, 6, 4, 12, 0), alias_index=[]
    )
    assert len(df) == 2
    assert (df["also_reported_by"].apply(len) == 0).all()


def test_build_records_tier1_dedup_populates_also_reported_by():
    """Tier 1（標題正規化相同）去重也要把其他來源記入 also_reported_by。"""
    items = [
        {  # 原始報導，發布較早 -> 留存
            "source": "cnyes", "category": "台股",
            "title": "台積電法說會展望樂觀", "content": "短內文", "summary": "",
            "url": "https://cnyes/1", "published_at": "2026-06-12T10:00:00+08:00",
        },
        {  # 同標題（差一個驚嘆號，正規化後相同）轉載，發布較晚 -> 併入主筆
            "source": "yahoo_stock", "category": "台股",
            "title": "台積電法說會展望樂觀！", "content": "短內文", "summary": "",
            "url": "https://yahoo/2", "published_at": "2026-06-12T11:00:00+08:00",
        },
    ]
    df = process_day.build_records(
        items, default_ingestion=datetime(2026, 6, 12, 12, 0), alias_index=[]
    )
    assert len(df) == 1
    row = df.iloc[0]
    assert row["source"] == "cnyes"  # 較早發布者為主
    assert row["also_reported_by"] == ["yahoo_stock"]


def test_build_records_tier1_and_tier2_also_reported_by_union():
    """Tier 1 與 Tier 2 同時命中時，also_reported_by 取聯集（含 Tier 1 帶上來的來源）。"""
    items = [
        {  # 原始報導
            "source": "cnyes", "category": "台股",
            "title": "原始標題", "content": _LONG_CONTENT, "summary": "",
            "url": "https://cnyes/1", "published_at": "2026-06-12T10:00:00+08:00",
        },
        {  # 與 cnyes 同標題 -> Tier 1 併入
            "source": "yahoo_stock", "category": "台股",
            "title": "原始標題！", "content": "短", "summary": "",
            "url": "https://yahoo/2", "published_at": "2026-06-12T10:15:00+08:00",
        },
        {  # 標題改寫但同內文 -> Tier 2 併入
            "source": "udn", "category": "財經",
            "title": "改寫後的標題", "content": _LONG_CONTENT, "summary": "",
            "url": "https://udn/3", "published_at": "2026-06-12T10:30:00+08:00",
        },
        {  # 與 udn 同標題 -> 先 Tier 1 併入 udn，再隨 udn 經 Tier 2 傳遞上來
            "source": "ettoday", "category": "財經",
            "title": "改寫後的標題！", "content": "短2", "summary": "",
            "url": "https://ettoday/4", "published_at": "2026-06-12T10:45:00+08:00",
        },
    ]
    df = process_day.build_records(
        items, default_ingestion=datetime(2026, 6, 12, 12, 0), alias_index=[]
    )
    assert len(df) == 1
    row = df.iloc[0]
    assert row["source"] == "cnyes"  # 全部合併到最早發布者
    assert row["also_reported_by"] == ["ettoday", "udn", "yahoo_stock"]


def test_build_records_clock_skew_clamp():
    # 來源時鐘快於我們：ingestion 被校正為不早於 publish
    items = [{
        "source": "cnyes", "category": "台股", "title": "時鐘誤差測試",
        "summary": "", "url": "https://a/9",
        "published_at": "2026-06-12T10:00:00+08:00",
    }]
    df = process_day.build_records(
        items, default_ingestion=datetime(2026, 6, 12, 9, 59), alias_index=[]
    )
    assert df.iloc[0]["ingestion_ts"] == pd.Timestamp(2026, 6, 12, 10, 0)


# --------------------------------------------------------------------------- #
# 內文全文抓取（統一 fetch_content 旗標）
# --------------------------------------------------------------------------- #

def test_collectors_share_unified_fetch_content_flag():
    """udn / ctee / rss 三個收集器統一以 fetch_content 控制是否抓全文。"""
    for fn in (udn.fetch, ctee.fetch, rss_sources.fetch, rss_sources.fetch_source):
        assert "fetch_content" in inspect.signature(fn).parameters, fn.__name__
    # 舊的不一致參數名已移除
    assert "fetch_body" not in inspect.signature(udn.fetch).parameters
    assert "fetch_detail" not in inspect.signature(ctee.fetch).parameters


def test_rss_fetch_source_fetches_full_content_when_flag_on(monkeypatch):
    """fetch_content=True 時逐篇進內頁抽全文，並沿用該來源的 body_selectors。"""
    entry = {"link": "https://cna/1", "title": "中央社頭條", "summary": "RSS 摘要"}
    monkeypatch.setattr(rss_sources, "request_get",
                        lambda *a, **k: types.SimpleNamespace(content=b""))
    monkeypatch.setattr(rss_sources.feedparser, "parse",
                        lambda *a, **k: types.SimpleNamespace(entries=[entry], bozo=0))
    monkeypatch.setattr(rss_sources.time, "sleep", lambda *a, **k: None)

    calls: list = []

    def fake_fetch_article(url, body_selectors=None):
        calls.append((url, body_selectors))
        return {"author": "記者A", "summary": "內頁摘要", "content": "完整內文全文"}

    monkeypatch.setattr(rss_sources, "fetch_article", fake_fetch_article)
    on = rss_sources.fetch_source("cna", limit_per_feed=1, fetch_content=True)
    assert on[0]["content"] == "完整內文全文"
    assert calls and calls[0][1] == rss_sources.SOURCES["cna"]["body_selectors"]

    # flag off：不進內頁、content 留空、fetch_article 不被呼叫
    def boom(*a, **k):
        raise AssertionError("fetch_content=False 不應抓內頁")

    monkeypatch.setattr(rss_sources, "fetch_article", boom)
    off = rss_sources.fetch_source("cna", limit_per_feed=1, fetch_content=False)
    assert off[0]["content"] == ""


def test_watch_enrich_content_uses_source_selectors(monkeypatch):
    """盤中監看補抓全文時，沿用該 RSS 來源的 body_selectors，並回填 summary/author。"""
    captured: dict = {}

    def fake_fetch_article(url, body_selectors=None):
        captured["url"] = url
        captured["selectors"] = body_selectors
        return {"author": "記者B", "summary": "補摘要", "content": "補全文"}

    monkeypatch.setattr(watch_intraday, "fetch_article", fake_fetch_article)
    monkeypatch.setattr(watch_intraday.time_mod, "sleep", lambda *a, **k: None)
    item = {"source": "cna", "url": "https://cna/9", "title": "標題",
            "content": "", "summary": "", "author": ""}
    watch_intraday.enrich_content(item)
    assert item["content"] == "補全文"
    assert item["summary"] == "補摘要"
    assert captured["selectors"] == watch_intraday.RSS_SOURCES["cna"]["body_selectors"]


def test_watch_enrich_skips_when_content_already_present(monkeypatch):
    """cnyes/announce 等已含全文者不應再進內頁抓取。"""
    def boom(*a, **k):
        raise AssertionError("已有 content 不應再抓內頁")

    monkeypatch.setattr(watch_intraday, "fetch_article", boom)
    item = {"source": "cnyes", "url": "u", "title": "T", "content": "API 已含全文"}
    watch_intraday.enrich_content(item)  # 不應拋例外
    assert item["content"] == "API 已含全文"


def test_watch_enrich_skips_unknown_source(monkeypatch):
    """非 RSS 來源（無 body_selectors）不抓內頁，content 留空。"""
    def boom(*a, **k):
        raise AssertionError("非 RSS 來源不應抓內頁")

    monkeypatch.setattr(watch_intraday, "fetch_article", boom)
    item = {"source": "announce_twse", "url": "u", "title": "T", "content": ""}
    watch_intraday.enrich_content(item)
    assert item["content"] == ""
