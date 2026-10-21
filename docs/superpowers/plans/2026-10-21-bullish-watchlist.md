# 新聞利多自選股清單 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 每個交易日 07:50 由排程產出 `out/bullish/latest.json`（規則層的利多個股清單），Shioaji Pro 的 AI agent 08:00 讀檔，整份替換專用自選股「新聞利多」。

**Architecture:** 新增兩個模組。`scripts/stock_mentions.py` 負責全市場股名反查（每則新聞提到哪些股票，標題級或內文級）；`scripts/news_bullish.py` 負責計票、排除、排序、組檔、寫檔與 `run()`。`news.py --bullish` 呼叫 `run()`，原料來自 `fetch_market_news(since="last_close", keep_codes=True)`，沿用既有的 15 分鐘磁碟快取與跨進程抓取鎖，所以和 07:40 盤前信共用同一份新聞。Pro 端不寫程式，只有設定指南與排程 prompt。

**Tech Stack:** Python 3.12 標準函式庫加既有模組（不加依賴）；Windows PowerShell 5.1 工作排程；Shioaji Pro MCP 工具（上游分支 `feat/340-agent-watchlist-tools`）。

**Spec:** `docs/superpowers/specs/2026-10-21-bullish-watchlist-design.md`（本 repo）

## Global Constraints

- skill repo 是 `~/.claude/skills/stock-news-skill`，以下路徑都相對於它，指令都在這個目錄執行。在分支 `feat/bullish-watchlist` 上做，每個 task 結束 commit；push 前先問使用者。
- 不加依賴，只用標準函式庫與既有模組。
- 不改 `news_providers.match_news_to_codes`、`news_providers._alias_map`，也不改 `data/stocks/tw_names.json`、`tw_stocks.json` 的格式（會影響 `--codes` 與 Sino-notify-skill）。
- 不讀也不寫 `out/news_result.json`；`fetch_market_news` 不帶新參數時輸出逐鍵不變（07:40 盤前信依賴它）。
- 不改 `SKILL.md` frontmatter 的 `description`，不改 `evals/`。
- 測試全部離線。不准跑 `tests/test_cli_smoke.py`、`tests/test_health.py`、`tests/test_query_news_api.py`、`scripts/healthcheck.py`、`tests/run_all.ps1`。會碰到 2027 年日期的測試，先把 `update_holidays.update` 換成丟例外，並照 `tests/test_query_news_internals.py` 的 `saved_state` 寫法備份、在 `finally` 還原 storage 的休市狀態。
- 不讀 `config.json`；不讀、不引用 `scripts/premarket_digest.ps1`、`scripts/send_digest.ps1`、`scripts/digest_watchdog.ps1`。
- repo 公開：commit 的檔案不寫使用者名稱、工號、email、內部路徑。
- 文件與程式註解不用破折號（— 或 ─），改用逗號、句點或括號；新測試的 `record()` 用 ` | ` 分隔訊息，不照抄既有的 ` — `。程式註解沿用既有寫法（中文加半形標點）。
- 時間一律台北時間：`NC._now_tw()`、`NC.TAIPEI`。
- 門檻（spec 5.2 的 `rule`）：`{"confidence_min": 0.5, "title_weight": 3, "body_weight": 1, "body_max_stocks_per_news": 3}`。
- 測試指令一律在 skill 根目錄執行：`python -X utf8 tests/<檔名>.py`，通過的輸出是 `=== 結果: N/N pass, 0 fail ===` 且結束碼 0。

## Review Focus

1. 交易日所有來源都失敗，`fetch_market_news` 回空清單：要寫 `status: "error"`（訊息含「沒有抓到任何新聞」），不是 `empty`。測試在 Task 4 `test_payload_zero_news`。
2. `news_sentiment` 載入失敗，整批新聞都沒有 `sentiment` 鍵：要寫 `status: "error"`，不是悄悄變成空清單。測試在 Task 4 `test_payload_no_sentiment`。
3. 12/31 執行，`next_trade_date` 跨進還沒有休市資料的年度：離線也算得出（2026-12-31 得到 2027-01-04），不能卡在連網。測試在 Task 4 `test_payload_year_rollover`。
4. 新聞欄位是 None 或缺漏（title、body、time、sentiment），`stock_codes` 混有美股代號（`"US-NVDA"`、`"NVDA"`）：不當掉，美股代號忽略。測試在 Task 2 `test_mentions_missing_fields`、Task 3 `test_score_missing_fields`。
5. 同一檔在同一則新聞出現多次，又出現在別則新聞：每則新聞只算一票、一筆 evidence。測試在 Task 3 `test_one_vote_per_article`。

---

### Task 1: `fetch_market_news` 保留出版商代號

**Files:**
- Modify: `scripts/news_core.py:733`（簽名與 docstring）、`scripts/news_core.py:782-788`（組項目）
- Test: `tests/test_query_news_internals.py`（新增 `test_market_news_keep_codes`，並在 `main()` 呼叫）

**Interfaces:**
- Produces: `fetch_market_news(since="last_close", days=1, tag_sentiment=None, keep_codes=False) -> list[dict]`。`keep_codes=True` 時每則多一個 `"stock_codes": list[str]`（取 fetch_sanbao 對映後的 `stock_codes`，缺就 `[]`）。

- [ ] **Step 0: 開分支**

Run: `git switch -c feat/bullish-watchlist`
Expected: `Switched to a new branch 'feat/bullish-watchlist'`

- [ ] **Step 1: 寫失敗測試**

```python
def test_market_news_keep_codes():
    """keep_codes=True 才帶 stock_codes;預設輸出不變(07:40 盤前信依賴)。"""
    import copy
    now = datetime.datetime(2026, 10, 22, 7, 50, tzinfo=NC.TAIPEI)
    fake = [{"source": "cnyes", "title": "南亞科報價調漲", "summary": "", "body": "內文",
             "url": "http://x/1", "published_at": "2026-10-22T07:00:00+08:00",
             "keywords": [], "stock_codes": ["2408", "US-MU"], "category": ""}]
    orig = (NP.fetch_sanbao, NC._now_tw)
    NP.fetch_sanbao = lambda cfg: copy.deepcopy(fake)
    NC._now_tw = lambda: now
    try:
        NC.clear_news_cache()
        plain = NC.fetch_market_news(since="last_close", tag_sentiment=False)
        NC.clear_news_cache()
        kept = NC.fetch_market_news(since="last_close", tag_sentiment=False, keep_codes=True)
    finally:
        NP.fetch_sanbao, NC._now_tw = orig
        NC.clear_news_cache()
    check("fetch_market_news:預設不帶 stock_codes",
          set(plain[0]) == {"time", "title", "source", "url", "summary", "body"}, str(plain[0].keys()))
    check("fetch_market_news:keep_codes=True 帶出版商代號",
          kept[0].get("stock_codes") == ["2408", "US-MU"], str(kept[0]))
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -X utf8 tests/test_query_news_internals.py`
Expected: `TypeError: fetch_market_news() got an unexpected keyword argument 'keep_codes'`

- [ ] **Step 3: 實作**

在 `fetch_market_news` 參數最後加 `keep_codes=False`；782-788 組項目時，`keep_codes` 為真才加 `"stock_codes": list(it.get("stock_codes") or [])`。docstring 補一行說明。

- [ ] **Step 4: 跑測試確認通過**

Run: `python -X utf8 tests/test_query_news_internals.py`
Expected: `=== 結果: 64/64 pass, 0 fail ===`

- [ ] **Step 5: Commit**

```bash
git add scripts/news_core.py tests/test_query_news_internals.py
git commit -m "fetch_market_news 可選擇保留出版商代號(keep_codes)"
```

---

### Task 2: 全市場股名反查（`stock_mentions.py`）

**Files:**
- Create: `scripts/stock_mentions.py`
- Create: `tests/test_bullish.py`

**Interfaces:**
- Produces:
  - `THEME_ALIASES: frozenset[str]`、`COMMON_WORD_NAMES: frozenset[str]`（內容見下）
  - `build_lexicon(code_names: dict[str, str], curated: dict[str, dict]) -> dict`，回傳 `{"names": {code: name}, "terms": {term: code}, "first": {首字: [term, ...]}}`，`first` 每組依長度由長到短。
  - `load_lexicon() -> dict`：讀 `data/stocks/tw_names.json`（`{代號: 簡稱}`）與 `data/stocks/tw_stocks.json`（key 像 `"2330.TW"`，值有 `name_zh`、`aliases`），呼叫 `build_lexicon`，模組層快取。
  - `find_mentions(title: str | None, body: str | None, stock_codes: list | None, lex: dict) -> dict[str, str]`，回傳 `{code: "title" 或 "body"}`。

**字典規則（`build_lexicon`）：**
- `names`：`code_names` 全部；`curated` 依裸代號（`key.split(".")[0]`，同一代號的 `.TW`、`.TWO`、`.TWO2` 合併）補進 `code_names` 沒有的代號，名稱用 `name_zh`。
- 詞的優先序：先放所有正式簡稱（`code_names` 的值）。再放別名：`curated` 同一裸代號下所有 key 的 `aliases` 聯集，加上與正式簡稱不同的 `name_zh`。
- 丟掉的詞：長度小於 2；全是數字或含 `.`（代號與 ticker 交給代號比對）；在 `THEME_ALIASES` 或 `COMMON_WORD_NAMES` 裡（股票本身仍能靠代號命中）；別名已是另一檔的正式簡稱（例如 2454 的別名「聯發」就是 1459 的簡稱，丟別名）；同一個別名出現在兩檔以上（全部丟）。
- `THEME_ALIASES = {"AI伺服器", "ABF載板", "MLCC", "DRAM", "散熱", "IC設計", "EMC", "CCL", "半導體通路", "白牌交換器", "伺服器BMC", "高股息ETF", "台灣50", "台50", "晶圓代工龍頭", "Toyota台灣代理", "Delta", "Mega", "Cathay", "Quanta", "MSI"}`。不在 `tw_stocks.json` 任何別名裡的項目就從集合拿掉（由 `test_real_lexicon` 抓）。
- `COMMON_WORD_NAMES`（起始清單，實作者可再加）：`大量 新產 數字 中華 聯合 世界 新興 全新 新建 全台 統一 南亞 華電 至上 卓越 業強 大成 及成 力士 三星 精確 時報 全國 資通 力新 南港 承啟 泰山 地球 典範 根基 互動 宏觀 巨大 全家 光譜 帝寶 首利 合一 力成 達新 達能 中台 國統 大華 大亞 合機 中工 星通 立德 利機 華廣 高技 東森 高力 佳能 大樹 氣立 元晶 華城 大台北 光明 幸福 國產 安心 冠軍 傳奇 正文 有益 易發 綠電 精華 精英 進階 台南 建國 華夏 華東 無敵 樂意 得力 慶生 惠普 康普 昇陽 海光 花王 亞航 大塚 強生 恆大 新華 中航 中電 中天 中視 遠見 浪凡 台灣大 中石化 新零售 雲嘉南`。每一個都必須是 `tw_names.json` 的簡稱或 `tw_stocks.json` 的 `name_zh`，不是就拿掉（由 `test_real_lexicon` 抓）。

**比對規則（`find_mentions`）：**
- `title`、`body` 是 None 就當空字串；先把 `https?://\S+` 換成空白。
- 股名與別名用最長匹配，命中就吃掉那一段（演算法見 Step 3）。詞首是英數時，前一字不能是英數；詞尾是英數時，後一字不能是英數（區分大小寫）。
- 代號用 `re.compile(r"(?<![0-9A-Za-z./$])(\d{4,6})(?![0-9A-Za-z.%點元億萬張])(?!\s*[年月日])")`，代號要在 `lex["names"]` 裡才算。
- 標題命中算 `"title"`。只在內文命中，或只出現在 `stock_codes`，算 `"body"`。`stock_codes` 只取 `lex["names"]` 裡的代號（美股代號因此忽略）。

- [ ] **Step 1: 建立測試檔，寫失敗測試**

檔頭照 `tests/test_query_news_internals.py:26-47`：`BASE`、`sys.path.insert(0, str(BASE / "scripts"))`、模組層 `results = []`、`record(name, ok, msg="")`（訊息用 `" | "` 接）、`check(name, cond, msg="")`。結尾 `main()` 逐一呼叫 test 函式後印 `=== 結果: {ok}/{len(results)} pass, {fail} fail ===`，`sys.exit(0 if fail == 0 else 1)`。

```python
import stock_mentions as SM

LEX = SM.build_lexicon(
    {"2408": "南亞科", "1303": "南亞", "2027": "大成鋼", "5347": "世界", "6643": "M31",
     "2330": "台積電", "1459": "聯發", "2454": "聯發科"},
    {"2330.TW": {"name_zh": "台積電", "aliases": ["台積電", "TSMC", "2330.TW", "2330"]},
     "2330.TWO": {"name_zh": "台積電", "aliases": ["台積", "護國神山"]},
     "2408.TW": {"name_zh": "南亞科", "aliases": ["DRAM"]},
     "2454.TW": {"name_zh": "聯發科", "aliases": ["聯發", "MTK"]}})


def test_mentions_title_and_body():
    check("標題點名算 title,只在內文算 body",
          SM.find_mentions("南亞科報價調漲", "台積電也受惠", [], LEX) == {"2408": "title", "2330": "body"})


def test_mentions_filters():
    f = SM.find_mentions
    check("最長匹配:聯發科不連帶聯發", f("聯發科法說", "", [], LEX) == {"2454": "title"})
    check("主題詞 DRAM 不算點名", f("DRAM 報價大漲", "", [], LEX) == {})
    check("常用詞股名不算", f("世界經濟展望", "", [], LEX) == {})
    check("常用詞股名靠代號仍命中", f("世界(5347)營收創高", "", [], LEX) == {"5347": "title"})
    check("代號後接年不算", f("2027年展望", "預估 2027 年", [], LEX) == {})
    check("網址裡的數字不算", f("", "見 https://x.com/a/2027 說明", [], LEX) == {})
    check("英數邊界", f("M310 晶片", "", [], LEX) == {} and f("M31 營收", "", [], LEX) == {"6643": "title"})
    check(".TW 與 .TWO 的別名合併", f("台積拿下大單", "", [], LEX) == {"2330": "title"})
    check("英文別名", f("TSMC capex", "", [], LEX) == {"2330": "title"})
    check("別名是他檔簡稱就丟別名", f("聯發公告", "", [], LEX) == {"1459": "title"})


def test_mentions_publisher_codes():
    f = SM.find_mentions
    check("出版商代號算 body,美股代號忽略", f("盤勢", "", ["2408", "US-NVDA", "NVDA"], LEX) == {"2408": "body"})
    check("出版商代號加標題股名算 title", f("南亞科大漲", "", ["2408"], LEX) == {"2408": "title"})


def test_mentions_missing_fields():
    check("欄位 None 不當掉", SM.find_mentions(None, None, None, LEX) == {})


def test_real_lexicon():
    import json
    lex = SM.load_lexicon()
    names = set(json.loads((BASE / "data/stocks/tw_names.json").read_text(encoding="utf-8")).values())
    curated = json.loads((BASE / "data/stocks/tw_stocks.json").read_text(encoding="utf-8"))
    names |= {v["name_zh"] for v in curated.values()}
    aliases = {a for v in curated.values() for a in v["aliases"]}
    check("常用詞清單每個都是真股名", SM.COMMON_WORD_NAMES <= names, str(SM.COMMON_WORD_NAMES - names))
    check("主題詞清單每個都在別名裡", SM.THEME_ALIASES <= aliases, str(SM.THEME_ALIASES - aliases))
    check("真實字典:南亞科、台積、聯發", lex["terms"].get("南亞科") == "2408"
          and lex["terms"].get("台積") == "2330" and lex["terms"].get("聯發") == "1459")
    check("真實字典:常用詞與主題詞已剔除", "世界" not in lex["terms"] and "DRAM" not in lex["terms"])


def test_mentions_speed():
    import time
    lex = SM.load_lexicon()
    body = ("台股今日中小型股大漲,華碩與台積電領軍,大立光、中華電走穩。" * 70)[:2000]
    t0 = time.perf_counter()
    for _ in range(200):
        SM.find_mentions("南亞科法說會", body, ["2408"], lex)
    dt = time.perf_counter() - t0
    check("效能:200 則 x 2,000 字 < 3 秒", dt < 3, f"{dt:.2f}s")
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -X utf8 tests/test_bullish.py`
Expected: `ModuleNotFoundError: No module named 'stock_mentions'`

- [ ] **Step 3: 實作 `scripts/stock_mentions.py`**

最長匹配用首字索引掃描（單一大型 regex 交替式在 2,000 個詞上太慢）：

```python
def _scan(text, lex):
    found, i, n = set(), 0, len(text)
    while i < n:
        for term in lex["first"].get(text[i], ()):          # 同首字的詞,長的在前
            j = i + len(term)
            if text.startswith(term, i) and _edge_ok(text, i, j, term):
                found.add(lex["terms"][term])
                i = j                                        # 吃掉這段,短名不再重複命中
                break
        else:
            i += 1
    return found
```

`_edge_ok` 依「比對規則」的英數邊界判斷。`find_mentions` 的結果：標題（`_scan` 加代號 regex）是 title；內文（`_scan` 加代號 regex 加過濾後的 `stock_codes`）扣掉 title 的是 body。

- [ ] **Step 4: 跑測試確認通過**

Run: `python -X utf8 tests/test_bullish.py`
Expected: `=== 結果: N/N pass, 0 fail ===`，結束碼 0

- [ ] **Step 5: Commit**

```bash
git add scripts/stock_mentions.py tests/test_bullish.py
git commit -m "新增全市場股名反查(標題級、內文級、常用詞與主題詞剔除)"
```

---

### Task 3: 計票、排除與排序（`news_bullish.score_news`）

**Files:**
- Create: `scripts/news_bullish.py`
- Test: `tests/test_bullish.py`

**Interfaces:**
- Consumes: Task 2 `stock_mentions.find_mentions`；`NC._snippets(text, kws, width=60, limit=3) -> list[str]`（`scripts/news_core.py:424`）。
- Produces:
  - `RULE`：值見 Global Constraints。
  - `vote(item: dict, rule: dict = RULE) -> str | None`：`sentiment == "bullish"` 且 `confidence >= confidence_min` 回 `"bull"`；`"bearish"` 且過門檻回 `"bear"`；其他（含缺鍵）回 `None`。
  - `score_news(news: list[dict], lex: dict, rule: dict = RULE) -> dict`，回傳 `{"items": [...], "excluded": [...], "candidates": [...]}`。
    - item：`{"code", "name", "score", "title_votes", "body_votes", "reason", "evidence"}`
    - excluded：`{"code", "name", "why": "mixed"}`
    - candidate：`{"code", "name", "evidence"}`
    - evidence：`{"title", "url", "time", "source", "match", "sentiment", "confidence", "events", "counted", "snippet"}`，`match` 是 `"title"` 或 `"body"`；`counted` 表示這筆有沒有參與計票。

**規則：**
- 每則新聞：`m = find_mentions(title, body or summary, stock_codes, lex)`。這則的 body 級代號超過 `body_max_stocks_per_news` 檔時，這些 body 級的 `counted` 都是 False；title 級一律 True。
- 每檔每則新聞只產生一筆 evidence、最多一票。`counted` 且 `vote == "bull"` 時，title 級加 `title_votes`、body 級加 `body_votes`；`"bear"` 記一張利空票。
- `score = title_votes * title_weight + body_votes * body_weight`。
- 利多票至少 1 且利空票 0 的進 `items`。利多、利空都有的進 `excluded`（`why: "mixed"`）。
- evidence 的 `time` 取 `item.get("time") or ""`，直接比字串（全部是 `+08:00` ISO，字典序就是時間序；空字串最舊）。
- `items` 排序：有標題級利多票的一組在前，只有內文級的一組在後；同組依 `score` 由高到低；同分時最新一筆 evidence 的 time 較新的在前；再相同就依 code 由小到大。
- `candidates`：所有被提到但沒進 `items` 的股票（含 excluded、只有利空、中性、信心不足、被內文上限擋掉），依 evidence 筆數由多到少，再依最新 time 由新到舊，再依 code。
- evidence 依 time 由新到舊。`snippet` 是 `NC._snippets(body or summary or "", [name, code])` 的第一段，沒有就 `""`。
- `reason`：標題級利多票 t 大於 0 時加 `f"標題點名 {t} 則利多"`，內文級 b 大於 0 時加 `f"內文提到 {b} 則利多"`，兩段用 `"，"` 接；計票的利多 evidence 有 events 時，取去重後前 3 個，接 `"（" + "、".join(events) + "）"`。

- [ ] **Step 1: 寫失敗測試**

```python
import news_bullish as NB


def N(title, body="", codes=(), s="bullish", c=0.667, t="2026-10-22T07:00:00+08:00", ev=()):
    return {"time": t, "title": title, "source": "ctee", "url": f"http://x/{title}", "summary": "",
            "body": body, "sentiment": s, "confidence": c, "events": list(ev), "stock_codes": list(codes)}


def test_vote():
    check("利多過門檻", NB.vote(N("a", c=0.5)) == "bull")
    check("利多不過門檻", NB.vote(N("a", c=0.25)) is None)
    check("利空過門檻", NB.vote(N("a", s="bearish")) == "bear")
    check("中性與缺鍵", NB.vote(N("a", s="neutral")) is None and NB.vote({"title": "a"}) is None)


def test_score_basic():
    r = NB.score_news([N("南亞科報價調漲", ev=["訂單"]), N("市場觀察", body="台積電受惠")], LEX)
    codes = [i["code"] for i in r["items"]]
    check("標題級在前", codes == ["2408", "2330"], str(codes))
    top = r["items"][0]
    check("分數與票數", (top["score"], top["title_votes"], top["body_votes"]) == (3, 1, 0), str(top))
    check("reason", top["reason"] == "標題點名 1 則利多（訂單）", top["reason"])


def test_body_cap():
    r = NB.score_news([N("聯發科大漲", body="南亞科、台積電、大成鋼、M31 同步走高")], LEX)
    check("內文超過 3 檔不計票,標題級照算", [i["code"] for i in r["items"]] == ["2454"], str(r["items"]))
    capped = [e for c in r["candidates"] for e in c["evidence"] if c["code"] == "2408"]
    check("被擋的仍在 candidates 且 counted=False", capped and capped[0]["counted"] is False)


def test_mixed_excluded():
    r = NB.score_news([N("南亞科報價調漲"), N("南亞科遭降評", s="bearish")], LEX)
    check("利多利空並存:不列", r["items"] == [] and r["excluded"] == [{"code": "2408", "name": "南亞科", "why": "mixed"}])
    check("並存的仍在 candidates", [c["code"] for c in r["candidates"]] == ["2408"])


def test_rank_title_first():
    news = [N("聯發科報喜")] + [N(f"盤勢{i}", body="台積電受惠") for i in range(4)]
    r = NB.score_news(news, LEX)
    check("標題 1 票(3 分)排在內文 4 票(4 分)前", [i["code"] for i in r["items"]] == ["2454", "2330"])


def test_rank_tie_latest():
    r = NB.score_news([N("南亞科報喜", t="2026-10-22T06:00:00+08:00"),
                       N("聯發科報喜", t="2026-10-22T07:00:00+08:00")], LEX)
    check("同分較新的在前", [i["code"] for i in r["items"]] == ["2454", "2408"])


def test_one_vote_per_article():
    r = NB.score_news([N("南亞科南亞科", body="南亞科再提南亞科"), N("南亞科法說")], LEX)
    top = r["items"][0]
    check("每則只算一票一筆", top["title_votes"] == 2 and len(top["evidence"]) == 2, str(top))


def test_score_missing_fields():
    r = NB.score_news([{"title": None, "body": None}, {"time": None, "title": "南亞科報喜",
                       "sentiment": "bullish", "confidence": 0.667, "stock_codes": ["US-NVDA"]}], LEX)
    check("缺欄位不當掉", [i["code"] for i in r["items"]] == ["2408"], str(r))


def test_snippet():
    r = NB.score_news([N("市場觀察", body="法人指出南亞科第四季報價續漲", s="neutral", c=0.0)], LEX)
    ev = r["candidates"][0]["evidence"][0]
    check("候選附個股片段", "南亞科" in ev["snippet"] and ev["match"] == "body", str(ev))
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -X utf8 tests/test_bullish.py`
Expected: `ModuleNotFoundError: No module named 'news_bullish'`

- [ ] **Step 3: 實作 `RULE`、`vote`、`score_news`**（`scripts/news_bullish.py` 開頭 `import news_core as NC`、`import stock_mentions as SM`）

- [ ] **Step 4: 跑測試確認通過**

Run: `python -X utf8 tests/test_bullish.py`
Expected: `0 fail`

- [ ] **Step 5: Commit**

```bash
git add scripts/news_bullish.py tests/test_bullish.py
git commit -m "利多清單計票、混合排除與排序"
```

---

### Task 4: 組檔、寫檔、`run()` 與 `news.py --bullish`

**Files:**
- Modify: `scripts/news_bullish.py`
- Modify: `scripts/news.py:39-93`（`parse_args` 加 `"bullish": False` 與 `--bullish`）、`scripts/news.py:176-185`（`main()` 在 `--today` 分派之前先分派 `--bullish`）
- Test: `tests/test_bullish.py`

**Interfaces:**
- Consumes: Task 1 `NC.fetch_market_news(since="last_close", keep_codes=True)`；Task 2 `SM.load_lexicon()`；Task 3 `score_news`、`RULE`；`NC._now_tw()`、`NC._is_closed(d: datetime) -> bool`、`NC.market_session_cutoff(now) -> (aware datetime, date)`；`storage._next_trading_day(d)`（傳 `date` 回 `date`）；`update_holidays._write(path: Path, data: dict)`（暫存檔加 `os.replace`，重試 PermissionError）。
- Produces:
  - `OUT_DIR = NC.BASE / "out" / "bullish"`
  - `make_payload(news: list[dict], now: datetime.datetime, lex: dict) -> dict`
  - `error_payload(now: datetime.datetime, message: str) -> dict`
  - `write_payload(payload: dict, out_dir: pathlib.Path = OUT_DIR) -> pathlib.Path`：寫 `bullish_YYYYMMDD.json`（日期取 `trade_date`）再寫 `latest.json`，內容相同，回傳日期檔路徑。
  - `run(now: datetime.datetime | None = None, out_dir: pathlib.Path = OUT_DIR, fetch=None) -> int`：0 表示 ok、empty 或休市；1 表示 error。`fetch` 預設 `lambda: NC.fetch_market_news(since="last_close", keep_codes=True)`。
  - CLI：`python -X utf8 scripts/news.py --bullish`，結束碼等於 `run()`；stderr 印 `[輸出] <日期檔路徑>` 與一行 `[利多清單] <trade_date> <status> <items 檔數> 檔`。

**檔案欄位（spec 5.2）：** `schema_version` 1、`status`、`trade_date`（`now.date()`）、`next_trade_date`（`storage._next_trading_day(now.date())`）、`generated_at`（`now.isoformat(timespec="seconds")`）、`window`（`from` 是 `market_session_cutoff(now)[0].isoformat()`，`to` 是 `generated_at`）、`method` `"rule"`、`rule`、`items`、`excluded`、`candidates`。`error_payload` 同一組鍵，三個清單都是 `[]`，多一個 `"error": message`；它算 `next_trade_date` 或 `window` 失敗時填 `None`。

**狀態：** `news` 是空的回 error（`"沒有抓到任何新聞"`）；沒有任何一則帶 `sentiment` 鍵回 error（`"新聞沒有情緒標籤,news_sentiment 可能載入失敗"`）；其餘依 `score_news` 的 `items` 是否為空回 ok 或 empty。

**`run()` 流程：** `now = now or NC._now_tw()`；`NC._is_closed(now)` 為真就印 `[利多清單] 今天休市,不產出` 回 0，不寫檔。否則在 try 裡取新聞、載字典、`make_payload`；任何例外改用 `error_payload(now, repr(e))`。然後 `write_payload`，status 是 error 回 1，其餘回 0。

- [ ] **Step 1: 寫失敗測試**

```python
import datetime
import json
import tempfile
import shutil
import storage
import update_holidays as UH

D = lambda *a: datetime.datetime(*a, tzinfo=NC.TAIPEI)
KEYS = {"schema_version", "status", "trade_date", "next_trade_date", "generated_at", "window",
        "method", "rule", "items", "excluded", "candidates"}


def test_payload_ok_shape():
    p = NB.make_payload([N("南亞科報價調漲")], D(2026, 10, 22, 7, 50), LEX)
    check("欄位齊全", set(p) == KEYS, str(set(p) ^ KEYS))
    check("狀態與日期", (p["status"], p["trade_date"], p["next_trade_date"]) == ("ok", "2026-10-22", "2026-10-23"))
    check("時間窗", p["window"]["from"] == "2026-10-21T14:00:00+08:00", str(p["window"]))


def test_payload_next_trade_date_holiday():
    p = NB.make_payload([N("南亞科報喜")], D(2026, 10, 23, 7, 50), LEX)
    check("週五的下一交易日跳過 10/26 休市", p["next_trade_date"] == "2026-10-27", p["next_trade_date"])


def test_payload_year_rollover():
    saved = (storage._HOLIDAYS, set(storage._HOLIDAY_YEARS), set(storage._MISSING_YEAR_HANDLED), UH.update)
    UH.update = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("離線測試不連網"))
    try:
        p = NB.make_payload([N("南亞科報喜")], D(2026, 12, 31, 7, 50), LEX)
    finally:
        storage._HOLIDAYS, storage._HOLIDAY_YEARS = saved[0], saved[1]
        storage._MISSING_YEAR_HANDLED.clear()
        storage._MISSING_YEAR_HANDLED.update(saved[2])
        UH.update = saved[3]
    check("跨年離線也算得出", p["next_trade_date"] == "2027-01-04", p["next_trade_date"])


def test_payload_empty():
    p = NB.make_payload([N("南亞科法說", s="neutral", c=0.0)], D(2026, 10, 22, 7, 50), LEX)
    check("沒有利多是 empty", p["status"] == "empty" and p["items"] == [])


def test_payload_zero_news():
    p = NB.make_payload([], D(2026, 10, 22, 7, 50), LEX)
    check("零則新聞是 error", p["status"] == "error" and "沒有抓到任何新聞" in p["error"], str(p))


def test_payload_no_sentiment():
    raw = [{k: v for k, v in N("南亞科報喜").items() if k not in ("sentiment", "confidence", "events")}]
    p = NB.make_payload(raw, D(2026, 10, 22, 7, 50), LEX)
    check("沒有情緒標籤是 error", p["status"] == "error", str(p))


def test_run_writes_files():
    tmp = pathlib.Path(tempfile.mkdtemp())
    shared = NC.BASE / "out" / "news_result.json"
    before = shared.stat().st_mtime_ns if shared.exists() else None
    try:
        rc = NB.run(now=D(2026, 10, 22, 7, 50), out_dir=tmp, fetch=lambda: [N("南亞科報價調漲")])
        dated, latest = tmp / "bullish_20261022.json", tmp / "latest.json"
        check("run 回 0 並寫兩個檔", rc == 0 and dated.exists() and latest.exists())
        check("兩檔內容相同", dated.read_bytes() == latest.read_bytes())
        check("清單內容", json.loads(latest.read_text(encoding="utf-8"))["items"][0]["code"] == "2408")
        check("沒動到 news_result.json", (shared.stat().st_mtime_ns if shared.exists() else None) == before)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_run_closed_day():
    tmp = pathlib.Path(tempfile.mkdtemp())
    try:
        rc = NB.run(now=D(2026, 10, 24, 7, 50), out_dir=tmp, fetch=lambda: [N("南亞科報喜")])
        check("休市日回 0 且不寫檔", rc == 0 and not any(tmp.iterdir()))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_run_fetch_error():
    tmp = pathlib.Path(tempfile.mkdtemp())

    def boom():
        raise RuntimeError("缺套件")
    try:
        rc = NB.run(now=D(2026, 10, 22, 7, 50), out_dir=tmp, fetch=boom)
        p = json.loads((tmp / "latest.json").read_text(encoding="utf-8"))
        check("抓取失敗回 1 並寫 error 檔", rc == 1 and p["status"] == "error" and "缺套件" in p["error"], str(p))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_cli_flag():
    import news
    check("--bullish 旗標", news.parse_args(["--bullish"])["bullish"] is True)
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `python -X utf8 tests/test_bullish.py`
Expected: `AttributeError: module 'news_bullish' has no attribute 'make_payload'`

- [ ] **Step 3: 實作 `make_payload`、`error_payload`、`write_payload`、`run`，以及 `news.py` 的旗標與分派**

`storage` 在函式內 import（它會載入 pandas，約 1 秒，只在需要時付）。`news.py` 分派寫成 `if args["bullish"]: import news_bullish; sys.exit(news_bullish.run())`。

- [ ] **Step 4: 跑測試確認通過，並跑既有離線測試**

Run: `python -X utf8 tests/test_bullish.py`
Expected: `0 fail`
Run: `python -X utf8 tests/test_query_news_internals.py`、`python -X utf8 tests/test_sentiment.py`、`python -X utf8 tests/test_formatters.py`、`python -X utf8 tests/test_digest_render.py`
Expected: 依序 `64/64`、`45/45`、`79/79` pass，`test_digest_render: 24 passed, 0 failed`

- [ ] **Step 5: Commit**

```bash
git add scripts/news_bullish.py scripts/news.py tests/test_bullish.py
git commit -m "新增 news.py --bullish:產出 out/bullish/latest.json"
```

---

### Task 5: 排程登記腳本與 skill 文件

**Files:**
- Create: `scripts/register_bullish_task.ps1`
- Create: `references/bullish_watchlist.md`
- Modify: `SKILL.md`（L104 公開函式清單；在 `## 今日盤後議題重點(--today digest)` 小節之後新增 `## 每日利多清單(排程)`；L107-117 `## 需要時再讀` 表加一列）
- Modify: `references/cli.md`（L8 的 exit 1 說明加入 `--bullish`；L12-27 `## 旗標` 表加一列；`## 各模式在做什麼` 加 `### --bullish`）
- Modify: `references/maintenance.md`（L5-38 `## 檔案` 表加 3 列；L40-56 `## 測試` 表加 1 列；L88-105 `## 已知問題` 表加 2 列）

**Interfaces:**
- Consumes: Task 4 的 CLI 與檔案契約。
- Produces: 排程工作名稱 `stock-news-bullish`；`references/bullish_watchlist.md` 的章節 `## 什麼時候用`、`## 執行與排程`、`## 輸出檔案(schema_version 1)`、`## 判斷規則`、`## 已知限制`（Task 6 再加 Pro 端章節）。

**`register_bullish_task.ps1` 規格：**
- 參數：`-Remove`（移除工作）、`-DryRun`（只印設定不登記）、`-At`（預設 `'07:50'`）。
- 觸發：每週一到週五 `-At`。動作：`(Get-Command python).Source`，參數 `-X utf8 "<scripts 目錄>\news.py" --bullish`，工作目錄是 skill 根目錄（`Split-Path $PSScriptRoot`）。設定：`-StartWhenAvailable`、執行上限 15 分鐘。以目前使用者、只在登入時執行（不存密碼）。`Register-ScheduledTask -Force` 覆蓋同名工作。
- 路徑全部由 `$PSScriptRoot` 推算，不寫死任何使用者路徑。檔案存成 UTF-8 with BOM（PowerShell 5.1）。

**文件內容要點：**
- `SKILL.md` 新小節不超過 6 行：用途、指令 `python -X utf8 scripts/news.py --bullish`、輸出 `out/bullish/latest.json`、休市日不產出、可隨時手動跑（不碰 `out/news_result.json`）、細節見 `references/bullish_watchlist.md`。表格新列：`| 每日利多清單、Shioaji Pro 自選股排程 | [references/bullish_watchlist.md](references/bullish_watchlist.md) |`。L104 的 `fetch_market_news(since="last_close")` 改成 `fetch_market_news(since="last_close", keep_codes=False)`。
- `references/bullish_watchlist.md`：
  - `## 執行與排程`：寫明同事的前置（Python、`pip install -r requirements.txt`、從 `config.example.json` 複製一份 `config.json`、不需要 Metabase），登記與移除指令（`powershell -ExecutionPolicy Bypass -File scripts\register_bullish_task.ps1 [-DryRun|-Remove]`），以及和 07:40 共用快取的說明。
  - `## 輸出檔案`：欄位表照 spec 5.2，加上 evidence 的 `counted` 與 `snippet`。
  - `## 判斷規則`：照 Task 2、Task 3 的規則。
  - `## 已知限制`：每個來源只抓最新 10 到 15 則；情緒是整篇一個標籤；`-KY` 股名要完整寫出才中；常用詞股名只能靠代號命中；`out/bullish/` 每個交易日留一個檔，不會自動清。
- `maintenance.md` 檔案表新列：`scripts/stock_mentions.py`、`scripts/news_bullish.py`、`scripts/register_bullish_task.ps1`。測試表新列：`| \`python tests/test_bullish.py\` | 股名反查、計票、排序、組檔、寫檔、--bullish | 否 | <日期> 共 N 項 |`。已知問題新列：新聞覆蓋不完整（第一版接受）；`-KY` 股名省略連字號時比不到。

- [ ] **Step 1: 寫 `register_bullish_task.ps1`**

- [ ] **Step 2: 驗證語法與 DryRun（不登記）**

以下三行直接在 PowerShell 裡跑（不要包在 `powershell -Command "..."` 裡，`$` 會被外層展開）：
Run: `$e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path scripts\register_bullish_task.ps1).Path,[ref]$null,[ref]$e); $e.Count`
Expected: `0`
Run: `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\register_bullish_task.ps1 -DryRun`
Expected: 輸出含 `stock-news-bullish`、`news.py" --bullish`、`07:50`、`Monday` 到 `Friday`
Run: `$null -eq (Get-ScheduledTask -TaskName stock-news-bullish -ErrorAction SilentlyContinue)`
Expected: `True`（DryRun 沒有真的登記；真正登記由使用者確認後自己跑）

- [ ] **Step 3: 寫 `references/bullish_watchlist.md`，改 `SKILL.md`、`references/cli.md`、`references/maintenance.md`**

- [ ] **Step 4: 驗證文件**

Run: `git diff --unified=0 main -- SKILL.md | findstr /B "+description -description"`
Expected: 沒有輸出（description 沒動）
Run: `git grep -n -e "—" -e "─" -- SKILL.md references scripts/register_bullish_task.ps1 scripts/stock_mentions.py scripts/news_bullish.py tests/test_bullish.py`
Expected: 沒有輸出（新寫的部分沒有破折號；若命中的是既有舊行，不在本計畫範圍）

- [ ] **Step 5: Commit**

```bash
git add scripts/register_bullish_task.ps1 references/bullish_watchlist.md SKILL.md references/cli.md references/maintenance.md
git commit -m "利多清單排程登記腳本與文件"
```

---

### Task 6: Shioaji Pro 端設定指南、排程 prompt 與實測關卡

**Files:**
- Modify: `references/bullish_watchlist.md`（新增 `## Shioaji Pro 端設定`、`## 每日排程任務 prompt`、`## 進階版(對話追問)`、`## 實測清單`）

**Interfaces:**
- Consumes: Task 4 的 `latest.json` 契約；上游 `feat/340-agent-watchlist-tools` 的 `MCP_TOOLS.md` 工具名稱：`list_watchlists`、`get_watchlist`、`create_watchlist`、`add_to_watchlist`、`remove_from_watchlist`、`reorder_watchlist`、`search_products`、`create_task`、`notify_user`。各工具的參數名稱公開文件沒寫，prompt 要求 agent 照 MCP server 公告的 schema 呼叫，且每個寫入動作用新的 `idempotency_key`。

**每日排程任務 prompt（照抄進文件，路徑由使用者填）：**

```text
每天 08:00 執行（休市日的判斷在第 2 步）。你只能維護名為「新聞利多」的自選股清單，其他清單一律不碰；不要用 delete_watchlist、rename_watchlist 或 shioaji CLI。
1. 讀檔 <latest.json 的絕對路徑>。今天的日期以台北時間為準。
2. 判斷目標成員：
   a. trade_date 等於今天：status 是 ok，目標是 items 的 code，照檔案順序；status 是 empty，目標是空清單；status 是 error，視同失敗。
   b. trade_date 不是今天，而且今天早於 next_trade_date：今天休市，什麼都不做、不通知，直接結束。
   c. 其他情況（讀不到檔、格式不對、trade_date 過期、next_trade_date 是 null）：視同失敗。
   失敗時目標是空清單。
3. 用 list_watchlists 找「新聞利多」的 watchlist_id，找不到就用 create_watchlist 建立。
4. 每個目標代號先用 search_products 解析成台股商品，解析不到的跳過並記下。
5. 用 get_watchlist 取現有成員，多的用 remove_from_watchlist 移除，缺的用 add_to_watchlist 加入，順序不同就用 reorder_watchlist 照目標順序排。每個寫入動作用新的 idempotency_key。
6. 再用 get_watchlist 讀回，確認成員與順序和目標一致。
7. 失敗或清空時用 notify_user 說明原因（附 status 與 error）；有解析不到的代號一併列出。正常有清單時不通知。
```

**實測清單（關卡，要等 `feat/340` 合併發佈後在 App 裡做，任一項不過就停下回報使用者，不自行改成 skill 直接寫自選股）：**
1. App 的工具清單出現 `list_watchlists` 等自選股工具。
2. 授權 `ui.control`、`task.manage` 後重啟 App，確認授權還在；排程在沒人操作時不跳授權詢問。（上游 `AGENT_HARNESS_CONTRACT.md` 寫授權重啟後失效，這項最可能不過；不過就代表 spec 規則 11 的前提不成立。）
3. agent 讀得到 `latest.json` 的絕對路徑。
4. 把排程時間設成兩分鐘後跑一次：清單成員與順序等於 `items`，其他清單沒變。
5. 換成 `status: "empty"` 的檔：清單清空並收到通知。換成 `trade_date` 是昨天、今天早於 `next_trade_date` 的檔：清單不動、沒有通知。

- [ ] **Step 1: 把 Pro 端設定（建立「新聞利多」清單、授權、建立排程、路徑填法）、上面的 prompt、進階版用法（對話裡請 AI 讀 `items` 與 `candidates` 的 `snippet`、`url` 做語意判斷）與實測清單寫進 `references/bullish_watchlist.md`**

- [ ] **Step 2: 驗證文件**

Run: `git grep -n -e "—" -e "─" -- references/bullish_watchlist.md`
Expected: 沒有輸出

- [ ] **Step 3: 全部離線測試回歸**

Run: `python -X utf8 tests/test_bullish.py`、`python -X utf8 tests/test_query_news_internals.py`、`python -X utf8 tests/test_sentiment.py`、`python -X utf8 tests/test_formatters.py`、`python -X utf8 tests/test_digest_render.py`
Expected: 全部 `0 fail`，結束碼 0

- [ ] **Step 4: Commit**

```bash
git add references/bullish_watchlist.md
git commit -m "利多清單的 Shioaji Pro 端設定指南與排程 prompt"
```

---

## 交接給使用者（實作完成後）

- 真正登記排程：使用者確認後執行 `powershell -ExecutionPolicy Bypass -File scripts\register_bullish_task.ps1`。
- 合併 `feat/bullish-watchlist` 回 `main`、推 GitHub：都要使用者同意。
- Task 6 的實測清單等上游發佈後再做。
