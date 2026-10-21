# -*- coding: utf-8 -*-
"""
新聞來源層。即時新聞一律走 fetch_sanbao() 委派 main.aggregate()(9 家主路徑,採集器在
cnyes.py/udn.py/ctee.py/rss_sources.py),本檔只做欄位映射,主路徑跑不起來就直接報錯。
其餘:補內文(fetch_body/prefetch_candidate_bodies/attach_bodies,並行抓)、cnyes 全站搜尋、
個股直取、即時流比對個股、報告型新鮮度判斷、別名與離線股名。
fetch_sanbao 輸出: {source, title, summary, body, url, published_at, keywords[], stock_codes[], category}
"""
import sys, json, ssl, re, datetime
import urllib.request
from concurrent.futures import ThreadPoolExecutor

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
TIMEOUT = 12
_UNVERIFIED = ssl._create_unverified_context()


def _get(url, as_json=False):
    if "ctee.com.tw" in url:
        try:
            import requests
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            r = requests.get(url, headers=UA, timeout=TIMEOUT, verify=False)
            return r.json() if as_json else r.text
        except Exception as e:
            print(f"  requests fallback ctee fail: {e!r}", file=sys.stderr)

    req = urllib.request.Request(url, headers=UA)
    try:
        r = urllib.request.urlopen(req, timeout=TIMEOUT)
    except ssl.SSLError:
        r = urllib.request.urlopen(req, timeout=TIMEOUT, context=_UNVERIFIED)
    raw = r.read()
    return json.loads(raw) if as_json else raw.decode("utf-8", "replace")


def _now_iso():
    return datetime.datetime.now().astimezone().isoformat()


# 文章內文選擇器(逐源 fallback);cnyes/anue 不在此 —— 它們的 newslist 已內含 content
_BODY_SELECTORS = {
    "udn": ["section.article-body__editor", "#article_body",
            "div.article-content__editor"],
    "ctee": ["div.entry-content", "div.post-content", "article"],
    # moneydj 文章頁:#NewsArticleContent 為內容容器;備援 article / div.article
    "moneydj": ["#NewsArticleContent", "div.article", "article"],
    # yahoo 股市文章:.caas-body 為主要文章容器;備援 article
    "yahoo": ["div.caas-body", "article", "div.article-body"],
}


def fetch_body(url, source, max_chars=600):
    """抓單篇文章內文(udn/ctee 用;cnyes 內文已在 list 內)。逐篇容錯。"""
    if not url:
        return ""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(_get(url), "html.parser")
    except Exception as e:
        print(f"  body warn {source} {url[:50]}: {e!r}", file=sys.stderr)
        return ""
    for sel in _BODY_SELECTORS.get(source, ["article"]):
        el = soup.select_one(sel)
        if el:
            t = " ".join(el.get_text(" ", strip=True).split())
            if len(t) > 60:                     # 過濾抓到空殼/導覽
                return t[:max_chars] if max_chars else t
    return ""


# 產業熱詞:標題含這些 → 很可能是個股漲因深度文,比對前先補內文(解雞生蛋)
HOT_TERMS = ["目標價", "EPS", "稼動率", "缺貨", "漲價", "報價", "調升", "評等",
             "外資", "投信", "法說", "營收", "載板", "封裝", "封測", "矽光子",
             "記憶體", "受惠", "供應鏈", "訂單", "毛利"]

# 註:描述性稱謂(IC載板大廠=南電…)不另建表——只要「比對前先抓內文(prefetch)」+
#     P1-1 別名比對,內文一出現股名/別名就會配到,稱謂表反而易在內文沒點名時誤配整族群,故不做。


def _fetch_bodies_parallel(jobs, max_chars):
    """jobs: {url: source}。以 6 條執行緒並行抓內文,回 {url: body}。
    單篇失敗回空字串,不影響其他篇。"""
    if not jobs:
        return {}

    def _one(url, src):
        try:
            return fetch_body(url, src, max_chars)
        except Exception:
            return ""

    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {url: ex.submit(_one, url, src) for url, src in jobs.items()}
    return {url: f.result() for url, f in futs.items()}


def prefetch_candidate_bodies(items, max_chars=600, limit=40):
    """比對前先補內文:對『標題含產業熱詞、body 仍空、需上網抓』的候選文抓內文,
    讓 match_news_to_codes 的 blob 在比對當下就有內文(否則標題無股名者永遠命不中)。
    有總量上限(盤中時間敏感)。先收集要抓的 url(同 url 只抓一次),再並行抓、回填。"""
    jobs, targets = {}, []                  # jobs: {url: src} 依加入順序;targets: (item, url)
    for it in items:
        if len(jobs) >= limit:              # 到上限就停止掃描(後面同 url 的也不回填,同原行為)
            break
        if it.get("body"):
            continue
        title = it.get("title", "") or ""
        if not any(h in title for h in HOT_TERMS):
            continue
        url, src = it.get("url", ""), it.get("source", "")
        if not url or src in ("metabase", "cnyes", "anue", "cnyes-search"):
            continue
        jobs.setdefault(url, src)
        targets.append((it, url))
    bodies = _fetch_bodies_parallel(jobs, max_chars)
    for it, url in targets:
        it["body"] = bodies.get(url, "")
    return len(jobs)


def attach_bodies(by_code, max_chars=600, limit=40):
    """對已命中個股的新聞補內文。同一 url 只抓一次(一篇可命中多檔)。
    cnyes/anue 已有 body 就略過;udn/ctee/moneydj/yahoo 才上網抓。
    0940 時間敏感故設總量上限。先收集要抓的 url,再並行抓、回填同 url 的每一則。"""
    jobs, targets = {}, []                  # jobs: {url: src} 依加入順序;targets: (item, url)
    for lst in by_code.values():
        for it in lst:
            if it.get("body"):
                continue
            url, src = it.get("url", ""), it.get("source", "")
            if not url or src in ("metabase", "cnyes", "anue"):
                continue
            if url not in jobs:
                if len(jobs) >= limit:      # 超過上限的新 url 略過,已排入的 url 仍回填
                    continue
                jobs[url] = src
            targets.append((it, url))
    bodies = _fetch_bodies_parallel(jobs, max_chars)
    for it, url in targets:
        it["body"] = bodies.get(url, "")
    return len(jobs)


def fetch_sanbao(news_cfg):
    """即時新聞主路徑:呼叫 main.aggregate()(cnyes/udn/ctee + rss_sources 六家,共 9 家),
    映射成本檔共通格式。import main 失敗或 aggregate 拋例外時直接 raise RuntimeError,
    不再退回舊版爬蟲(舊備援會少 stock_codes/category 欄位,靜默降級反而難發現問題)。"""
    import pathlib
    scripts_path = str(pathlib.Path(__file__).resolve().parent)
    if scripts_path not in sys.path:
        sys.path.insert(0, scripts_path)
    fb = news_cfg.get("fetch_body", True)
    try:
        import main as M
        print(f"  [Provider] Fetching news via new modular aggregator (fetch_content={fb})...", file=sys.stderr)
        raw_items = M.aggregate(fetch_content=fb)
    except Exception as e:
        raise RuntimeError(
            f"即時新聞主路徑(main.aggregate)無法執行,多半是缺套件,"
            f"請先執行 pip install -r requirements.txt。原始錯誤: {e!r}") from e

    mapped_items = []
    for it in raw_items:
        mapped_items.append({
            "source": it.get("source", "unknown"),
            "title": it.get("title", ""),
            "summary": it.get("summary") or (it.get("content") or "")[:150],
            "body": it.get("content") or it.get("summary") or "",
            "url": it.get("url", ""),
            "published_at": it.get("published_at", ""),
            "keywords": [],
            "stock_codes": it.get("stock_codes", []),   # 出版商標的代號(cnyes/anue)
            "category": it.get("category", "") or "",   # 來源分類(國際焦點/外匯…),--intl 用
        })
    return mapped_items


# 產業/法人報告型新聞:時效較長(目標價、EPS、評等、法說…),放寬到 report_days 天;
# 一般即時新聞用 news_days 天。
REPORT_TERMS = ["目標價", "EPS", "評等", "調升", "升評", "降評", "Factset", "法說",
                "分析師", "研報", "上看", "重申", "買進", "加碼", "減碼", "中立",
                "財測", "展望", "外資看", "外資調", "券商", "預估"]


def is_report(title):
    t = title or ""
    return any(k in t for k in REPORT_TERMS)


def recent_ok(pub, title, news_days=3, report_days=10):
    """新鮮度:報告型(is_report)取 report_days 與 news_days 較大者(只放寬不縮短),
    其餘 news_days。無日期/無法解析 → 保留(與現行『無時間視為當日』一致)。"""
    if not pub:
        return True
    try:
        d = datetime.datetime.fromisoformat(str(pub).strip())
    except Exception:
        return True
    if d.tzinfo is None:
        d = d.astimezone()
    lim = max(report_days, news_days) if is_report(title) else news_days
    return d >= datetime.datetime.now().astimezone() - datetime.timedelta(days=lim)


_ALIAS_MAP = None
_NAME_MAP = {}


def _alias_map():
    """{裸代號: [別名…]} 取自 data/stocks/tw_stocks.json(已過 build_stock_dict 黑名單)。
    別名長度 >=2;讓 match_news_to_codes 除了單一簡稱外,也認『南亞電路板/ABF載板』等。
    同時記下 name_zh 給 local_stock_name(沒有 Metabase 時的離線股名)。"""
    global _ALIAS_MAP
    if _ALIAS_MAP is None:
        _ALIAS_MAP = {}
        try:
            import pathlib
            p = (pathlib.Path(__file__).resolve().parent.parent
                 / "data" / "stocks" / "tw_stocks.json")
            for tk, info in json.loads(p.read_text(encoding="utf-8")).items():
                bare = str(tk).split(".")[0]
                if info.get("name_zh"):
                    _NAME_MAP[bare] = info["name_zh"]
                al = [a for a in (info.get("aliases") or []) if a and len(a) >= 2]
                if al:
                    _ALIAS_MAP[bare] = al
        except Exception as e:
            print(f"  alias map load warn: {e!r}", file=sys.stderr)
            _ALIAS_MAP = {}
    return _ALIAS_MAP


_FULL_NAMES = None


def local_stock_name(code):
    """離線股名:先查官方全市場 tw_names.json(build_stock_dict.py --names 產生,上市加上櫃,
    改名時較新),再查策展字典 tw_stocks.json 的 name_zh(補 ETF 等);都沒有回 ""(只能靠代號比對)。"""
    global _FULL_NAMES
    _alias_map()
    code = str(code)
    if _FULL_NAMES is None:
        try:
            import pathlib
            p = (pathlib.Path(__file__).resolve().parent.parent
                 / "data" / "stocks" / "tw_names.json")
            _FULL_NAMES = json.loads(p.read_text(encoding="utf-8"))
        except Exception:                  # 檔案不在就只用策展字典
            _FULL_NAMES = {}
    return _FULL_NAMES.get(code) or _NAME_MAP.get(code, "")


def _alias_hit(aliases, blob):
    for a in aliases:
        if re.search(r"[A-Za-z0-9]", a):           # 英數別名加邊界防誤命中
            if re.search(r"(?<![A-Za-z0-9])" + re.escape(a) + r"(?![A-Za-z0-9])", blob):
                return True
        elif a in blob:                            # 中文別名直接比對
            return True
    return False


def _http_json(url, params=None, timeout=12):
    import urllib.request, urllib.parse
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0", "Origin": "https://news.cnyes.com",
        "Referer": "https://news.cnyes.com/"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def search_cnyes_news(keyword, limit=30):
    """cnyes 全站搜尋(關鍵字模式補腿,約 0.1 到 1 秒/詞)。回 provider 共通格式 + category。
    注意:API 的 content 是命中處附近的短片段(非全文),直接當 body 用,不另抓內頁。
    速報(自動價格快報)略過;任何失敗回 []。"""
    try:
        from common import html_to_text, to_taipei_iso
    except ImportError:
        from .common import html_to_text, to_taipei_iso
    try:
        j = _http_json("https://api.cnyes.com/media/api/v1/search/news",
                       {"q": keyword, "limit": limit})
    except Exception as e:
        print(f"  cnyes-search warn {keyword}: {e!r}", file=sys.stderr)
        return []
    out = []
    for it in ((j.get("items") or {}).get("data")) or []:
        title = re.sub(r"</?mark>", "", it.get("title") or "")
        if not title or "速報" in title:
            continue
        cats = it.get("category") or []
        out.append({
            "source": "cnyes-search", "title": title, "summary": "",
            "body": html_to_text(re.sub(r"</?mark>", "", it.get("content") or "")),
            "url": (f"https://news.cnyes.com/news/id/{it.get('newsId')}"
                    if it.get("newsId") else ""),
            "published_at": to_taipei_iso(it.get("publishAt")),
            "category": ((cats[0] or {}).get("name", "") if cats else "") or "",
            "keywords": [],
        })
    return out


def fetch_stock_news(code, name, limit=30, body_cap=600):
    """per-代號『直取』個股新聞(補綜合清單抓不到的個股深度報導)。
    主力:cnyes search API(依股名全文搜 cnyes 全站)。搜尋結果含雜訊,
    只留標題/內文真的提到該股名或代號者,再標 stock_codes=[code](來源即該股)。
    任何失敗回 [](非致命)。Yahoo 個股頁為 best-effort 補充。"""
    try:
        from common import html_to_text, to_taipei_iso
    except ImportError:
        from .common import html_to_text, to_taipei_iso
    code = str(code)
    out = []
    # ── cnyes search(主力)──
    try:
        j = _http_json("https://api.cnyes.com/media/api/v1/search/news",
                       {"q": name, "limit": limit})
        data = ((j.get("items") or {}).get("data")) or []
        for it in data:
            title = re.sub(r"</?mark>", "", it.get("title") or "")
            if "速報" in title:                  # 盤中/盤後速報=自動價格快報,非漲因,跳過
                continue
            body = html_to_text(it.get("content") or "")
            blob = title + " " + body
            if (name and name != code and name in blob) or re.search(   # 用代號當股名時只走邊界比對
                    r"(?<!\d)" + re.escape(code) + r"(?![\d億萬點元張])", blob):
                out.append({
                    "time": to_taipei_iso(it.get("publishAt")) or _now_iso(),
                    "title": title, "source": "cnyes-search",
                    "url": f"https://news.cnyes.com/news/id/{it.get('newsId')}",
                    "summary": "", "body": body[:body_cap], "stock_codes": [code]})
    except Exception as e:
        print(f"  fetch_stock_news cnyes-search warn {code}: {e!r}", file=sys.stderr)
    # ── Yahoo 個股頁(best-effort 補充)──
    try:
        import urllib.request
        req = urllib.request.Request(
            f"https://tw.stock.yahoo.com/quote/{code}.TW/news",
            headers={"User-Agent": "Mozilla/5.0"})
        html = urllib.request.urlopen(req, timeout=12).read().decode("utf-8", "replace")
        seen = {o["url"] for o in out}
        for m in re.finditer(r'"title":"([^"]{6,})","[^"]*?url":"(https://[^"]*?news[^"]*?)"', html):
            t = m.group(1).encode().decode("unicode_escape", "replace")
            u = m.group(2)
            if u in seen or (name not in t):
                continue
            seen.add(u)
            out.append({"time": _now_iso(), "title": t, "source": "yahoo-quote",
                        "url": u, "summary": "", "body": "", "stock_codes": [code]})
    except Exception as e:
        print(f"  fetch_stock_news yahoo warn {code}: {e!r}", file=sys.stderr)
    return out


def match_news_to_codes(items, code_to_name, lookback_days=3):
    """新聞流比對個股:標題/摘要/關鍵字含股名或代號 → 掛到該代號。
    cnyes/udn 有時間 → 過濾近 N 日;ctee 無時間 → 視為當日納入。"""
    cutoff = (datetime.datetime.now().astimezone()
              - datetime.timedelta(days=lookback_days))
    by_code = {}
    for it in items:
        pub = it.get("published_at") or ""
        if pub:
            try:
                if datetime.datetime.fromisoformat(pub) < cutoff:
                    continue
            except Exception:
                pass
        blob = (it["title"] + " " + it.get("summary", "") + " "
                + it.get("body", "") + " "        # cnyes body 已在,提高命中率
                + " ".join(it.get("keywords", [])))
        pub_codes = {str(x) for x in (it.get("stock_codes") or [])}   # 出版商標的代號
        amap = _alias_map()
        for code, name in code_to_name.items():
            # 優先:出版商已標代號 → 直接命中(零誤判,連標題用描述性指稱的也中);
            #       次:股名/代號字串(代號加數字/金額單位邊界防誤命中);
            #       再次:別名字典(南亞電路板/ABF載板…)。
            # 代號字串比對不依賴股名:沒有 Metabase 時股名可能是空字串,仍要認得「(2408)」
            hit = (str(code) in pub_codes) or bool(name and name in blob) \
                or bool(re.search(
                    r"(?<!\d)" + re.escape(str(code)) + r"(?![\d億萬點元張])", blob)) \
                or _alias_hit(amap.get(str(code), []), blob)
            if hit:
                by_code.setdefault(code, []).append({
                    "time": pub or _now_iso(),
                    "title": it["title"],
                    "source": it["source"],
                    "url": it["url"],
                    "summary": it.get("summary", ""),
                    "body": it.get("body", ""),
                })
    return by_code
