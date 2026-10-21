# -*- coding: utf-8 -*-
"""
新聞查詢 CLI(整合 Metabase cmoney + 多家新聞來源 cnyes/udn/ctee/...,含內文)。

用法:
  python -X utf8 news.py --keyword=希捷,產能極限          # 關鍵字查
  python -X utf8 news.py --codes=2408,8299 --days=7        # 指定個股近 N 日
  python -X utf8 news.py --keyword=低軌衛星 --source=sanbao  # 只用即時新聞流(不碰 Metabase)
  python -X utf8 news.py --keyword=台積電 --individual-only   # 濾掉泛大盤新聞
  python -X utf8 news.py --keyword=台積電 --no-sentiment     # 關掉利多利空標記
  python -X utf8 news.py --keyword=希捷,產能極限 --all       # AND:所有關鍵字都要出現
  python -X utf8 news.py --keyword=非農,聯準會 --intl        # 只留國際/總經分類
  python -X utf8 news.py --keyword=OpenAI --out=auto        # 寫 out/news_<時間戳>_<pid>.json(平行查詢不互蓋)
  python -X utf8 news.py --keyword=OpenAI --out=D:/tmp/x.json

  # 新功能 — 輸出格式
  python -X utf8 news.py --keyword=台積電 --format=md         # Markdown
  python -X utf8 news.py --keyword=台積電 --format=json       # 純 JSON 到 stdout

  # 新功能 — 個股深度報告
  python -X utf8 news.py --report=2330,2454 --days=7         # console 報告
  python -X utf8 news.py --report=2330 --days=7 --format=md  # Markdown 報告

輸出:console/md → stdout;json → stdout(同步寫 out/news_result.json)。
  --out=PATH|auto(只影響 codes/keyword/report 模式):改寫到指定檔(auto = out/news_<時間戳>_<pid>.json),
  並把每則 body 截到 config body_max_chars(比對與 snippets 在截斷前已完成);
  不給 --out 時行為不變(寫 out/news_result.json、內文不截)。--today 不受影響。
"""
import os
import sys
import copy
import json
import pathlib
import datetime
import news_core as NC
import news_formatters as NF


def parse_args(argv):
    args = {
        "codes": None,
        "keyword": None,
        "days": None,
        "source": None,
        "individual_only": False,
        "no_sentiment": False,
        "report": None,                # list[str] or None
        "format": "console",           # console | md | json
        "today": False,                # 今日盤後四象限重點 digest 模式
        "match_all": False,            # --all:多關鍵字 AND
        "intl": False,                 # --intl:只留國際/總經分類
        "out": None,                   # --out=PATH|auto
    }
    for a in argv:
        if a in ("--today", "--digest"):
            args["today"] = True
            continue
        if a == "--all":
            args["match_all"] = True
            continue
        if a == "--intl":
            args["intl"] = True
            continue
        if a == "--out":
            args["out"] = "auto"
            continue
        if a.startswith("--out="):
            args["out"] = a.split("=", 1)[1].strip() or "auto"
            continue
        if a.startswith("--codes="):
            args["codes"] = [c.strip() for c in a.split("=", 1)[1].split(",")
                             if c.strip()]
        elif a.startswith("--keyword="):
            args["keyword"] = a.split("=", 1)[1]
        elif a.startswith("--days="):
            args["days"] = int(a.split("=", 1)[1])
        elif a.startswith("--source="):
            args["source"] = a.split("=", 1)[1]
        elif a == "--individual-only":
            args["individual_only"] = True
        elif a == "--no-sentiment":
            args["no_sentiment"] = True
        elif a.startswith("--report="):
            args["report"] = [c.strip() for c in a.split("=", 1)[1].split(",")
                              if c.strip()]
        elif a.startswith("--format="):
            v = a.split("=", 1)[1].strip().lower()
            if v not in ("console", "md", "json"):
                print(f"--format= 只接受 console|md|json,got: {v}",
                      file=sys.stderr)
                sys.exit(2)
            args["format"] = v
    return args


def _resolve_code_to_name(codes, source=None):
    """code -> 中文簡稱(Metabase 可用時查 Metabase,否則離線字典),失敗回 {}(不阻擋輸出)。"""
    if not codes:
        return {}
    try:
        return NC.resolve_stock_names(codes, source)
    except Exception as e:
        print(f"  warn: 股名解析失敗: {e!r}", file=sys.stderr)
        return {}


def _resolve_out_path(out):
    """--out 值 → 輸出路徑。auto = out/news_<時間戳>_<pid>.json(平行查詢不互相覆寫)。"""
    if not out:
        return None
    if out == "auto":
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        return NC.BASE / "out" / f"news_{ts}_{os.getpid()}.json"
    return pathlib.Path(out)


def _truncate_bodies(payload, cap):
    """回傳 payload 的深拷貝,其中每則 body 截到 cap 字(by_code / keyword_hits / reports)。
    snippets 與關鍵字比對在 query_news 內已用全文做完,截斷不影響命中。"""
    p = copy.deepcopy(payload)

    def cut(lst):
        for it in lst or []:
            b = it.get("body")
            if isinstance(b, str) and len(b) > cap:
                it["body"] = b[:cap] + "…"
    for lst in (p.get("by_code") or {}).values():
        cut(lst)
    cut(p.get("keyword_hits"))
    for rp in p.get("reports") or []:
        cut(rp.get("top"))
        cut(rp.get("timeline"))
    return p


def run_today_digest(args):
    """今日議題重點 digest:撈前一交易日 14:00 起的全市場新聞 → 寫完整清單檔 → 輸出原料。
    依議題分組與點名個股查證由模型依 SKILL.md「今日盤後議題重點」與
    references/today_digest.md 接手,此函式只負責取數+排版。"""
    fmt = args["format"]
    tag = not args["no_sentiment"]
    # 盤前窗:自前一交易日 14:00 → 涵蓋昨晚個股營收速報+隔夜美股+今早盤前,不漏
    items = NC.fetch_market_news(since="last_close", tag_sentiment=tag)
    today = datetime.date.today()
    _cutoff, _prev = NC.market_session_cutoff()
    date_str = (f"{today.isoformat()} 盤前（涵蓋 {_prev.strftime('%m/%d')} "
                f"{NC.PREMARKET_CUTOFF.strftime('%H:%M')}～現在）")

    # 寫『完整清單檔』(含連結),供查閱與下游引用
    out_dir = NC.BASE / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"today_news_{today.strftime('%Y%m%d')}.md"
    md_path.write_text(NF.render_digest_md(items, date_str), encoding="utf-8")

    # JSON 契約:同步寫 out/news_result.json
    payload = {
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "mode": "today_digest", "date": date_str, "count": len(items),
        "items": items,
    }
    (out_dir / "news_result.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8")

    print(f"[今日彙整] {date_str} 共 {len(items)} 則 → {md_path}", file=sys.stderr)
    if fmt == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return
    if fmt == "md":
        print(NF.render_digest_md(items, date_str))
    else:
        print(NF.render_digest_console(items, date_str))
    print(f"\n完整清單: {md_path}", file=sys.stderr)


def main():
    args = parse_args(sys.argv[1:])

    # 今日議題重點 digest 模式(不需 codes/keyword)
    if args["today"]:
        if args["out"] or args["intl"] or args["match_all"]:
            print("  note: --today 不吃 --out/--intl/--all(07:40 自動信依賴固定的"
                  " out/news_result.json 全文),已忽略", file=sys.stderr)
        run_today_digest(args)
        return

    # --report 模式:本質仍走 codes=,只是後續多算統計
    is_report = bool(args["report"])
    codes = args["report"] if is_report else args["codes"]
    keyword = None if is_report else args["keyword"]

    if not codes and not keyword:
        print("需 --codes= 或 --keyword= 或 --report=,擇一或併用",
              file=sys.stderr)
        sys.exit(1)

    fmt = args["format"]
    days = args["days"] or NC.news_cfg()["lookback_days"]

    # 進度訊息一律走 stderr,避免污染 --format=json 的 stdout
    print(f"[查詢] codes={codes} keyword={keyword} report={is_report} "
          f"days={days} format={fmt} "
          f"source={args['source'] or NC.news_cfg()['source']} "
          f"individual_only={args['individual_only']} "
          f"tag_sentiment={not args['no_sentiment']} "
          f"all={args['match_all']} intl={args['intl']}",
          file=sys.stderr)

    res = NC.query_news(
        codes=codes, keyword=keyword,
        days=args["days"], source=args["source"],
        individual_only=args["individual_only"],
        tag_sentiment=not args["no_sentiment"],
        match_all=args["match_all"], intl=args["intl"],
    )

    code_to_name = _resolve_code_to_name(codes, args["source"]) if codes else {}

    # 組 reports(若 --report)
    reports_data = None
    if is_report:
        reports_data = []
        for code in codes:
            items = res["by_code"].get(code, [])
            reports_data.append(NF.build_report(
                code=code, name=code_to_name.get(code, ""),
                items=items, days=days,
            ))

    # ---- 輸出 ----
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    payload = {
        "generated_at": ts,
        "query": {
            "codes": codes, "keyword": keyword,
            "days": args["days"], "source": args["source"],
            "report": is_report, "format": fmt,
            "match_all": args["match_all"], "intl": args["intl"],
        },
        **res,
    }
    if reports_data is not None:
        payload["reports"] = NF.render_report_json(reports_data)

    # JSON 一定要寫檔(契約)。out/ 可能不存在(乾淨打包/重裝後 zip 不留空目錄),
    # write_text 不會自動建父目錄 → 先確保 out/ 在,否則首次跑會 FileNotFoundError。
    # --out:改寫到指定檔(內文截到 body_max_chars),不碰共用的 out/news_result.json。
    out_path = _resolve_out_path(args["out"])
    if out_path is not None:
        payload = _truncate_bodies(payload, int(NC.news_cfg().get("body_max_chars", 600)))
    else:
        out_path = NC.BASE / "out" / "news_result.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2,
                   default=str),
        encoding="utf-8")
    print(f"[輸出] {out_path}", file=sys.stderr)

    if fmt == "json":
        # JSON 模式:純 JSON 到 stdout,不另印摘要
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return

    if fmt == "md":
        if is_report:
            print(NF.render_report_md(reports_data))
        else:
            print(NF.render_markdown(res, code_to_name=code_to_name))
        return

    # console(預設)
    if is_report:
        print(NF.render_report_console(reports_data))
    else:
        print(NF.render_console(res, code_to_name=code_to_name))


if __name__ == "__main__":
    main()
