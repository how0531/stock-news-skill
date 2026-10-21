---
name: stock-news-skill
description: >-
  台股新聞查證與內文彙整，可依代號、關鍵字或當日全市場查新聞並讀內文。使用者問「有沒有 X 的新聞」「這消息是真的嗎」「某股最近有什麼消息」「某股為什麼漲／跌」「某事件有報導嗎」「這算利多還是利空」，或要整理某股某題材的新聞、今天（含盤前與隔夜美股）的新聞重點、今天哪些族群或個股在動，都用本 skill；沒說「新聞」，只要是在查證消息或找最新報導也要用。不用於：做成發給客戶的推播或快訊、0940 動能選股、區間聲量統計（改用 Sino-notify-skill）；完整盤前長文（sinotrade-morning-briefing）；原始數據、SQL、Excel（sinopac-metabase）；研報、口袋學堂（stock-report-skill）；即時報價、K 線、漲幅排行（sjxs-query）。
---

# 台股新聞查詢(stock-news-skill)

查台股新聞並讀內文，只轉述新聞事實，不給買賣建議。新聞有兩條來源：

- **即時流**：九家財經媒體的最新新聞（cnyes 鉅亨、udn 經濟日報、ctee 工商時報、中央社、自由財經、科技新報、ETtoday、MoneyDJ、Yahoo 奇摩股市），主路徑逐篇補全文。每個分類或 feed 只取最新 10 到 15 則（cnyes 每類 15、其他每條 feed 10），合計約 200 則，大約是最近一兩天。設定與 CLI 裡叫 `sanbao`（歷史命名）。
- **Metabase** `cmoney.證券市場新聞`：公司內部新聞庫，可回溯歷史，是用關鍵字查舊聞的主力。不是每個使用者都連得上，連不上時自動只用即時流，見「沒有 Metabase 時」。

每則另附規則層的 `sentiment`（利多／利空／中性）與 `events`（事件標籤），只用來快速分群。

## 前置需求

1. `config.json`：第一次使用先把 skill 根目錄的 `config.example.json` 複製成同目錄的 `config.json`（`news_core` 匯入時就讀，缺檔會直接報錯）。有 Metabase 的人把 `metabase.scripts` 裡的 `<USER>` 換成實際路徑，沒有的人不用改。
2. 套件：`pip install -r requirements.txt`。缺 requests、python-dateutil、pandas、beautifulsoup4、feedparser、tzdata 任一個時，即時新聞流會直接報錯並提示安裝（`--codes`、`--keyword` 只剩 Metabase 的結果）；缺 lxml 時 udn 內文全空、ctee 整家 0 則。
3. Metabase（選用）：隔壁 `sinopac-metabase` skill 的 `metabase_client`，加環境變數 `METABASE_USER`、`METABASE_PASS`、`METABASE_URL`（沒設時會從 Windows 使用者環境變數讀）。
4. 網路：要能連各家新聞網站，網域清單見 [references/sources.md](references/sources.md)。

## 步驟

### 1. 選查法

| 使用者給的 | 指令 | 結果 |
|---|---|---|
| 股票代號（數字） | `--codes=2330,2454 --days=3` | 近 N 日個股新聞（預設 3 天）。請傳代號；傳股名不會報錯，但只會被當成字串比對，股名請用 `--keyword` |
| 股名、題材、事件、傳聞 | `--keyword=希捷,產能極限` | 標題與內文全文比對，每則附命中片段。半形逗號分詞，預設任一命中，`--all` 改成全部命中；英文大小寫要對；回溯至少 10 天 |
| 沒指定，要今天全市場重點 | `--today` | 前一交易日 14:00 到現在的原料，見「今日盤後議題重點」 |
| 要可貼給同事的個股整理 | `--report=2330 --days=7 --format=md` | 情緒分布、事件統計、來源分布、Top 5、事件時序 |

只有股名時直接用 `--keyword=股名`，不用先換成代號。代號和題材都有時可以同一次帶 `--codes=... --keyword=...`，結果分別在 `by_code` 與 `keyword_hits`。國際財經題材加 `--intl`，只留國際類版面。

使用者要的是發給客戶的推播或快訊時，直接改用 Sino-notify-skill，不要先跑本 skill 再交棒（它內部會自己呼叫本 skill 拿新聞）。

### 2. 執行

```powershell
$env:PYTHONIOENCODING = 'utf-8'; chcp 65001 | Out-Null
$S = Join-Path $HOME '.claude\skills\stock-news-skill\scripts'
python -X utf8 "$S\news.py" --keyword=希捷,產能極限 --format=md --out=auto
python -X utf8 "$S\news.py" --codes=2408,8299 --days=7 --format=md --out=auto
python -X utf8 "$S\news.py" --keyword=非農,聯準會 --intl --format=md --out=auto
python -X utf8 "$S\news.py" --today --format=md
```

- 旗標只認 `--旗標=值` 的寫法，用空格隔開或拼錯都會被靜默忽略。全部旗標、輸出格式與更多範例見 [references/cli.md](references/cli.md)。
- 除了 `--today`，一律加 `--out=auto`。結果寫到自己的 `out/news_<時間戳>_<pid>.json`（stderr 的 `[輸出]` 那行有路徑），不會覆寫共用的 `out/news_result.json`；那份是 `--today` 的原料，也是每天 07:40 自動盤前信的輸入。
- 先讀 `--format=md` 的 stdout。要用程式讀 JSON 就讀 `--out` 的檔；Windows PowerShell 5.1 的 `|` 與 `>` 會弄壞中文，不要用管線接 JSON。
- 快取冷的時候，第一次查詢要 1 到 2 分鐘：先告訴使用者，工具逾時設 5 分鐘以上，或改用背景執行。抓完的即時流快取 15 分鐘（`cache_ttl_sec`），這段時間其他查詢與其他進程都直接沿用。平行查證多個題材可以直接同時跑：快取冷的時候只有一個進程會抓全量，其他進程會等它抓完再沿用（最多等 3 分鐘）。
- 盤中要最新資料：只查一兩次就先刪 `out/.sanbao_cache.json`；要連續查很多次就把 `cache_ttl_sec` 調小（例如 300）。不要設成 0，設 0 之後每次查詢都要重抓 1 到 2 分鐘。

### 3. 回報

- 先交代命中幾則、來源、時間範圍，每則附標題與連結。stderr 出現 `[cache] 沿用 N 秒前` 時，說明資料來自快取。
- 引用內文重點，先看命中片段。內文完整度依來源而異：即時流多半是全文；`--keyword` 的 Metabase 命中有全文但沒有連結（標明來源是 cmoney 新聞庫）；`cnyes-search` 只是命中處附近的短片段；`--codes` 的 Metabase 命中只有標題，沒有內文與連結。
- 方向看內文，不看標題。例：「希捷產能極限論」內文是 CEO 示警 AI 產能跟不上、建廠緩不濟急，市場解讀是利空。`sentiment` 與 `events` 只用來分群；`confidence` 是字面一面倒的程度，不是正確率，高分也可能整個反向。
- 查無時先排查再下結論：看 stderr 有沒有 warn、有沒有來源是 0 則；再放寬條件（加大 `--days`、換同義詞或英文名、拿掉 `--all` 與 `--individual-only`）。仍然沒有就回報「查無」，並列出查過的條件與時間窗。不杜撰。

## 沒有 Metabase 時

不是每個使用者都有 Metabase 權限或在內網。`--codes`、`--keyword`、`--report` 每個進程第一次查詢時會先測一次：帳密環境變數齊全、client 路徑存在、主機 3 秒內連得上（`--today` 不用 Metabase，不會測）。這個測試不驗帳密與資料庫權限：帳密錯或沒權限時照常跑，stderr 會出現 `get_stock_names warn`、`metabase news warn` 或 `metabase kw warn`，一樣要告訴使用者這次沒有 Metabase 的歷史回溯。想先確認這台連不連得上：

```powershell
python -X utf8 -c "import sys; sys.path.insert(0, r'$S'); import news_core as NC; print(NC.metabase_available())"
```

任何一項不通時：

- 預設的 `source=both` 自動改成只用即時流，stderr 印出「Metabase 無法使用(沒有權限、未設定或連不上),本次只用即時新聞流,沒有 Metabase 歷史回溯」。回報時告訴使用者「這次沒有 Metabase 的歷史回溯」，舊聞可能查不到。
- `--keyword` 與 `--today` 照常可用（`--today` 本來就不用 Metabase）。
- `--codes` 與 `--report` 改用離線股名比對：先查官方全市場清單 `data/stocks/tw_names.json`（上市加上櫃約 2,000 檔），再查策展字典 `data/stocks/tw_stocks.json`（含少數 ETF）。兩份都沒有的代號（多數 ETF、興櫃）只靠代號字串與出版商標的代號比對，個股直取改用代號搜尋。冷門股查無時，改用 `--keyword=股名` 再查一次。
- 確定用不到 Metabase 的使用者，可以把 `config.json` 的 `news.source` 設成 `sanbao`，或每次加 `--source=sanbao`，連測試連線都省掉。
- 程式化呼叫傳 `names={"2330": "台積電"}` 只省掉股名查詢；要完全不碰 Metabase，再加 `source="sanbao"`。

## 今日盤後議題重點(--today digest)

使用者沒指定代號或題材、要當日全市場彙整時用（「給我今天的新聞」「今天台股重點」「今天哪些族群或個股在動」）。產出是給人看的議題導向重點，不是大戶投推播（Sino-notify-skill），也不是盤前定稿（sinotrade-morning-briefing）。

1. 先讀 [references/today_digest.md](references/today_digest.md)：鐵律、議題 checklist、輸出範本、時間窗的限制。
2. `news.py --today --format=md` 取原料。時間窗是前一交易日 14:00 到現在，休市日依 `data/calendar/tw_holidays.json`。這個窗只是下界，每個分類或 feed 只取最新 10 到 15 則，高頻來源可能只涵蓋最近幾小時。stdout 和 `out/today_news_YYYYMMDD.md` 內容相同，約 200 則，被截斷時直接讀檔。07:30 到 08:30 之間不要手動跑（自動信正在用這兩個檔）。
3. 依議題分組、有就列出，只述事實不下結論。
4. 點名個股時，先從 `out/news_result.json` 的 `items[].body`（全文）找。原料裡沒有才補查，每檔最多一次（多檔可合併成 `--keyword=A,B`），一律加 `--out=auto`，不加會覆寫原料。補查的關鍵字模式回溯至少 10 天，要用 `time` 欄挑出今天的。

每天 07:40 的自動盤前信由 `scripts/premarket_digest.ps1` 產生，用的是它自己內嵌的規則，不讀 today_digest.md，改其中一邊不會影響另一邊。

## 每日利多清單(排程)

用途：每天產出「新聞利多」個股清單，給 Shioaji Pro 的自選股排程使用（skill 只產檔，不寫自選股）。
指令：`python -X utf8 scripts/news.py --bullish`，輸出 `out/bullish/latest.json`；休市日不產出，檔案維持上一個交易日的內容。
可隨時手動跑，不碰 `out/news_result.json`，不影響 07:40 盤前信；排程登記用 `scripts\register_bullish_task.ps1`。
前置、檔案欄位、判斷規則、Pro 端設定見 [references/bullish_watchlist.md](references/bullish_watchlist.md)。

## 程式化呼叫(供其他 skill)

```python
import sys; sys.path.insert(0, r"<stock-news-skill 路徑>\scripts")
import news_core as NC
res = NC.query_news(codes=["2408", "8299"], days=3)              # res["by_code"]
res = NC.query_news(codes=["2330"], names={"2330": "台積電"}, source="sanbao")  # 完全不碰 Metabase
res = NC.query_news(keyword="希捷,產能極限", match_all=True)      # res["keyword_hits"]
res = NC.query_news(keyword="非農,聯準會", intl=True)             # 只留國際類版面
```

API 契約（Sino-notify-skill 的 `scripts/core.py` `get_news()` 用 codes 加 names 呼叫、sinotrade-morning-briefing 的 `scripts/fetch_news.py` 用 codes 或 keyword 加 days 呼叫；新聞抓取碼只在本 skill 維護，改動前先確認下游）：

- `query_news()` 前 6 個參數順序固定為 `(codes, keyword, days, source, fetch_body, individual_only)`，全部預設 None；之後依序是 `tag_sentiment`、`names`、`match_all`、`intl`。新參數只能加在最後、預設 None，呼叫端一律用關鍵字傳參。`tests/test_query_news_api.py` 檢查簽名（要手動跑，部分 case 會連網）。
- 回傳 `{"by_code": {代號: [news]}, "keyword_hits": [news]}`。news 穩定欄位是 `time, title, source, url, summary, body`；`tag_sentiment=True`（預設）時另有 `sentiment`（`bullish`、`bearish`、`neutral`）、`confidence`（0 到 1）、`events`（list）。`keyword_hits` 另帶 `code`、`name`（只有 Metabase 命中有值）、`category`、`snippets`。
- 其他公開函式：`news_cfg()`（Sino-notify 讀它的 `source`）、`clear_news_cache(disk=False)`、`fetch_market_news(since="last_close", keep_codes=False)`、`resolve_stock_names(codes)`、`metabase_available()`。
- 各模式的細節（關鍵字模式回溯至少 10 天、報告型標題的 `report_days`、去重先後、`fetch_body` 參數只管補內文步驟）見 [references/cli.md](references/cli.md) 與 [references/config_fields.md](references/config_fields.md)。

## 需要時再讀

| 情境 | 讀這份 |
|---|---|
| 調 `config.json` 或確認預設值 | [references/config_fields.md](references/config_fields.md) |
| 解讀或質疑 sentiment、events 標籤 | [references/sentiment.md](references/sentiment.md) |
| 執行 `--today` 前 | [references/today_digest.md](references/today_digest.md) |
| 每日利多清單、Shioaji Pro 自選股排程 | [references/bullish_watchlist.md](references/bullish_watchlist.md) |
| 全部 CLI 旗標、輸出格式、`--report` 細節 | [references/cli.md](references/cli.md) |
| 來源清單、抓取流程、某家 0 則或被擋 | [references/sources.md](references/sources.md) |
| 快取、編碼、PowerShell、時區等踩雷紀錄 | [references/gotchas.md](references/gotchas.md) |
| 改程式、跑測試、檔案結構、07:40 自動信、年度維護 | [references/maintenance.md](references/maintenance.md) |
