# -*- coding: utf-8 -*-
"""
test_sentiment.py — news_sentiment.classify() 行為契約測試。

classify() 是 news_core.query_news() 在 keyword/codes 模式最後一步呼叫的
規則層分類器,簽名與回傳結構是契約。

本檔只測「結構契約」+「強訊號(明確無爭議)案例方向」:
  A. 結構契約(對任意輸入都成立):
     - 回傳 dict,鍵齊全 {sentiment, confidence, events, rationale}
     - sentiment ∈ {bullish, bearish, neutral}
     - confidence 是 float 且 ∈ [0, 1]
     - events 是 list[str]
     - rationale 是 str
  B. 強訊號方向(僅取無爭議的極端案例):
     - 「訂單滿手 / 獲利大增 / 創新高」等 → bullish
     - 「跌停 / 踩雷 / 認列損失 / 砍單」等 → bearish

刻意「不」對模糊/中性偏邊界的標題寫死斷言 —— news_sentiment.py 詞庫正由
另一 agent 同步強化,邊界案例的判定可能浮動,只測結構 + 強訊號才穩。

退出碼: 全 OK → 0;任一 FAIL → 1。
"""
import sys
import pathlib

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "scripts"))

import news_sentiment as NS  # noqa: E402

REQUIRED_KEYS = {"sentiment", "confidence", "events", "rationale"}
VALID_SENT = {"bullish", "bearish", "neutral"}

results = []  # (name, ok, msg)


def record(name, ok, msg=""):
    tag = "OK  " if ok else "FAIL"
    print(f"  [{tag}] {name}" + (f" — {msg}" if msg else ""))
    results.append((name, ok, msg))


def assert_contract(name, title, body=""):
    """對單一輸入跑 classify,逐項驗結構契約。回傳 result dict(或 None)。"""
    try:
        r = NS.classify(title, body)
    except Exception as e:
        record(f"{name}:invoke", False, f"{type(e).__name__}: {e}")
        return None
    if not isinstance(r, dict):
        record(f"{name}:type", False, f"回傳非 dict: {type(r).__name__}")
        return None
    miss = REQUIRED_KEYS - set(r.keys())
    if miss:
        record(f"{name}:keys", False, f"缺鍵 {sorted(miss)}")
        return None
    ok_all = True
    # sentiment 合法
    if r["sentiment"] not in VALID_SENT:
        record(f"{name}:sentiment", False,
               f"sentiment 非法值: {r['sentiment']!r}")
        ok_all = False
    # confidence 是數字且 0~1
    conf = r["confidence"]
    if not isinstance(conf, (int, float)) or isinstance(conf, bool):
        record(f"{name}:confidence-type", False,
               f"confidence 非 float: {type(conf).__name__}")
        ok_all = False
    elif not (0.0 <= float(conf) <= 1.0):
        record(f"{name}:confidence-range", False,
               f"confidence 超出 [0,1]: {conf}")
        ok_all = False
    # events 是 list[str]
    evs = r["events"]
    if not isinstance(evs, list):
        record(f"{name}:events-type", False,
               f"events 非 list: {type(evs).__name__}")
        ok_all = False
    elif any(not isinstance(e, str) for e in evs):
        record(f"{name}:events-elem", False, "events 含非 str 元素")
        ok_all = False
    # rationale 是 str
    if not isinstance(r["rationale"], str):
        record(f"{name}:rationale-type", False,
               f"rationale 非 str: {type(r['rationale']).__name__}")
        ok_all = False
    if ok_all:
        record(f"{name}:contract", True,
               f"sent={r['sentiment']} conf={conf} events={evs}")
    return r


def main():
    print("\n=== news_sentiment.classify 行為契約測試 ===")

    # --- A. 結構契約:涵蓋空字串、純中性、極端、含 body 等多型態 ---
    print("\n--- A. 結構契約(任意輸入都該成立) ---")
    contract_inputs = [
        ("empty", "", ""),
        ("blank-title-only", "聯電法說會召開 第四季展望持平", ""),
        ("with-body", "某公司今日召開股東會",
         "公司說明營運狀況,並回應股東提問,整體展望持平。"),
        ("bullish-extreme", "鴻海營收創新高 訂單滿手 獲利大增", ""),
        ("bearish-extreme", "華邦電踩雷 認列損失 跌停鎖死", ""),
        ("none-args", None, None),  # classify 內部會 or '' 容錯
        ("mixed-pos-neg", "雖訂單滿手但毛利下滑 法人看法分歧", ""),
    ]
    for name, title, body in contract_inputs:
        assert_contract(f"contract:{name}", title, body)

    # --- B. 強訊號方向(無爭議的極端案例) ---
    # 全用多個強利多 / 強利空詞堆疊,確保遠超 1.3 倍門檻,不踩詞庫邊界。
    print("\n--- B. 強訊號方向(僅極端無爭議案例) ---")
    strong_bullish = [
        ("b1", "鴻海11月營收年增15% 訂單滿手 獲利大增"),
        ("b2", "群創營收創新高 法人看好 強勢漲停"),
        ("b3", "台積電急單湧入 出貨暢旺 獲利倍增"),
    ]
    strong_bearish = [
        ("s1", "台積電遭客戶砍單 出貨大幅下修 獲利衰退"),
        ("s2", "華邦電踩雷 認列損失 跌停崩跌"),
        ("s3", "某公司獲利預警 財測下修 重挫破底"),
    ]
    for name, title in strong_bullish:
        r = assert_contract(f"bullish:{name}", title)
        if r is not None:
            ok = r["sentiment"] == "bullish"
            record(f"bullish:{name}:direction", ok,
                   f"got={r['sentiment']} (expect bullish) | {title}")
    for name, title in strong_bearish:
        r = assert_contract(f"bearish:{name}", title)
        if r is not None:
            ok = r["sentiment"] == "bearish"
            record(f"bearish:{name}:direction", ok,
                   f"got={r['sentiment']} (expect bearish) | {title}")

    # --- C. 事件抽取:強訊號標題應至少抽到對應事件(寬鬆,只要 list 非錯型) ---
    # 不寫死「一定有某事件」,只驗:含明確事件詞時 events 至少命中 1 個。
    print("\n--- C. 事件抽取(明確事件詞應被命中) ---")
    event_cases = [
        ("ev-faShuo", "聯發科召開法說會 說明Q4展望", "法說"),
        ("ev-zhangTing", "某股亮燈漲停 買盤湧入", "漲停"),
        ("ev-caiLei", "某公司踩雷 提列損失15億", "踩雷"),
    ]
    for name, title, expect_ev in event_cases:
        r = assert_contract(f"event:{name}", title)
        if r is not None:
            ok = expect_ev in r["events"]
            record(f"event:{name}:hit", ok,
                   f"events={r['events']} (expect 含 '{expect_ev}')")

    ok = sum(1 for _, p, _ in results if p)
    fail = sum(1 for _, p, _ in results if not p)
    print(f"\n=== 結果: {ok}/{len(results)} pass, {fail} fail ===")
    sys.exit(0 if fail == 0 else 1)


if __name__ == "__main__":
    main()
