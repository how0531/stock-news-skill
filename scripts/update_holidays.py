# -*- coding: utf-8 -*-
"""從證交所更新台股休市日 data/calendar/tw_holidays.json。

用法:
  python scripts/update_holidays.py              # 今年與明年(明年還沒公布就略過)
  python scripts/update_holidays.py 2025 2026    # 指定年度(證交所網站從 2021 年起有資料)
  python scripts/update_holidays.py --force      # 官方資料會移除既有日期時仍寫入
颱風等臨時停市不在證交所休市表裡,要手動加在檔內 _adhoc,例如 {"2026": ["2026-07-10"]},
再跑一次本程式併進年度清單;更新永遠不會移除 _adhoc 的日子。
storage._is_closed 查到缺少今年或明年時,也會自動呼叫一次 update()。
"""
import datetime
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

API = "https://www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule?response=json&date={year}0101"
HOLIDAY_FILE = Path(__file__).resolve().parent.parent / "data" / "calendar" / "tw_holidays.json"


def _is_open(date_iso, name, desc):
    """開始交易日、最後交易日照常開盤;但名稱或說明寫明「該日市場無交易」的不算
    (2021、2022 年春節前只辦結算的日子也叫「最後交易日」,說明寫「2月8日市場無交易」)。"""
    m, d = int(date_iso[5:7]), int(date_iso[8:10])
    return "交易日" in name and "無交易" not in name and f"{m}月{d}日市場無交易" not in desc


def closed_dates(rows):
    """證交所列 [日期 YYYY-MM-DD, 名稱, 說明] → 休市日清單。任何一列格式不對就整批失敗。"""
    out = set()
    for r in rows:
        if not isinstance(r, (list, tuple)) or len(r) < 2 or not str(r[1] or "").strip():
            raise ValueError(f"休市表列格式不對:{r!r}")
        date_iso, name = str(r[0] or ""), str(r[1])
        desc = str(r[2] or "") if len(r) > 2 else ""
        datetime.date.fromisoformat(date_iso)
        if not _is_open(date_iso, name, desc):
            out.add(date_iso)
    return sorted(out)


def validate_adhoc(adhoc):
    """_adhoc 必須是 {年: [該年的 YYYY-MM-DD, ...]},否則丟 ValueError(手動編輯最容易出錯的地方)。"""
    if not isinstance(adhoc, dict):
        raise ValueError(f"_adhoc 必須是物件,收到 {type(adhoc).__name__}")
    for year, dates in adhoc.items():
        if not isinstance(dates, list):
            raise ValueError(f"_adhoc[{year!r}] 必須是日期清單")
        for s in dates:
            if (not isinstance(s, str) or datetime.date.fromisoformat(s).isoformat() != s
                    or not s.startswith(f"{year}-")):
                raise ValueError(f"_adhoc[{year!r}] 的日期不對:{s!r}(格式 YYYY-MM-DD,年份要和鍵相同)")
    return adhoc


def fetch_year(year, timeout=15):
    """抓證交所某一年的休市表。還沒公布回 []。"""
    req = urllib.request.Request(API.format(year=year), headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        j = json.loads(r.read().decode("utf-8"))
    if j.get("stat") != "ok":
        raise RuntimeError(f"證交所回應異常:{j.get('stat')!r}")
    dates = closed_dates(j.get("data") or [])
    if any(not d.startswith(f"{year}-") for d in dates):
        raise RuntimeError(f"{year} 年休市表混入其他年度的日期,不更新")
    return dates


def _load(path):
    """讀休市檔;接受 UTF-8 BOM(記事本或 PowerShell 存檔會加)。壞檔直接報錯,絕不自動重建。
    回傳 (資料, 是否帶 BOM)。"""
    if not path.exists():
        return {}, False
    raw = path.read_bytes()
    try:
        return json.loads(raw.decode("utf-8-sig")), raw.startswith(b"\xef\xbb\xbf")
    except ValueError as e:
        raise RuntimeError(f"{path} 無法解析,請修正後重跑(不會自動重建,以免手動補的 _adhoc 遺失):{e}") from e


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        for i in range(5):                       # Windows 上別的進程正在讀時 replace 會被拒
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if i == 4:
                    raise
                time.sleep(0.2)
    finally:
        if tmp.exists():
            tmp.unlink()


class _FileLock:
    """跨進程鎖,讓「讀檔、合併、寫檔」不會被另一個進程的更新蓋掉。超過 60 秒的舊鎖視為持有者當掉。"""

    def __init__(self, path, wait=10):
        self.path, self.wait = path.with_name(path.name + ".lock"), wait

    def __enter__(self):
        deadline = time.time() + self.wait
        self.path.parent.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                os.close(os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                return self
            except FileExistsError:
                # shortcut: 兩個進程同時清同一個舊鎖時可能都拿到鎖(只在持有者被硬殺後發生,
                # 蓋掉的年度下次缺年度會自動補回);要嚴格互斥再改用 msvcrt.locking
                try:
                    if time.time() - self.path.stat().st_mtime > 60:
                        self.path.unlink()
                        continue
                except OSError:                  # 別的進程剛清掉或正在清,當成鎖忙碌
                    pass
            except PermissionError:              # Windows:鎖檔正在被刪除
                pass
            if time.time() > deadline:
                raise RuntimeError(f"等不到休市檔的更新鎖 {self.path}")
            time.sleep(0.2)

    def __exit__(self, *exc):
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


def update(years=None, path=None, force=False, timeout=15):
    """抓指定年度(預設今年與明年)寫回檔案,只改有變動的年度。
    官方資料會移除既有日期時,沒有 force 就拒絕寫入。回傳 {年: (新增日, 移除日)}。"""
    path = Path(path) if path else HOLIDAY_FILE
    today = datetime.date.today()
    years = [int(y) for y in (years or [today.year, today.year + 1])]
    fetched = {y: fetch_year(y, timeout) for y in years}   # 先全部抓完,網路失敗就不動檔
    with _FileLock(path):
        data, had_bom = _load(path)
        adhoc = validate_adhoc(data.get("_adhoc") or {})
        changed = {}
        for y, official in fetched.items():
            if not official:                     # 證交所還沒公布
                continue
            key = str(y)
            new = sorted(set(official) | set(adhoc.get(key, [])))
            old = data.get(key, [])
            removed = sorted(set(old) - set(new))
            if removed and not force:
                raise RuntimeError(f"{y} 年官方資料會移除 {removed},未寫入;確認無誤後加 --force")
            if set(new) != set(old):
                changed[key] = (sorted(set(new) - set(old)), removed)
                data[key] = new
        if not changed and not had_bom:
            return changed
        meta = data.get("_meta") or {}
        if changed:
            meta.update({
                "description": "台股休市日(證交所公告,含落在週末的假日與春節前只辦結算的日子;"
                               "颱風等臨時停市放 _adhoc)。compute_actionable_ts 與 --today 時間窗據此跳過休市日。",
                "source": API.format(year="YYYY"),
                "verified_years": sorted(set(meta.get("verified_years", [])) | set(changed)),
                "updated": today.isoformat(),
                "maintenance": "執行 python scripts/update_holidays.py;缺少今年或明年時 storage 會自動嘗試一次。",
            })
            for k in ("verified", "note"):       # 舊版依規則推算時的欄位,已不適用
                meta.pop(k, None)
        out = {"_meta": meta, "_adhoc": adhoc}
        out.update({k: v for k, v in data.items() if k.startswith("_") and k not in out})
        out.update({k: data[k] for k in sorted(k for k in data if not k.startswith("_"))})
        _write(path, out)                        # 帶 BOM 的檔順便改存成無 BOM(render_premarket 讀不了 BOM)
        if not changed:
            print(f"[holiday] {path.name} 帶 BOM,已改存成無 BOM(日期沒變)", file=sys.stderr)
        return changed


if __name__ == "__main__":
    args = sys.argv[1:]
    force = "--force" in args
    yrs = [a for a in args if a != "--force"] or None
    try:
        result = update(yrs, force=force)
    except Exception as e:
        print(f"更新失敗:{e!r}", file=sys.stderr)
        sys.exit(1)
    if not result:
        print("沒有變動(或指定年度證交所尚未公布)")
    for year, (added, removed) in sorted(result.items()):
        print(f"{year}: 新增 {added or '無'};移除 {removed or '無'}")
