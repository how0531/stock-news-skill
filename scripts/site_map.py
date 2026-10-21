"""來源網站地圖 (site_maps) 載入、驗證與索引彙整。

Phase 2 交付物的程式入口：
- load_all()  讀取 data/site_maps/*.json
- validate()  檢查每份地圖具備必要欄位、stock_relevant_columns 與 columns 一致
- build_index() 彙整成單一 manifest，供下游 skill（資訊大腦 / 推播）一次讀取

用法：
  python scripts/site_map.py            # 驗證並印出摘要表
  python scripts/site_map.py --index    # 同時寫出 data/site_maps/_index.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SITE_MAPS = Path(__file__).resolve().parent.parent / "data" / "site_maps"
INDEX_FILE = SITE_MAPS / "_index.json"

REQUIRED_KEYS = {
    "source_id", "label", "agent", "home", "access",
    "columns", "stock_relevant_columns", "cleaning",
    "researched_via", "researched_at", "verified_live",
}
REQUIRED_ACCESS_KEYS = {"method", "endpoints", "implemented_in"}
VALID_METHODS = {"json_api", "sitemap", "html", "rss", "openapi"}


def load_all() -> dict[str, dict]:
    """讀取所有 site_map（檔名以 _ 開頭者為產出物，略過）。"""
    out: dict[str, dict] = {}
    for path in sorted(SITE_MAPS.glob("*.json")):
        if path.name.startswith("_"):
            continue
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        out[path.stem] = data
    return out


def validate(maps: dict[str, dict]) -> list[str]:
    """回傳問題清單；空清單代表全部通過。"""
    problems: list[str] = []
    for sid, m in maps.items():
        missing = REQUIRED_KEYS - set(m)
        if missing:
            problems.append(f"{sid}: 缺少欄位 {sorted(missing)}")
            continue
        if m.get("source_id") != sid:
            problems.append(f"{sid}: source_id={m.get('source_id')!r} 與檔名不符")

        access = m.get("access", {})
        amiss = REQUIRED_ACCESS_KEYS - set(access)
        if amiss:
            problems.append(f"{sid}: access 缺少 {sorted(amiss)}")
        elif access.get("method") not in VALID_METHODS:
            problems.append(f"{sid}: access.method={access.get('method')!r} 非法")

        col_names = {c.get("name") for c in m.get("columns", [])}
        relevant_flagged = {c.get("name") for c in m.get("columns", []) if c.get("stock_relevant")}
        declared = set(m.get("stock_relevant_columns", []))
        if not declared:
            problems.append(f"{sid}: stock_relevant_columns 為空")
        if not declared <= col_names:
            problems.append(f"{sid}: stock_relevant_columns 有不在 columns 內的項目 {sorted(declared - col_names)}")
        if declared != relevant_flagged:
            problems.append(
                f"{sid}: stock_relevant_columns 與 columns 內 stock_relevant=true 不一致 "
                f"(宣告 {sorted(declared)} vs 旗標 {sorted(relevant_flagged)})"
            )
    return problems


def build_index(maps: dict[str, dict]) -> dict:
    """彙整成單一 manifest。"""
    sources = []
    for sid, m in maps.items():
        sources.append({
            "source_id": sid,
            "label": m.get("label"),
            "agent": m.get("agent"),
            "method": m.get("access", {}).get("method"),
            "implemented_in": m.get("access", {}).get("implemented_in"),
            "history_backfill": m.get("access", {}).get("history_backfill", False),
            "n_columns": len(m.get("columns", [])),
            "stock_relevant_columns": m.get("stock_relevant_columns", []),
            "verified_live": m.get("verified_live", False),
        })
    return {
        "phase": "2_structure_map",
        "n_sources": len(sources),
        "n_verified_live": sum(1 for s in sources if s["verified_live"]),
        "sources": sources,
    }


def main(argv: list[str]) -> int:
    maps = load_all()
    problems = validate(maps)

    print(f"{'SOURCE':<14}{'METHOD':<10}{'COLS':>5}{'REL':>5}{'LIVE':>6}  AGENT")
    print("-" * 72)
    for sid, m in maps.items():
        access = m.get("access", {})
        print(f"{sid:<14}{access.get('method', '?'):<10}"
              f"{len(m.get('columns', [])):>5}{len(m.get('stock_relevant_columns', [])):>5}"
              f"{'✓' if m.get('verified_live') else '✗':>6}  {m.get('agent', '')}")
    print("-" * 72)
    print(f"{len(maps)} 來源；通過驗證 {len(maps) - len({p.split(':')[0] for p in problems})}/{len(maps)}")

    if problems:
        print("\n問題：")
        for p in problems:
            print(f"  - {p}")

    if "--index" in argv:
        index = build_index(maps)
        INDEX_FILE.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n已寫出 {INDEX_FILE}")

    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
