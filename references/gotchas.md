# 踩雷紀錄

何時讀：遇到快取、編碼、PowerShell、時區、內文抽不到、輸出被污染、沒有 Metabase 等問題時。來源被擋或 0 則見 [sources.md](sources.md)。

## 網路與內文

- 公司網路 TLS 攔截：曾經出現 requests 加 certifi 報 CERTIFICATE_VERIFY_FAILED。現況：主路徑採集器走 `common.request_get`（requests 預設驗證），ctee 解碼也用 requests，只有 ctee 的 Google News 清單走 feedparser。各來源的失敗都在自己內部吞掉，憑證錯誤時不會退回備援路徑，只會各來源 0 則（stderr 各家印抓取失敗），先跑 `healthcheck.py` 確認。`news_providers._get`（備援路徑與補內文共用）的「SSL 失敗退回未驗證連線」攔的是 `ssl.SSLError`，但 urllib 丟的是 `URLError`，實際不會生效；要修得同時處理 `common.request_get` 與 `_get`。
- cnyes 內文是 HTML 實體編碼：先 `html.unescape` 再交給 BeautifulSoup。
- 內文容器第一個是空殼（2026-06-28）：有些站（例如自由財經）第一個 `div.text` 是空的佔位，真正內文在第二個同名容器。`common.parse_article_fields` 改成掃同選擇器的所有匹配、取段落文字最多的那個（`python common.py` 有離線自測）。新增來源抓不到內文時先查這個，再查是不是缺 lxml（缺了 udn 內文會全空、ctee 整家 0 則）。
- 缺套件（2026-10-21 改）：以前 `import main` 失敗會悄悄退回舊版六家爬蟲，少了代號標記與版面欄位又不易發現；現在刪掉備援，直接報錯並提示 `pip install -r requirements.txt`。

## 快取

- 時間戳要記在抓完之後（2026-10-09）：舊版記在抓取開始，但全量抓取要一兩分鐘、遠超當時的 TTL 120 秒，快取一出生就過期。現在抓完才記，加上磁碟層 `out/.sanbao_cache.json`（暫存檔加 `os.replace` 原子寫入，跨 CLI 進程共用），TTL 改 900 秒。
- 空結果不落磁碟：網路瞬斷時不會讓 15 分鐘內的其他進程（含 07:40 自動信）都拿到 0 則。
- 被 monkeypatch 的假抓取不讀寫磁碟（`_is_real_fetch`），避免單元測試的假新聞流進自動信。
- `clear_news_cache()` 只清記憶體（單元測試用）；`clear_news_cache(disk=True)` 連磁碟一起清。
- 跨進程抓取鎖（2026-10-21）：冷快取時用 `out/.sanbao_fetch.lock`（`os.O_EXCL` 建檔）只讓一個進程抓全量，其他進程每秒檢查磁碟快取，抓完就沿用；等超過 3 分鐘、或鎖檔超過 3 分鐘沒更新（持有者當掉）就自己抓。以前沒有鎖，同時起 3 個平行查證會各抓一次全量。

## 輸出與編碼

- stdout 污染（2026-10-09）：採集器的「抓取失敗」原本印在 stdout，會破壞 `--format=json`。`main.aggregate` 與 cnyes、udn、ctee、RSS 採集器已全部改走 stderr（`twse_announce.py` 仍印 stdout，但不在 news.py 的路徑上）。內文抽取失敗是靜默回空字串，不印訊息。
- PowerShell 5.1：`2>&1 | Select -First N` 會把 stderr 混進 stdout，觸發 NativeCommandError 加 exit 255，不是 Python 真的出錯；長輸出測試用 `1> stdout.txt 2> stderr.txt` 分開。`|` 會插入 BOM 並把中文變成 `?`，`>` 會存成 UTF-16，JSON 請讀 `--out` 的檔。

## 時間

- Metabase 新聞時間是假 UTC（2026-10-09）：`發布日期時間` 回 `2026-10-09T18:21:19Z`，其實是台北牆鐘。直接當 UTC 解析會偏 8 小時（排序永遠浮到最前、近 N 日過濾偏移），`news_core._mb_time()` 去掉 Z、補 +08:00。
- 連假後的前一交易日（2026-10-09）：`_prev_business_day` 原本只跳週末，10/12（一）會算成 10/09（補假），整段 10/08 盤後新聞漏掉。現在用 `storage._is_closed`（讀 `tw_holidays.json`），該檔每年要更新，見 [maintenance.md](maintenance.md)。
- 本機時區：now 與 cutoff 一律用台北時區（`common.TAIPEI`），不依賴本機設定（Git Bash 設了 TZ 時 `astimezone()` 會偏）。

## Metabase

- 子程序常讀不到 Windows 使用者層級的環境變數：`METABASE_*` 沒在環境裡時，`news_core` 會用 PowerShell 回讀注入。
- 沒有 Metabase 時代號查詢曾經靜默回 0 則（2026-10-21 修）：股名只從 Metabase 來，失敗時個股直取與即時流比對整批跳過，看起來像查無新聞。現在 `metabase_available()` 每個進程先測一次，不通就退成只用即時流，股名改用 `tw_stocks.json`、`tw_names.json` 與代號比對。
- 全市場股名清單漏了上櫃股（2026-10-21 修）：`build_stock_dict.fetch_tw_universe` 只認中文欄位，但櫃買中心 OpenAPI 是英文欄位（`SecuritiesCompanyCode`、`CompanyAbbreviation`），893 檔上櫃股全被跳過；證交所簡稱的「*」標記（例如 國巨*）也要去掉才比得到。

## 查詢判讀

- 關鍵字查方向一定看內文：標題常誤導，尤其 ctee、moneydj 的列表常沒有內文。keyword 模式已內建補內文、依標題去重、近 N 日過濾、時間倒序與 sentiment 標記，呼叫端不必自己處理。

## 效能

- 主路徑全量：2026-10-09 實測 111 秒（原序列版 305 秒）。2026-10-21 量測瓶頸：單篇下載 0.3 到 0.7 秒、解析 0.01 到 0.05 秒，ltn 單獨跑 7 秒，九家一起跑卻要 51 到 62 秒，代表整體同時連線數受限（推測是公司網路的代理或 TLS 檢查）。試過每家內部再開 3 條執行緒，全量反而從 111 秒變 119 秒、cnyes 從 35 秒被拖到 78 秒，已撤回。要再快只能減少請求數（只抓新文章的增量收集），不是加執行緒。
- Metabase 關鍵字搜尋把關鍵字推進 SQL（`positionUTF8` 比對標題加內文），實測不到 0.1 秒；撈回的列有進程內 TTL 快取（key 是 days、keywords、match_all）。
- 主路徑在 `fetch_body=true`（預設）時已逐篇抓好全文，抓不到才退回摘要。查詢階段只補 body 仍是空的項目：codes 模式在比對前先預抓標題含產業熱詞的候選文，比對後再補命中項；keyword 模式只補命中項。metabase、cnyes、anue 不抓；同一輪內同一網址只抓一次，每輪上限 `body_fetch_limit`。
