# -*- coding: utf-8 -*-
"""
三大報新聞來源(cnyes 鉅亨 / udn 經濟日報 / ctee 工商時報)。
共通輸出: {source, title, summary, body, url, published_at(ISO 或 ""), keywords[]}
  body: cnyes 直接帶(newslist 內含 content);udn/ctee 命中個股後才 attach_bodies
每家獨立容錯 —— 0940 時間敏感,一家掛掉不可拖累其他家。

註:永豐公司網路是 TLS 攔截(MITM),requests+certifi 會 CERTIFICATE_VERIFY_FAILED;
   stdlib urllib 用系統憑證實測可通。故全程走 urllib,並在 SSL 失敗時退回未驗證
   context(內部受控網路 + 公開新聞源,可接受)。
"""
import sys, json, ssl, time, re, datetime
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

_CTEE_DATE = re.compile(r"/news/(\d{8})")

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
TIMEOUT = 12
_UNVERIFIED = ssl._create_unverified_context()


def _get(url, as_json=False):
    req = urllib.request.Request(url, headers=UA)
    try:
        r = urllib.request.urlopen(req, timeout=TIMEOUT)
    except ssl.SSLError:
        r = urllib.request.urlopen(req, timeout=TIMEOUT, context=_UNVERIFIED)
    raw = r.read()
    return json.loads(raw) if as_json else raw.decode("utf-8", "replace")


def _now_iso():
    return datetime.datetime.now().astimezone().isoformat()


def _strip_html(html, max_chars=0):
    import html as _h
    from bs4 import BeautifulSoup
    raw = _h.unescape(html or "")          # cnyes content 是實體編碼,先還原
    txt = BeautifulSoup(raw, "html.parser").get_text(" ", strip=True)
    txt = " ".join(txt.split())
    return txt[:max_chars] if max_chars else txt


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


def attach_bodies(by_code, max_chars=600, limit=40):
    """對已命中個股的新聞補內文。同一 url 只抓一次(一篇可命中多檔)。
    cnyes/anue 已有 body 就略過;udn/ctee/moneydj/yahoo 才上網抓。
    0940 時間敏感故設總量上限。"""
    cache, fetched = {}, 0
    for lst in by_code.values():
        for it in lst:
            if it.get("body"):
                continue
            url, src = it.get("url", ""), it.get("source", "")
            if not url or src in ("metabase", "cnyes", "anue"):
                continue
            if url in cache:
                it["body"] = cache[url]
                continue
            if fetched >= limit:
                continue
            body = fetch_body(url, src, max_chars)
            cache[url] = body
            it["body"] = body
            fetched += 1
    return fetched


def fetch_cnyes(categories, pages=3):
    out = []
    for cat in categories:
        for page in range(1, pages + 1):
            url = (f"https://api.cnyes.com/media/api/v1/newslist/"
                   f"category/{cat}?limit=30&page={page}")
            try:
                items = _get(url, as_json=True).get("items", {}).get("data", [])
            except Exception as e:
                print(f"  cnyes warn {cat} p{page}: {e!r}", file=sys.stderr)
                break
            if not items:
                break
            for it in items:
                ts = it.get("publishAt")
                pub = (datetime.datetime.fromtimestamp(ts).astimezone().isoformat()
                       if ts else "")
                out.append({
                    "source": "cnyes",
                    "title": it.get("title", "") or "",
                    "summary": it.get("summary", "") or "",
                    "body": _strip_html(it.get("content", "")),  # 已在 list 內,免費
                    "url": f"https://news.cnyes.com/news/id/{it.get('newsId')}"
                           if it.get("newsId") else "",
                    "published_at": pub,
                    "keywords": list(it.get("keyword") or []),
                })
    return out


def fetch_udn(feeds, limit=30):
    import feedparser
    out = []
    for feed in feeds:
        try:
            raw = _get(feed)
            d = feedparser.parse(raw)
        except Exception as e:
            print(f"  udn warn {feed}: {e!r}", file=sys.stderr)
            continue
        for e in d.entries[:limit]:
            pub = ""
            if getattr(e, "published_parsed", None):
                pub = datetime.datetime.fromtimestamp(
                    time.mktime(e.published_parsed)).astimezone().isoformat()
            out.append({
                "source": "udn",
                "title": getattr(e, "title", "") or "",
                "summary": getattr(e, "summary", "") or "",
                "body": "",                      # 命中個股後才 attach_bodies
                "url": getattr(e, "link", "") or "",
                "published_at": pub,
                "keywords": [],
            })
    return out


def fetch_ctee(pages, limit=60):
    from bs4 import BeautifulSoup
    out, seen = [], set()
    for page in pages:
        try:
            html = _get(page)
            soup = BeautifulSoup(html, "html.parser")
        except Exception as e:
            print(f"  ctee warn {page}: {e!r}", file=sys.stderr)
            continue
        anchors = (soup.select("h3.post-title a")
                   or soup.select("article.post h3 a")
                   or soup.select("h3 a[href*='/news/']")
                   or soup.select("h3 a"))
        for a in anchors[:limit]:
            href = a.get("href", "")
            title = a.get_text(strip=True)
            if not title or not href or "/news/" not in href or href in seen:
                continue
            seen.add(href)
            # ctee URL 含 /news/YYYYMMDD... → 可還原日期(無時分,取當日 08:00)
            pub = ""
            m = _CTEE_DATE.search(href)
            if m:
                try:
                    d = datetime.datetime.strptime(m.group(1), "%Y%m%d")
                    pub = d.replace(hour=8).astimezone().isoformat()
                except Exception:
                    pass
            out.append({
                "source": "ctee",
                "title": title,
                "summary": "",
                "body": "",                      # 命中個股後才 attach_bodies
                "url": href if href.startswith("http")
                       else "https://www.ctee.com.tw" + href,
                "published_at": pub,
                "keywords": [],
            })
    return out


def fetch_anue_forum(categories, pages=2):
    """Anue 鉅亨「論壇/精選版面」入口。
    forum.cnyes.com 與部分 sub-domain 在公司網路常 504,故改走 cnyes 公開
    newslist API 但取與 fetch_cnyes 預設不同的 category(精選版面,如
    tw_stock_news 台股新聞)。source 標 'anue' 以便使用者區分。
    格式與 fetch_cnyes 完全相同;newslist 已含 content,免再 attach_bodies。"""
    out = []
    for cat in categories:
        for page in range(1, pages + 1):
            url = (f"https://api.cnyes.com/media/api/v1/newslist/"
                   f"category/{cat}?limit=30&page={page}")
            try:
                items = _get(url, as_json=True).get("items", {}).get("data", [])
            except Exception as e:
                print(f"  anue warn {cat} p{page}: {e!r}", file=sys.stderr)
                break
            if not items:
                break
            for it in items:
                ts = it.get("publishAt")
                pub = (datetime.datetime.fromtimestamp(ts).astimezone().isoformat()
                       if ts else "")
                out.append({
                    "source": "anue",
                    "title": it.get("title", "") or "",
                    "summary": it.get("summary", "") or "",
                    "body": _strip_html(it.get("content", "")),
                    "url": f"https://news.cnyes.com/news/id/{it.get('newsId')}"
                           if it.get("newsId") else "",
                    "published_at": pub,
                    "keywords": list(it.get("keyword") or []),
                })
    return out


_MONEYDJ_TIME = re.compile(r"(\d{1,2})/(\d{1,2})\s+(\d{1,2}):(\d{2})")


def fetch_moneydj(pages, limit=40):
    """MoneyDJ 新聞列表(table 結構)。
    pages: list[str] — 例如 'https://www.moneydj.com/kmdj/news/newsreallist.aspx?a=mb010000'
    擷取每列「時間 + 標題 a + href」,連結為 newsviewer.aspx?a=<uuid>&c=<cat>。
    時間欄是 'MM/DD HH:MM' 無年份 → 取當年(若 MM/DD 大於今日,視為去年)。
    body 留空,等 attach_bodies(個股命中時)抓內文。"""
    from bs4 import BeautifulSoup
    out, seen = [], set()
    today = datetime.date.today()
    for page in pages:
        try:
            html = _get(page)
            soup = BeautifulSoup(html, "html.parser")
        except Exception as e:
            print(f"  moneydj warn {page}: {e!r}", file=sys.stderr)
            continue
        # newsviewer 連結作為錨點;往上找 <tr> 取同列時間 cell
        anchors = soup.select("a[href*='newsviewer.aspx']")
        cnt = 0
        for a in anchors:
            if cnt >= limit:
                break
            href = a.get("href", "")
            title = a.get_text(strip=True)
            if not title or not href:
                continue
            full = (href if href.startswith("http")
                    else "https://www.moneydj.com" + (
                        href if href.startswith("/") else "/kmdj/news/" + href))
            if full in seen:
                continue
            seen.add(full)
            # 找同列 tr 內第一個 td 的時間文字
            pub = ""
            tr = a.find_parent("tr")
            if tr:
                tds = tr.find_all("td")
                if tds:
                    m = _MONEYDJ_TIME.search(tds[0].get_text(" ", strip=True))
                    if m:
                        mm, dd, hh, mi = map(int, m.groups())
                        try:
                            yr = today.year
                            d = datetime.datetime(yr, mm, dd, hh, mi)
                            if d.date() > today:  # 未來日期 → 去年
                                d = d.replace(year=yr - 1)
                            pub = d.astimezone().isoformat()
                        except Exception:
                            pass
            out.append({
                "source": "moneydj",
                "title": title,
                "summary": "",
                "body": "",
                "url": full,
                "published_at": pub,
                "keywords": [],
            })
            cnt += 1
    return out


def fetch_yahoo_stock(feeds, limit=40):
    """Yahoo 奇摩股市 RSS(tw.stock.yahoo.com/rss?category=...)。
    用法同 fetch_udn:走 feedparser。body 留空等 attach_bodies。"""
    import feedparser
    out = []
    for feed in feeds:
        try:
            raw = _get(feed)
            d = feedparser.parse(raw)
        except Exception as e:
            print(f"  yahoo warn {feed}: {e!r}", file=sys.stderr)
            continue
        for e in d.entries[:limit]:
            pub = ""
            if getattr(e, "published_parsed", None):
                pub = datetime.datetime.fromtimestamp(
                    time.mktime(e.published_parsed)).astimezone().isoformat()
            out.append({
                "source": "yahoo",
                "title": getattr(e, "title", "") or "",
                "summary": getattr(e, "summary", "") or "",
                "body": "",
                "url": getattr(e, "link", "") or "",
                "published_at": pub,
                "keywords": [],
            })
    return out


def fetch_sanbao(news_cfg):
    """抓多家、依 url/title 去重。
    歷史命名為 'sanbao'(三大報),已擴充至 cnyes/udn/ctee/anue/moneydj/yahoo。

    六家以 ThreadPoolExecutor 並行抓取(urllib 為 I/O bound,threading 有效益)。
    每家獨立 try/except —— 0940 時間敏感,一家掛掉/逾時只 warn,不拖垮其他家。
    各 fetch 回傳自己的 list(thread-safe,不共用可變狀態),主執行緒依固定來源
    順序合併後再去重 —— 順序穩定 → 去重結果與原序列版完全一致。"""

    # 各家獨立 worker:自帶 try/except,失敗只 warn 回 []。
    # source 標籤用於合併時排序,確保去重保留順序與序列版一致。
    def _safe(name, fn, *a):
        try:
            return fn(*a)
        except Exception as e:
            print(f"  {name} fatal: {e!r}", file=sys.stderr)
            return []

    tasks = [
        ("cnyes", _safe, "cnyes", fetch_cnyes,
         news_cfg.get("cnyes_categories", ["tw_stock", "headline"]),
         news_cfg.get("cnyes_pages", 3)),
        ("udn", _safe, "udn", fetch_udn,
         news_cfg.get("udn_feeds", []),
         news_cfg.get("udn_limit", 30)),
        ("ctee", _safe, "ctee", fetch_ctee,
         news_cfg.get("ctee_pages", ["https://www.ctee.com.tw/livenews"]),
         news_cfg.get("ctee_limit", 60)),
        # anue 預設取 cnyes 主流程沒覆蓋的子站(美股雷達/外匯),避免與
        # fetch_cnyes 完全重複(tw_stock_news 是 tw_stock 子集 → 100% 被去重)。
        ("anue", _safe, "anue", fetch_anue_forum,
         news_cfg.get("anue_categories", ["wd_stock", "forex"]),
         news_cfg.get("anue_pages", 2)),
        ("moneydj", _safe, "moneydj", fetch_moneydj,
         news_cfg.get("moneydj_pages",
                      ["https://www.moneydj.com/kmdj/news/newsreallist.aspx"
                       "?a=mb010000"]),
         news_cfg.get("moneydj_limit", 40)),
        ("yahoo", _safe, "yahoo", fetch_yahoo_stock,
         news_cfg.get("yahoo_feeds",
                      ["https://tw.stock.yahoo.com/rss?category=tw-market"]),
         news_cfg.get("yahoo_limit", 40)),
    ]
    order = [t[0] for t in tasks]               # 固定來源順序

    # 並行送出;各 future 回傳自己那家的 list,互不共用狀態。
    by_src = {}
    with ThreadPoolExecutor(max_workers=len(tasks)) as ex:
        fut_to_name = {ex.submit(t[1], *t[2:]): t[0] for t in tasks}
        for fut in as_completed(fut_to_name):
            name = fut_to_name[fut]
            try:
                by_src[name] = fut.result()
            except Exception as e:                # _safe 已吞例外,此為雙保險
                print(f"  {name} fatal: {e!r}", file=sys.stderr)
                by_src[name] = []

    # 依固定來源順序攤平 → 去重(保留先出現者),結果與原序列版一致。
    items = []
    for name in order:
        items += by_src.get(name, [])

    seen, uniq = set(), []
    for it in items:
        key = it["url"] or it["title"]
        if key in seen:
            continue
        seen.add(key)
        uniq.append(it)
    return uniq


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
        for code, name in code_to_name.items():
            if not name:
                continue
            # 代號加數字/金額單位邊界,避免「逾2330億」「12330張」誤命中
            if name in blob or re.search(
                    r"(?<!\d)" + re.escape(str(code)) + r"(?![\d億萬點元張])", blob):
                by_code.setdefault(code, []).append({
                    "time": pub or _now_iso(),
                    "title": it["title"],
                    "source": it["source"],
                    "url": it["url"],
                    "summary": it.get("summary", ""),
                    "body": it.get("body", ""),
                })
    return by_code
