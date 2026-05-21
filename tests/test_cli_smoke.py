# -*- coding: utf-8 -*-
"""
test_cli_smoke.py — scripts/news.py CLI 黑箱煙霧測試。

subprocess 跑各組合,驗:
  1) exit code == 0
  2) out/news_result.json 存在且為合法 JSON
  3) JSON 含 generated_at / query / by_code / keyword_hits 四個頂層鍵

跑 7 個組合:
  - --codes=2330 --days=3
  - --keyword=台積電
  - --keyword=台積電 --individual-only
  - --keyword=台積電 --source=sanbao
  - --report=2330 --days=3                       (新)console report
  - --report=2330 --days=3 --format=md           (新)markdown report
  - --keyword=台積電 --format=json --days=2      (新)JSON to stdout

退出碼: 全 OK → 0;任一 FAIL → 1。
"""
import os
import sys
import json
import time
import shutil
import pathlib
import subprocess

BASE = pathlib.Path(__file__).resolve().parent.parent
NEWS_PY = BASE / "scripts" / "news.py"
OUT_JSON = BASE / "out" / "news_result.json"

REQUIRED_TOP_KEYS = {"generated_at", "query", "by_code", "keyword_hits"}

results = []  # (case, ok, msg)


def record(case, ok, msg=""):
    tag = "OK  " if ok else "FAIL"
    print(f"  [{tag}] {case}" + (f" — {msg}" if msg else ""))
    results.append((case, ok, msg))


def run_one(case, args, timeout=180, stdout_check=None,
            expect_report_in_json=False):
    """跑一個 CLI 組合。

    stdout_check: callable(stdout_str) -> (ok:bool, msg:str) or None。
                  None 表不驗 stdout。
    expect_report_in_json: True 則驗 out/news_result.json 內含 reports 鍵。
    """
    print(f"\n--- case: {case} args={args} ---")
    # 清舊輸出,避免 false positive
    if OUT_JSON.exists():
        try:
            OUT_JSON.unlink()
        except Exception as e:
            print(f"  warn: 無法刪舊 out/news_result.json: {e!r}",
                  file=sys.stderr)

    cmd = [sys.executable, "-X", "utf8", str(NEWS_PY)] + args
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        record(f"{case}:exit", False, f"timeout > {timeout}s")
        return
    elapsed = time.time() - t0

    if proc.returncode != 0:
        # 印 stderr 末段方便 debug
        err_tail = "\n".join((proc.stderr or "").splitlines()[-8:])
        record(f"{case}:exit", False,
               f"returncode={proc.returncode} ({elapsed:.1f}s); "
               f"stderr_tail=\n{err_tail}")
        return
    record(f"{case}:exit", True, f"returncode=0 ({elapsed:.1f}s)")

    if not OUT_JSON.exists():
        record(f"{case}:output", False, "out/news_result.json 未產生")
        return
    try:
        data = json.loads(OUT_JSON.read_text(encoding="utf-8"))
    except Exception as e:
        record(f"{case}:json", False, f"JSON parse 失敗: {e!r}")
        return

    miss = REQUIRED_TOP_KEYS - set(data.keys())
    if miss:
        record(f"{case}:json-keys", False, f"缺頂層鍵: {sorted(miss)}")
        return
    if not isinstance(data["by_code"], dict):
        record(f"{case}:json-keys", False,
               f"by_code 非 dict: {type(data['by_code']).__name__}")
        return
    if not isinstance(data["keyword_hits"], list):
        record(f"{case}:json-keys", False,
               f"keyword_hits 非 list: {type(data['keyword_hits']).__name__}")
        return
    record(f"{case}:json-keys", True,
           f"by_code={len(data['by_code'])} codes, "
           f"keyword_hits={len(data['keyword_hits'])} 則")

    if expect_report_in_json:
        if "reports" not in data:
            record(f"{case}:reports-key", False,
                   "out/news_result.json 缺 reports 鍵")
        elif not isinstance(data["reports"], list):
            record(f"{case}:reports-key", False,
                   f"reports 非 list: {type(data['reports']).__name__}")
        else:
            record(f"{case}:reports-key", True,
                   f"reports={len(data['reports'])} 檔")

    if stdout_check is not None:
        try:
            ok, msg = stdout_check(proc.stdout or "")
        except Exception as e:
            ok, msg = False, f"stdout_check 拋例外: {e!r}"
        record(f"{case}:stdout", ok, msg)


def main():
    print(f"\n=== news.py CLI 煙霧測試 ===")
    print(f"  Python: {sys.executable}")
    print(f"  news.py: {NEWS_PY}")

    if not NEWS_PY.exists():
        print(f"FATAL: news.py 不存在: {NEWS_PY}", file=sys.stderr)
        sys.exit(1)

    cases = [
        ("codes-2330", ["--codes=2330", "--days=3"], {}),
        ("keyword-tsmc", ["--keyword=台積電"], {}),
        ("keyword-individual-only",
         ["--keyword=台積電", "--individual-only"], {}),
        ("keyword-sanbao", ["--keyword=台積電", "--source=sanbao"], {}),
        # 新功能 — report 模式 (console)
        ("report-2330-console", ["--report=2330", "--days=3"],
         {"expect_report_in_json": True,
          "stdout_check": lambda s: (
              "個股深度報告" in s and "Sentiment 分布" in s,
              "報告標題/Sentiment 分布 已出現" if (
                  "個股深度報告" in s and "Sentiment 分布" in s)
              else "stdout 未含「個股深度報告」或「Sentiment 分布」"
          )}),
        # 新功能 — report + markdown
        ("report-2330-md", ["--report=2330", "--days=3", "--format=md"],
         {"expect_report_in_json": True,
          "stdout_check": lambda s: (
              "## " in s,
              "stdout 含 ## (markdown H2)" if "## " in s
              else "stdout 未含任何 ## (markdown H2)"
          )}),
        # 新功能 — keyword + json
        ("keyword-tsmc-json",
         ["--keyword=台積電", "--format=json", "--days=2"],
         {"stdout_check": lambda s: (
             s.strip().startswith("{"),
             "stdout 第一個非空字元為 {" if s.strip().startswith("{")
             else f"stdout 第一個非空字元非 {{ — got: {(s.strip() or '')[:30]!r}"
         )}),
    ]
    for case, args, kw in cases:
        run_one(case, args, **kw)

    ok = sum(1 for _, p, _ in results if p)
    fail = sum(1 for _, p, _ in results if not p)
    print(f"\n=== 結果: {ok}/{len(results)} pass, {fail} fail ===")
    sys.exit(0 if fail == 0 else 1)


if __name__ == "__main__":
    main()
