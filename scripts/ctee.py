"""工商時報 ctee.com.tw 新聞爬蟲 — Google News URL 解碼 API（無瀏覽器）。

2026-06-26：ctee.com.tw 全域 Cloudflare 403，列表頁/RSS/sitemap 均無法直連；
但 robots.txt 與個別 /news/ 文章頁（社群預覽需求）回 200 OK 可全文取。
修法：
  1. Google News RSS (feedparser) 取工商時報文章清單（標題/日期/摘要，~1-2s）
  2. 用 Google News 解碼 API 把 redirect 還原成真實 ctee /news/ URL
     （GET 文章頁取 signature/timestamp → POST batchexecute，~0.5s/篇，
      伺服器對伺服器、不開瀏覽器、不會中 CAPTCHA；舊 Playwright 版每篇開
      Chromium 會被 google.com/sorry 限流頁擋掉，已棄用）
  3. 直接抓 ctee /news/ 文章內文（200 OK，article 選擇器確認有效）

文章解析重用 backfill_ctee.parse_article / _publish_str_to_iso（工商版型）。
"""
from __future__ import annotations

import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Iterable
from urllib.parse import quote

import feedparser
import requests
from bs4 import BeautifulSoup

try:
    from .common import parse_article_fields, request_get, to_taipei_iso, UA
    from .backfill_ctee import URL_DATE_RE, parse_article, _publish_str_to_iso, classify
except ImportError:
    from common import parse_article_fields, request_get, to_taipei_iso, UA
    from backfill_ctee import URL_DATE_RE, parse_article, _publish_str_to_iso, classify

HEADERS = {"User-Agent": UA}

# Google News RSS - 工商時報台股財經
_GNEWS_RSS = (
    "https://news.google.com/rss/search"
    "?q=%E5%B7%A5%E5%95%86%E6%99%82%E5%A0%B1+%E8%82%A1%E5%B8%82"
    "&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
)
_BATCHEXECUTE = "https://news.google.com/_/DotsSplashUi/data/batchexecute"
_DECODE_WORKERS = 6  # ponytail: 併發解碼數,Google 偶爾限流就調低


# ── 步驟 1：取 RSS 文章清單（快速，~1-2s）─────────────────────────────────

def _fetch_rss(limit: int = 50) -> list[dict]:
    """從 Google News RSS 取工商時報文章（標題/日期/摘要 + Google redirect URL）。"""
    try:
        feed = feedparser.parse(_GNEWS_RSS)
        items = []
        for e in feed.entries[:limit]:
            if "工商" not in e.get("title", "") and "ctee" not in e.get("source", {}).get("href", ""):
                continue
            title = e.get("title", "")
            # 去掉 " - 工商時報" 或 " - 證券 - 工商時報" 尾綴
            title = re.sub(r"\s*-\s*工商時報$", "", title).strip()
            items.append({
                "title": title,
                "google_url": e.get("link", ""),
                "published_date": e.get("published", ""),
                "summary": e.get("summary", ""),
            })
        return items
    except Exception as e:
        print(f"[ctee] RSS 取得失敗: {e}", file=sys.stderr)
        return []


# ── 步驟 2：Google News 解碼 API 還原 → ctee URL（~0.5s/篇，併發）─────────

_CTEE_URL_RE = re.compile(r"https?://www\.ctee\.com\.tw/news/[0-9]+-[0-9]+")


def _decode_one(session: requests.Session, gurl: str) -> tuple[str, str] | None:
    """解碼單一 Google News URL → 真實 ctee URL。

    兩步：GET 文章頁取 c-wiz 的 data-n-a-sg / data-n-a-ts，再 POST batchexecute。
    失敗回 None。
    """
    try:
        gn_id = gurl.split("/articles/")[1].split("?")[0]
    except IndexError:
        return None
    try:
        r = session.get(f"https://news.google.com/rss/articles/{gn_id}", timeout=15)
        if r.status_code != 200:
            return None
        div = BeautifulSoup(r.text, "html.parser").select_one("c-wiz > div")
        if not div:
            return None
        sig = div.get("data-n-a-sg")
        ts = div.get("data-n-a-ts")
        if not sig or not ts:
            return None
        inner = (
            '["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,'
            'null,null,null,null,null,0,1],"X","X",1,[1,1,1],1,1,null,0,0,null,0],'
            f'"{gn_id}",{ts},"{sig}"]'
        )
        payload = "f.req=" + quote(json.dumps([[["Fbv4je", inner]]]))
        pr = session.post(
            _BATCHEXECUTE,
            headers={"content-type": "application/x-www-form-urlencoded;charset=UTF-8"},
            data=payload,
            timeout=15,
        )
        m = _CTEE_URL_RE.search(pr.text)
        return (gurl, m.group(0)) if m else None
    except Exception:
        return None


def _resolve_urls(google_urls: list[str]) -> dict[str, str]:
    """併發解碼 Google News URL → ctee URL。回傳 {google_url: ctee_url}。"""
    session = requests.Session()
    session.headers.update(HEADERS)
    result: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=_DECODE_WORKERS) as ex:
        for pair in ex.map(lambda u: _decode_one(session, u), google_urls):
            if pair:
                result[pair[0]] = pair[1]
    return result


# ── 步驟 3：抓文章頁全文（ctee /news/ URL，200 OK）─────────────────────────

def _detail_fields(url: str) -> dict:
    """抓 ctee 文章頁：精確時間 + 作者 + 摘要 + 全文（失敗回空欄位）。

    parse_article 的 body 選擇器（article / div.article-content）
    與 /news/ URL 格式相容（2026-06-26 確認 article 選擇器命中 17+ 段落）。
    """
    try:
        html = request_get(url, headers=HEADERS).text
    except Exception:
        return {"publish": "", "author": "", "summary": "", "content": ""}
    pa = parse_article(html)
    af = parse_article_fields(html)
    iso = _publish_str_to_iso(pa.get("publish_str", ""))
    return {
        "publish": to_taipei_iso(iso) if iso else "",
        "author": af["author"],
        "summary": pa.get("summary") or af["summary"],
        "content": pa.get("body") or af["content"],
    }


# ── 公開 API ─────────────────────────────────────────────────────────────

def fetch(
    categories: Iterable[str] | None = None,
    limit_per_cat: int = 15,
    fetch_content: bool = False,
) -> list[dict]:
    """抓取工商時報新聞。

    流程：
      1. Google News RSS 取文章清單（快速）
      2. 解碼 API 併發還原 URL → 真實 ctee URL
      3. 分類過濾
      4. 可選：抓全文

    categories=None：接受所有分類（證券/產業/國際財經/美股/日股/外匯/日報）。
    fetch_content=False：只回標題/摘要/URL，不抓內文（僅 RSS + 解碼，~7s/20 篇）。
    fetch_content=True：逐篇抓 ctee 文章全文（每篇 +1 request + 0.3s sleep）。
    """
    target_cats = set(categories) if categories else set()
    rss_limit = max(limit_per_cat * 5, 30)

    # 步驟 1: RSS
    rss_items = _fetch_rss(rss_limit)
    if not rss_items:
        return []

    # 步驟 2: 解碼 API 還原 URL
    google_urls = [item["google_url"] for item in rss_items if item["google_url"]]
    url_map = _resolve_urls(google_urls)  # {google_url: ctee_url}

    # 步驟 3: 組裝結果。
    # 盤前信只吃財經版位：/stock/star（亮點個股）與 /industry/i-prime（產業焦點）
    # 是編輯策展頁沒有專屬分類碼，且列表頁被 WAF 擋（文章頁 200、列表頁 403，
    # 換無痕或換 UA 都無效，擋的是路徑規則），無法直接訂閱；但它們的取材來源
    # 就是 430201 證券與 430503 產業，所以改成優先保留這兩碼、排除非財經版位。
    # 先排序再套 limit_per_cat，避免高價值文章被低價值的先佔滿額度。
    # 已知上限：進料是 Google News RSS，本身就以日報(4399)為大宗，實測 13 則裡
    # 證券僅 1 則、產業 0 則。排序解決的是「有貨時別被擠掉」，不能無中生有。
    # 注意：classify 會把 4307 國際再依標題細分成 國際財經/美股/日股/外匯，
    # 4399 日報則歸「即時新聞」，優先序表要用細分後的標籤才對得上。
    PRIORITY = {"證券": 0, "產業": 1, "金融": 2,
                "美股": 3, "國際財經": 4, "日股": 5, "外匯": 6,
                "即時新聞": 7, "商情": 8, "要聞": 9}
    EXCLUDE = {"房市", "生活", "兩岸", "理財"}

    decoded = []
    for item in rss_items:
        ctee_url = url_map.get(item["google_url"])
        if not ctee_url:
            continue
        m = URL_DATE_RE.search(ctee_url)
        if not m:
            continue
        sub_label, _ = classify(ctee_url, m.group(3), item["title"])
        if target_cats:
            if sub_label not in target_cats:
                continue
        elif sub_label in EXCLUDE:
            continue
        decoded.append((PRIORITY.get(sub_label, 99), sub_label, ctee_url, item))
    decoded.sort(key=lambda x: x[0])

    cat_counts: dict[str, int] = {}
    out: list[dict] = []

    for _prio, sub_label, ctee_url, item in decoded:
        if cat_counts.get(sub_label, 0) >= limit_per_cat:
            continue

        pub = to_taipei_iso(item["published_date"]) if item["published_date"] else ""
        author = summary = content = ""

        if fetch_content:
            det = _detail_fields(ctee_url)
            if det["publish"]:
                pub = det["publish"]
            author, summary, content = det["author"], det["summary"], det["content"]
            time.sleep(0.3)  # 同網域禮貌間隔(來源間已並行,見 main.aggregate)
        else:
            summary = item.get("summary", "")

        out.append({
            "source": "ctee",
            "category": sub_label,
            "title": item["title"],
            "author": author,
            "url": ctee_url,
            "summary": summary,
            "content": content,
            "published_at": pub,
        })
        cat_counts[sub_label] = cat_counts.get(sub_label, 0) + 1

    return out


if __name__ == "__main__":
    import sys
    do_content = "--content" in sys.argv
    t0 = time.time()
    results = fetch(limit_per_cat=5, fetch_content=do_content)
    elapsed = time.time() - t0
    print(f"Done: {len(results)} articles in {elapsed:.1f}s")
    for r in results:
        print(r["published_at"], f"[{r['category']}]", r["title"][:60])
        print("  ", r["url"])
        if do_content and r["content"]:
            print("  ", r["content"][:100])
