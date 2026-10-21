"""官方重大訊息 — TWSE / TPEx OpenAPI（上市、上櫃當日重大訊息）。

與媒體新聞不同，這是發行公司依法發布的第一手公告，無記者改寫延遲。
注意：OpenAPI 為當日彙總快照，更新頻率非逐秒；需秒級即時請改接
MOPS 即時重大訊息（t05sr01_1，反爬蟲較強，尚未實作）。
"""
from __future__ import annotations

import re
from datetime import datetime

try:
    from .common import TAIPEI, request_get
except ImportError:
    from common import TAIPEI, request_get

HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

ENDPOINTS = {
    "twse": ("上市重大訊息", "https://openapi.twse.com.tw/v1/opendata/t187ap04_L"),
    "tpex": ("上櫃重大訊息", "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap04_O"),
}


def _roc_to_iso(date_str: str, time_str: str = "") -> str:
    """民國年日期（1150612 或 115/06/12）+ 時間 -> ISO 字串；解析失敗回傳空字串。"""
    digits = re.sub(r"\D", "", date_str or "")
    if len(digits) < 6:
        return ""
    try:
        if len(digits) == 7:  # ROC: yyymmdd
            y, m, d = int(digits[:3]) + 1911, int(digits[3:5]), int(digits[5:7])
        elif len(digits) == 8:  # 西元: yyyymmdd
            y, m, d = int(digits[:4]), int(digits[4:6]), int(digits[6:8])
        else:
            return ""
        t = re.sub(r"\D", "", time_str or "").ljust(6, "0")[:6]
        return datetime(
            y, m, d, int(t[:2]), int(t[2:4]), int(t[4:6]), tzinfo=TAIPEI
        ).isoformat()
    except ValueError:
        return ""


def _field(row: dict, *keywords: str) -> str:
    """OpenAPI 中文欄位名偶有空白/版本差異，用關鍵字模糊取值。"""
    for k, v in row.items():
        if all(kw in k for kw in keywords):
            return str(v).strip()
    return ""


def fetch(markets: list[str] | None = None) -> list[dict]:
    """抓取上市/上櫃當日重大訊息，回傳標準化欄位。"""
    chosen = markets or list(ENDPOINTS.keys())
    out: list[dict] = []
    for mkt in chosen:
        label, url = ENDPOINTS[mkt]
        try:
            resp = request_get(url, headers=HEADERS, timeout=15)
            for row in resp.json():
                code = _field(row, "公司代號")
                name = _field(row, "公司名稱")
                subject = _field(row, "主旨")
                if not subject:
                    continue
                detail = _field(row, "說明")
                out.append(
                    {
                        "source": f"announce_{mkt}",
                        "category": label,
                        "title": f"[重大訊息] {name}({code}) {subject}",
                        # 公告無記者，作者填發布公司
                        "author": f"{name}({code})" if name else "公開資訊觀測站",
                        "summary": detail,
                        # 「說明」為公開法定公告全文，無版權疑慮，可全文存
                        "content": detail,
                        # 無單篇 URL，組出 MOPS 查詢頁供人工查看
                        "url": f"https://mops.twse.com.tw/mops/web/t05sr01_1?step=1&co_id={code}",
                        "published_at": _roc_to_iso(
                            _field(row, "發言日期"), _field(row, "發言時間")
                        ),
                        "ticker_hint": f"{code}.TW" if code.isdigit() else "",
                    }
                )
        except Exception as e:
            print(f"[announce] {mkt} 抓取失敗: {e}")
    return out


if __name__ == "__main__":
    for n in fetch():
        print(n["published_at"], n["title"])
