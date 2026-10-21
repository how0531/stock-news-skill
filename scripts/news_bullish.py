# -*- coding: utf-8 -*-
"""
新聞利多自選股清單: 計票、混合排除與排序。
輸入是已打好情緒標籤的新聞(sentiment / confidence / events),輸出是依利多票排序的個股清單。
計票的 vote / score_news 是純函式; 組檔 make_payload / error_payload 不寫檔, 只查休市日曆
(十二月與一月可能經 storage._ensure_year 連證交所補休市表), write_payload / run 才寫
out/bullish/ 下的檔案, 不碰 out/news_result.json。

  RULE                           計票門檻與權重
  vote(item, rule)               一則新聞的票: "bull" / "bear" / None
  score_news(news, lex, rule)    回傳 {"items": [...], "excluded": [...], "candidates": [...]}
  make_payload(news, now, lex)   組成 spec 5.2 的檔案內容(status 為 ok / empty / error, 含 codes 欄)
  error_payload(now, message)    同一組鍵, 三個清單為空, 多一個 error
  write_payload(payload, dir)    寫 bullish_YYYYMMDD.json 再寫 latest.json
  run(now, out_dir, fetch)       抓新聞、組檔、寫檔, 回結束碼(error 為 1, 其餘 0)
"""
import sys
import news_core as NC
import stock_mentions as SM
import update_holidays as UH

RULE = {"confidence_min": 0.5, "title_weight": 3, "body_weight": 1, "body_max_stocks_per_news": 3}
OUT_DIR = NC.BASE / "out" / "bullish"


def vote(item, rule=RULE):
    """利多或利空且信心達門檻才算票, 其他(含缺鍵)回 None。"""
    if (item.get("confidence") or 0) < rule["confidence_min"]:
        return None
    sentiment = item.get("sentiment")
    if sentiment == "bullish":
        return "bull"
    if sentiment == "bearish":
        return "bear"
    return None


def _sort(rows, *specs):
    """多鍵穩定排序, specs 由主鍵到次鍵, 每項是 (key 函式, 是否由大到小)。"""
    for key, desc in reversed(specs):
        rows.sort(key=key, reverse=desc)
    return rows


def _latest(row):
    return row["evidence"][0]["time"]


def _reason(t, b, events):
    parts = []
    if t:
        parts.append(f"標題點名 {t} 則利多")
    if b:
        parts.append(f"內文提到 {b} 則利多")
    text = "，".join(parts)
    if events:
        text += "（" + "、".join(events) + "）"
    return text


def score_news(news, lex, rule=RULE):
    names = lex["names"]
    per_code = {}                        # 代號 -> [(evidence, 這筆的票或 None), ...]
    for item in news:
        title = item.get("title") or ""
        body = item.get("body") or item.get("summary") or ""
        mentions = SM.find_mentions(title, body, item.get("stock_codes"), lex)
        body_level = sum(1 for m in mentions.values() if m == "body")
        capped = body_level > rule["body_max_stocks_per_news"]   # 內文點名太多檔, 內文級都不計票
        v = vote(item, rule)
        for code, match in mentions.items():
            counted = match == "title" or not capped
            name = names.get(code, "")
            snippets = NC._snippets(body, [name, code])
            ev = {"title": title, "url": item.get("url"), "time": item.get("time") or "",
                  "source": item.get("source"), "match": match, "sentiment": item.get("sentiment"),
                  "confidence": item.get("confidence"), "events": list(item.get("events") or []),
                  "counted": counted, "snippet": snippets[0] if snippets else ""}
            per_code.setdefault(code, []).append((ev, v if counted else None))

    items, excluded, candidates = [], [], []
    for code, entries in per_code.items():
        entries.sort(key=lambda e: e[0]["time"], reverse=True)   # 由新到舊, 同時間維持輸入順序
        evidence = [e for e, _ in entries]
        name = names.get(code, "")
        t = sum(1 for e, v in entries if v == "bull" and e["match"] == "title")
        b = sum(1 for e, v in entries if v == "bull" and e["match"] == "body")
        bears = sum(1 for _, v in entries if v == "bear")
        if t + b == 0:
            candidates.append({"code": code, "name": name, "evidence": evidence})
        elif bears:
            excluded.append({"code": code, "name": name, "why": "mixed"})
            candidates.append({"code": code, "name": name, "evidence": evidence})
        else:
            events = list(dict.fromkeys(x for e, v in entries if v == "bull" for x in e["events"]))[:3]
            items.append({"code": code, "name": name,
                          "score": t * rule["title_weight"] + b * rule["body_weight"],
                          "title_votes": t, "body_votes": b,
                          "reason": _reason(t, b, events), "evidence": evidence})

    _sort(items, (lambda r: r["title_votes"] == 0, False), (lambda r: r["score"], True),
          (_latest, True), (lambda r: r["code"], False))
    _sort(excluded, (lambda r: r["code"], False))
    _sort(candidates, (lambda r: len(r["evidence"]), True), (_latest, True), (lambda r: r["code"], False))
    return {"items": items, "excluded": excluded, "candidates": candidates}


def _next_trade_date(now):
    import storage                        # 會載入 pandas(約 1 秒), 只在需要時才付
    return storage._next_trading_day(now.date()).isoformat()


def _window(now):
    return {"from": NC.market_session_cutoff(now)[0].isoformat(), "to": now.isoformat(timespec="seconds")}


def _body(now, status, next_trade_date, window, r=None):
    """spec 5.2 的檔案內容; r 是 score_news 的結果, 錯誤檔沒有就三個清單都空。"""
    r = r or {}
    items = r.get("items", [])
    # codes 是 items 代號依序的精簡清單, Pro 端只讀它就夠, 不必把整份檔讀進對話
    return {"schema_version": 1, "status": status, "trade_date": now.date().isoformat(),
            "next_trade_date": next_trade_date, "codes": [i["code"] for i in items],
            "generated_at": now.isoformat(timespec="seconds"),
            "window": window, "method": "rule", "rule": dict(RULE),
            "items": items, "excluded": r.get("excluded", []),
            "candidates": r.get("candidates", [])}


def error_payload(now, message):
    def safe(fn, *a):                    # 錯誤檔本身不能再出錯, 算不出的欄位填 None
        try:
            return fn(*a)
        except Exception:
            return None
    p = _body(now, "error", safe(_next_trade_date, now), safe(_window, now))
    p["error"] = message
    return p


def make_payload(news, now, lex):
    if not news:
        return error_payload(now, "沒有抓到任何新聞")
    if not any("sentiment" in n for n in news):
        return error_payload(now, "新聞沒有情緒標籤,news_sentiment 可能載入失敗")
    r = score_news(news, lex)
    return _body(now, "ok" if r["items"] else "empty", _next_trade_date(now), _window(now), r)


def write_payload(payload, out_dir=OUT_DIR):
    """先寫日期檔再寫 latest.json(內容相同), 回傳日期檔路徑。"""
    dated = out_dir / f"bullish_{payload['trade_date'].replace('-', '')}.json"
    UH._write(dated, payload)
    UH._write(out_dir / "latest.json", payload)
    return dated


def run(now=None, out_dir=OUT_DIR, fetch=None):
    now = now or NC._now_tw()
    if NC._is_closed(now):
        print("[利多清單] 今天休市,不產出", file=sys.stderr)
        return 0
    # tag_sentiment 明確傳 True, 不讀 config(config 設 false 會讓每天都產出 error 檔)
    fetch = fetch or (lambda: NC.fetch_market_news(since="last_close", keep_codes=True, tag_sentiment=True))
    try:
        payload = make_payload(fetch(), now, SM.load_lexicon())
    except Exception as e:
        payload = error_payload(now, repr(e))
    path = write_payload(payload, out_dir)
    print(f"[輸出] {path}", file=sys.stderr)
    print(f"[利多清單] {payload['trade_date']} {payload['status']} {len(payload['items'])} 檔", file=sys.stderr)
    return 1 if payload["status"] == "error" else 0
