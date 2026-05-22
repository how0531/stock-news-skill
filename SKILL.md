---
name: stock-news-skill
description: >-
  台股新聞查詢 skill。整合永豐 Metabase cmoney.證券市場新聞(內部、歷史可回溯)
  與六家即時新聞流:cnyes 鉅亨 / udn 經濟日報 / ctee 工商時報 / anue 鉅亨子站
  / MoneyDJ / Yahoo 奇摩股市(全部含文章內文),支援「依股票代號查近 N 日個股
  新聞」與「依關鍵字查新聞(含內文)」,並內建利多/利空 + 事件分類(規則層,
  可關)。**只要使用者問「有沒有 X 的新聞」「X 這篇新聞是真的嗎」「某股最近
  有什麼消息」「幫我查 OOO 新聞/內文」「整理 XX 的新聞」「希捷/輝達…說了
  什麼」「某事件有報導嗎」、或要對某代號/關鍵字做新聞查證與內文彙整,務必
  使用本 skill。** 即使沒明說「新聞」,只要情境是要查證某消息是否有報導、或要
  某股/某題材的最新新聞與內文,也要觸發。**分工界線:本 skill 只負責「取得/
  查證新聞」,輸出新聞清單與內文(含 sentiment 標籤);若使用者要的是「產出
  發給客戶的盤前/盤中快訊/0940/00981A 大戶投推播」,那是 Sino-notify-skill
  的工作,不要用本 skill(本 skill 會被 Sino-notify-skill 當新聞引擎在內部
  呼叫);若要的是「從 Metabase/cmoney 撈原始資料表、跑 SQL、匯出數字或
  Excel 報表」(而非讀新聞標題與內文),那是 sinopac-metabase 的工作。** 判準:
  目的是「知道有什麼新聞內容」→ 本 skill;「產出大戶投推播」→
  Sino-notify-skill;「從 Metabase 撈原始數據/SQL/匯出 Excel」→ sinopac-metabase。
---

# 台股新聞查詢(stock-news-skill)

## 這個 skill 做什麼

一個**自給自足**的台股新聞查詢引擎,兩種查法:

1. **依代號**:給股票代號 → 回近 N 日個股新聞(Metabase 依代號直查 + 6 家即時流
   依股名/代號比對標題,合併去重,並補文章內文)
2. **依關鍵字**:給關鍵字 → 回命中新聞(Metabase 標題搜尋 + 6 家標題/摘要/
   內文全文比對),用於查證某消息是否有報導、彙整某題材新聞

每則新聞自動補上 **sentiment(利多/利空/中性)+ confidence + events(法說/購併/
警示/獲利預警/產能/訂單/訴訟/股利/增資/減資/公開收購/漲停/跌停/踩雷)**,
規則層、純標準庫、可由 `tag_sentiment=False` 關掉。

可獨立使用(CLI),也被 **Sino-notify-skill** 當新聞來源呼叫。

## 前置需求

1. **Python 套件**:`pip install -r requirements.txt`(即 `beautifulsoup4` + `feedparser`;其餘走標準庫)。
2. **Metabase 腿**(關鍵字搜尋主力 / 依代號直查):靠隔壁 `sinopac-metabase` skill 的 `metabase_client`(路徑在 `config.json` 的 `metabase.scripts`)+ 環境變數 `METABASE_USER` / `METABASE_PASS` / `METABASE_URL`(未設時自動讀 Windows User 環境變數)。**缺套件或環境變數時 Metabase 腿會掛,但六家即時流仍可獨立運作。**
3. **網路**:需可連 `api.cnyes.com` / `money.udn.com` / `www.ctee.com.tw` / `www.moneydj.com` / `tw.stock.yahoo.com`。

## 與 Sino-notify-skill 的分工(務必遵守)

| 使用者要的是… | 用哪支 |
|---|---|
| 知道/查證某新聞、整理某股某題材的新聞內文(**輸出=新聞**) | **本 skill** |
| 發給客戶的盤前/0940 盤中快訊/00981A 推播(**輸出=大戶投推播**) | Sino-notify-skill |
| 「整理 XX 新聞」(無「推播/快訊/客戶」字樣) | 本 skill |
| 「整理 XX 做成盤中快訊/推播」 | Sino-notify-skill |

判準一句話:**目的是「得到新聞」用本 skill;目的是「產出大戶投推播」用
Sino-notify-skill**。Sino-notify-skill 內部自會呼叫本 skill 拿新聞,使用者
要推播時不需(也不該)先單獨叫本 skill。

## 新聞來源

| 來源 | 取法 | 時間 | 角色 |
|---|---|---|---|
| Metabase `cmoney.證券市場新聞` | 依代號/日期直查(借 sinopac-metabase client) | 有 | 內部、**歷史可回溯**(關鍵字搜尋主力) |
| cnyes 鉅亨 | `api.cnyes.com` 公開 JSON(`tw_stock`台股+`us_stock`美股),**內文已在回應內** | 有 | **即時最快**,內文免額外請求 |
| udn 經濟日報 | money RSS:`5590`證券 / `5591`產業 / `12017`金融 | 有 | 即時+深度,命中後抓內文 |
| ctee 工商時報 | `livenews/stock`+`/finance`+`/tech` HTML 爬 | URL 還原 | 補充,命中後抓內文 |
| anue 鉅亨子站(註) | 同 cnyes newslist API 但取不同 category(`wd_stock` 美股雷達 + `forex` 外匯) | 有 | 跟 cnyes 預設互補,**內文已在回應內** |
| MoneyDJ | `newsreallist.aspx` HTML 爬(table → newsviewer 連結) | 有(無年份自動補) | 補財金/產業/國際,命中後抓內文 |
| Yahoo 奇摩股市 | RSS:`tw.stock.yahoo.com/rss?category=tw-market` | 有 | 補台股盤面/個股,命中後抓內文 |

> 來源已收斂為**財金版面**(已排除 cnyes 綜合頭條、ctee 全站 livenews 的觀光/職場等非財金雜訊;udn「行情」非新聞無 RSS、ctee「要聞/專題」僅前端假分版故未納)。要更純或更廣改 `config.json` 的 `cnyes_categories`/`udn_feeds`/`ctee_pages`/`anue_categories`/`moneydj_pages`/`yahoo_feeds`。
>
> 註:`anue` source 標籤實際走 cnyes 公開 newslist API,因 `forum.cnyes.com` 在公司網路常 504,改取 cnyes 主流程未涵蓋的子站(美股雷達/外匯)避免完全重複,跟「鉅亨論壇」原意有差。詳見 `SUGGESTED_CONFIG.md`。

## 觸發後怎麼做

### Step 1:判斷查法

- 使用者給**代號/股名** → `--codes` 模式(可加 `--days=N`)
- 使用者給**關鍵字/事件**(「希捷產能極限」「SpaceX IPO」)→ `--keyword` 模式
- 兩者都有就一起帶

### Step 2:執行 CLI

```powershell
$env:PYTHONIOENCODING = 'utf-8'; chcp 65001 | Out-Null
$S = "C:\Users\<USER>\.claude\skills\stock-news-skill\scripts"
python -X utf8 "$S\news.py" --keyword=希捷,產能極限
python -X utf8 "$S\news.py" --codes=2408,8299 --days=7
python -X utf8 "$S\news.py" --keyword=低軌衛星 --source=sanbao
python -X utf8 "$S\news.py" --keyword=台積電 --individual-only      # 濾掉泛大盤
python -X utf8 "$S\news.py" --keyword=台積電 --no-sentiment         # 關掉利多利空標記
python -X utf8 "$S\news.py" --keyword=台積電 --format=md            # Markdown(可貼)
python -X utf8 "$S\news.py" --keyword=台積電 --format=json          # 純 JSON 到 stdout
python -X utf8 "$S\news.py" --report=2330,2454 --days=7             # 個股深度報告
python -X utf8 "$S\news.py" --report=2330 --days=7 --format=md      # 報告 + Markdown
```

輸出 console 摘要(含 `|利多 0.80|` 等 sentiment 標籤 + `事件: 訂單,法說`)+ `out/news_result.json`。`--format=md` 走 stdout 純 markdown,`--format=json` 走 stdout 純 JSON(方便 pipe 給下游),兩者進度訊息都走 stderr。

> Metabase 帳密走 `METABASE_USER/PASS/URL` 環境變數;子程序常拿不到 User-scope
> 變數,`news_core.py` 已內建用 PowerShell 回讀注入。

### Step 3:回報

讀 `out/news_result.json` 或主控台,**據實回報**:
- 有沒有這則(命中幾則、來源、時間)
- 引用內文重點(cnyes/anue 通常有全文,最具體)
- 參考 sentiment + events 標籤快速分群(例:`利空 0.67 事件:警示` 表示
  規則層偵測到負向警示語);**但 confidence < 0.3 時仍要自己看內文**,
  規則層只能抓得到字面情緒,反諷/客戶端利好讀為公司端利空等情境會誤判
- **新聞方向要看內文不要只看標題**(例:「希捷產能極限論」內文是 CEO 示警
  AI 產能跟不上、建廠緩不濟急 → 市場解讀利空,記憶體血洗)
- 查無就老實說查無,不杜撰

## 程式化呼叫(供其他 skill)

```python
import sys; sys.path.insert(0, r"...\stock-news-skill\scripts")
import news_core as NC
res = NC.query_news(codes=["2408","8299"], days=3)      # → res["by_code"]
res = NC.query_news(keyword="希捷,產能極限")             # → res["keyword_hits"]
res = NC.query_news(keyword="台積電", individual_only=True)  # 濾泛大盤
res = NC.query_news(keyword="台積電", tag_sentiment=False)  # 不標 sentiment(省時)

# 契約欄位(Sino-notify-skill 依賴):
#   news = {time, title, source, url, summary, body}
# 擴充欄位(tag_sentiment=True 時補,預設 True):
#   news += {sentiment, confidence, events}
# keyword_hits 額外有 {code, name}
# keyword_hits 已內建:近 N 日過濾 → 依標題去重 → udn/ctee/yahoo/moneydj 補內文
#                     → 依時間倒序 → sentiment 標記
```

`Sino-notify-skill` 即以此方式委派(其 `core.get_news()` 呼叫
`NC.query_news`),新聞碼只此一份、不重複。

> **API 契約**:`query_news()` 前 6 個參數順序鎖死為
> `(codes, keyword, days, source, fetch_body, individual_only)`,全部預設 None。
> 新功能用 keyword-only argument 加在後面(如 `tag_sentiment`),向後相容。
> `tests/test_query_news_api.py` 會自動把關。

## 設定(config.json)

| 欄位 | 意義 | 預設 |
|---|---|---|
| `metabase.scripts` | sinopac-metabase 的 scripts 路徑(借 client) | — |
| `news.source` | `metabase`/`sanbao`(歷史命名,含 6 家即時)/`both` | both |
| `news.lookback_days` | 預設回溯天數 | 3 |
| `news.cache_ttl_sec` | fetch_sanbao 進程內 TTL 快取秒數(0=關閉;同進程連查多次免重抓) | 120 |
| `news.cnyes_categories` / `cnyes_pages` | cnyes 抓的分類/頁數 | tw_stock,us_stock / 3 |
| `news.udn_feeds` / `udn_limit` | udn RSS 清單/每feed上限 | 證券/產業/金融 / 30 |
| `news.ctee_pages` / `ctee_limit` | ctee 列表頁/上限 | livenews/stock+finance+tech / 60 |
| `news.anue_categories` / `anue_pages` | anue 取 cnyes API 的子站/頁數 | wd_stock,forex / 2 |
| `news.moneydj_pages` / `moneydj_limit` | MoneyDJ 列表頁/上限 | newsreallist a=mb010000 / 40 |
| `news.yahoo_feeds` / `yahoo_limit` | Yahoo 股市 RSS/上限 | tw-market / 40 |
| `news.fetch_body` | 是否抓內文 | true |
| `news.body_max_chars` | 內文截斷字數 | 600 |
| `news.body_fetch_limit` | udn/ctee/yahoo/moneydj 內文抓取總量上限 | 40 |
| `news.individual_only` | keyword 是否濾掉泛大盤新聞 | false |
| `news.tag_sentiment` | 是否補 sentiment/confidence/events 標籤 | true |

## 檔案

```
stock-news-skill/
├── SKILL.md
├── config.json / config.example.json
├── SUGGESTED_CONFIG.md   anue/moneydj/yahoo 細部設定參考
├── scripts/
│   ├── news_core.py        Metabase 連線 + query_news() 公開 API
│   │                       + is_individual_news + _tag_sentiment_inplace()
│   │                       + fetch_sanbao / metabase關鍵字 TTL 快取(clear_news_cache())
│   ├── news_providers.py   6 家來源 cnyes/udn/ctee/anue/moneydj/yahoo
│   │                       ThreadPool 並行抓取 + 內文(urllib/bs4/feedparser)
│   ├── news_sentiment.py   規則層利多/利空(155/156 詞)+ 20 類事件分類
│   │                       + 否定/轉折/反轉/主體 上下文規則(純標準庫)
│   ├── news_formatters.py  console/md/json 三格式 + 個股深度報告 builder
│   └── news.py             CLI(--codes/--keyword/--days/--source/
│                           --individual-only/--no-sentiment/
│                           --format=console|md|json/--report=)
├── tests/
│   ├── test_health.py            6 家+Metabase 端點可達性
│   ├── test_query_news_api.py    query_news 簽名+回傳 schema 契約
│   ├── test_cli_smoke.py         CLI 黑箱(含 report/format)
│   ├── test_sentiment.py         classify 結構契約+強訊號方向(25 case)
│   ├── test_formatters.py        formatters 純函式(63 case)
│   ├── test_query_news_internals.py  去重/排序/過濾 monkeypatch(16 case)
│   └── run_all.ps1               一鍵跑全部(6/6)
└── out/news_result.json
```

## 利多/利空 + 事件標籤(規則層)

`news_sentiment.classify(title, body)` 在 keyword/by_code 模式最後一步被
`_tag_sentiment_inplace()` 對每則新聞呼叫,回填三個鍵:

| 鍵 | 型別 | 內容 |
|---|---|---|
| `sentiment`  | `"bullish"` / `"bearish"` / `"neutral"` | 利多/利空/中性 |
| `confidence` | 0~1 float | 差距 / (總分+1) |
| `events`     | list[str] | 20 類事件(法說/購併/警示/獲利預警/產能/訂單/訴訟/股利/增資/減資/公開收購/漲停/跌停/踩雷/財報/營收/庫藏股/法人動向/財務危機/重大訊息) |

詞庫規模:利多 155 詞、利空 156 詞、事件 20 類(自我測試 27 例全過)。除字面
計分外已內建上下文規則:**否定翻轉**(命中詞前 6 字內有「未/沒/不…」則翻轉
計分)、**轉折加權**(「但/卻/然而…」後子句 ×2)、**反轉慣用語**(「利空出盡」
判多、「利多出盡」判空)、**主體區分**(「客戶砍單」對被報導公司計利空)。
**`confidence < 0.3` 仍需自己看內文判**,規則層仍不懂完整語境、不會反諷,
「競爭對手搶單」這類主體判斷只部分涵蓋。

`tag_sentiment=False`(或 CLI `--no-sentiment`)可關掉,例如批次抓取要省時。

## 輸出格式(--format)

| 格式 | stdout | 寫檔 | 用途 |
|---|---|---|---|
| `console`(預設) | 對齊文字摘要 | ✓ `out/news_result.json` | 終端機快速看 |
| `md` | 乾淨 markdown(H2/list/引用塊/表格) | ✓ | 貼 Notion / Slack / 郵件 |
| `json` | 完整 JSON(同寫檔內容) | ✓ | pipe 給下游程式 |

`json` 模式進度訊息一律走 **stderr**,stdout 第一個非空字元就是 `{`,放心 `| python -c "import json,sys;print(json.load(sys.stdin)['keyword_hits'][0])"` 之類的 pipe。

## 個股深度報告(--report)

`--report=2330,2454 --days=7`(會自動覆蓋 `--codes`/`--keyword`),每檔輸出:

1. **Sentiment 分布表**:利多 / 利空 / 中性 / 合計
2. **事件統計**:按出現次數降序(法說/購併/警示/獲利預警/產能/訂單/...)
3. **來源分布**:metabase / cnyes / udn / yahoo / ctee / ...
4. **Top 5 重要新聞**:挑 `|confidence|` 最高的 5 則(平手用時間最近),含 url + body 摘要
5. **時序事件流**:只挑有 events 的,依時間倒序

搭 `--format=md` 出乾淨 markdown 報告可直接貼客戶/同事;搭 `--format=json` 報告結構放在 `out/news_result.json` 的 `reports` 鍵。

對外 API 也可呼叫:`news_formatters.build_report(code, name, items, days)` 是純函式,可重用。

## 測試與健康檢查

```powershell
$env:PYTHONIOENCODING = 'utf-8'; chcp 65001 | Out-Null
& "C:\Users\<USER>\.claude\skills\stock-news-skill\tests\run_all.ps1"
# Pass: 6/6 約 4 分鐘(health 4s / 契約 16s / CLI smoke 224s / 3 個單元測試 <1s)
```

| 測試檔 | 範圍 |
|---|---|
| `test_health.py`         | cnyes / udn x3 / ctee x3 / Metabase 8 個端點可達性 |
| `test_query_news_api.py` | 簽名鎖死前 6 參數順序+全部預設 None+回傳 schema 契約 |
| `test_cli_smoke.py`      | CLI 黑箱(codes / keyword / individual-only / sanbao) |
| `test_sentiment.py`      | classify 結構契約 + 強訊號方向 + 事件抽取(25 case,純記憶體) |
| `test_formatters.py`     | 計數/排序/build_report/render×5 純函式(63 case,純記憶體) |
| `test_query_news_internals.py` | monkeypatch 假新聞測去重/排序/時間過濾/個股過濾(16 case,不觸網) |

> 改 `query_news()` 簽名時測試會擋:新參數請加在後面、必須有預設值 None。
> 單元測試(sentiment/formatters/internals)純記憶體不觸網,秒級;改邏輯後先跑這三個快速回歸。

## 已知重點(踩過的雷)

- **公司網路 TLS 攔截**:`requests`+certifi 會 CERTIFICATE_VERIFY_FAILED;
  `news_providers.py` 全程走 stdlib `urllib`,SSL 失敗自動退回未驗證 context
  (內部受控網路 + 公開新聞源,可接受)。
- **cnyes 內文是 HTML 實體編碼**:先 `html.unescape` 再 BeautifulSoup 才乾淨。
- **anue ≠ 鉅亨論壇**:`forum.cnyes.com` 在公司網路常 504,改走 cnyes 公開
  newslist API 但取主流程未涵蓋的 category(`wd_stock` 美股雷達+`forex` 外匯)
  以區分標籤;`tw_stock_news` 跟 cnyes 預設 `tw_stock` 高度重疊會被 url 去重。
- **MoneyDJ 時間欄無年份**:列表頁只給 `MM/DD HH:MM`,parser 取當年,若日期
  大於今日則退回去年(跨年保險)。
- **效能**:六家來源以 `ThreadPoolExecutor` 並行抓(序列 ~7.3s → 並行 ~5s);
  `fetch_sanbao` 有進程內 TTL 快取(`cache_ttl_sec`,預設 120s),同進程連查多
  個 keyword 免重抓(實測 _pick.py 連查 6 詞 19s→1.9s,`clear_news_cache()`
  可清、`cache_ttl_sec=0` 可關)。**Metabase 關鍵字搜尋**同理:
  `search_metabase_keyword` 的 SQL 不含 keyword 條件(撈近 N 日全部標題、過濾
  在記憶體做),撈回列由 `_fetch_metabase_news_rows` 做進程內 TTL 快取(共用
  `cache_ttl_sec`/`clear_news_cache()`,key=days),同進程連查多 keyword 只撈一
  次大表(實測 6 詞純 metabase 路徑首查後其餘 5 次 ~0s)。外部內文只對「命中」的抓(cnyes/anue 免抓,
  內文已在 list),同 url 只抓一次,上限 `body_fetch_limit`。快取是**進程內**,
  跨 CLI 進程(如 test_cli_smoke 各 case)不共用。
- **六家獨立容錯**:任一家失敗只印 warn 不中斷;`fetch_sanbao` 內部 try/except
  逐家包覆。
- **關鍵字查方向**:一定看內文判利多/利空,標題常誤導(尤其 ctee/moneydj 列表
  常無內文)。keyword 模式已內建補 udn/ctee/moneydj/yahoo 內文 + 依標題去重 +
  近 N 日過濾 + 依時間倒序 + sentiment 標記(呼叫端不需自理);
  `individual_only=True` 可再濾掉泛大盤新聞。
- **PowerShell 5.1 `2>&1 | Select -First N`** 會把 stderr 混進 stdout 觸發
  `NativeCommandError` + Exit 255,不是 Python 真的炸。長輸出測試走
  `1> stdout.txt 2> stderr.txt` 分流。

> 相依套件 / 網路網域 / Metabase client 需求見上方「## 前置需求」。
