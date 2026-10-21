# 連線校正清單（Phase 1 待辦）

目前所有 site_map 皆 `verified_live: false`——結構、專欄、選擇器、端點都是**沙箱離線研究**
（WebSearch + 公開爬蟲實作）的成果，尚未對真實站台實測。沙箱對外連線一律 403，故本清單
列出「等連線可用時」要逐項勾掉的校正工作。每項標注**為什麼存疑**與**怎麼驗**。

驗完一項就把對應 `data/site_maps/{source}.json` 的相關欄位修正，最後將該檔
`verified_live` 設為 `true`，並重跑 `python scripts/site_map.py --index` 更新 manifest。

## 0. 一鍵連通性（先做這個）

```bash
python scripts/healthcheck.py            # 探測所有來源存活，印出 ok/count/with_ts/detail
python scripts/healthcheck.py cnyes udn  # 只探指定來源
```

`ok=False` 或 `count=0` 的來源代表端點掛了或被擋，優先處理；`with_ts` 偏低代表時間欄位
解析有問題，回頭看該來源的時間正規化。

## 1. RSS feed URL 有效性（method=rss）

逐一確認 feed 仍回 200 且有 entries（feedparser `bozo` 為 0）。下列為已登記 feed：

| 來源 | feed URL | 風險 |
|------|----------|------|
| cna | `feeds.feedburner.com/rsscna/finance` | FeedBurner 代理，Google 偶有停用風險 |
| ltn | `news.ltn.com.tw/rss/business.xml` | 單一綜合財經 feed，確認非空 |
| technews | `technews.tw/feed/` | **全站** feed，混科普；確認 `finance.technews.tw/feed/` 是否存在可替換 |
| ettoday | `feeds.feedburner.com/ettoday/finance` | FeedBurner 代理 |
| chinatimes | `www.chinatimes.com/rss/realtimenews-finance.xml` | 確認命名仍為 `realtimenews-{slug}` |
| moneydj | `www.moneydj.com/KMDJ/RssCenter.aspx?svc=NR&fno=1&arg=X0` | 只驗過 fno=1&arg=X0；見 §4 |
| yahoo_stock | `tw.stock.yahoo.com/rss?category=tw-market` / `intl-markets` | category 參數見 §3 |

## 2. body_selectors 內文抽取準確度（全 RSS/HTML 來源）

`fetch_content=True` 時用 `SOURCES[sid]['body_selectors']` 抽全文。
研究自公開爬蟲，**信心不一**，需抓 2-3 篇真實文章肉眼比對抽出的內文是否完整、無導航/廣告殘留。

| 來源 | 首選 selector | 信心 | 驗證重點 |
|------|--------------|------|----------|
| chinatimes | `div.article-body` | 高（程式碼實證） | 確認無「延伸閱讀」尾段混入 |
| yahoo_stock | `div.caas-body` | 高（Yahoo CaaS） | 轉載文確認抓到原文非導購卡 |
| ettoday | `div.story` | 中高 | 確認非 `div.story_intro` 只抓到前言 |
| cna | `div.paragraph` | 中 | 多段是否完整串接 |
| ltn | `div.text` → `div[itemprop=articleBody]` | 中 | 自由常有「不用抽中獎」浮層，確認被濾掉 |
| technews | `div.indent` → `div.entry-content` | 中（WP） | WP 版型確認 class 名 |
| moneydj | `article`（靠泛用 fallback） | **低** | NewsViewer 版型未確認，最可能要改；優先補真實 selector |
| ctee | 經 `parse_article`（backfill_ctee）| 中 | 列表頁無內文，靠內頁；確認 byline/發布時間解析 |

## 3. Yahoo category 參數（推測待驗）

`yahoo_stock.json` 的 RSS category：
- **已確認可用**：`tw-market`、`intl-markets`、`research`、`funds-news`、`column`
- **推測待驗**：`tw-etf`、`forex`、`futures`——逐一打 `?category={name}` 確認是否回有效 RSS。
  - 注意：`forex`/`futures`/`funds`（基金）依使用者檢核屬**排除**類，即使存在也不納入 stock_relevant，
    但仍可驗證端點是否存在以利文件正確。

## 4. MoneyDJ fno/arg 變體（推測待驗）

只驗過 `fno=1&arg=X0`（頭條）。`moneydj.json` 列的其餘欄目其 `fno`/`arg` 精確值未證實，
且基金/ETF/美股**可能不走 RssCenter**，而有 `/etf/`、`/funddj/` 專屬 feed。逐一實測對應，
更新端點。（基金欄依使用者檢核已排除，僅需確認其餘 stock_relevant 欄目走得通。）

## 5. TPEx OpenAPI 端點名稱（swagger 推定）

`twse.json` 的 TWSE 四端點命名較有把握；**TPEx 三端點以 swagger 推定**，正式串接前實測：
- `www.tpex.org.tw/openapi/v1/mopsfin_t187ap04_O`（重大訊息）
- `www.tpex.org.tw/openapi/v1/tpex_disposal_information`（處置）
- `www.tpex.org.tw/openapi/v1/tpex_attention_information`（注意）

確認路徑、HTTP 200、回傳欄位名（特別是 `co_id`/日期/說明欄）與 `twse_announce.py` 解析一致。

## 6. ctee WP REST API 已知 404

`ctee.json` 已記 WP REST API 全站 404，只能靠列表頁 HTML + sitemap。連線後確認此結論仍成立
（若 WP API 復活可大幅簡化），否則維持 HTML 解析路徑。

## 7. 時間欄位與 PIT（全來源）

抽樣比對每來源 `publish_ts` 是否為正確的**官方發布時間**（非抓取時間、非列表頁粗略日期）：
- ctee 列表頁僅日粒度，須 `fetch_content` 取內頁精確時間——確認 `_detail_fields` 解析到時分秒。
- cnyes API 時間戳為 epoch，確認時區換算 Asia/Taipei 正確。
- 確認 `actionable_ts` 假日感知對近期實際假日（看 `data/calendar/tw_holidays.json`）落點正確。

## 8. 去重對真實資料的效果（連線後才測得到）

兩層去重（`process_day`）目前只有離線單元測試覆蓋，需用**真實當日多來源抓取**驗證：
- **Tier 1**（標題正規化完全相同）：確認 Yahoo 原樣轉載中央社/經濟日報的同標題被正確合併。
- **Tier 2**（內文指紋，標題改寫同全文）：確認 Yahoo 改寫標題引用他媒體全文的情形被抓到，
  `also_reported_by` 正確填入來源；並反向確認**不同事件**未被誤併（指紋 60 字門檻 + 48h 時間窗）。
  - 前提：Tier 2 需 `content`/`summary` 正規化後 ≥60 字，故須先確認 `fetch_content` 有抓到夠長全文，
    否則純 RSS 摘要太短會比不出指紋——這條與 §2 連動。

## 收尾

全部驗完並修正後：
1. 各 `data/site_maps/{source}.json` 的 `verified_live` 改 `true`、`researched_via` 補上實測註記。
2. `python scripts/site_map.py` 確認仍通過 schema/一致性驗證。
3. `python scripts/site_map.py --index` 重寫 `_index.json`（`n_verified_live` 應上升）。
4. 更新 SKILL.md 來源清單的驗證狀態欄。
