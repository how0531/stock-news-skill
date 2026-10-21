# 新聞來源與抓取流程

何時讀：要知道有哪些來源、某家 0 則或被擋、要調整來源或抓取量、要開網路白名單時。

## 抓取流程

`query_news` 與 `fetch_market_news` 都經 `_fetch_sanbao_cached`（TTL 快取，記憶體加 `out/.sanbao_cache.json`）呼叫 `news_providers.fetch_sanbao`：

1. 主路徑 `main.aggregate()`：九家各佔一個執行緒並行（`ThreadPoolExecutor(max_workers=10)`），同一家內序列，最後跨來源去重。
2. 備援路徑：只有在 `import main` 失敗（通常是缺套件）或 `aggregate()` 整個拋例外時，才退回 `news_providers.py` 裡的舊版六家並行爬蟲，stderr 會有 `New modular aggregator failed`。單一來源失敗只會印 `[來源] 抓取失敗`，不會觸發備援。

判斷主路徑是否健康：看 stderr 每家的 `[來源] 完成 N 則 (X s)`，或跑 `python scripts/healthcheck.py`。

## 主路徑九家

| source 標籤 | 取法 | 每次抓取量 | 內文 |
|---|---|---|---|
| `cnyes` 鉅亨 | `api.cnyes.com/media/api/v1/newslist/category/{分類}`，固定五類：headline 頭條、wd_stock 國際股市、tw_stock 台股、forex 外匯、future 期貨（`cnyes.py` CATEGORIES） | 每類 15 則 | API 回應內就有全文 |
| `udn` 經濟日報 | money.udn.com RSS 八個版面：國際焦點、國際綜合、美股雷達、全球財經、要聞、證券、證券要聞、股市（`udn.py` FEEDS） | 每版 10 則 | 逐篇進內頁抽取 |
| `ctee` 工商時報 | Google News RSS 搜尋「工商時報 股市」取清單，排除房市、生活、兩岸、理財，再用解碼 API 還原真實 `/news/` 網址，直連文章頁（`ctee.py`） | 每分類 10 則 | 逐篇進內頁抽取 |
| `cna` 中央社 | RSS 財經（feeds.feedburner.com/rsscna/finance） | 10 則 | 逐篇進內頁 |
| `ltn` 自由財經 | RSS news.ltn.com.tw/rss/business.xml | 10 則 | 逐篇進內頁 |
| `technews` 科技新報 | RSS 全站 technews.tw/feed/（不是財經專版，會混入科普文） | 10 則 | 逐篇進內頁 |
| `ettoday` ETtoday 財經 | RSS feeds.feedburner.com/ettoday/finance | 10 則 | 逐篇進內頁 |
| `moneydj` MoneyDJ | RSS 頭條新聞（www.moneydj.com/KMDJ/RssCenter.aspx） | 10 則 | 逐篇進內頁（內文選擇器信心低） |
| `yahoo_stock` Yahoo 奇摩股市 | RSS 四條：台股、國際股市、產業動態（tw.news.yahoo.com）、產業個股 | 每條 10 則 | 逐篇進內頁 |

合計約 200 則（去重後），大約涵蓋最近一兩天。較舊或冷門的題材要靠 Metabase 與 cnyes 全站搜尋。單篇內文抓不到時退回 RSS 摘要。

非財經雜訊：udn 的全球財經、國際焦點、國際綜合（都在 5588 國際版底下）以國際財經為主，但會混入國際政治、軍事等時事；科技新報是全站 feed，會混入科普文。

內文雜訊：`yahoo_stock` 內文開頭常帶「加入為 Google 偏好來源」之類的頁面文字；ETtoday 與 MoneyDJ 的 summary 含原始 HTML。

## 另外兩條腿

- Metabase `cmoney.證券市場新聞`：關鍵字推進 SQL（`positionUTF8` 比對標題與內文），依代號直查只回標題。需要 `sinopac-metabase` 的 client 與帳密；`metabase_available()` 測不通時整條腿跳過。發布時間是假 UTC（台北牆鐘帶 Z），`_mb_time()` 改成 +08:00。
- 個股直取（只在 `--codes`）：cnyes 全站搜尋 API（有股名用股名，沒有就用代號）加 Yahoo 個股頁新聞，`per_stock_fetch` 控制，不受 `--source` 影響。

## 備援路徑六家（平常不跑）

`cnyes`、`udn`、`ctee`、`anue`、`moneydj`、`yahoo`，ThreadPool 並行。設定讀 `config.json` 的 `*_categories`、`*_feeds`、`*_pages`、`*_limit`（主路徑不讀這些鍵，改了只會讓快取失效一次）。和主路徑的差異：

- 沒有 `stock_codes` 與 `category` 欄位，所以出版商代號比對失效，`--intl` 只剩 cnyes 搜尋腿的結果。
- `anue` 不是鉅亨論壇：`forum.cnyes.com` 在公司網路常 504，改用 cnyes 公開 newslist API 取 `wd_stock` 與 `forex`。主路徑的 cnyes 已含這兩類。
- MoneyDJ 走 `newsreallist.aspx` 的 HTML 列表，時間欄只有 `MM/DD HH:MM`，parser 補當年，日期大於今天就退回去年。
- 細部設定參考：[../SUGGESTED_CONFIG.md](../SUGGESTED_CONFIG.md)（只影響備援路徑）。

## 調整來源

主路徑的來源與數量寫死在程式，不讀 config：`scripts/main.py` 的 tasks 與各家 limit、`cnyes.py` CATEGORIES、`udn.py` FEEDS、`rss_sources.py` SOURCES、`ctee.py` 的查詢字串與 EXCLUDE。新增或恢復來源時，同步改 `scripts/healthcheck.py` 的預設清單，以及 07:40 自動信 `premarket_digest.ps1` 的「來源 0 則黃燈」名單（寫死九個 source id）。

## 網路網域

清單與抓取：api.cnyes.com、money.udn.com、news.google.com（ctee 清單與解碼）、feeds.feedburner.com（中央社、ETtoday）、news.ltn.com.tw、technews.tw、www.moneydj.com、tw.stock.yahoo.com、tw.news.yahoo.com。文章頁：www.ctee.com.tw、www.cna.com.tw、ec.ltn.com.tw、finance.ettoday.net、technews.tw 子網域等，依 RSS 條目而定。全市場股名清單（`build_stock_dict.py --names`）：openapi.twse.com.tw、www.tpex.org.tw。

## 延遲與上限

- 同一家內序列：udn、ctee、RSS 六家每篇內文間隔 0.3 秒；cnyes 每分類、RSS 每條 feed 之間停 1 秒。
- 採集器共用的 `common.request_get`：單一請求逾時 10 秒，失敗重試 2 次（退避 2、4 秒）。ctee 例外：Google News 清單用 feedparser 直接抓，沒有逾時也不重試；解碼的 GET 與 POST 各有 15 秒逾時，不重試。查詢階段的補內文、cnyes 全站搜尋與 Yahoo 個股頁走 urllib，逾時 12 秒，不重試。
- 全量抓取約 1.5 到 2 分鐘。2026-10-09 單次實測 111 秒、199 則（原序列版 305 秒），瓶頸是 yahoo_stock 與 udn 的逐篇內文；2026-10-21 實測 112 秒。數字只供量級參考，現況看 stderr。

## 來源狀態紀錄

- ctee（2026-06-26）：`www.ctee.com.tw` 的列表頁、livenews、RSS、sitemap 全面 Cloudflare 403（偽造 Googlebot 也擋，Cloudflare 用反向 DNS 驗證），但 `robots.txt` 與個別 `/news/` 文章頁回 200。所以改走 Google News RSS 加解碼 API（GET `news.google.com/rss/articles/{id}` 取 `data-n-a-sg`、`data-n-a-ts`，再 POST `batchexecute`），純 HTTP、不開瀏覽器。gnews 套件與 Playwright 逐篇開 headless Chromium 會被 `google.com/sorry` 限流，已棄用。清單加解碼約 7 秒 20 篇（不含逐篇內文）。
- cnyes RSS（2026-06-26）：`news.cnyes.com/rss/` 系列全部 404；cnyes 的分類 newslist API 正常，主路徑不受影響。
- udn（2026-06-26）：`udn.com/rssfeed/` 的 pubDate 全是 1970-01-01，所以只用 `money.udn.com/rssfeed/`。
- 中時 chinatimes（2026-10-05 起）：列表頁 403，重試還白耗約 8 秒，已移出主路徑。恢復方式見 `scripts/main.py` 註解，`python scripts/healthcheck.py chinatimes` 可單獨點名測。
- 這些是外站狀態，會變，要確認請實際連網測。
