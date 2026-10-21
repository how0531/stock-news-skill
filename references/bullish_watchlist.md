# 每日利多清單(--bullish)

何時讀：要產出或排程「新聞利多」個股清單、解讀 `out/bullish/latest.json`、這份清單漏股或錯股要排查，或要設定 Shioaji Pro 的自選股排程時。一般查新聞不需要讀。

## 什麼時候用

- 想每天自動拿到一份「前一交易日 14:00 到現在，新聞偏利多的個股」清單，給 Shioaji Pro 的自選股使用。
- skill 只產出檔案，不寫自選股、不下單、不碰券商帳號；把清單搬進自選股是 Shioaji Pro 的 AI agent 的工作（設定見「Shioaji Pro 端設定」）。
- 只看新聞，不看股價與量能，不限檔數。清單是規則算出來的新聞分群，不是買賣建議。
- 要查證單一股票或題材的新聞，改用 [SKILL.md](../SKILL.md) 的 `--codes`、`--keyword`；要做客戶推播，改用 Sino-notify-skill。

## 執行與排程

前置（自己和同事都一樣）：

1. 安裝 Python，在 skill 根目錄執行 `pip install -r requirements.txt`。
2. 把 `config.example.json` 複製成同目錄的 `config.json`。`news_core` 匯入時就讀，缺檔會直接報錯；`tests/test_bullish.py` 也要有這個檔才跑得起來。
3. 不需要 Metabase，`--bullish` 只用即時新聞流。

手動執行（在 skill 根目錄）：

```powershell
python -X utf8 scripts\news.py --bullish
```

- 進度走 stderr：`[輸出] <檔案路徑>` 與 `[利多清單] <日期> <status> <N> 檔`，stdout 沒有輸出。
- 結束碼：有清單、清單為空、休市日都是 0；產出 error 檔是 1。
- 休市日（週末與 `data/calendar/tw_holidays.json` 的日子）不寫檔，stderr 印「今天休市,不產出」，`latest.json` 維持上一個交易日的內容。
- 不讀也不寫 `out/news_result.json`，可以隨時手動跑，不影響 07:40 盤前信。

登記與移除 Windows 工作排程（直接在 PowerShell 或命令提示字元執行）：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\register_bullish_task.ps1 -DryRun    # 只印設定，不登記
powershell -ExecutionPolicy Bypass -File scripts\register_bullish_task.ps1            # 登記
powershell -ExecutionPolicy Bypass -File scripts\register_bullish_task.ps1 -At 08:10   # 改時間，重跑會覆蓋同名工作
powershell -ExecutionPolicy Bypass -File scripts\register_bullish_task.ps1 -Remove     # 移除
```

| 項目 | 設定 |
|---|---|
| 工作名稱 | `stock-news-bullish` |
| 觸發 | 週一到週五 07:50（`-At` 可改，格式 `HH:mm`）。休市日也會觸發，由 `--bullish` 自己判斷後結束 |
| 動作 | `python -X utf8 "<scripts 目錄>\news.py" --bullish`。`python` 是登記當下 `(Get-Command python).Source` 解出的完整路徑，換了 Python 要重跑一次登記 |
| 工作目錄 | skill 根目錄 |
| 帳號 | 目前使用者，只在登入時執行，不存密碼 |
| 設定 | 錯過時間會在開機後補跑（`StartWhenAvailable`）、執行上限 15 分鐘、電池供電也執行 |
| 路徑 | 全部由腳本位置推算，不寫死使用者名稱或內部路徑 |

和 07:40 盤前信共用快取：盤前信的 `--today` 抓完的即時流會留在 `out/.sanbao_cache.json`（15 分鐘，跨進程共用，裡面有出版商標的股票代號），07:50 的 `--bullish` 直接沿用，不重抓，用的是同一份新聞。盤前信還在抓時，跨進程抓取鎖會讓 `--bullish` 等它抓完再沿用（最多 3 分鐘）。沒有盤前信的同事，`--bullish` 自己抓一次，約 2 分鐘。`-At` 離盤前信超過約 15 分鐘就等於重抓一次，結果一樣，只是慢一點。

## 輸出檔案(schema_version 1)

位置：`out/bullish/bullish_YYYYMMDD.json`（每個交易日一個）與 `out/bullish/latest.json`（同內容，永遠是最近一次產出）。`out/` 在 `.gitignore`。寫入先寫暫存檔再 `os.replace`，讀的人不會讀到寫一半的檔；UTF-8，縮排 2。

頂層欄位：

| 欄位 | 說明 |
|---|---|
| `schema_version` | 整數，目前是 1 |
| `status` | `ok`（`items` 非空）、`empty`（成功但沒有符合的股票）、`error`（失敗，另有 `error` 欄） |
| `trade_date` | 產出當天（台北時間）`YYYY-MM-DD` |
| `next_trade_date` | `trade_date` 之後的下一個交易日。Pro 端靠它分辨「今天休市」與「今天該有清單卻沒有」。error 檔算不出時是 `null` |
| `generated_at` | 產出時間，帶 `+08:00` |
| `window` | `{"from", "to"}`：`from` 是前一交易日 14:00，`to` 是產出時間。error 檔算不出時是 `null` |
| `method` | 固定 `"rule"` |
| `rule` | 計票門檻：`{"confidence_min": 0.5, "title_weight": 3, "body_weight": 1, "body_max_stocks_per_news": 3}` |
| `items` | 簡易版清單，順序就是優先順序，Pro 排程直接套用 |
| `excluded` | 被排除的股票，`{"code", "name", "why"}`，`why` 目前只有 `"mixed"` |
| `candidates` | 給進階版讀：被提到但沒進 `items` 的股票 |
| `error` | 只在 `status` 是 `error` 時才有，錯誤說明字串 |

`status: error` 的情況：沒抓到任何新聞、新聞沒有情緒標籤（`news_sentiment` 載入失敗）、或執行中丟了例外。error 檔的 `items`、`excluded`、`candidates` 都是空陣列，結束碼 1。Pro 端靠 `status` 分辨「沒有利多」（`empty`）和「出錯」（`error`）。

`items[]`：

| 欄位 | 說明 |
|---|---|
| `code`、`name` | 股票代號與簡稱 |
| `score` | `title_votes` × 3 + `body_votes` × 1 |
| `title_votes` | 標題點名的利多票數 |
| `body_votes` | 只在內文點名的利多票數 |
| `reason` | 程式組的字串，不是 AI 寫的，例如「標題點名 2 則利多，內文提到 1 則利多（訂單、法說）」。次數為 0 的部分省略，括號內是利多那幾則新聞的事件標籤，最多 3 個 |
| `evidence` | 這檔所有被點名的新聞，由新到舊，欄位見下表 |

`candidates[]` 是 `{"code", "name", "evidence"}`，包含三種股票：沒有任何票的（中性或信心不足）、只有利空票的、被 `excluded` 排除的混合股。排序：`evidence` 則數多到少，同則數依最新一則新聞時間由新到舊，再依代號。

`evidence[]`（`items` 與 `candidates` 共用）：

| 欄位 | 說明 |
|---|---|
| `title`、`url`、`time`、`source` | 新聞標題、連結、發布時間（ISO 字串，可能是空字串）、來源 id |
| `match` | `"title"`（標題點名）或 `"body"`（只在內文或出版商標的代號） |
| `sentiment`、`confidence` | 規則層情緒 `bullish`、`bearish`、`neutral` 與信心 0 到 1，見 [sentiment.md](sentiment.md) |
| `events` | 事件標籤 list |
| `counted` | 這則有沒有資格計票。`match` 是 `"body"` 且該則新聞內文點名超過 3 檔時是 `false`（多半是盤勢彙整），其餘是 `true`。`true` 不代表有一票，還要看情緒與信心 |
| `snippet` | 在內文（沒有內文用摘要）找這檔的股名或代號，取位置最前面的一段，前後各 60 字（有截斷的一端加 `…`，HTML 標籤已去掉）。內文沒提到時是空字串（例如只靠出版商標的代號命中） |

## 判斷規則

程式在 `scripts/stock_mentions.py`（點名）與 `scripts/news_bullish.py`（計票、排序、組檔）。全部是規則，不呼叫 AI。

新聞原料：`fetch_market_news(since="last_close", keep_codes=True)`，前一交易日 14:00 到現在的九家即時流，約 200 則，每則已標 `sentiment`、`confidence`、`events`，並保留出版商標的 `stock_codes`。

一則新聞點名了哪些股票：

- 字典來自 `data/stocks/tw_names.json`（上市加上櫃約 2,000 檔簡稱）與 `tw_stocks.json`（策展別名）。
- 標題級（`match: "title"`）：股名、單一公司的別名或代號出現在標題。
- 內文級（`match: "body"`）：只出現在內文，或只出現在出版商標的 `stock_codes`。同一檔標題與內文都有時算標題級。
- 最長匹配優先：命中「南亞科」就不再算「南亞」。
- 主題詞別名（DRAM、AI伺服器、ABF載板、MLCC、散熱、IC設計等）是產業名詞，不算點名。
- 常用詞股名（世界、全新、中華、光明、幸福、泰山等）不當股名比對，這些股票只能靠代號命中。別名同時屬於兩檔以上、或是別檔的正式簡稱時，別名也丟掉。
- 代號是 4 到 6 碼數字且是已知代號。前面不能緊接英數字、`.`、`/`、`$`；後面不能緊接英數字、`.`、`%`、點、元、億、萬、張，也不能接年、月、日（中間隔空白也不行），所以「2027年」不是 2027 大成鋼。網址內的數字先剝除。
- 英數字股名（例如 M31、TSMC）前後不能緊鄰英數字，區分大小寫。

一則新聞的票：

- `sentiment` 是 `bullish` 且 `confidence` 達 0.5 算一張利多票；`bearish` 且達 0.5 算一張利空票；中性、信心不足、缺欄位都不計。
- 這一票同時給這則新聞點名的每一檔。
- 一則新聞內文級點名超過 3 檔時，這則的內文級都不計票（`counted: false`），標題級照計。

彙整到個股：

- 有任何利空票的股票排除，記在 `excluded`（`why: "mixed"`），同一檔同時有利多與利空新聞不列入。
- 沒有利空票、至少一張利多票的股票進 `items`。
- 沒有利多票的股票（含只有利空票的）只出現在 `candidates`。

`items` 排序：有標題級利多票的一律排在只有內文級的前面；同一組內依 `score` 由高到低；同分依最新一則新聞時間由新到舊；再同依代號由小到大。

日期：`trade_date` 是執行當天的台北日期；休市日不產出。

## Shioaji Pro 端設定

前提：上游 `feat/340-agent-watchlist-tools`（讓 AI agent 操作自選股的工具）合併並發佈之後才能設定。截至 2026-10-21 還沒合併，之後的狀態未驗證。用到的工具名稱取自該分支的 `MCP_TOOLS.md`：`list_watchlists`、`get_watchlist`、`create_watchlist`、`add_to_watchlist`、`remove_from_watchlist`、`reorder_watchlist`、`search_products`、`create_task`、`notify_user`。各工具的參數名稱公開文件沒寫，以 App 的 MCP server 公告的 schema 為準。

分工：skill 在 07:50 產出 `latest.json`，Pro 的每日排程任務在 08:00 讀它，把專用自選股清單「新聞利多」整份替換成檔案裡的內容。

設定步驟（只做一次）：

1. skill 端先備妥：能手動產出 `out/bullish/latest.json`，並登記好 07:50 的工作排程（見「執行與排程」）。
2. 專用清單：名稱固定為「新聞利多」。可以自己先在 App 建，也可以讓排程第一次執行時用 `create_watchlist` 建。之後一律用它的 `watchlist_id` 操作，不要改名（改名會換 id）。AI 只准動這一份，其他清單一律不碰。
3. 授權：在 App 把 `ui.control`（自選股工具需要）與 `task.manage`（排程工具需要）設成永久允許。兩個權限各自獨立、預設拒絕。注意上游公開文件找不到「永久允許」的說法，`AGENT_HARNESS_CONTRACT.md` 還寫授權重啟後失效，授權能不能撐過重啟要靠下面「實測清單」第 2 項驗證。
4. 建排程：在 App 建一個每天 08:00 的排程任務（晚於 skill 的 07:50），內容貼下一節的 prompt。可以請 AI 用 `create_task` 建，或用 App 的排程介面（介面細節以實際版本為準，未驗證）。
5. 路徑填法：prompt 第 1 步的 `<latest.json 的絕對路徑>` 換成實際的完整路徑。skill 放在預設位置時是 `C:\Users\<使用者名稱>\.claude\skills\stock-news-skill\out\bullish\latest.json`（也就是 `~/.claude/skills/stock-news-skill/out/bullish/latest.json` 展開後的樣子）；放在別處就填別處。寫完整路徑，不要留 `~` 或環境變數，agent 不一定會展開。
6. 執行條件：App 要開著（可縮到系統匣）排程才會跑；每次排程消耗一次 AI 額度；provider 要選連得上的（網路連不到 OpenAI 時 Codex 跑不起來，改用 Claude Code 或 Pi）。

## 每日排程任務 prompt

整段貼進排程任務，只需要換第 1 步的路徑。

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

說明：

- 為什麼用差集更新，不用 `delete_watchlist` 加 `create_watchlist`：delete 會跳確認，重建後 id 也會變。
- 休市日靠 `next_trade_date` 判斷：週末與休市日 skill 不產出，`latest.json` 還是上一個交易日的內容，今天早於它的 `next_trade_date` 就代表今天休市。
- 失敗時清空清單，是使用者決定的規則：當天一檔都沒有，或排程失敗沒有產出，專用清單都清空（spec 規則 9）。
- 這段 prompt 沒有寫各工具的參數名稱，agent 要依 MCP server 公告的 schema 呼叫。實測時若發現參數用錯，在 prompt 開頭加一句「各工具的參數名稱與格式，以 MCP server 公告的 schema 為準」。
- 08:00 只讀一次 `latest.json`。07:50 到 08:00 之間要手動重跑 `--bullish` 時，見「已知限制」。

## 進階版(對話追問)

在 Shioaji Pro 的 AI 對話裡主動詢問時才用，由那邊的 AI 做語意判斷，不是排程自動做。請 AI 讀同一份 `latest.json`：

- `items`：簡易版結果，每檔有 `reason` 和 `evidence`。
- `candidates`：被提到但沒進清單的股票（中性、信心不足、只有利空、混合排除）。
- 判斷依據：`evidence` 裡的 `snippet`（提到該股前後 60 字）、`title`、`url`、`time`。`snippet` 是空字串時只能看標題；`counted: false` 的那幾則是盤勢彙整類文章，不代表個別股票。

問法範例（三個以內）：

- 「讀 `<latest.json 的絕對路徑>`，看 `candidates` 裡有哪幾檔其實是利多，依 `snippet` 說明理由。」
- 「`items` 裡有哪幾檔的利多其實是別家公司的新聞、只是順帶提到它？」
- 「`excluded` 的混合股，利多和利空新聞各是什麼？」

要不要把結果寫回「新聞利多」清單，由對話當下決定。注意隔天 08:00 的排程會整份替換，對話裡手動加的股票不會保留。

## 實測清單

這是關卡：要等 `feat/340` 合併發佈後，在 App 裡逐項做。任一項不過就停下來回報使用者，不要自行改成 skill 直接寫自選股。

1. App 的工具清單出現 `list_watchlists` 等自選股工具。
2. 授權 `ui.control`、`task.manage` 後重啟 App，確認授權還在；排程在沒人操作時不跳授權詢問。（上游 `AGENT_HARNESS_CONTRACT.md` 寫授權重啟後失效，這項最可能不過；不過就代表 spec 規則 11 的前提不成立。）
3. agent 讀得到 `latest.json` 的絕對路徑。
4. 把排程時間設成兩分鐘後跑一次：清單成員與順序等於 `items`，其他清單沒變。
5. 換成 `status: "empty"` 的檔：清單清空並收到通知。換成 `trade_date` 是昨天、今天早於 `next_trade_date` 的檔：清單不動、沒有通知。

## 已知限制

- 新聞覆蓋不完整：每個來源只抓最新 10 到 15 則（cnyes 每類 15，其他每條 feed 10），前一天傍晚的新聞可能被擠掉，清單會漏幾檔，混合排除也可能漏判。第一版接受，之後做增量收集再補。
- 情緒是整篇新聞一個標籤，一篇提到多檔時無法分開判斷；規則層的已知誤判見 [sentiment.md](sentiment.md)。
- `-KY` 股名要完整寫出才比得到：新聞把「亞德客-KY」寫成「亞德客」時不會命中（代號仍可命中）。
- 常用詞股名只能靠代號命中：標題寫「世界」不算，寫「5347」才算。
- 沒有市場別（上市或上櫃）：Pro 端加入自選前要先用 `search_products` 解析代號。
- `out/bullish/` 每個交易日留一個 `bullish_YYYYMMDD.json`，不會自動清，需要時自己刪舊檔（保留 `latest.json`）。
- 同一天手動重跑若抓取失敗，error 檔會蓋掉當天已成功的清單檔（日期檔與 `latest.json` 都會被換掉）。Pro 端只在 08:00 讀一次，所以只有 07:50 到 08:00 之間重跑失敗才會影響當天清單。
- 排程只在使用者登入時執行（不存密碼），電腦關機或沒登入就不會產出。

文中的 spec 是設計文件 `docs/superpowers/specs/2026-10-21-bullish-watchlist-design.md`，裡面有使用者已決定的規則 1 到 13 與各項取捨。
