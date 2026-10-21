"""共用工具 — 台北時區時間正規化、標題正規化去重 key、HTTP retry。

所有爬蟲共用，確保 publish_ts 一律輸出 Asia/Taipei ISO 格式、
抓取失敗自動 retry、跨來源轉載可用標題正規化後去重。
"""
from __future__ import annotations

import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup  # type: ignore
from dateutil import parser as dtparser  # type: ignore

TAIPEI = ZoneInfo("Asia/Taipei")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def to_taipei_iso(value) -> str:
    """epoch / datetime / 時間字串 -> Asia/Taipei ISO 字串；無法解析回傳空字串。

    naive（無時區）輸入視為台北時間；aware 輸入換算成台北時間。
    """
    if value is None or value == "" or value == 0:
        return ""
    if isinstance(value, (int, float)):
        dt = datetime.fromtimestamp(value, TAIPEI)
    elif isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = dtparser.parse(str(value))
        except (ValueError, OverflowError):
            return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TAIPEI)
    return dt.astimezone(TAIPEI).isoformat()


# \w 在 Python3 str 模式下涵蓋 CJK，故 \W 只會移除標點/空白，保留中文
_NON_WORD_RE = re.compile(r"[\W_]+")


def norm_title(title: str) -> str:
    """標題正規化：去空白標點、轉小寫。同文轉載（URL 不同）可據此去重。"""
    return _NON_WORD_RE.sub("", title or "").lower()


def request_get(
    url: str,
    *,
    retries: int = 2,
    backoff: float = 2.0,
    timeout: int = 10,
    **kwargs,
) -> requests.Response:
    """requests.get + raise_for_status，失敗時指數退避重試（共 retries+1 次）。"""
    last_exc: Exception = RuntimeError("unreachable")
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, timeout=timeout, **kwargs)
            resp.raise_for_status()
            return resp
        except Exception as e:
            last_exc = e
            if attempt < retries:
                time.sleep(backoff * (2**attempt))
    raise last_exc


# --------------------------------------------------------------------------- #
# 作者 / 全文抽取（Phase 3 統一清洗）
# --------------------------------------------------------------------------- #

# 內文容器選擇器（依序嘗試）。各來源可在 fetch 時傳入專屬選擇器覆蓋；
# 這些是泛用最佳推測，待有連線時以實測校正（見 data/site_maps/*.json 的 note）。
DEFAULT_BODY_SELECTORS = [
    "div.entry-content",
    "div.article-content",
    "div.article-body",
    "article",
    "main",
]


def html_to_text(html: str) -> str:
    """把 HTML 片段轉成純文字（段落以換行分隔）；給已內含全文 HTML 的 API 用。"""
    if not html:
        return ""
    if "<" not in html and ">" not in html:
        return html.strip()
    soup = BeautifulSoup(html, "html.parser")
    paras = [p.get_text(strip=True) for p in soup.find_all("p")]
    return "\n".join(p for p in paras if p) or soup.get_text("\n", strip=True)


def extract_author_from_entry(entry) -> str:
    """從 feedparser entry 取作者；缺則回空字串。"""
    for key in ("author", "dc_creator", "creator"):
        v = entry.get(key) if hasattr(entry, "get") else None
        if v:
            return str(v).strip()
    authors = entry.get("authors") if hasattr(entry, "get") else None
    if authors:
        first = authors[0]
        name = first.get("name") if isinstance(first, dict) else first
        if name:
            return str(name).strip()
    return ""


def parse_article_fields(html: str, body_selectors: list[str] | None = None) -> dict:
    """從文章 HTML 抽 author / summary / content。純函式，可離線測試。

    author  : meta[author|article:author|dc.creator] -> .author/.byline 類別
    summary : og:description -> meta[name=description]
    content : body_selectors（或 DEFAULT_BODY_SELECTORS）命中容器內的段落文字
    """
    soup = BeautifulSoup(html or "", "html.parser")

    author = ""
    for attrs in (
        {"name": "author"},
        {"property": "article:author"},
        {"name": "dc.creator"},
        {"name": "dcterms.creator"},
    ):
        m = soup.find("meta", attrs=attrs)
        if m and m.get("content"):
            author = m["content"].strip()
            break
    if not author:
        el = soup.select_one(".author, .byline, .article-author, [rel=author]")
        if el:
            author = el.get_text(strip=True)

    summary = ""
    d = (soup.find("meta", attrs={"property": "og:description"})
         or soup.find("meta", attrs={"name": "description"}))
    if d and d.get("content"):
        summary = d["content"].strip()

    content = ""
    for sel in (body_selectors or DEFAULT_BODY_SELECTORS):
        # 掃同選擇器的「所有」匹配取最長者 —— 有些站第一個容器是空佔位
        # (如 ltn 的 div.text),select_one 會抓到空殼,需挑段落最豐富的那個。
        for body_el in soup.select(sel):
            paras = [p.get_text(strip=True) for p in body_el.find_all("p")]
            cand = "\n".join(p for p in paras if p) or body_el.get_text("\n", strip=True)
            if len(cand) > len(content):
                content = cand
        if content:
            break

    return {"author": author, "summary": summary, "content": content}


def fetch_article(url: str, *, body_selectors: list[str] | None = None,
                  ua: str = UA, **kwargs) -> dict:
    """抓取單篇文章頁並抽 author/summary/content；失敗回空欄位字典，不外拋。"""
    try:
        resp = request_get(url, headers={"User-Agent": ua}, **kwargs)
    except Exception:
        return {"author": "", "summary": "", "content": ""}
    return parse_article_fields(resp.text, body_selectors)


if __name__ == "__main__":
    # 回歸守門:第一個同名容器是空殼(如 ltn 的 div.text)時,須跳過空殼挑到有內文的那個。
    _html = """<html><body>
      <div class="text"></div>
      <div class="text"><p>第一段內文。</p><p>第二段內文較長一些。</p></div>
    </body></html>"""
    _r = parse_article_fields(_html, ["div.text", "article"])
    assert "第二段內文" in _r["content"], f"空殼跳過失敗: {_r['content']!r}"
    print("common self-check OK:", repr(_r["content"]))
