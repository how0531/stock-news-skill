# -*- coding: utf-8 -*-
"""
stock-news-skill 核心:整合 Metabase cmoney.證券市場新聞 + 多家新聞來源
(cnyes/udn/ctee/anue/moneydj/yahoo,含內文)的新聞查詢庫。自帶完整新聞碼,自給自足。

公開 API:
  query_news(codes=None, keyword=None, days=None, source=None,
             fetch_body=None, individual_only=None, tag_sentiment=None,
             names=None, match_all=None, intl=None) -> dict
    回傳 {"by_code": {code:[news...]}, "keyword_hits": [news...]}
    news = {time,title,source,url,summary,body, sentiment,confidence,events}
       前 6 鍵是穩定契約(Sino-notify-skill 依賴);
       後 3 鍵在 tag_sentiment=True(預設)時補上,規則層分類。
    keyword_hits 已內建:近 N 日過濾 + 依標題去重 + udn/ctee 補內文
    + 依時間倒序 + sentiment 標記;individual_only=True 再濾掉泛大盤新聞。
    keyword_hits 另帶 code,name,category,snippets(命中片段);match_all=True 為 AND,
    intl=True 只留國際/總經分類。

供 CLI(news.py)與其他 skill(如 Sino-notify-skill)呼叫。
"""
import os, sys, json, subprocess, datetime, pathlib, hashlib, time, copy, threading, socket, urllib.parse

BASE = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = pathlib.Path(__file__).resolve().parent
CFG = json.loads((BASE / "config.json").read_text(encoding="utf-8"))

# 台北時區:now/cutoff 一律用它,不依賴本機時區(Git Bash 設了 TZ 時 astimezone() 會偏)
try:
    from common import TAIPEI
except Exception:                     # common 依賴 requests/bs4;極端情況退回固定 +08:00
    TAIPEI = datetime.timezone(datetime.timedelta(hours=8))


def _now_tw():
    return datetime.datetime.now(TAIPEI)


# ---- fetch_sanbao TTL 快取(進程內記憶體 + 跨進程磁碟)--------------------
# 場景:同一進程連續多次 query_news(如 _pick.py 連查多個 keyword),或多個 CLI
# 進程/平行查證 agent 在短時間內各查一次;每次都 fetch_sanbao 全量重抓約 5 分。
# TTL 內同指紋直接回快取,大幅加速。
# key   = 影響抓取結果的設定指紋(六家 categories/feeds/pages/limit + fetch_body)
# value = (抓取『完成』時間, sb_items)  ← 抓取本身要數分鐘,時間戳一定要抓完才記
# 磁碟層: out/.sanbao_cache.json,跨 CLI 進程共用;寫入走暫存檔 + os.replace(原子)。
# 關閉: config news.cache_ttl_sec=0 → 每次都重抓、不讀不寫任何快取(測試/即時性出口)。
_SB_CACHE = {}
_SB_LOCK = threading.Lock()          # 保護 _SB_CACHE get/set(query_news 為公開 API,可能被多執行緒呼叫)
_SB_DISK = BASE / "out" / ".sanbao_cache.json"

# 只有這些 key 會影響 fetch_sanbao 抓到的內容;納入指紋。
# 主路徑 main.aggregate 的來源寫死在程式,config 只有 fetch_body 會改變抓取內容。
_CACHE_FINGERPRINT_KEYS = ("fetch_body",)


def _cache_key(n):
    """對影響抓取結果的設定做穩定指紋(json sort + sha1)。
    fetch_sanbao 不吃 source,故 source 不入指紋(避免 sanbao/both 各存一份相同內容)。"""
    fp = {k: n.get(k) for k in _CACHE_FINGERPRINT_KEYS}
    blob = json.dumps(fp, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def clear_news_cache(disk=False):
    """清空進程內快取(fetch_sanbao + metabase 關鍵字撈回)。測試/強制重抓用。公開 API。
    disk=True 時連 out/.sanbao_cache.json 一起刪(跨進程強制重抓);預設不碰磁碟,
    單元測試呼叫時不會清掉正式快取。"""
    with _SB_LOCK:
        _SB_CACHE.clear()
    with _MB_KW_LOCK:
        _MB_KW_CACHE.clear()
    if disk:
        try:
            _SB_DISK.unlink()
        except Exception:             # 不存在或被別的進程開著讀:略過即可
            pass


def _cache_ttl():
    try:
        return int(news_cfg().get("cache_ttl_sec", 900))
    except Exception:
        return 900


def _is_real_fetch(NP):
    """NP.fetch_sanbao 是否為原廠函式。被測試 monkeypatch 成假資料時不碰磁碟快取,
    避免假新聞寫進 out/.sanbao_cache.json 讓下一個真實查詢(如 07:40 自動信)讀到。"""
    return getattr(NP.fetch_sanbao, "__module__", "") == getattr(NP, "__name__", None)


def _disk_cache_load(key, ttl):
    """讀磁碟快取;檔案過期/指紋不符/壞檔一律回 None(當作 miss)。"""
    try:
        if time.time() - _SB_DISK.stat().st_mtime >= ttl:
            return None
        d = json.loads(_SB_DISK.read_text(encoding="utf-8"))
        ts = float(d.get("ts", 0))
        items = d.get("items")
        if d.get("key") != key or time.time() - ts >= ttl or not isinstance(items, list):
            return None
        return ts, items
    except Exception:
        return None


def _disk_cache_save(key, ts, items):
    """先寫暫存檔再 os.replace,平行讀取的進程不會讀到半個檔。失敗只 warn。"""
    tmp = _SB_DISK.with_name(f"{_SB_DISK.name}.{os.getpid()}.tmp")
    try:
        _SB_DISK.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps({"key": key, "ts": ts, "items": items},
                                  ensure_ascii=False, default=str), encoding="utf-8")
        os.replace(tmp, _SB_DISK)
    except Exception as e:
        print(f"  sanbao disk cache write warn: {e!r}", file=sys.stderr)
        try:
            tmp.unlink()
        except Exception:
            pass


_SB_LOCKFILE = _SB_DISK.with_name(".sanbao_fetch.lock")


def _wait_fetch_lock(key, ttl, wait=180):
    """冷快取時只讓一個進程抓全量,其他進程等它寫好磁碟快取再沿用(平行查證不再各抓一次)。
    回 (拿到鎖?, 磁碟快取或 None)。等超過 wait 秒、或建不了鎖檔,就自己抓。"""
    deadline = time.time() + wait
    while True:
        try:
            _SB_LOCKFILE.parent.mkdir(parents=True, exist_ok=True)
            os.close(os.open(_SB_LOCKFILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            disk = _disk_cache_load(key, ttl)    # 前一個持有者可能剛寫完快取才放鎖
            if disk is not None:
                _SB_LOCKFILE.unlink()
                return False, disk
            return True, None
        except FileExistsError:
            try:
                if time.time() - _SB_LOCKFILE.stat().st_mtime > wait:   # 持有者當掉留下的舊鎖
                    _SB_LOCKFILE.unlink()
                    continue
            except Exception:
                pass
            disk = _disk_cache_load(key, ttl)
            if disk is not None:
                return False, disk
            if time.time() > deadline:
                return False, None
            time.sleep(1)
        except Exception:
            return False, None


def _fetch_sanbao_cached(NP, n):
    """fetch_sanbao 的 TTL 快取包裝(記憶體 → 磁碟 → 重抓)。
    - TTL 內同指紋 → 回快取的**深拷貝**(不重抓;深拷貝避免呼叫端 mutate 污染快取)。
    - 時間戳記在『抓取完成』時(抓取約數分鐘,記開始時間會讓快取一出生就過期)。
    - cache_ttl_sec<=0 → 停用(每次都呼叫 NP.fetch_sanbao,也不讀寫任何快取)。
    - 一律呼叫『當下的』NP.fetch_sanbao(讓外部 monkeypatch 生效);被 patch 時不碰磁碟。
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
    use_disk = _is_real_fetch(NP)
    owned = False
    if use_disk:
        disk = _disk_cache_load(key, ttl)
        if disk is None:                         # 沒快取:搶跨進程抓取鎖,搶不到就等別人抓完
            owned, disk = _wait_fetch_lock(key, ttl)
        if disk is not None:                     # 別的進程剛抓過 → 直接沿用
            print(f"  [cache] 沿用 {int(time.time() - disk[0])} 秒前的即時新聞快取 "
                  f"({len(disk[1])} 則,TTL {ttl}s)", file=sys.stderr)
            with _SB_LOCK:
                _SB_CACHE[key] = disk
            return copy.deepcopy(disk[1])
    try:
        items = NP.fetch_sanbao(n)                # miss/過期 → 鎖外重抓
        done = time.time()                        # 抓完才記時間
        with _SB_LOCK:
            _SB_CACHE[key] = (done, items)
        if use_disk and items:                    # 空結果(網路瞬斷)不落磁碟,免得 15 分鐘內別的進程(含 07:40 自動信)都拿 0 則
            _disk_cache_save(key, done, items)
    finally:                                      # 先寫好磁碟快取再放鎖,等待中的進程才拿得到
        if owned:
            try:
                _SB_LOCKFILE.unlink()
            except Exception:
                pass
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


def _load_mb_env():
    """METABASE_USER/PASS/URL 不在環境裡時,從 Windows User 環境變數回讀(子程序常拿不到)。"""
    for k in ("METABASE_USER", "METABASE_PASS", "METABASE_URL"):
        if not os.environ.get(k):
            v = _win_user_env(k)
            if v:
                os.environ[k] = v


_MB_CLIENT = None


def mb():
    """同一進程共用一個 client:每建一個新 client,第一次查詢前都要多一次 token 驗證請求。"""
    global _MB_CLIENT
    if _MB_CLIENT is None:
        _load_mb_env()
        sys.path.insert(0, CFG["metabase"]["scripts"])
        from metabase_client import MetabaseClient
        _MB_CLIENT = MetabaseClient()
    return _MB_CLIENT


_MB_OK = None


def metabase_available():
    """Metabase 能不能用:帳密環境變數齊全、metabase.scripts 路徑存在、主機 3 秒內連得上。
    每個進程只測一次。不是每個使用者都有 Metabase 權限或在內網;不可用時 query_news
    預設的 source=both 退成只用即時流,代號查詢改用離線字典與代號比對。"""
    global _MB_OK
    if _MB_OK is None:
        try:
            scripts = (CFG.get("metabase") or {}).get("scripts") or ""
            if not os.path.isdir(scripts):   # 沒裝 sinopac-metabase 就不必開 PowerShell 讀環境變數
                _MB_OK = False
                return _MB_OK
            _load_mb_env()
            url = os.environ.get("METABASE_URL") or ""
            u = urllib.parse.urlparse(url if "://" in url else "http://" + url)   # 沒寫 http:// 也要認得主機
            _MB_OK = bool(os.environ.get("METABASE_USER") and os.environ.get("METABASE_PASS")
                          and u.hostname)
            if _MB_OK:
                socket.create_connection(
                    (u.hostname, u.port or (443 if u.scheme == "https" else 80)),
                    timeout=3).close()
                os.environ["METABASE_URL"] = u.geturl()   # client 與探測用同一個網址
        except Exception:
            _MB_OK = False
    return _MB_OK


def resolve_stock_names(codes, source=None):
    """代號 → 股名。source 不是 sanbao 且 Metabase 可用時先查 Metabase;沒查到的用離線字典
    (data/stocks/tw_stocks.json)補,再沒有就給空字串(後續只靠代號比對)。"""
    codes = [str(c) for c in codes or []]
    source = news_cfg()["source"] if source is None else source
    c2n = {}
    if codes and source != "sanbao" and metabase_available():
        try:
            c2n = get_stock_names(codes)
        except Exception as e:
            print(f"  get_stock_names warn(改用離線字典與代號比對):{e!r}", file=sys.stderr)
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    import news_providers as NP
    return {c: c2n.get(c) or NP.local_stock_name(c) for c in codes}


def news_cfg():
    n = dict(CFG.get("news", {}))
    n.setdefault("source", "both")          # metabase | sanbao | both
    n.setdefault("lookback_days", 3)
    return n


GENERIC_NEWS = ["三大法人", "台股", "大盤", "加權", "收盤", "權證",
                "外資賣超", "外資買超", "投信買超", "怒神", "創新高不敵"]


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


def _mb_time(v):
    """Metabase cmoney 的『發布日期時間』是台北牆鐘卻帶 Z 後綴(假 UTC,實測
    台北 21:25 查到 '...T20:45:04Z')。去掉 Z、補 +08:00,避免被當 UTC 解析後
    偏 8 小時(排序永遠浮到最前、近 N 日過濾偏移)。已帶時區或非日期時間者原樣回傳。"""
    s = str(v or "").strip()
    if s.endswith("Z"):
        s = s[:-1]
    tail = s[10:]
    if len(s) >= 16 and "+" not in tail and "-" not in tail:
        s += "+08:00"
    return s


def get_news_metabase(codes, days):
    since = (_now_tw().date() - datetime.timedelta(days=days)).isoformat()
    inlist = _sql_in_list(codes)
    sql = f'''SELECT "代號","名稱","發布日期時間","新聞標題"
FROM cmoney."證券市場新聞"
WHERE "代號" IN ({inlist}) AND "日期" >= toDate('{since}')
ORDER BY "代號","發布日期時間" DESC'''
    df = mb().query_df(sql, db=10)
    by_code = {}
    for rec in df.to_dict("records"):
        by_code.setdefault(str(rec["代號"]), []).append(
            {"time": _mb_time(rec["發布日期時間"]), "title": rec["新聞標題"],
             "source": "metabase", "url": "", "summary": "", "body": ""})
    return by_code


# ---- search_metabase_keyword 撈回結果的進程內 TTL 快取 -------------------
# 場景:同一進程連查多個 keyword(如 _pick.py 連查 6 個 keyword)。
# 關鍵字已推進 SQL(positionUTF8 比對標題 + 新聞內容,實測 <0.1s),只撈命中列
# 並帶回內文;同一組 (days, keywords, match_all) 在 TTL 內共用撈回結果。
# key   = (days, keywords, match_all);value = (timestamp, rows)
# rows  = list[dict] 原始列(代號/名稱/發布日期時間/新聞標題[/新聞內容])
# 關閉: 同 _SB_CACHE,config news.cache_ttl_sec=0 → 每次重撈(不快取)。
_MB_KW_CACHE = {}
_MB_KW_LOCK = threading.Lock()       # 保護 _MB_KW_CACHE get/set(同 _SB_LOCK 之精神)


def _sql_str(s):
    """ClickHouse 字串常值跳脫(反斜線、單引號)。"""
    return "'" + str(s).replace("\\", "\\\\").replace("'", "\\'") + "'"


def _fetch_metabase_news_rows(days, keywords=None, match_all=False):
    """撈近 N 日 cmoney.證券市場新聞,TTL 快取。
    keywords 有給 → 條件推進 SQL(標題或內文含關鍵字;match_all=True 時每個都要出現),
    並多撈「新聞內容」;keywords=None → 舊行為(近 N 日全部標題,不含內文)。
    回 list[dict]。cache_ttl_sec<=0 → 停用。呼叫端只讀不改回傳列,故可安全共享。"""
    since = (_now_tw().date() - datetime.timedelta(days=days)).isoformat()
    kws = tuple(k for k in (keywords or []) if k)
    if kws:
        conds = [f'(positionUTF8("新聞標題", {_sql_str(k)}) > 0 OR '
                 f'positionUTF8(ifNull("新聞內容", \'\'), {_sql_str(k)}) > 0)' for k in kws]
        joiner = " AND " if match_all else " OR "
        # 同一篇新聞每個關聯代號各一列(實測 台積電 10 日 1007 列只有 185 篇),
        # 下游本來就依標題去重,LIMIT 1 BY 標題先在 DB 端收斂,內文傳輸量降約 5 倍
        sql = f'''SELECT "代號","名稱","發布日期時間","新聞標題","新聞內容"
FROM cmoney."證券市場新聞"
WHERE "日期" >= toDate('{since}') AND ({joiner.join(conds)})
ORDER BY "發布日期時間" DESC
LIMIT 1 BY "新聞標題"'''
    else:
        sql = f'''SELECT "代號","名稱","發布日期時間","新聞標題"
FROM cmoney."證券市場新聞"
WHERE "日期" >= toDate('{since}')
ORDER BY "發布日期時間" DESC'''
    key = (days, kws, bool(match_all)) if kws else days
    ttl = _cache_ttl()
    if ttl <= 0:                                  # 停用:每次重查,不寫快取
        return mb().query_df(sql, db=10).to_dict("records")
    now = time.time()
    with _MB_KW_LOCK:                             # 只鎖 dict 存取,不鎖 SQL 查詢
        hit = _MB_KW_CACHE.get(key)
        if hit is not None and (now - hit[0]) < ttl:
            return hit[1]                         # TTL 內 → 命中(呼叫端只讀,不需拷貝)
    rows = mb().query_df(sql, db=10).to_dict("records")  # miss/過期 → 鎖外重查
    with _MB_KW_LOCK:
        _MB_KW_CACHE[key] = (now, rows)
    return rows


def _kw_match(blob, kws, match_all=False):
    """關鍵字比對:預設任一命中(OR);match_all=True 時全部都要出現(AND)。"""
    return all(k in blob for k in kws) if match_all else any(k in blob for k in kws)


def search_metabase_keyword(keywords, days, match_all=False):
    """關鍵字搜 cmoney.證券市場新聞 標題 + 內文(歷史可回溯),命中列回填 body。"""
    hits = []
    for r in _fetch_metabase_news_rows(days, keywords, match_all):
        t = r["新聞標題"] or ""
        body = r.get("新聞內容") or ""
        if _kw_match(t + " " + body, keywords, match_all):
            hits.append({"time": _mb_time(r["發布日期時間"]), "title": t,
                         "source": "metabase", "url": "",
                         "code": str(r["代號"]), "name": r["名稱"],
                         "summary": "", "body": body, "category": ""})
    return hits


# 國際/總經類分類名(CLI --intl / query_news(intl=True) 用):udn 國際版、cnyes 國際股市/
# 外匯/期貨、Yahoo 國際股市、ctee 國際細分類、cnyes 搜尋結果的國際分類。
INTL_CATEGORIES = {
    "國際焦點", "國際綜合", "美股雷達", "全球財經", "國際股市", "外匯", "期貨",
    "國際財經", "美股", "日股",
    "國際政經", "美股盤中", "美股預估", "歐亞股",
}


def _snippets(text, kws, width=60, limit=3):
    """回傳內文中關鍵字命中處前後各 width 字的片段(最多 limit 段,依出現位置排序)。
    先保證每個關鍵字各取第一次出現(AND 查詢時每個詞都看得到),再依位置補其餘命中;
    命中處已落在既有片段內的不重複取。
    cnyes 內文常是 HTML 實體編碼(&lt;p&gt;),先還原並去標籤,片段才不會被標記字元佔掉。"""
    import html as _html
    import re as _re
    text = " ".join(_re.sub(r"<[^>]+>", " ", _html.unescape(text or "")).split())
    firsts, rest = [], []
    for k in kws:
        if not k:
            continue
        start, first = 0, True
        while True:
            i = text.find(k, start)
            if i < 0:
                break
            (firsts if first else rest).append((i, i + len(k)))
            first = False
            start = i + len(k)
    wins = []
    for i, j in sorted(firsts) + sorted(rest):
        if len(wins) >= limit:
            break
        if any(a <= i and j <= b for a, b in wins):   # 已在既有片段內看得到
            continue
        wins.append((max(0, i - width), min(len(text), j + width)))
    return [("…" if a > 0 else "") + text[a:b] + ("…" if b < len(text) else "")
            for a, b in sorted(wins)]


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


def _sb_or_empty(NP, n):
    """即時流抓不到(主路徑缺套件或例外)時,query_news 只回 Metabase 的結果,並在 stderr 講清楚原因。"""
    try:
        return _fetch_sanbao_cached(NP, n)
    except Exception as e:
        print(f"  即時新聞流失敗,本次只有 Metabase 的結果:{e}", file=sys.stderr)
        return []


def query_news(codes=None, keyword=None, days=None, source=None,
               fetch_body=None, individual_only=None, tag_sentiment=None,
               names=None, match_all=None, intl=None):
    """統一新聞查詢入口。
       codes  : list[str] 指定個股 → 回 by_code
       names  : {code:中文名} 外部已知股名 → 跳過 Metabase get_stock_names
                (即時六家新聞本來不需 Metabase;呼叫端有股名時傳入,Metabase
                 掛掉也能照抓近 N 日即時新聞)
       keyword: str/list  關鍵字   → 回 keyword_hits(Metabase標題+內文、多家全文、
                cnyes 全站搜尋);每則多帶 snippets(命中處前後 60 字,最多 3 段)與 category
       individual_only: True 則 keyword_hits 濾掉泛大盤新聞(預設讀 config)
       tag_sentiment  : True 則對 by_code/keyword_hits 每則補 sentiment/
                        confidence/events(預設讀 config,預設 True)
       match_all: True 則多個關鍵字都要出現才算命中(AND);預設任一命中(OR)
       intl     : True 則 keyword_hits 只留國際/總經分類(INTL_CATEGORIES)
       兩者可同時給。"""
    n = news_cfg()
    days = n["lookback_days"] if days is None else int(days)
    source = n["source"] if source is None else source
    if source == "both" and not metabase_available():
        print("  Metabase 無法使用(沒有權限、未設定或連不上),本次只用即時新聞流,"
              "沒有 Metabase 歷史回溯", file=sys.stderr)
        source = "sanbao"
    fb = n.get("fetch_body", True) if fetch_body is None else bool(fetch_body)
    indiv = (n.get("individual_only", False) if individual_only is None
             else bool(individual_only))
    tag = (n.get("tag_sentiment", True) if tag_sentiment is None
           else bool(tag_sentiment))
    mall = bool(match_all)
    kws = ([k.strip() for k in keyword.split(",")] if isinstance(keyword, str)
           else list(keyword)) if keyword else []
    kws = [k for k in kws if k]

    sys.path.insert(0, str(SCRIPTS))
    import news_providers as NP

    result = {"by_code": {}, "keyword_hits": []}
    sb_items = None

    # ---- 指定個股(fallback 鏈:Metabase per-代號 → per-代號直取 → 綜合流比對)----
    if codes:
        codes = [str(c) for c in codes]
        by_code = {}
        # 股名(給直取與比對用):外部 names 優先(不碰 Metabase,缺的用離線字典補);
        # 否則 Metabase(可用時)→ 離線字典 → 空字串(只靠代號比對)
        if names:
            c2n = {str(k): v for k, v in names.items()}
            c2n.update({c: NP.local_stock_name(c) for c in codes if not c2n.get(c)})
        else:
            c2n = resolve_stock_names(codes, source)

        def _merge(code, lst):
            code = str(code)
            tgt = by_code.setdefault(code, [])
            pos = {x["title"]: i for i, x in enumerate(tgt)}
            for it in lst:
                t = it.get("title")
                if not t:
                    continue
                i = pos.get(t)
                if i is None:
                    pos[t] = len(tgt)
                    tgt.append(it)
                elif not tgt[i].get("body") and (it.get("body") or it.get("url")):
                    tgt[i] = it          # Metabase 只有標題;同標題的全文版取代它

        rd = int(n.get("report_days", 10))      # 產業報告放寬窗;一般新聞用 days(預設 3)
        win = max(days, rd)                      # 拉取時先用較寬窗,最後再用 recent_ok 精準收口
        # 1) Metabase cmoney per-代號(健康時最準)
        if source in ("metabase", "both"):
            try:
                for code, lst in get_news_metabase(codes, win).items():
                    _merge(code, lst)
            except Exception as e:
                print(f"  metabase news warn: {e!r}", file=sys.stderr)
        # 2) per-代號『直取』(cnyes search + Yahoo 個股頁)—— 補綜合清單抓不到的個股深度報導
        if n.get("per_stock_fetch", True):
            cap = n.get("body_max_chars", 600)

            def _one(code):
                nm = c2n.get(str(code)) or str(code)     # 沒有股名就用代號搜尋
                try:
                    return str(code), NP.fetch_stock_news(code, nm, body_cap=cap)
                except Exception as e:
                    print(f"  per-stock fetch warn {code}: {e!r}", file=sys.stderr)
                    return str(code), []
            try:
                import concurrent.futures as _cf
                with _cf.ThreadPoolExecutor(max_workers=6) as ex:
                    for code, lst in ex.map(_one, codes):
                        _merge(code, lst)
            except Exception as e:
                print(f"  per-stock fetch pool warn: {e!r}", file=sys.stderr)
        # 3) 綜合清單 + 比對(股名/代號/出版商代號/別名)補遺
        if source in ("sanbao", "both"):
            sb_items = _sb_or_empty(NP, n)
            if fb:                                  # 比對前先抓『標題含產業熱詞』候選文內文(解雞生蛋)
                NP.prefetch_candidate_bodies(sb_items, n.get("body_max_chars", 600),
                                             n.get("body_fetch_limit", 40))
            sb = NP.match_news_to_codes(sb_items, c2n, win)
            if fb:
                NP.attach_bodies(sb, n.get("body_max_chars", 600),
                                 n.get("body_fetch_limit", 40))
            for code, lst in sb.items():
                _merge(code, lst)
        # 新鮮度收口:一般新聞 days(預設3)天、產業報告 report_days(預設10)天
        for code in list(by_code):
            by_code[code] = [it for it in by_code[code]
                             if NP.recent_ok(it.get("time"), it.get("title", ""), days, rd)]
        # 標 sentiment(by_code 每檔逐則)
        if tag:
            for lst in by_code.values():
                _tag_sentiment_inplace(lst)
        result["by_code"] = by_code

    # ---- 關鍵字 ----
    if kws:
        kw_days = max(days, 10)             # 關鍵字保留歷史回溯(Metabase 賣點)
        hits = []

        def _kw_hit(it):
            return {"time": it.get("published_at", ""),
                    "title": it["title"], "source": it["source"],
                    "url": it["url"], "code": "", "name": "",
                    "summary": it.get("summary", "") or "",
                    "body": it.get("body", "") or "",
                    "category": it.get("category", "") or ""}

        # 三條腿(Metabase、即時流、每個關鍵字一次 cnyes 全站搜尋)彼此獨立,並行跑;
        # 結果依固定順序合併,去重結果與序列版一致。
        def _sb_hits():
            items = sb_items if sb_items is not None else _sb_or_empty(NP, n)
            return [_kw_hit(it) for it in items
                    if _kw_match(it["title"] + " " + (it.get("summary") or "") + " "
                                 + (it.get("body") or ""), kws, mall)]

        def _cnyes_hits(k):
            # cnyes 全站搜尋腿:即時流只有最新約 200 則,總經/國際題材常在更早或不在清單裡
            return [_kw_hit(it) for it in NP.search_cnyes_news(k)
                    if _kw_match(it["title"] + " " + it.get("body", ""), kws, mall)]

        legs = []
        if source in ("metabase", "both"):
            legs.append(("metabase kw", lambda: search_metabase_keyword(kws, kw_days, mall)))
        if source in ("sanbao", "both"):
            legs.append(("sanbao kw", _sb_hits))
            if n.get("kw_search_cnyes", True):
                legs += [(f"cnyes-search {k}", lambda k=k: _cnyes_hits(k)) for k in kws]
        if legs:
            import concurrent.futures as _cf
            with _cf.ThreadPoolExecutor(max_workers=len(legs)) as ex:
                futs = [(name, ex.submit(fn)) for name, fn in legs]
                for name, fut in futs:
                    try:
                        hits += fut.result()
                    except Exception as e:
                        print(f"  {name} warn: {e!r}", file=sys.stderr)
        if intl:                            # 只留國際/總經分類(metabase 無分類,一併排除)
            hits = [h for h in hits if h.get("category") in INTL_CATEGORIES]

        def _dt(s):
            try:
                d = datetime.datetime.fromisoformat((s or "").strip())
                return d if d.tzinfo else d.replace(tzinfo=TAIPEI)
            except Exception:
                return None

        # 1) 近 kw_days 日過濾(有日期才濾,無日期保留 — 同 codes 模式)
        cutoff = _now_tw() - datetime.timedelta(days=kw_days)
        hits = [h for h in hits
                if (_dt(h.get("time")) is None) or _dt(h.get("time")) >= cutoff]
        # 2) 依標題去重,保留內文較豐富/有 url 者(metabase 無 url 會被即時流取代,
        #    但若 metabase 內文較完整就把內文帶過去)
        best = {}
        for h in hits:
            key = (h.get("title") or "").strip() or h.get("url", "")
            cur = best.get(key)
            if (cur is None
                    or len(h.get("body") or "") > len(cur.get("body") or "")
                    or (not cur.get("url") and h.get("url"))):
                if cur is not None and len(cur.get("body") or "") > len(h.get("body") or ""):
                    h = dict(h, body=cur["body"])
                best[key] = h
        hits = list(best.values())
        # 3) 命中的 udn/ctee 補內文(cnyes 內文已內含,metabase 無 url 會略過)
        if fb:
            NP.attach_bodies({"kw": hits}, n.get("body_max_chars", 600),
                             n.get("body_fetch_limit", 40))
        # 3b) 命中片段:每則取關鍵字前後 60 字(最多 3 段),關鍵字在內文後段也看得到
        for h in hits:
            h["snippets"] = _snippets(h.get("body") or h.get("summary") or "", kws)
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


def _is_closed(d):
    """休市日:週末 + data/calendar/tw_holidays.json(沿用 storage._is_closed)。
    storage 載入失敗時退回只跳週末,並在 stderr 警告一次(時間窗可能把國定假日當交易日)。"""
    global _CLOSED_FALLBACK_WARNED
    try:
        if str(SCRIPTS) not in sys.path:
            sys.path.insert(0, str(SCRIPTS))
        import storage
        return storage._is_closed(d)
    except Exception as e:
        if not _CLOSED_FALLBACK_WARNED:
            _CLOSED_FALLBACK_WARNED = True
            print(f"  [holiday] 休市判斷失敗,只跳週末:{e!r}", file=sys.stderr)
        return d.weekday() >= 5


_CLOSED_FALLBACK_WARNED = False


def _prev_business_day(d):
    """回傳 d 之前最近的交易日(跳過週末與國定休市日)。不含 d 本身。
    連假後首日(如 10/12 週一,10/09 補假)會正確回溯到 10/08,不漏整段盤後新聞。"""
    pd = d - datetime.timedelta(days=1)
    while _is_closed(pd):
        pd -= datetime.timedelta(days=1)
    return pd


PREMARKET_CUTOFF = datetime.time(14, 0)   # 使用者 2026-08-13 指定:前一交易日 14:00


def market_session_cutoff(now=None):
    """盤前彙整時間窗『下界』:前一交易日 14:00。
    回 (cutoff_datetime_aware, prev_date)。盤前 digest 用此窗 → 涵蓋昨晚
    傍晚公布的個股營收速報 + 隔夜美股 + 今早盤前,不會把『昨天傍晚』的漏掉。
    _prev_business_day 跳週末與休市日:週一回溯週五,連假後首日回溯到假期前最後交易日。"""
    now = (now or _now_tw()).astimezone(TAIPEI)
    prev = _prev_business_day(now.date())
    cutoff = datetime.datetime.combine(prev, PREMARKET_CUTOFF, tzinfo=TAIPEI)
    return cutoff, prev


def fetch_market_news(since="last_close", days=1, tag_sentiment=None):
    """彙整『全市場』新聞(不需 codes/keyword),供「盤前四象限重點」digest 模式。

    與 query_news 不同:它不依代號/關鍵字過濾,而是把六家即時流(cnyes/udn/
    ctee/anue/moneydj/yahoo)在時間窗內的新聞整批撈回,去重 → 時間過濾 →
    依時間倒序 → 標 sentiment。提供 --today CLI 與下游(四象限整理)當原料。

    參數 since(時間窗,預設 'last_close'):
      'last_close' : 自『前一交易日 14:00』到現在。**盤前正解** —— 台股
                     個股營收速報是盤後/傍晚才發(掛在前一日),用此窗才不會漏。
      'today'      : 只留今天(同一日曆日)。盤後純當日用。
      'days'       : 近 days 日(無日期者保留;向後相容舊行為)。
    days          : since='days' 時的回溯天數。
    tag_sentiment : 是否補 sentiment/confidence/events(預設讀 config,預設 True)。

    回傳: list[news],news = {time,title,source,url,summary,body
                            [, sentiment,confidence,events]}。
    主路徑(main.aggregate)已逐篇抓好全文,body 即全文;同一份抓取結果走 TTL 快取
    (記憶體 + out/.sanbao_cache.json),短時間內再查不重抓。
    """
    n = news_cfg()
    tag = (n.get("tag_sentiment", True) if tag_sentiment is None
           else bool(tag_sentiment))

    sys.path.insert(0, str(SCRIPTS))
    import news_providers as NP
    sb = _fetch_sanbao_cached(NP, n)          # 約十家即時流,已依 url/title 去重

    def _dt(s):
        try:
            d = datetime.datetime.fromisoformat((s or "").strip())
            return d if d.tzinfo else d.replace(tzinfo=TAIPEI)
        except Exception:
            return None

    now = _now_tw()
    today = now.date()
    if since == "last_close":                     # 盤前窗:前一交易日 14:00 起
        cutoff, _ = market_session_cutoff(now)
        def _keep(d):
            return d is not None and d >= cutoff
    elif since == "today":                         # 只今天(同一日曆日,台北時間)
        def _keep(d):
            return d is not None and d.astimezone(TAIPEI).date() == today
    else:                                          # 近 N 日(無日期保留)
        cutoff = now - datetime.timedelta(days=days)
        def _keep(d):
            return d is None or d >= cutoff

    items = []
    for it in sb:
        if not _keep(_dt(it.get("published_at", ""))):
            continue
        items.append({"time": it.get("published_at", ""), "title": it["title"],
                      "source": it["source"], "url": it["url"],
                      "summary": it.get("summary", ""), "body": it.get("body", "")})

    _MIN = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)
    items.sort(key=lambda h: _dt(h.get("time")) or _MIN, reverse=True)
    if tag:
        _tag_sentiment_inplace(items)
    return items
