# -*- coding: utf-8 -*-
"""
stock-news-skill 核心:整合 Metabase cmoney.證券市場新聞 + 多家新聞來源
(cnyes/udn/ctee/anue/moneydj/yahoo,含內文)的新聞查詢庫。自帶完整新聞碼,自給自足。

公開 API:
  query_news(codes=None, keyword=None, days=None, source=None,
             fetch_body=None, individual_only=None, tag_sentiment=None) -> dict
    回傳 {"by_code": {code:[news...]}, "keyword_hits": [news...]}
    news = {time,title,source,url,summary,body, sentiment,confidence,events}
       前 6 鍵是穩定契約(Sino-notify-skill 依賴);
       後 3 鍵在 tag_sentiment=True(預設)時補上,規則層分類。
    keyword_hits 已內建:近 N 日過濾 + 依標題去重 + udn/ctee 補內文
    + 依時間倒序 + sentiment 標記;individual_only=True 再濾掉泛大盤新聞。

供 CLI(news.py)與其他 skill(如 Sino-notify-skill)呼叫。
"""
import os, sys, json, subprocess, datetime, pathlib, hashlib, time, copy, threading

BASE = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = pathlib.Path(__file__).resolve().parent
CFG = json.loads((BASE / "config.json").read_text(encoding="utf-8"))


# ---- fetch_sanbao 進程內 TTL 記憶體快取 ----------------------------------
# 場景:同一進程連續多次 query_news(如 _pick.py 連查多個 keyword,每次都
# 會 fetch_sanbao 重抓六家)。TTL 內同指紋直接回快取,大幅加速。
# key   = 影響抓取結果的設定指紋(六家 categories/feeds/pages/limit + source)
# value = (timestamp, sb_items)
# 關閉: config news.cache_ttl_sec=0 → 每次都重抓(測試/即時性出口)。
_SB_CACHE = {}
_SB_LOCK = threading.Lock()          # 保護 _SB_CACHE get/set(query_news 為公開 API,可能被多執行緒呼叫)

# 只有這些 key 會影響 fetch_sanbao 抓到的內容;納入指紋。
# 注意:fetch_sanbao(n) 不吃 source、六家照抓,故 source 不影響抓取內容、不納入指紋。
_CACHE_FINGERPRINT_KEYS = (
    "cnyes_categories", "cnyes_pages",
    "udn_feeds", "udn_limit",
    "ctee_pages", "ctee_limit",
    "anue_categories", "anue_pages",
    "moneydj_pages", "moneydj_limit",
    "yahoo_feeds", "yahoo_limit",
)


def _cache_key(n):
    """對影響抓取結果的設定做穩定指紋(json sort + sha1)。
    fetch_sanbao 不吃 source,故 source 不入指紋(避免 sanbao/both 各存一份相同內容)。"""
    fp = {k: n.get(k) for k in _CACHE_FINGERPRINT_KEYS}
    blob = json.dumps(fp, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def clear_news_cache():
    """清空進程內快取(fetch_sanbao + metabase 關鍵字撈回)。測試/強制重抓用。公開 API。"""
    with _SB_LOCK:
        _SB_CACHE.clear()
    with _MB_KW_LOCK:
        _MB_KW_CACHE.clear()


def _cache_ttl():
    try:
        return int(news_cfg().get("cache_ttl_sec", 120))
    except Exception:
        return 120


def _fetch_sanbao_cached(NP, n):
    """fetch_sanbao 的 TTL 快取包裝。
    - TTL 內同指紋 → 回快取的**深拷貝**(不重抓;深拷貝避免呼叫端 mutate 污染快取)。
    - cache_ttl_sec<=0 → 停用(每次都呼叫 NP.fetch_sanbao,也不寫快取)。
    - 一律呼叫『當下的』NP.fetch_sanbao(讓外部 monkeypatch 生效)。
    - _SB_CACHE get/set 以 _SB_LOCK 保護;網路抓取在鎖外,不阻塞其他執行緒。"""
    ttl = _cache_ttl()
    if ttl <= 0:                                 # 停用:每次重抓
        return NP.fetch_sanbao(n)
    key = _cache_key(n)
    now = time.time()
    with _SB_LOCK:                               # 只鎖 dict 存取,不鎖網路抓取
        hit = _SB_CACHE.get(key)
        if hit is not None and (now - hit[0]) < ttl:
            return copy.deepcopy(hit[1])         # TTL 內 → 命中(回拷貝防污染)
    items = NP.fetch_sanbao(n)                    # miss/過期 → 鎖外重抓
    with _SB_LOCK:
        _SB_CACHE[key] = (now, items)
    return copy.deepcopy(items)                   # 原件留快取,回拷貝給呼叫端
# --------------------------------------------------------------------------


def _win_user_env(name):
    try:
        out = subprocess.check_output(
            ["powershell.exe", "-NoProfile", "-Command",
             f"[Environment]::GetEnvironmentVariable('{name}','User')"],
            text=True).strip()
        return out or None
    except Exception:
        return None


def mb():
    for k in ("METABASE_USER", "METABASE_PASS", "METABASE_URL"):
        if not os.environ.get(k):
            v = _win_user_env(k)
            if v:
                os.environ[k] = v
    sys.path.insert(0, CFG["metabase"]["scripts"])
    from metabase_client import MetabaseClient
    return MetabaseClient()


def news_cfg():
    n = dict(CFG.get("news", {}))
    n.setdefault("source", "both")          # metabase | sanbao | both
    n.setdefault("lookback_days", 3)
    return n


GENERIC_NEWS = ["三大法人", "台股", "大盤", "加權", "收盤", "權證", "盤中",
                "外資賣超", "外資買超", "投信買超", "怒神", "創新高不敵",
                "下跌", "上漲"]


def is_individual_news(title):
    """泛大盤新聞 → False;個股新聞 → True。"""
    return not any(g in (title or "") for g in GENERIC_NEWS)


def _sql_in_list(codes):
    """把 codes 安全組成 SQL IN(...) 值字串(單引號跳脫,防注入)。"""
    return ",".join("'" + str(c).replace("'", "''") + "'" for c in codes)


def get_stock_names(codes):
    """code -> 中文簡稱(cmoney.上市櫃公司基本資料)。"""
    if not codes:
        return {}
    inlist = _sql_in_list(codes)
    sql = f'''SELECT "股票代號","中文簡稱" FROM cmoney."上市櫃公司基本資料"
WHERE "股票代號" IN ({inlist})
  AND "年度" = (SELECT max("年度") FROM cmoney."上市櫃公司基本資料")'''
    df = mb().query_df(sql, db=10)
    return {str(r["股票代號"]): r["中文簡稱"] for r in df.to_dict("records")}


def get_news_metabase(codes, days):
    since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    inlist = _sql_in_list(codes)
    sql = f'''SELECT "代號","名稱","發布日期時間","新聞標題"
FROM cmoney."證券市場新聞"
WHERE "代號" IN ({inlist}) AND "日期" >= toDate('{since}')
ORDER BY "代號","發布日期時間" DESC'''
    df = mb().query_df(sql, db=10)
    by_code = {}
    for rec in df.to_dict("records"):
        by_code.setdefault(str(rec["代號"]), []).append(
            {"time": str(rec["發布日期時間"]), "title": rec["新聞標題"],
             "source": "metabase", "url": "", "summary": "", "body": ""})
    return by_code


# ---- search_metabase_keyword 撈回結果的進程內 TTL 快取 -------------------
# 場景:同一進程連查多個 keyword(如 _pick.py 連查 6 個 keyword)。本層 SQL
# 完全不含 keyword 條件 — 它撈回近 N 日全部標題,keyword 過濾在 Python 端
# 做。故同一 days 的撈回結果可共用:撈一次大表,多個 keyword 在記憶體過濾,
# 不再對大表重複查詢(對應 _SB_CACHE 在三大報那層做的事)。
# key   = days(唯一影響 SQL 結果的變數);value = (timestamp, rows)
# rows  = list[dict] 原始列(代號/名稱/發布日期時間/新聞標題)
# 關閉: 同 _SB_CACHE,config news.cache_ttl_sec=0 → 每次重撈(不快取)。
_MB_KW_CACHE = {}
_MB_KW_LOCK = threading.Lock()       # 保護 _MB_KW_CACHE get/set(同 _SB_LOCK 之精神)


def _fetch_metabase_news_rows(days):
    """撈近 N 日 cmoney.證券市場新聞 標題列,TTL 快取(key=days)。
    回 list[dict]。TTL 內同 days → 回快取不重查;cache_ttl_sec<=0 → 停用。
    呼叫端只讀不改回傳列(多 keyword 共用同一份),故可安全共享。"""
    since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    sql = f'''SELECT "代號","名稱","發布日期時間","新聞標題"
FROM cmoney."證券市場新聞"
WHERE "日期" >= toDate('{since}')
ORDER BY "發布日期時間" DESC'''
    ttl = _cache_ttl()
    if ttl <= 0:                                  # 停用:每次重查,不寫快取
        return mb().query_df(sql, db=10).to_dict("records")
    now = time.time()
    with _MB_KW_LOCK:                             # 只鎖 dict 存取,不鎖 SQL 查詢
        hit = _MB_KW_CACHE.get(days)
        if hit is not None and (now - hit[0]) < ttl:
            return hit[1]                         # TTL 內 → 命中(呼叫端只讀,不需拷貝)
    rows = mb().query_df(sql, db=10).to_dict("records")  # miss/過期 → 鎖外重查
    with _MB_KW_LOCK:
        _MB_KW_CACHE[days] = (now, rows)
    return rows


def search_metabase_keyword(keywords, days):
    """關鍵字搜 cmoney.證券市場新聞 標題(歷史可回溯)。
    撈回的近 N 日標題列由 _fetch_metabase_news_rows 做 TTL 快取,同一進程
    連查多個 keyword 共用同一份撈回(只在記憶體過濾,免重查大表)。"""
    hits = []
    for r in _fetch_metabase_news_rows(days):
        t = r["新聞標題"] or ""
        if any(k in t for k in keywords):
            hits.append({"time": str(r["發布日期時間"]), "title": t,
                         "source": "metabase", "url": "",
                         "code": str(r["代號"]), "name": r["名稱"],
                         "summary": "", "body": ""})
    return hits


def _tag_sentiment_inplace(items):
    """對 items(list[dict])原地補上 sentiment/confidence/events 三鍵。
    失敗只 warn 不中斷(規則層極少噴錯,但保險)。"""
    try:
        import news_sentiment as NS
    except Exception as e:
        print(f"  sentiment import warn: {e!r}", file=sys.stderr)
        return
    for it in items:
        try:
            tag = NS.classify(it.get("title", ""),
                              it.get("body", "") or it.get("summary", ""))
            it["sentiment"] = tag["sentiment"]
            it["confidence"] = tag["confidence"]
            it["events"] = tag["events"]
        except Exception as e:
            print(f"  sentiment warn: {e!r}", file=sys.stderr)
            it.setdefault("sentiment", "neutral")
            it.setdefault("confidence", 0.0)
            it.setdefault("events", [])


def query_news(codes=None, keyword=None, days=None, source=None,
               fetch_body=None, individual_only=None, tag_sentiment=None):
    """統一新聞查詢入口。
       codes  : list[str] 指定個股 → 回 by_code
       keyword: str/list  關鍵字   → 回 keyword_hits(Metabase標題+多家全文)
       individual_only: True 則 keyword_hits 濾掉泛大盤新聞(預設讀 config)
       tag_sentiment  : True 則對 by_code/keyword_hits 每則補 sentiment/
                        confidence/events(預設讀 config,預設 True)
       兩者可同時給。"""
    n = news_cfg()
    days = n["lookback_days"] if days is None else int(days)
    source = n["source"] if source is None else source
    fb = n.get("fetch_body", True) if fetch_body is None else bool(fetch_body)
    indiv = (n.get("individual_only", False) if individual_only is None
             else bool(individual_only))
    tag = (n.get("tag_sentiment", True) if tag_sentiment is None
           else bool(tag_sentiment))
    kws = ([k.strip() for k in keyword.split(",")] if isinstance(keyword, str)
           else list(keyword)) if keyword else []

    sys.path.insert(0, str(SCRIPTS))
    import news_providers as NP

    result = {"by_code": {}, "keyword_hits": []}
    sb_items = None

    # ---- 指定個股 ----
    if codes:
        codes = [str(c) for c in codes]
        by_code = {}
        if source in ("metabase", "both"):
            try:
                by_code = get_news_metabase(codes, days)
            except Exception as e:
                print(f"  metabase news warn: {e!r}", file=sys.stderr)
        if source in ("sanbao", "both"):
            c2n = get_stock_names(codes)
            sb_items = _fetch_sanbao_cached(NP, n)
            sb = NP.match_news_to_codes(sb_items, c2n, days)
            if fb:
                NP.attach_bodies(sb, n.get("body_max_chars", 600),
                                 n.get("body_fetch_limit", 40))
            for code, lst in sb.items():
                seen = {x["title"] for x in by_code.get(code, [])}
                merged = by_code.setdefault(code, [])
                for it in lst:
                    if it["title"] not in seen:
                        merged.append(it)
                        seen.add(it["title"])
        # 標 sentiment(by_code 每檔逐則)
        if tag:
            for lst in by_code.values():
                _tag_sentiment_inplace(lst)
        result["by_code"] = by_code

    # ---- 關鍵字 ----
    if kws:
        kw_days = max(days, 10)             # 關鍵字保留歷史回溯(Metabase 賣點)
        hits = []
        if source in ("metabase", "both"):
            try:
                hits += search_metabase_keyword(kws, kw_days)
            except Exception as e:
                print(f"  metabase kw warn: {e!r}", file=sys.stderr)
        if source in ("sanbao", "both"):
            if sb_items is None:
                sb_items = _fetch_sanbao_cached(NP, n)
            for it in sb_items:
                blob = (it["title"] + " " + it.get("summary", "") + " "
                        + it.get("body", ""))
                if any(k in blob for k in kws):
                    hits.append({"time": it.get("published_at", ""),
                                 "title": it["title"], "source": it["source"],
                                 "url": it["url"], "code": "", "name": "",
                                 "summary": it.get("summary", ""),
                                 "body": it.get("body", "")})

        def _dt(s):
            try:
                d = datetime.datetime.fromisoformat((s or "").strip())
                return d if d.tzinfo else d.astimezone()
            except Exception:
                return None

        # 1) 近 kw_days 日過濾(有日期才濾,無日期保留 — 同 codes 模式)
        cutoff = (datetime.datetime.now().astimezone()
                  - datetime.timedelta(days=kw_days))
        hits = [h for h in hits
                if (_dt(h.get("time")) is None) or _dt(h.get("time")) >= cutoff]
        # 2) 依標題去重,保留內文較豐富/有 url 者(metabase 純標題會被三大報取代)
        best = {}
        for h in hits:
            key = (h.get("title") or "").strip() or h.get("url", "")
            cur = best.get(key)
            if (cur is None
                    or len(h.get("body") or "") > len(cur.get("body") or "")
                    or (not cur.get("url") and h.get("url"))):
                best[key] = h
        hits = list(best.values())
        # 3) 命中的 udn/ctee 補內文(cnyes 內文已內含,metabase 無 url 會略過)
        if fb:
            NP.attach_bodies({"kw": hits}, n.get("body_max_chars", 600),
                             n.get("body_fetch_limit", 40))
        # 4) 泛大盤過濾(可選)
        if indiv:
            hits = [h for h in hits
                    if is_individual_news(h.get("title", ""))]
        # 5) 依時間倒序(無法解析時間者排最後)
        _MIN = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)
        hits.sort(key=lambda h: _dt(h.get("time")) or _MIN, reverse=True)
        # 6) 標 sentiment / events(規則層,可由 tag_sentiment 關掉)
        if tag:
            _tag_sentiment_inplace(hits)
        result["keyword_hits"] = hits
    return result
