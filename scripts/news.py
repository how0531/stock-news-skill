# -*- coding: utf-8 -*-
"""
新聞查詢 CLI(整合 Metabase cmoney + 多家新聞來源 cnyes/udn/ctee/...,含內文)。

用法:
  python -X utf8 news.py --keyword=希捷,產能極限          # 關鍵字查
  python -X utf8 news.py --codes=2408,8299 --days=7        # 指定個股近 N 日
  python -X utf8 news.py --keyword=低軌衛星 --source=sanbao  # 只查三大報/多家
  python -X utf8 news.py --keyword=台積電 --individual-only   # 濾掉泛大盤新聞
  python -X utf8 news.py --keyword=台積電 --no-sentiment     # 關掉利多利空標記

  # 新功能 — 輸出格式
  python -X utf8 news.py --keyword=台積電 --format=md         # Markdown
  python -X utf8 news.py --keyword=台積電 --format=json       # 純 JSON 到 stdout

  # 新功能 — 個股深度報告
  python -X utf8 news.py --report=2330,2454 --days=7         # console 報告
  python -X utf8 news.py --report=2330 --days=7 --format=md  # Markdown 報告

輸出:console/md → stdout;json → stdout(同步寫 out/news_result.json)。
"""
import sys
import json
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
    }
    for a in argv:
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


def _resolve_code_to_name(codes):
    """嘗試從 Metabase 拉 code -> 中文簡稱,失敗回 {}(不阻擋輸出)。"""
    if not codes:
        return {}
    try:
        return NC.get_stock_names([str(c) for c in codes])
    except Exception as e:
        print(f"  warn: get_stock_names 失敗: {e!r}", file=sys.stderr)
        return {}


def main():
    args = parse_args(sys.argv[1:])

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
          f"tag_sentiment={not args['no_sentiment']}",
          file=sys.stderr)

    res = NC.query_news(
        codes=codes, keyword=keyword,
        days=args["days"], source=args["source"],
        individual_only=args["individual_only"],
        tag_sentiment=not args["no_sentiment"],
    )

    code_to_name = _resolve_code_to_name(codes) if codes else {}

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
        },
        **res,
    }
    if reports_data is not None:
        payload["reports"] = NF.render_report_json(reports_data)

    # JSON 一定要寫檔(契約)。out/ 可能不存在(乾淨打包/重裝後 zip 不留空目錄),
    # write_text 不會自動建父目錄 → 先確保 out/ 在,否則首次跑會 FileNotFoundError。
    out_dir = NC.BASE / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "news_result.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2,
                   default=str),
        encoding="utf-8")

    if fmt == "json":
        # JSON 模式:純 JSON 到 stdout,不另印摘要
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return

    if fmt == "md":
        if is_report:
            print(NF.render_report_md(reports_data))
        else:
            print(NF.render_markdown(res, code_to_name=code_to_name))
        print(f"\n<!-- 輸出 out/news_result.json -->", file=sys.stderr)
        return

    # console(預設)
    if is_report:
        print(NF.render_report_console(reports_data))
    else:
        print(NF.render_console(res, code_to_name=code_to_name))
    print("\n輸出 out/news_result.json", file=sys.stderr)


if __name__ == "__main__":
    main()
