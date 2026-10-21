# 來源網站地圖 (site_maps)

每個檔案 `{source_id}.json` 描述一個新聞來源的結構，由一個具名 agent（如「鉅亨網agent」）
研究後產出，作為三階段工程的 **Phase 2 交付物**：

1. **Phase 1 連通性** — 確認每個來源可被讀取（`scripts/healthcheck.py`，需網路）
2. **Phase 2 結構地圖** — 列出該站專欄、標記對股市有幫助的欄目 **(本檔案)**
3. **Phase 3 統一清洗** — 各來源輸出對齊 `data/stream/*.jsonl` schema

## Schema

```jsonc
{
  "source_id": "cnyes",              // 內部代號，對應 scripts/ 與 rss_sources SOURCES
  "label": "鉅亨網",                  // 顯示名
  "agent": "鉅亨網agent",             // 負責研究的具名 agent
  "home": "https://news.cnyes.com",
  "access": {
    "method": "json_api|sitemap|html|rss|openapi",
    "endpoints": ["..."],            // 已知可用端點
    "implemented_in": "scripts/cnyes.py",
    "history_backfill": true          // 是否能歷史回溯
  },
  "columns": [                        // 全站專欄盤點
    { "name": "台股", "url": "...", "stock_relevant": true, "note": "..." }
  ],
  "stock_relevant_columns": ["台股", "國際股"],  // columns 中 stock_relevant=true 的快照
  "noise_notes": "需過濾的雜訊類型（如純技術科普、娛樂）",
  "cleaning": {                       // Phase 3 對齊提示
    "publish_ts": "來源時間欄位與時區處理",
    "dedup": "norm_title 跨源去重"
  },
  "researched_via": "websearch",     // 研究方法（sandbox egress 受限時用 websearch）
  "researched_at": "2026-06-13",
  "verified_live": false              // 是否已用真實連線驗證（Phase 1）
}
```

`verified_live` 一律先標 `false`；待有可用連線（本機 / VPS / 開通白名單）後
跑 `scripts/healthcheck.py` 與實際抓取，再逐一改為 `true`。
