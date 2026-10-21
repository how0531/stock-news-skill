# -*- coding: utf-8 -*-
"""
新聞利多自選股清單: 計票、混合排除與排序。
輸入是已打好情緒標籤的新聞(sentiment / confidence / events),輸出是依利多票排序的個股清單。
本模組目前只含純函式, 不連網、不讀寫檔案。

  RULE                           計票門檻與權重
  vote(item, rule)               一則新聞的票: "bull" / "bear" / None
  score_news(news, lex, rule)    回傳 {"items": [...], "excluded": [...], "candidates": [...]}
"""
import news_core as NC
import stock_mentions as SM

RULE = {"confidence_min": 0.5, "title_weight": 3, "body_weight": 1, "body_max_stocks_per_news": 3}


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
