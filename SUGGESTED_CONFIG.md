# config.json 建議新增鍵 (Anue / MoneyDJ / Yahoo)

供使用者事後合併到 `config.json` 的 `news` 區塊。所有鍵都有 hard-coded
預設值在 `news_providers.fetch_sanbao` 內,**不填也能跑**;以下僅供調整時參考。

```jsonc
{
  "news": {
    /* ---- 原有鍵保留 ---- */

    /* ---- Anue 鉅亨 (走 cnyes newslist API,但取主流程未覆蓋的子站) ---- */
    // categoryId 對照(節選):
    //   wd_stock   = 美股雷達      (predefault,與 cnyes_categories 的 tw_stock 不重疊)
    //   forex      = 外匯
    //   tw_stock_news = 台股新聞   (注意:tw_stock 子集,易被 url 去重幹掉)
    //   headline   = 頭條          (已在 cnyes_categories 預設使用,勿重複)
    "anue_categories": ["wd_stock", "forex"],
    "anue_pages": 2,

    /* ---- MoneyDJ 新聞列表 (HTML 爬,連結 newsviewer.aspx) ---- */
    // 列表 URL 範例:
    //   a=mb010000 → 頭條/總覽
    //   a=mb030000 → 國際財經
    //   a=mb050000 → 產業動態
    "moneydj_pages": [
      "https://www.moneydj.com/kmdj/news/newsreallist.aspx?a=mb010000"
    ],
    "moneydj_limit": 40,

    /* ---- Yahoo 奇摩股市 (RSS,走 feedparser) ---- */
    // RSS URL 範例:
    //   category=tw-market   → 台股市場
    //   category=intl-market → 國際市場
    "yahoo_feeds": [
      "https://tw.stock.yahoo.com/rss?category=tw-market"
    ],
    "yahoo_limit": 40
  }
}
```

## 行為註記

1. **Anue source 標籤為 `anue`**(不是 `cnyes`),`attach_bodies` 已加入白名單
   略過內文抓取(因 newslist API 已內含 `content`,免再上網抓)。
2. **MoneyDJ 列表頁時間欄位無年份**(只有 `MM/DD HH:MM`),解析時取當年;
   若 `MM/DD` 大於今日則視為去年。
3. **Yahoo RSS 走 feedparser** 同 udn,`body` 留空,命中個股時才透過
   `attach_bodies` 抓 `div.caas-body`。
4. **每家獨立 try/except**:任一家失敗(網路斷/HTML 改版)只 stderr 警告,
   不會中斷其他家或整個 `fetch_sanbao`。
5. **去重 key 為 `url or title`**:同一篇文章被多家 source 抓到時,
   保留**最先進入清單者**的 source 標籤(目前順序:cnyes → udn → ctee
   → anue → moneydj → yahoo);若希望 anue 優先,把 anue 寫到 fetch_sanbao
   清單最前面即可。
