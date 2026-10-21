# CLI 完整用法(news.py)

何時讀：要用到 SKILL.md 沒列的旗標、要確認某個模式的細節（回溯天數、去重、內文完整度），或要產 `--report` 時。

## 語法

- 只認 `--旗標=值`。`--days 7` 這種空格寫法與拼錯的旗標一律靜默忽略。
- `--days=abc` 會直接 traceback；`--format` 只接受 `console`、`md`、`json`（不分大小寫，其他值 exit 2）；`--codes`、`--keyword`、`--report`、`--today` 一個都沒給時 exit 1。
- 開關旗標（`--all`、`--intl`、`--today`、`--individual-only`、`--no-sentiment`）只能單寫，寫成 `--all=true` 會被忽略；`--out` 兩種都收。
- `--source` 不檢查值。打錯（例如 `--source=cnyes`）不會報錯：`--keyword` 三條腿都不跑，結果是空的；`--codes`、`--report` 只剩個股直取（`cnyes-search`、`yahoo-quote`）的結果。

## 旗標

| 旗標 | 作用 |
|---|---|
| `--codes=2330,2454` | 依代號查。傳股名不會報錯，但只會被當成字串比對與搜尋（沒有別名比對），股名請用 `--keyword` |
| `--keyword=A,B` | 依關鍵字查。只有半形逗號會切詞（全形逗號、頓號、空白都不會切）；英文大小寫有別（`nvidia` 不會命中 `NVIDIA`）；含空白的詞要字面連續出現 |
| `--days=N` | 回溯天數，預設 config 的 `lookback_days`（3）。`--keyword` 模式至少 10 天（小於 10 等同 10）；`--today` 不吃這個旗標 |
| `--source=metabase\|sanbao\|both` | 只用 Metabase、只用即時流（含 cnyes 全站搜尋）、兩者併用。預設 both；Metabase 不可用時 both 自動退成 sanbao |
| `--all` | 多個關鍵字改成全部都要出現。cnyes 搜尋腿只回命中處的短片段，AND 時那條腿幾乎不會命中 |
| `--intl` | 只留國際類版面的命中（白名單見下方），只對 `--keyword` 有效 |
| `--individual-only` | 剔除標題含 三大法人、台股、大盤、加權、收盤、權證、外資賣超、外資買超、投信買超、怒神、創新高不敵 的新聞。個股標題含「台股」「收盤」也會被剔除。只對 `--keyword` 有效，查證某消息有沒有報導時不要加 |
| `--no-sentiment` | 不標 sentiment 與 events。`--report` 會全部算中性，Top 5 改依時間 |
| `--format=console\|md\|json` | 輸出格式，見下方 |
| `--out=auto`、`--out=路徑`（單寫 `--out` 等同 auto） | 寫到自己的 JSON 檔，內文截到 `body_max_chars`，不碰共用的 `out/news_result.json`。對 `--today` 無效 |
| `--report=2330,2454` | 個股深度報告，會蓋掉 `--codes` 與 `--keyword` |
| `--today`（別名 `--digest`） | 今日議題重點的原料 |

## 各模式在做什麼

### --codes

1. Metabase 依代號直查。只有標題，沒有內文與連結。Metabase 不可用時跳過。
2. 個股直取（config `per_stock_fetch`，預設開，不受 `--source` 控制）：cnyes 全站搜尋（有股名用股名，沒有就用代號）加 Yahoo 個股頁新聞，來源標成 `cnyes-search`、`yahoo-quote`。`yahoo-quote` 的時間是查詢當下，不是發布時間。
3. 即時流比對：股名、代號字串、出版商標的代號、別名字典，比對標題、摘要與內文。
4. 同一檔內以完全相同的標題去重，先到先留（順序是 Metabase、直取、即時流），所以和 Metabase 同標題的全文版會被丟掉。
5. 時間：一般新聞取近 `days` 天；標題含目標價、EPS、評等、法說、券商、預估等報告型字眼的新聞改用 `report_days`（預設 10）天。這是取代不是取大：`--days` 大於 10 時，報告型新聞反而只留 10 天。沒有發布時間的新聞一律保留。
6. 股名來源：有傳 `names` 就用它，缺的直接查離線清單（不查 Metabase）；沒傳時，source 不是 sanbao 且 Metabase 可用才先查 Metabase，查不到的再依序查 `data/stocks/tw_names.json`（官方全市場）、`data/stocks/tw_stocks.json`（策展）；都沒有就只靠代號比對。2026-10-21 起，有 Metabase 時漏名的代號也會這樣補名並比對（以前整檔跳過）。
7. 結果不依時間排序。console 每檔最多印 6 則（標頭的則數才是總數），要看全部請用 md 或 json。

### --keyword

處理順序：

1. 三條腿合併：Metabase 標題加內文（source 為 metabase 或 both）、即時流標題摘要內文、cnyes 全站搜尋（`kw_search_cnyes`，預設開，source 為 sanbao 或 both）。
2. `--intl` 時只留白名單版面。
3. 近 max(days, 10) 天，沒有日期的保留。
4. 依標題去重，留內文較長的那則。
5. 補內文：body 空、有連結、來源不是 metabase、cnyes、anue 的才補，上限 `body_fetch_limit`。
6. 命中片段 `snippets`：取自內文，沒有內文才用摘要；每個命中前後各 60 字，最多 3 段；只有標題命中時是空的。
7. `--individual-only` 過濾，依時間倒序，標 sentiment。

`code`、`name` 只有 Metabase 命中有值（同一篇關聯多檔時只留其中一檔），即時流與 cnyes 搜尋的命中是空字串。

`--intl` 白名單（來源的版面名）：國際焦點、國際綜合、美股雷達、全球財經、國際股市、外匯、期貨、國際財經、美股、日股、國際政經、美股盤中、美股預估、歐亞股。Metabase 命中沒有版面名，會全部排除；中央社、自由財經、ETtoday、MoneyDJ、科技新報的版面不在名單內，也不會保留。

### --today

- 時間窗：前一交易日 14:00 到現在（跳過週末與 `data/calendar/tw_holidays.json` 的休市日）。這只是下界過濾，每個分類或 feed 只取最新 10 到 15 則（cnyes 每類 15，其餘每條 feed 或 ctee 每分類 10）；沒有發布時間的新聞不納入。
- 靜默忽略 `--codes`、`--keyword`、`--days`、`--source`、`--individual-only`、`--report`；`--out`、`--intl`、`--all` 會在 stderr 提示後忽略；`--no-sentiment` 有效。
- 一定會寫兩個檔：`out/news_result.json`（結構是 `mode`、`date`、`count`、`items`，`items[].body` 是全文），以及 `out/today_news_YYYYMMDD.md`（表頭統計加依來源分組的清單，每則一行時間、情緒、事件、標題連結，沒有內文）。
- stdout：console 版沒有連結；`--format=md` 有連結；`--format=json` 是含全文的完整內容。標題固定寫成「盤前（涵蓋 MM/DD 14:00～現在）」，盤後執行也一樣，要當日的部分請看 `time` 欄。

### --report

每檔輸出五段：情緒分布（利多、利空、中性、合計）、事件統計（依次數）、來源分布、Top 5（`|confidence|` 最高，平手取較新）、事件時序（只列有 events 的，時間倒序）。標頭寫「近 N 日」，但報告型新聞可能到 10 天前。`--format=md` 可以直接貼給同事；`--format=json` 時報告放在輸出檔的 `reports` 鍵。`news_formatters.build_report(code, name, items, days)` 是純函式，可重用。

## 輸出格式

| 格式 | stdout | 用途 |
|---|---|---|
| `console`（預設） | 每則一行 `[來源\|時間\|利多 0.80] 標題`，下一行 `事件: 訂單, 法說`；關鍵字命中會印命中片段 | 終端機快速看 |
| `md` | 乾淨的 Markdown（標題、清單、引用、表格） | 貼 Notion、Slack、郵件 |
| `json` | 完整 JSON，第一個非空字元就是 `{` | 給程式讀 |

- 進度訊息一律走 stderr；`[輸出] 路徑` 那行告訴你寫到哪個檔。
- 沒有 `--out` 時寫 `out/news_result.json`，內文不截斷；有 `--out` 時內文截到 `body_max_chars`（預設 600）。
- Windows PowerShell 5.1：`|` 會插入 BOM 並把中文變成 `?`，`>` 會存成 UTF-16。要給程式吃就用 `--out=auto`，再用 `json.load(open(path, encoding="utf-8"))` 讀檔。Git Bash 與 cmd 的管線沒有這個問題。

## 更多範例

```powershell
python -X utf8 "$S\news.py" --keyword=低軌衛星 --source=sanbao --out=auto   # 只用即時流
python -X utf8 "$S\news.py" --keyword=台積電 --individual-only --out=auto    # 剔除泛大盤標題
python -X utf8 "$S\news.py" --keyword=台積電 --no-sentiment --out=auto       # 不標情緒
python -X utf8 "$S\news.py" --keyword=希捷,產能極限 --all --out=auto         # 兩個詞都要出現
python -X utf8 "$S\news.py" --keyword=OpenAI --format=json --out=auto        # JSON 寫到自己的檔
python -X utf8 "$S\news.py" --report=2330,2454 --days=7 --out=auto           # console 報告
python -X utf8 "$S\news.py" --report=2330 --days=7 --format=md --out=auto    # Markdown 報告
python -X utf8 "$S\news.py" --today                                         # 今日原料(console)
```
