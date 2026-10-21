# 新聞利多自選股清單：設計

日期：2026-10-21
範圍：stock-news-skill（本 repo）產出清單；Shioaji Pro 的 AI agent 套用到自選股。

## 1. 目的與緣由

使用者要在 Shioaji Pro 裡維護一份「新聞利多」專用自選股清單，每天由排程自動更新，不必手動挑股。新聞來源與判斷由 stock-news-skill 負責；Shioaji Pro 的 AI agent 只負責把清單搬進自選股。使用者另外希望在 Shioaji Pro 的 AI 對話裡追問時，AI 能讀新聞內文做更細的語意判斷。

分工（使用者已決定）：skill 只產出清單，不直接改自選股；改自選股交給 Shioaji Pro 的 AI agent。理由：skill 不碰券商帳號與 App 版本差異、可以離線測試；寫入走 App 的官方工具路徑，有冪等、紀錄與畫面同步。

## 2. 目標、非目標、反目標

目標

- 每天排程觸發後，skill 產出一份結構化的「利多個股清單」檔案。
- 簡易版判斷完全在 skill 裡用程式算完，不需要 AI。
- Shioaji Pro 的 AI agent 每天讀這份檔案，把專用自選股清單整份替換，全自動、不經使用者確認。
- 進階版：使用者在 Shioaji Pro 的 AI 對話裡主動詢問時，AI 讀同一份檔案裡的候選與內文片段，自己做語意判斷、寫理由。

非目標

- skill 不寫入自選股、不呼叫 Shioaji 的 sidecar 或 CLI、不持有券商帳密。
- 不下單、不做任何交易動作。
- 不用股價、量能等行情資料篩選（只看新聞）。
- 不限制清單檔數。

反目標（做了等於做壞）

- 動到使用者手動維護的其他自選股清單。
- 把同一天同時有利多與利空新聞的股票列進清單。
- 覆寫 `out/news_result.json` 或影響 07:40 自動盤前信。
- 需要 Metabase 才能產出（沒有 Metabase 權限的同事也要能用）。

## 3. 使用者已決定的規則

1. 觸發：排程。
2. 簡易版：直接用規則層情緒標籤（`news_sentiment`）判斷，在 skill 內算完。
3. 進階版：只有使用者在 Shioaji Pro 的 AI 對話裡詢問時才做語意判斷，由那邊的 AI 執行。
4. 專用自選股清單每天整份替換，全自動。
5. 不限檔數，符合條件的全部列入。
6. 標題直接點名的個股權重最高（例如工商時報這類標題就寫股名的新聞）。
7. 只在內文提到、標題沒點名的個股也列入，排在後面。
8. 同一檔同一天同時有利多與利空新聞時，不列入。
9. 當天一檔都沒有，或排程失敗沒有產出，專用清單清空。
10. 週末與休市日保留前一交易日的清單，Pro 排程直接跳過，不通知。
11. Pro 排程無人值守時的權限：第一次設定時把 `ui.control` 與 `task.manage` 設成永久允許，分工不變（skill 只產清單）。
12. 新聞覆蓋不完整（每個來源只抓最新 10 到 15 則）第一版先接受，之後做增量收集時再補齊。
13. 同事也要能用，不只使用者本機。

## 4. 現況（調查結果）

stock-news-skill

- `news_core.fetch_market_news(since="last_close")` 回傳前一交易日 14:00 之後的全市場新聞，但每個分類或 feed 只抓最新 10 到 15 則（總共約 200 則，`main.py:40-45`），時間窗只是下限，不保證涵蓋整段。每則有 time、title、source、url、summary、body、sentiment、confidence、events，但沒有對應的股票代號。主路徑採集器有出版商標的 `stock_codes`（cnyes），在 `fetch_market_news` 這一層被丟掉。
- 新聞對應個股的比對已存在於 `news_providers.match_news_to_codes`（出版商代號、股名、代號字串、別名），但它是給 `--codes` 用的「指定代號找新聞」，不是「每則新聞找出提到哪些股票」。
- 股名來源：`data/stocks/tw_names.json`（上市加上櫃約 2,000 檔，`build_stock_dict.py --names` 產生）、`data/stocks/tw_stocks.json`（策展約 160 檔，含別名）。目前都沒有市場別（上市或上櫃）。
- 情緒是整篇新聞一個標籤，不是個股層級；`news_sentiment.classify` 會算 rationale，但沒有輸出到新聞項目。
- 07:40 自動盤前信（`scripts/premarket_digest.ps1`，本機排程）每個交易日跑 `news.py --today`，產出 `out/news_result.json`（`items[].body` 全文）。休市日會自動略過。

Shioaji Pro（公開 repo 調查，私有 repo 看不到）

- AI agent 是 App 啟動的外接 runtime（Codex、Claude Code、Pi），用使用者自己的 AI 額度；有內建排程任務（每天定時等），App 要開著（可縮到系統匣）。
- 自選股存在伺服器端，經本機 sidecar（127.0.0.1:21322）的 `/api/v1/watchlist` 讀寫；資料模型是多個命名清單 `{id, name, contracts:[{security_type, exchange, code}]}`。
- AI agent 目前沒有自選股工具。上游分支 `feat/340-agent-watchlist-tools`（2026-10-21，未合併）新增 9 個工具：list、get、create、add_to、remove_from、reorder、rename、select、delete；delete 會跳確認，其他不會；沒有「整份替換」。
- 上游 `MCP_TOOLS.md` 寫明 agent 用這些工具修改後，自選面板會自己重讀（`sj-pro:watchlist-changed`），所以本功能不依賴另一個工作的 `watchlist-poll`（那是修 App 外部直接改 sidecar 的情況）。
- 上游 `MCP_TOOLS.md` 寫明 watchlist 工具需要 `ui.control` 權限、排程工具需要 `task.manage`，權限各自獨立、預設拒絕。

## 5. 設計

### 5.1 skill 端：新增「利多清單」產出

新增 CLI 模式（建議 `news.py --bullish`）與對應函式（建議 `news_core.bullish_watchlist()`），步驟如下：

1. 取原料：優先讀當天 07:40 自動信已產出的 `out/news_result.json`（`mode == "today_digest"` 且 `generated_at` 的前 10 字是今天；`date` 是「2026-10-22 盤前（涵蓋…）」這種顯示字串，`generated_at` 是沒有時區的 `YYYY-MM-DD HH:MM`，見 `news.py:146-158`）；沒有就自己呼叫 `fetch_market_news(since="last_close")`。不要寫回 `out/news_result.json`。（我的判斷：省一次約 2 分鐘的全量抓取，也確保兩者用同一份新聞。）
2. 每則新聞對應個股（我的判斷，依使用者「標題就寫股名的越好」）：
   - 標題級：股票自己的名稱（`tw_names.json` 簡稱，或 `tw_stocks.json` 裡指向單一公司的別名，例如 TSMC）或代號出現在標題。
   - 內文級：只出現在內文。出版商標記的代號（cnyes 的 `stock_codes`，需要讓 `fetch_market_news` 保留下來）也算內文級，除非股名同時出現在標題；cnyes 的標籤來自整篇文章，盤勢彙整文常一次標很多檔（`cnyes.py:39-51`）。
   - 主題詞別名（DRAM、AI伺服器、ABF載板、MLCC、散熱、IC設計、CCL 這類對到一檔以上或本身是產業名詞的詞）不算點名，不計票。
   - 比對要比 `match_news_to_codes` 嚴格，因為要拿全市場約 2,000 個股名反查：最長匹配優先（命中「南亞科」就不再算「南亞」，共約 85 組互為子字串）；常用詞股名（世界、全新、中華、光明、幸福、泰山等）只在標題同時出現代號時才算；代號後面緊接「年」不算（2023 到 2031 都是股票代號）。這套比對只給利多清單用，不改 `match_news_to_codes`，以免影響 `--codes` 與 Sino-notify-skill。
   - 一則新聞的內文級對應超過 3 檔時，這則的內文級對應都不計票（多半是盤勢彙整或排行榜，整篇情緒不代表個別股票）。門檻可調。
3. 每則新聞的票：`sentiment == bullish` 且 `confidence >= 0.5` 算一張利多票；`bearish` 且 `confidence >= 0.5` 算一張利空票；其他不計。（我的判斷。內文只命中一個詞時信心是 0.5，標題命中一個詞是 0.667，兩者都過門檻，見 `news_sentiment.py:256,510`。）
4. 彙整到個股：
   - 有任何利空票的股票排除（規則 8），記到 `excluded`，原因 `mixed`。
   - 至少一張利多票就列入。
   - 排序：有標題級利多票的一律排在只有內文級的前面（規則 7）；同一組內依分數（標題級利多票 × 3 + 內文級利多票 × 1）由高到低，同分依最新一則新聞時間由新到舊。
5. 產出檔案，見 5.2。
6. 休市日不產出（沿用 `storage._is_closed`）。

市場別（上市或上櫃）不由 skill 提供，`tw_names.json` 不改格式：上游 `MCP_TOOLS.md` 要求加入自選前一律先用 `search_products` 解析代號，Pro 端照做即可。（我的判斷，省掉一次格式遷移；`tw_stocks.json` 的 `.TW`／`.TWO` 後綴有錯，也不能拿來判斷。）

### 5.2 輸出檔案（契約）

位置：`out/bullish/bullish_YYYYMMDD.json`（交易日），另寫一份 `out/bullish/latest.json`（同內容）。`out/` 已在 `.gitignore`。寫入用暫存檔加 `os.replace`。

```json
{
  "schema_version": 1,
  "status": "ok",
  "trade_date": "2026-10-22",
  "next_trade_date": "2026-10-23",
  "generated_at": "2026-10-22T07:46:10+08:00",
  "window": {"from": "2026-10-21T14:00:00+08:00", "to": "2026-10-22T07:46:00+08:00"},
  "method": "rule",
  "rule": {"confidence_min": 0.5, "title_weight": 3, "body_weight": 1, "body_max_stocks_per_news": 3},
  "items": [
    {
      "code": "2408", "name": "南亞科",
      "score": 7, "title_votes": 2, "body_votes": 1,
      "reason": "標題點名 2 則利多：DRAM 報價調漲、法人上修目標價",
      "evidence": [
        {"title": "...", "url": "...", "time": "...", "source": "ctee",
         "match": "title", "sentiment": "bullish", "confidence": 0.667, "events": ["訂單"]}
      ]
    }
  ],
  "excluded": [{"code": "3035", "name": "智原", "why": "mixed"}],
  "candidates": [
    {"code": "...", "name": "...", "evidence": [{"title": "...", "url": "...", "time": "...",
      "source": "...", "match": "body", "sentiment": "neutral", "confidence": 0.0, "snippet": "提到該股前後 60 字"}]}
  ]
}
```

- `status`：`ok`（有清單）、`empty`（成功但沒有符合的股票）、`error`（失敗，另附 `error` 字串）。失敗時也要盡量寫出 `status: error` 的檔，讓 Shioaji Pro 分得出「沒有利多」與「出錯」。
- `next_trade_date`：`trade_date` 之後的下一個交易日（`storage._next_trading_day`）。Pro 端靠它分辨「今天休市」與「今天該有清單卻沒有」，skill 在休市日就不必跑。（我的判斷。）
- `items`：簡易版結果，Shioaji Pro 排程直接套用這份。
- `candidates`：給進階版用。所有被提到、但沒進 `items` 的股票（中性、信心不足、混合），每則附個股片段 `snippet`（沿用 `news_core._snippets`，以股名為關鍵字）。（我的判斷，進階版才需要讀內文。）
- `reason` 由程式組字串（標題級幾則、事件標籤），不是 AI 寫的。

### 5.3 skill 端排程

同事也要能用（規則 13），所以排程放進 repo，不接在只存在使用者本機、已 gitignore 的 `premarket_digest.ps1` 後面：

- 新增一支會進版控的排程登記腳本（例如 `scripts/register_bullish_task.ps1`），用 Windows 工作排程登記「週一到週五 07:50 執行 `python -X utf8 scripts/news.py --bullish`」。路徑用 `$PSScriptRoot` 推算，不寫死使用者名稱、工號、email 或內部路徑（repo 是公開的）；重跑會覆蓋同名工作，另提供移除用的參數。
- `--bullish` 自己判斷休市（`storage._is_closed`），休市日不寫檔、正常結束。
- 使用者本機也用同一支排程：07:40 的盤前信已寫好當天的 `out/news_result.json` 就直接沿用；還在抓的話，既有的跨進程抓取鎖與 15 分鐘磁碟快取會讓 `--bullish` 等它抓完再用同一份，不會抓兩次。同事那邊沒有盤前信，就自己抓一次（約 2 分鐘）。（我的判斷，一條路徑給所有人。）
- 同事需要的前置：Python 與 `requirements.txt`、skill 放在 Pro agent 讀得到的位置；不需要 Metabase。

### 5.4 Shioaji Pro 端

依賴：上游 `feat/340-agent-watchlist-tools` 合併並發佈。

- 專用清單：一個固定名稱的命名清單（建議「新聞利多」）。第一次用 `create_watchlist` 建立，之後一律用它的 `watchlist_id` 操作，不改名（改名會換 id）。
- 權限：第一次設定時，使用者在 App 把 `ui.control` 與 `task.manage` 設成永久允許（規則 11）。要先在 App 實測「排程無人值守時真的不跳詢問」以及 agent 讀得到 skill 的 `out/bullish/latest.json`；任一項做不到就是阻塞，回頭找使用者，不要自行改成 skill 直接寫自選股。
- 每日排程任務（App 內 `create_task`，每天定時，建議 08:00，晚於 skill 的 07:50）：
  1. 讀 `latest.json`，依今天日期分三種情況：
     - `trade_date` 是今天：正常套用（下一步）。`status` 是 `error` 時視同失敗。
     - `trade_date` 不是今天，而且今天早於 `next_trade_date`：今天休市，直接結束，不動清單、不通知（規則 10）。
     - 其他情況（檔案不存在、讀不懂、`trade_date` 過期）：視同失敗。
  2. 目標成員：`status == ok` 時是 `items` 的代號（照檔案順序）；`empty` 或失敗時是空清單（規則 9）。每個代號先用 `search_products` 解析成商品再加入。
  3. 用 `get_watchlist` 取現有成員，對差集呼叫 `remove_from_watchlist`、`add_to_watchlist`，必要時 `reorder_watchlist` 照檔案順序排，最後讀回核對。不要用 `delete_watchlist` 加 `create_watchlist`（delete 會跳確認，id 也會變）。
  4. 失敗或清空時用 `notify_user` 通知，附原因。
- 進階版：使用者在 AI 對話裡詢問時，AI 讀同一份 `latest.json` 的 `items` 與 `candidates`，依 `snippet` 與 `url` 做語意判斷、寫理由；要不要寫回專用清單由對話當下決定。

## 6. 限制

- Windows 環境；App 要開著，排程任務才會跑；每次排程消耗一次 AI 額度。
- 使用者這台電腦連不到 api.openai.com，Codex 跑不起來，provider 要用 Claude Code 或 Pi；同事的環境可能也一樣。
- Shioaji Pro 的 AI agent 能不能無人值守讀本機檔案（例如 `~/.claude/skills/stock-news-skill/out/bullish/latest.json`，同事的 skill 位置可能不同），以及永久允許設定是否存在，都還沒驗證（見 5.4 權限）。
- 新聞覆蓋不完整：每個來源只抓最新 10 到 15 則，前一天傍晚的新聞可能被擠掉，清單會漏幾檔，混合排除也可能漏判。第一版接受（規則 12），寫進 `references/` 的已知問題。
- 規則層情緒是整篇新聞一個標籤，一篇提到多檔時無法分開判斷；已知誤判見 `references/sentiment.md`。
- 不准覆寫 `out/news_result.json`；離線單元測試要涵蓋對應、計票、排除、排序、空清單、檔案格式。

## 7. 留給實作者決定

- `--bullish` 的實際旗標名、函式名與模組位置。
- 門檻（信心 0.5、標題權重 3、內文單篇最多 3 檔）的最終數值，可先照本文件，之後依實際清單調。
- 常用詞股名停用表的完整內容。
- Shioaji Pro 排程任務的 prompt 寫法，以及要不要另存成 App 內的 skill（`save_skill`）讓對話可以 `/技能名` 呼叫。
