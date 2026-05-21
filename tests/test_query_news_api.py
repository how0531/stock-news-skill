# -*- coding: utf-8 -*-
"""
test_query_news_api.py — news_core.query_news() 公開 API 契約測試。

Sino-notify-skill 依賴此 API,簽名/回傳結構絕對不能破壞。

驗證項:
  1) 簽名:**前 6 個參數**順序鎖死為 (codes, keyword, days, source,
     fetch_body, individual_only),全部參數預設值 = None(允許向後
     相容擴充新參數於後,例:tag_sentiment)
  2) 回傳必含: by_code(dict)、keyword_hits(list)
  3) by_code[code] 每項 schema: time, title, source, url, summary, body
     (sentiment/confidence/events 為可選擴充欄位,不算契約必要)
  4) keyword_hits 每項 schema: 上述 6 鍵 + code, name

跑 3 個 case:
  - codes=["2330"]
  - keyword="台積電"
  - codes=["2330"], keyword="台積電"

容錯設計:外部來源(Metabase/三大報)若臨時掛掉,只要回傳結構合法,單一 case
可放寬到「結構通過、內容為空」也算 pass,但 schema 違反即 FAIL。
退出碼: 全 OK → 0;任一 FAIL → 1。
"""
import os
import sys
import inspect
import pathlib
import traceback

BASE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "scripts"))

import news_core as NC  # noqa: E402

NEWS_KEYS = {"time", "title", "source", "url", "summary", "body"}
KW_EXTRA_KEYS = {"code", "name"}

results = []  # (name, ok, msg)


def record(name, ok, msg=""):
    tag = "OK  " if ok else "FAIL"
    print(f"  [{tag}] {name}" + (f" — {msg}" if msg else ""))
    results.append((name, ok, msg))


def check_signature():
    sig = inspect.signature(NC.query_news)
    required_in_order = ["codes", "keyword", "days", "source",
                         "fetch_body", "individual_only"]
    got = list(sig.parameters.keys())
    # 1) 前 6 個必須是原契約順序(positional 相容)
    if got[:6] != required_in_order:
        record("signature", False,
               f"前 6 個參數順序不符 expected={required_in_order} "
               f"got={got[:6]}")
        return False
    # 2) 全部參數預設值都得是 None(含後續向後相容擴充)
    bad = [n for n, p in sig.parameters.items() if p.default is not None]
    if bad:
        record("signature", False, f"以下參數預設值非 None: {bad}")
        return False
    extras = got[6:]
    extra_msg = f" + extras={extras}" if extras else ""
    record("signature", True,
           f"前 6 參數順序契約 OK, 全部預設 None{extra_msg}")
    return True


def check_news_item(case, item, require_kw_extras=False):
    """回 (ok, missing_keys_msg or '')。"""
    if not isinstance(item, dict):
        return False, f"item 非 dict: {type(item).__name__}"
    miss = NEWS_KEYS - set(item.keys())
    if miss:
        return False, f"缺鍵 {sorted(miss)}"
    if require_kw_extras:
        miss2 = KW_EXTRA_KEYS - set(item.keys())
        if miss2:
            return False, f"keyword_hits 缺額外鍵 {sorted(miss2)}"
    return True, ""


def check_result_shape(case, res, expect_by_code=False, expect_kw=False):
    """驗回傳結構;若 expect_* 開啟且該分支為空,只算 warning 不 fail。"""
    if not isinstance(res, dict):
        record(f"{case}:return-type", False,
               f"回傳非 dict: {type(res).__name__}")
        return
    if "by_code" not in res or not isinstance(res["by_code"], dict):
        record(f"{case}:by_code", False,
               f"缺 by_code 或非 dict: {type(res.get('by_code')).__name__}")
        return
    if "keyword_hits" not in res or not isinstance(res["keyword_hits"], list):
        record(f"{case}:keyword_hits", False,
               f"缺 keyword_hits 或非 list: "
               f"{type(res.get('keyword_hits')).__name__}")
        return
    record(f"{case}:return-shape", True,
           f"by_code={len(res['by_code'])} codes, "
           f"keyword_hits={len(res['keyword_hits'])} 則")

    # 細查 by_code 每項
    bad = []
    sample_count = 0
    for code, lst in res["by_code"].items():
        if not isinstance(lst, list):
            bad.append(f"{code} 非 list")
            continue
        for item in lst[:5]:
            ok, msg = check_news_item(case, item)
            sample_count += 1
            if not ok:
                bad.append(f"{code}: {msg}")
    if bad:
        record(f"{case}:by_code-items", False,
               f"schema 違反 {len(bad)} 項,首例: {bad[0]}")
    elif sample_count > 0:
        record(f"{case}:by_code-items", True,
               f"檢查 {sample_count} 項皆合 schema")
    else:
        # 來源可能掛了,但結構合法就放行(warning)
        if expect_by_code:
            record(f"{case}:by_code-items", True,
                   "(by_code 空 — 結構合法但無資料,可能來源掛了)")

    # 細查 keyword_hits
    bad2 = []
    for item in res["keyword_hits"][:10]:
        ok, msg = check_news_item(case, item, require_kw_extras=True)
        if not ok:
            bad2.append(msg)
    if bad2:
        record(f"{case}:keyword_hits-items", False,
               f"schema 違反 {len(bad2)} 項,首例: {bad2[0]}")
    elif res["keyword_hits"]:
        record(f"{case}:keyword_hits-items", True,
               f"檢查 {min(len(res['keyword_hits']), 10)} 項皆合 schema")
    elif expect_kw:
        record(f"{case}:keyword_hits-items", True,
               "(keyword_hits 空 — 結構合法但無資料,可能來源掛了)")


def run_case(case, **kwargs):
    print(f"\n--- case: {case} kwargs={kwargs} ---")
    try:
        res = NC.query_news(**kwargs)
    except Exception as e:
        record(f"{case}:invoke", False, f"{type(e).__name__}: {e}")
        traceback.print_exc(file=sys.stderr)
        return
    record(f"{case}:invoke", True, "未拋例外")
    check_result_shape(case, res,
                       expect_by_code=("codes" in kwargs),
                       expect_kw=("keyword" in kwargs))


def main():
    print(f"\n=== news_core.query_news 契約測試 ===")
    sig_ok = check_signature()
    if not sig_ok:
        print("\n=== 簽名測試失敗,終止 ===")
        sys.exit(1)

    # 個別 case;為節省時間,days 給小一點、不抓 body
    run_case("codes-only",
             codes=["2330"], days=3, fetch_body=False)
    run_case("keyword-only",
             keyword="台積電", days=3, fetch_body=False)
    run_case("codes+keyword",
             codes=["2330"], keyword="台積電", days=3, fetch_body=False)

    ok = sum(1 for _, p, _ in results if p)
    fail = sum(1 for _, p, _ in results if not p)
    print(f"\n=== 結果: {ok}/{len(results)} pass, {fail} fail ===")
    sys.exit(0 if fail == 0 else 1)


if __name__ == "__main__":
    main()
