# 維護手冊

何時讀：改程式、跑測試、找檔案、處理 07:40 自動盤前信、做年度維護時。一般查新聞不需要讀。

## 檔案

| 路徑 | 用途 |
|---|---|
| `SKILL.md` | 使用說明，每次觸發都讀 |
| `references/` | 細節，需要時讀（索引在 SKILL.md「需要時再讀」） |
| `config.example.json` | 設定範本，複製成 `config.json` 使用（`config.json` 不進版控） |
| `requirements.txt` | 第三方套件 |
| `NEWS_COVERAGE_PLAN.md` | 2026-06 的個股新聞覆蓋計畫（歷史文件，A1 到 A3、B1 已實作） |
| `evals/` | 觸發邊界題（`trigger_eval.json`）與任務評測題（`evals.json`），執行期不讀 |
| `scripts/news.py` | CLI |
| `scripts/news_core.py` | `query_news()` 公開 API、Metabase 連線與可用性偵測、股名解析、TTL 快取、`fetch_market_news()` |
| `scripts/news_providers.py` | `fetch_sanbao()`（呼叫主路徑，失敗直接報錯）、補內文（6 條並行）、個股直取、即時流比對、離線股名 |
| `scripts/news_sentiment.py` | 規則層情緒與事件，純標準庫；直接執行會跑自我測試 |
| `scripts/news_formatters.py` | console、md、json 排版，`--report`，digest 排版 |
| `scripts/stock_mentions.py` | 全市場股名反查：一則新聞點名了哪些個股、在標題還是只在內文（讀 `tw_names.json`、`tw_stocks.json`，不連網） |
| `scripts/news_bullish.py` | 利多清單：計票、混合排除、排序、組檔、寫 `out/bullish/`，`news.py --bullish` 的實作；說明見 [bullish_watchlist.md](bullish_watchlist.md) |
| `scripts/register_bullish_task.ps1` | 登記或移除 Windows 工作排程 `stock-news-bullish`（週一到週五 07:50），檔案必須存成 UTF-8 with BOM |
| `scripts/main.py` | 主路徑 `aggregate()`：九家並行加跨來源去重；直接執行才會寫 `data/raw/` |
| `scripts/cnyes.py`、`udn.py`、`ctee.py`、`rss_sources.py`、`chinatimes.py` | 各家採集器（中時已移出主路徑） |
| `scripts/common.py` | UA、時間正規化、內文抽取、request |
| `scripts/storage.py` | PIT（依資料可得時間保存）儲存層：raw、processed、factors，休市日判斷 `_is_closed` |
| `scripts/process_day.py` | 日終把 raw JSON 與盤中 stream 整理成 processed parquet |
| `scripts/watch_intraday.py` | 盤中監看，寫 `data/stream/YYYY-MM-DD.jsonl`（每行欄位見 `build_event()`；2026-07-03 後未執行） |
| `scripts/twse_announce.py` | 證交所與櫃買中心當日重大訊息 |
| `scripts/healthcheck.py` | 一條指令探測所有來源 |
| `scripts/build_stock_dict.py` | 重建股票字典；`--names` 只更新全市場代號對簡稱 `tw_names.json` |
| `scripts/fetch_by_date.py`、`backfill_cnyes.py`、`backfill_udn.py`、`backfill_ctee.py` | 指定日抓取與歷史回補 |
| `scripts/site_map.py` | `data/site_maps/` 的載入、驗證與索引 |
| `scripts/news_raw_ctee.py` | 把 ctee 新聞寫成 g-brain（外部管線）的 news-raw schema-v1 JSON |
| `scripts/premarket_digest.ps1` 等七支 | 07:40 自動盤前信管線，見下方 |
| `data/stocks/` | `tw_stocks.json`（策展約 160 檔，含別名）、`tw_names.json`（上市加上櫃約 2,000 檔代號對簡稱）、`us_stocks.json`、`jp_stocks.json` |
| `data/calendar/tw_holidays.json` | 台股休市日（證交所官方資料），見「年度維護」 |
| `scripts/update_holidays.py` | 從證交所網站休市表（www.twse.com.tw/rwd）更新休市表 |
| `data/site_maps/` | 各來源版型與驗證狀態 |
| `data/raw/`、`stream/`、`state/`、`processed/`、`factors/` | 採集層產物（新聞全文與狀態），已列入 `.gitignore` |
| `out/` | 查詢結果、快取、自動信產物（已在 `.gitignore`） |

## 測試

| 指令 | 範圍 | 連網 | 備註 |
|---|---|---|---|
| `python tests/test_query_news_internals.py` | 去重、排序、時間過濾、AND、snippets、intl、快取、前一交易日、沒有 Metabase 的代號查詢、離線股名 | 否 | 2026-10-21 共 47 項 |
| `python tests/test_sentiment.py` | classify 結構契約、強訊號方向、事件抽取 | 否 | 25 項 |
| `python tests/test_formatters.py` | 排版、`build_report`、digest、snippets | 否 | 79 項 |
| `python tests/test_digest_render.py` | 盤前信 HTML renderer | 否 | 24 項，樣本在 `tests/fixtures/digest_sample.md` |
| `python tests/test_bullish.py` | 股名反查、計票、排序、組檔、寫檔、--bullish | 否 | 2026-10-21 共 51 項；要有 `config.json`（`news_core` 匯入時讀），輸出寫暫存目錄 |
| `python scripts/news_sentiment.py` | 詞庫自我測試 | 否 | 37 例 |
| `python tests/test_query_news_api.py` | 簽名（前 6 參數順序、預設 None）與回傳結構 | 部分會 | 結構檢查會連 Metabase 與即時流 |
| `python tests/test_cli_smoke.py` | CLI 黑箱 7 組 | 是 | 每組會刪除並重寫 `out/news_result.json`，07:30 到 08:30 不要跑 |
| `python tests/test_health.py` | cnyes、udn、ctee 端點；`METABASE_URL` 有設才測 Metabase | 是 | |
| `python scripts/healthcheck.py` | 主路徑各來源實抓（每分類或 feed 取 3 則，不抓內文），任一來源 0 則即 FAIL；announce 抓當日全量；中時要點名才測 | 是 | |
| `pytest scripts/test_collect.py` | 採集層 | 否 | 需要 pytest；檔內沒有 `__main__`，直接用 python 執行不會跑任何測試 |
| `python scripts/test_storage.py` | PIT 儲存層 | 否 | 會把測試資料寫進真實的 `data/` 目錄而且不清理 |

`tests/run_all.ps1` 跑 8 項（上表的 test_health、healthcheck、test_query_news_api、test_cli_smoke、test_sentiment、test_formatters、test_query_news_internals、test_digest_render），含連網測試，也會洗掉 `out/news_result.json`。改邏輯後先跑四個離線測試做快速回歸。測試要設 `$env:PYTHONIOENCODING='utf-8'`；PowerShell 5.1 不要用 `2>&1`（會誤報 NativeCommandError），stdout 與 stderr 分開導向。

## 07:40 自動盤前信

Windows 工作排程：`premarket-news-digest` 週一到週五 07:40 跑 `scripts/premarket_digest.ps1`，`premarket-news-watchdog` 08:20 跑 `scripts/digest_watchdog.ps1`。排程註冊指令寫在兩支腳本的檔頭。

1. `news.py --today --format=md`，產生 `out/news_result.json` 與 `out/today_news_YYYYMMDD.md`；檢查則數與各來源是否 0 則（0 則記黃燈，名單寫死九個 source id）。
2. `build_material.py` 把原料編號成 `out/premarket_material_YYYYMMDD.md`（每則一行 `[#001] 時間 (來源) [標題](網址)`，財經標題多一行內文）。
3. `kpi_fetch.py` 從 Metabase 直查大盤數字（指數、成交金額、三大法人、融資券、期貨未平倉），寫 `out/kpi_YYYYMMDD.md`；exit 0 完整、2 部分、1 失敗，最新資料日落後超過 4 天就不輸出。
4. `claude -p`（opus 優先、sonnet 備援）依腳本內嵌的 prompt 寫成 `out/premarket_digest_YYYYMMDD.md`；被攔截的輸出存成 `out/rejected_*.txt`。
5. `render_digest_html.py` 轉成 HTML 並回填 `[#編號]` 的連結；`send_digest.ps1` 用 Outlook 寄出（單獨執行預設只建草稿，`-Send` 才寄），`send_teams.py` 發 Teams。
6. 寫 `out/heartbeat_YYYYMMDD.json`；watchdog 08:20 檢查心跳，涵蓋排程沒觸發、腳本語法錯、機器沒開這類主管線自己報不出來的狀況。

注意：

- 內嵌 prompt 的規則和 `references/today_digest.md` 不同（固定區塊、有數量上限、例行月營收不列、不用紅綠圖示、每則標 `[#編號]`），改其中一邊不會影響另一邊。
- 休市日自動略過（2026-10-21 起）：主管線與 watchdog 開頭都用 `storage._is_closed` 判斷，休市就不抓、不寄、不檢查心跳；判斷失敗則照常執行。休市日要強制產出，手動跑 `premarket_digest.ps1 -Force`。
- `premarket_digest.ps1`、`send_digest.ps1`、`digest_watchdog.ps1` 含公司 email，已列入 `.gitignore`，不在公開的 GitHub repo 裡，只存在本機。
- 收件者與告警地址寫死在 `send_digest.ps1`、`premarket_digest.ps1`、`digest_watchdog.ps1`，改收件者要改三支；不要把內容貼到對話或文件裡。
- 自動信依賴 `out/news_result.json`，所以互動查詢除了 `--today` 一律加 `--out=auto`。

## 年度維護

- `data/calendar/tw_holidays.json` 的資料來源是證交所網站休市表（`www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule?response=json&date=YYYY0101`，可以指定年度，2021 年起有資料），由 `python scripts/update_holidays.py [年度…] [--force]` 更新，預設抓今年與明年。
  - 分類規則：名稱含「交易日」的列（開始交易日、最後交易日）照常開盤，但名稱或說明寫明「M月D日市場無交易」的算休市（2021、2022 年春節前只辦結算的日子也叫「最後交易日」）。其餘列都算休市。
  - 安全規則：任何一列日期格式不對或欄位殘缺就整批放棄；官方資料會移除既有日期時拒絕寫入（確認後加 `--force`）；內容沒變就不寫檔；檔案壞掉時直接報錯，不會自動重建（以免手動補的 `_adhoc` 遺失）；帶 BOM 的檔讀得懂，下次寫入時改存成無 BOM；寫入有跨進程鎖，讀寫都有重試；`_adhoc` 單一日期寫錯時 storage 只略過那一項並在 stderr 點名；`_meta.verified_years` 記錄哪些年度對過官方資料。
- 颱風等臨時停市不在證交所休市表裡，要手動加在檔內 `_adhoc`（例如 `{"2026": ["2026-07-10"]}`），再跑一次 `update_holidays.py` 併進年度清單（`render_premarket.py` 只讀年度清單）。更新永遠不會移除 `_adhoc` 的日子，格式錯（不是 `{年: [YYYY-MM-DD]}`）會拒絕寫入。2026 年已加 7/10 巴威颱風停市；若要回填 2023、2024 年，對照證交所成交資料還有 2023-08-03、2024-07-24、07-25、10-02、10-03、10-31 這幾天颱風停市要加進 `_adhoc`。
- 缺少今年或明年時，`storage._is_closed` 每個進程會自動更新一次；證交所還沒公布（例如 12 月時的次年）就在 stderr 印 `[holiday] 休市表沒有 YYYY 年`，該年只跳週末與元旦。休市檔讀不到時 `news_core` 會印 `[holiday] 休市判斷失敗,只跳週末`。證交所公布次年行事曆後跑一次 `update_holidays.py` 最保險。
- 依賴這份檔案的還有 `sinotrade-morning-briefing/scripts/render_premarket.py`（推下一交易日），格式維持 `{"YYYY": [日期…]}`。
- 2026-10-21 更新前漏列 2/12、2/13、7/10、9/28、10/26、12/25 六個平日休市日，9/29 的盤前窗曾因此從 9/28 14:00 起算（正確是 9/24 14:00）。
- `data/stocks/tw_names.json` 偶爾重抓：`python scripts/build_stock_dict.py --names`（需能連 openapi.twse.com.tw 與 www.tpex.org.tw）。

## 已知問題（2026-10-21 審計，尚未修）

| 位置 | 問題 |
|---|---|
| `news_sentiment.py` 否定詞與轉折詞 | 已排除未來、非農、無人機、不動產、免稅、不但、卻步等常見詞（2026-10-21）；其他含「未、非、無、不、但、卻」的詞仍可能誤觸，加權範圍仍到文末 |
| `news_sentiment.py` `_scan_with_pos` | 命中詞極密集的長文近似平方成長；一般新聞接近線性，`--today` 目前不是瓶頸 |
| `news_core.py` `query_news(fetch_body=...)` | 參數不會傳進主路徑，`fetch_body=False` 不會省掉逐篇抓內文 |
| `news_core.py` `per_stock_fetch` | `source=metabase` 時仍會打 cnyes 搜尋與 Yahoo 個股頁 |
| `news_providers.py` Yahoo 個股頁與無時間項目 | `time` 補成查詢當下，看起來像剛發布 |
| `news_core.py` `_sql_in_list` | 只跳脫單引號、沒處理反斜線（ClickHouse），呼叫端目前都是內部，風險低 |
| `news_core.py` `query_news(codes="2330")` | 字串會被拆成單一字元，codes 必須傳 list |
| `news_core.py` `match_all` | cnyes 搜尋腿只有短片段，AND 時那條腿幾乎失效 |
| `news_providers.py` `_get` | SSL 失敗退回未驗證連線的設計攔的是 `ssl.SSLError`，但 urllib 丟的是 `URLError`，實際不會生效 |
| `news_core.py` 匯入 | 直接讀 `config.json`，沒有退回 `config.example.json` |
| `twse_announce.py:87` | 抓取失敗訊息印到 stdout（目前不在 `news.py` 路徑上） |
| `scripts/test_collect.py` | 匯入 `ctee._url_date_iso`，但這個函式已不在 `ctee.py`，整支測試無法載入（2026-10-21 以前就壞了） |
| `scripts/test_storage.py` | 會把測試資料寫進真實 `data/` 而且不清理（`test_cli_smoke.py` 已改用 `--out=auto`，不再覆寫 `out/news_result.json`） |
| 利多清單（`news_bullish.py`）新聞覆蓋 | 每個來源只抓最新 10 到 15 則，前一天傍晚的新聞可能被擠掉，清單會漏股、混合排除也可能漏判。第一版接受，之後做增量收集再補 |
| `stock_mentions.py` 股名比對 | `-KY` 股名在新聞裡省略連字號（寫成「亞德客」而不是「亞德客-KY」）時比不到，只能靠代號命中 |
| Sino-notify-skill `references/news_api.md` | news 欄位寫成含 `tag_sentiment`、來源寫六家，已落後本 skill 的 API 契約 |
