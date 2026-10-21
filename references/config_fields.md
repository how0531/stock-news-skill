# 設定欄位(config.json)

何時讀：要調整 `config.json`，或確認某個設定的預設值與實際作用時。

- 「預設」欄是 `config.example.json` 的值；鍵缺席時的程式內預設可能不同，表中有註明。
- 即時新聞主路徑 `main.aggregate()` 的來源與抓取量寫死在程式（見 [sources.md](sources.md)「調整來源」）。標「僅備援路徑」的鍵平常不生效，改了只會讓現有快取失效一次。
- CLI 用 `--individual-only`、`--no-sentiment` 控制，不讀 config 的 `individual_only`、`tag_sentiment`；這兩個鍵只在程式化呼叫沒傳參數時才讀。

| 欄位 | 意義 | 預設 |
|---|---|---|
| `metabase.scripts` | sinopac-metabase 的 scripts 路徑（借 `metabase_client`）。只有用 Metabase 才需要，範例的 `<USER>` 要換成實際使用者 | 佔位路徑 |
| `news.source` | `metabase`、`sanbao`（即時流加 cnyes 全站搜尋，歷史命名）、`both`。`both` 在 Metabase 不可用時自動退成 `sanbao`；確定沒有 Metabase 的人可以直接設 `sanbao`，連測試連線都省掉 | both |
| `news.lookback_days` | 預設回溯天數（codes 模式；keyword 模式實際窗口是 max(days, 10)） | 3 |
| `news.report_days` | codes 模式專用：標題含目標價、評等、法說等報告型字眼的新聞，改用這個天數當回溯窗。這是取代不是取大，`days` 大於它時報告型反而變短。keyword 模式不用 | 10 |
| `news.cache_ttl_sec` | TTL 快取秒數，涵蓋即時流（記憶體加磁碟 `out/.sanbao_cache.json`，跨進程共用，時間戳記在抓完之後，空結果不落磁碟）與 Metabase 關鍵字撈回（只在記憶體）。0 是全關，但之後每次查詢都重抓全量（1 到 2 分鐘）；要即時又要多查幾次，改小（例如 300），或在批次開頭呼叫 `clear_news_cache(disk=True)` | 900 |
| `news.kw_search_cnyes` | keyword 模式（source 含 sanbao 時）是否對每個關鍵字多打一次 cnyes 全站搜尋，API 只回命中處附近的短片段。範例沒列，未設等於開 | true |
| `news.per_stock_fetch` | codes 模式是否對每檔另做個股直取（cnyes 全站搜尋加 Yahoo 個股頁，來源標 `cnyes-search`、`yahoo-quote`），不受 `source` 控制。範例沒列，未設等於開 | true |
| `news.fetch_body` | 主路徑是否逐篇進內頁補全文。只認 config；`query_news(fetch_body=...)` 參數不會傳進主路徑，只控制 query_news 內的補內文步驟 | true |
| `news.body_max_chars` | 補內文、個股直取（cnyes-search）與 `news.py --out` 寫檔時的截斷字數。主路徑抓到的全文在回傳時不截斷（單則可達數千字），呼叫端要自己截 | 600 |
| `news.body_fetch_limit` | 補內文的網路抓取上限，每一輪各算一次（codes 模式的預抓與補抓各 40）；對象是 body 為空、有連結、來源不是 metabase、cnyes、anue 的項目 | 40 |
| `news.individual_only` | 程式化呼叫的 keyword 模式是否剔除泛大盤標題 | false |
| `news.tag_sentiment` | 程式化呼叫是否補 sentiment、confidence、events | true |
| `news.cnyes_categories` / `cnyes_pages` | cnyes 分類與頁數（僅備援路徑；鍵缺席時程式預設 tw_stock、headline 與 3 頁） | tw_stock、us_stock / 8 |
| `news.udn_feeds` / `udn_limit` | udn RSS 清單與每條上限（僅備援路徑；鍵缺席時程式預設為空） | 5591、5590、12017、5588、5592、5595 六條 / 30 |
| `news.ctee_pages` / `ctee_limit` | ctee 列表頁與上限（僅備援路徑；ctee 實際走 Google News 解碼，pages 已無作用） | livenews/feed / 60 |
| `news.anue_categories` / `anue_pages` | anue 取 cnyes API 的子站與頁數（僅備援路徑） | wd_stock、forex / 2 |
| `news.moneydj_pages` / `moneydj_limit` | MoneyDJ 列表頁與上限（僅備援路徑） | newsreallist a=mb010000 / 40 |
| `news.yahoo_feeds` / `yahoo_limit` | Yahoo RSS 與上限（僅備援路徑；鍵缺席時程式預設只有 tw-market、上限 40） | tw-market、tw.news.yahoo.com industry、tw.stock.yahoo.com industry 三條 / 60 |
