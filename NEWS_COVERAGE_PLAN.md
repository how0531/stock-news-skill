# 個股↔新聞漲因「不遺漏」工程計畫(P0~P2)

目標:讓「個股 ↔ 上漲原因新聞」覆蓋完整、不遺漏,盤中/盤後都實用。
驗收基準(每階段都用):南電 8046 這 3 篇要抓到 ——
  1. Yahoo 06-21「AI需求撐腰!IC載板大廠 目標價1150 EPS12.43」(標題無股名,內文才有)
  2. Yahoo 06-23「南電漲價效應發酵 高階載板需求 稼動率走升」(標題有南電)
  3. udn 06-24「外資按讚國巨南電 目標價1515/1444」(標題有南電,money.udn 7253)

根因(實測):抓取走 `main.aggregate`(非 legacy 六家)→ ① 只抓綜合/分類清單,個股深度/速報沒進管線
② cnyes/anue API 已回 `stock` 代號卻被丟棄 ③ 別名字典存在但 live match 沒用 ④ attach_bodies 雞生蛋
⑤ Metabase per-代號正解近日掛。

---

## 里程碑 A — P0(覆蓋核心;先做,完成即可抓到南電 3 篇)

### A1 / P0-1:撿回出版商代號(cnyes/anue stock_codes)— 工:低
- `cnyes.py fetch()`:每筆加 `"stock_codes": _codes(item)`,其中 `_codes` 取 `item.get("stock")`(list)
  + `item.get("market")` 內每個 `{code}`,去重成 list[str]。
- `rss_sources.py`(anue 若走此)同樣保留 anue 的 stock/market(若有)。
- `news_providers.fetch_sanbao` 的對映 dict 加 `"stock_codes": it.get("stock_codes", [])`(目前該對映把它漏掉)。
- `match_news_to_codes`:對有 `stock_codes` 的 item,**該股代號 in stock_codes → 直接命中**(零誤判),
  原 name/代號字串比對降為備援。
- 驗收:cnyes/anue 有標代號的篇章,即使標題用描述性指稱也配得到。

### A2 / P0-2:per-代號即時直取 `fetch_stock_news(code, name)`— 工:中 ⭐
- 新增於 `news_providers.py`:
  - 主力:cnyes search API `https://api.cnyes.com/media/api/v1/search/news?q={name}&limit=30`
    (實測回 content/contentWithKwd,免再 attach;來源即該股,免 name-match)。
  - 併:Yahoo 個股頁 `https://tw.stock.yahoo.com/quote/{code}.TW/news`,解析內嵌 JSON 的關聯新聞。
  - 回標準 item(含 url/title/body/published_at/source、stock_codes=[code])。
- 控量:只對傳入 codes(盤中動能股 <50 檔)跑;並發上限(如 6);**per-code TTL 快取**
  (cache key 必含 code,勿污染 `_SB_CACHE` 綜合清單快取)。
- 驗收:`fetch_stock_news("8046","南電")` 要含那 3 篇(至少 cnyes search 命中)。

### A3 / P0-3:`query_news` codes 分支改 fallback 鏈 — 工:低
- 順序:`get_news_metabase`(健康時 per-代號正解,主力)→ 失敗/空 → `fetch_stock_news`(A2)
  → 再疊現行 `match_news_to_codes`(A1 強化版)補綜合流。
- `get_news_metabase` 包 try;例外或 df 空 → set flag,後段一定跑 A2。
- 每則標 `source`(metabase / cnyes-search / yahoo-quote / sanbao),輸出去重(url 正規化去 utm + 標題正規化)。
- 驗收(里程碑 A 總驗收):南電/精材跑 query_news → 3 篇全到。

---

## 里程碑 B — P1(比對韌性)

### B1 / P1-1:別名字典接進 live match — 工:低
- `news_providers` 加 `_load_alias_index()`(複用 `watch_intraday.load_alias_index`,讀 `data/stocks/tw_stocks.json`;
  key `8046.TW` → 去 `.TW` 對映裸 code)。
- `match_news_to_codes` 每 code:先比中文簡稱 → 再比該 code 別名集合;中文別名直接 `in`,
  英數別名加 `(?<!\w)…(?!\w)` 邊界,套 `build_stock_dict.ALIAS_BLACKLIST`(AI/IC/EV…)。
- 驗收:內文出現「南亞電路板/ABF載板」的綜合流文章也配到 8046。

### B2 / P1-2:attach_bodies 倒序 + 描述性稱謂表 — 工:中
- 對綜合流「候選文」(標題含 目標價/稼動率/EPS/載板 等產業熱詞)**先補內文再 match**
  (`body_fetch_limit` 控量:盤中限量、盤後放寬)。
- 小型 `DESC_ALIAS`(描述性稱謂→候選代號):IC載板大廠/ABF載板廠→[8046,3037,3189]、晶圓代工龍頭→[2330]…
  命中稱謂 → 候選列「疑似」→ **內文同時出現某候選股簡稱才正式掛**(二次確認壓誤配)。
- 驗收:第1篇從綜合流也能配到(標題稱謂→候選→內文南電確認)。

---

## 里程碑 C — P2(長尾覆蓋)

### C1 / P2-1:補證券個股版/法人速報 feeds — 工:中
- `udn.py FEEDS` 加證券/上市電子(7253)/集中市場;統一雙路徑(讓 aggregate 也吃 config.json udn_feeds)。
- `cnyes.py CATEGORIES` 加台股個股/速報類(Factset 速報所在)。
- `rss_sources` 確認 technews/moneydj 載板·報告 feed 可用。
- 驗收:第3篇 udn 7253 從綜合流即可命中(不靠 per-股直取)。

### C2 / P2-2:embedding 語意召回(選配)— 工:高
- 本地 e5(@768);離線把每檔「簡稱+別名+產業+代表題材」組 query 向量;
  新聞算向量 → per-股 top-k 召回(門檻~0.8)→ **內文出現任一別名/同產業詞才掛**(驗證層壓噪)。
- **只當增量召回,勿全量重嵌**(MEMORY 警告勿做維度遷移)。
- 驗收:完全無字面別名命中的改寫型報導也能召回(P0/P1 後仍漏網才需要)。

---

## 取捨 / 風險
- per-股直取(A2)非官方端點,格式可能變 → 容錯 + 上線監看 + selftest 加檢查。
- 描述性稱謂/別名(B)易整族群誤掛 → 一律「內文須同時出現該股簡稱」二次確認。
- 補源(C1)增延遲 → limit/快取/盤中限量。
- 全程向後相容:新增欄位、fallback 疊加,不破壞既有 query_news 介面(Sino-notify 照常)。

## 落地順序
A1 → A2 → A3 →(里程碑 A 驗收:南電 3 篇)→ B1 → B2 →(B 驗收)→ C1 →(C 驗收)→ C2(選配)。
