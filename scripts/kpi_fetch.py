# kpi_fetch.py — 盤前摘要「大盤速覽」九格取數（Metabase ClickHouse 直查）
# 用法: python kpi_fetch.py <out.md>
# exit 0=完整 / 2=部分取到（呼叫端記黃燈，卡片會標示）/ 1=完全失敗
#
# 為什麼要有這支：KPI 數字若讓模型從新聞標題抄，週一早上的新聞流已洗掉上週五盤後籌碼，
# 九格只填得出一格且可能抄到過期數字。改由程式直查資料庫，數字要嘛正確要嘛留空。
# 四段查詢各自 try：壞一格不該讓其他八格一起消失。
import datetime
import os
import pathlib
import re
import sys

# 相對定位隔壁 skill，不寫死個人絕對路徑（換機器或換人接手才不會 ImportError）
_MB = pathlib.Path(__file__).resolve().parents[2] / 'sinopac-metabase' / 'scripts'
sys.path.insert(0, str(_MB))
from metabase_client import MetabaseClient  # noqa: E402

DB = int(os.environ.get('METABASE_DB_CMONEY', 10))  # 10 = ClickHouse（cmoney 所在）
MAX_LAG_DAYS = 4      # 資料日落後超過此天數就不輸出（連假最多 4 天）
FULL_ROWS = 9         # 視為「完整」的最少格數
MIN_MARGIN_STOCKS = 1200   # 融資券與收盤價比對後的最少檔數


def arrow(v):
    return '▲' if v > 0 else ('▼' if v < 0 else '')


def signed(v, unit, digits=1):
    """買賣超只用正負號表示，不寫「買超／賣超」字樣（使用者 2026-08-10 指定）"""
    return f"{v:+,.{digits}f}{unit}"


def main(out_path):
    cli = MetabaseClient()
    rows = []
    warns = []

    # 交易日以日收盤表為準，並斷言新鮮度：ETL 延遲時寧可不出速覽，也不出過期數字
    d = str(cli.query_df('SELECT max("日期") AS d FROM cmoney."日收盤表排行"', db=DB).iloc[0, 0])[:10]
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', d):
        sys.exit(f'資料日格式異常: {d}')
    lag = (datetime.date.today() - datetime.date.fromisoformat(d)).days
    if lag > MAX_LAG_DAYS:
        sys.exit(f'日收盤表資料日 {d} 落後 {lag} 天，不輸出大盤速覽')

    # ── 指數與成交金額 ──
    try:
        idx = cli.query_df(f'''
SELECT "股票代號","收盤價","漲跌","漲幅(%)" AS pct,"成交金額(千)" AS turn
FROM cmoney."日收盤表排行"
WHERE "日期" = toDate('{d}') AND "股票代號" IN ('TWA00','TWC00')
''', db=DB)
        m = {r['股票代號']: r for _, r in idx.iterrows()}
        # 指數漲跌只留 %（使用者 2026-08-10：點數拿掉）；成交金額附前一交易日變化 %
        if 'TWA00' in m:
            r = m['TWA00']
            rows.append(f"- 加權指數: {r['收盤價']:,.2f} {arrow(r['漲跌'])}{abs(r['pct']):.2f}%")
            turn_line = f"- 成交金額: {r['turn'] / 100000:,.0f}億元"
            try:
                pt = cli.query_df(f'''
SELECT "成交金額(千)" AS turn
FROM cmoney."日收盤表排行"
WHERE "股票代號" = 'TWA00' AND "日期" < toDate('{d}')
ORDER BY "日期" DESC LIMIT 1
''', db=DB)
                if len(pt) and pt.iloc[0]['turn']:
                    tchg = (r['turn'] / pt.iloc[0]['turn'] - 1) * 100
                    turn_line += f" {arrow(tchg)}{abs(tchg):.1f}%"
            except Exception as e:
                warns.append(f'前日成交金額取數失敗: {e}')
            rows.append(turn_line)
        if 'TWC00' in m:
            r = m['TWC00']
            rows.append(f"- 櫃買指數: {r['收盤價']:,.2f} {arrow(r['漲跌'])}{abs(r['pct']):.2f}%")
    except Exception as e:
        warns.append(f'指數取數失敗: {e}')

    # ── 三大法人（上市口徑，與加權指數一致）──
    INST_LABEL = {'A003': '外資', 'A002': '投信', 'A001': '自營商'}
    try:
        inst = cli.query_df(f'''
SELECT "代號" AS c,"上市買賣超金額(百萬)" AS mkt
FROM cmoney."三大法人買賣超"
WHERE "日期" = toDate('{d}') AND "代號" IN ('A001','A002','A003')
''', db=DB)
        im = {r['c']: r['mkt'] for _, r in inst.iterrows()}
        for code in ('A003', 'A002', 'A001'):
            if code in im:
                rows.append(f"- {INST_LABEL[code]}: {signed(im[code] / 100.0, '億元')}")  # 百萬→億
    except Exception as e:
        warns.append(f'三大法人取數失敗: {e}')

    # ── 融資 / 融券 ──
    # cmoney「資餘/券餘」單位是張不是金額（實測台積電 29,657 張 × 2,370 元），
    # 證交所官方放款金額表 twse.margin_short_market 停更於 2023-11-03，故餘額用
    # 「張數 × 收盤價」市值口徑。增減金額 = Σ(增減張數 × 當日收盤價)，只計量的
    # 變化不含價格效果（若改用 Δ(q×p) 會混入 Σ(q_{t-1} × Δp)，大跌日與量反向）。
    # 兩表分開查再 pandas merge：ClickHouse 端 join 這兩張表會撞 server 30 秒 timeout。
    try:
        # 融資券表 ETL 常晚於日收盤表，用它自己的最新日並在落後時標示，
        # 比整格空著有用（前一交易日的融資餘額仍有參考價值，只要講清楚是哪天）
        md_ = str(cli.query_df('SELECT max("日期") AS d FROM cmoney."日融資券排行"',
                               db=DB).iloc[0, 0])[:10]
        if md_ != d:
            warns.append(f'融資券資料日 {md_}（落後現貨 {d}）')
        mg = cli.query_df(f'''
SELECT "股票代號" AS code,"資餘" AS mb,"資增減" AS md,"券餘" AS sb,"券增減" AS sd
FROM cmoney."日融資券排行"
WHERE "日期" = toDate('{md_}') AND match("股票代號", '^[0-9]{{4}}$')
''', db=DB)
        px = cli.query_df(f'''
SELECT "股票代號" AS code,"收盤價" AS px
FROM cmoney."日收盤表排行"
WHERE "日期" = toDate('{md_}') AND match("股票代號", '^[0-9]{{4}}$')
''', db=DB)
        mm = mg.merge(px, on='code', how='inner').dropna(subset=['px'])
        if len(mm) < MIN_MARGIN_STOCKS:
            warns.append(f'融資券比對僅 {len(mm)} 檔（低於 {MIN_MARGIN_STOCKS}），不輸出這兩格')
        else:
            for label, bal, chg in (('融資(市值)', 'mb', 'md'), ('融券(市值)', 'sb', 'sd')):
                amt = (mm[bal] * mm['px']).sum() * 1000 / 1e8  # 張 × 元 × 1000股 → 億元
                chg_amt = (mm[chg] * mm['px']).sum() * 1000 / 1e8  # 增減張 × 當日收盤 → 億元
                bs = f'{amt / 10000:,.2f}兆元' if abs(amt) >= 10000 else f'{amt:,.0f}億元'
                rows.append(f"- {label}: {bs} {arrow(chg_amt)}{abs(chg_amt):,.1f}億元")
    except Exception as e:
        warns.append(f'融資券取數失敗: {e}')

    # ── 台指期未平倉（TX02 投信 / TX03 外資）+ 法人淨部位 ──
    try:
        oi = cli.query_df(f'''
SELECT "日期" AS dt,"代號" AS c,"期貨多空未平倉口數淨額" AS net
FROM cmoney."日期貨三大法人交易行情表"
WHERE "代號" IN ('TX02','TX03') AND "日期" <= toDate('{d}')
  AND "日期" >= toDate('{d}') - 14
ORDER BY "日期" DESC
''', db=DB)

        def oi_fmt(nm, cur, prev):
            s = f"- {nm}: 淨{'多' if cur >= 0 else '空'}單{abs(cur):,.0f}口"
            if prev is not None:
                diff = cur - prev  # 淨額變大＝偏多，變小＝偏空
                s += f" {arrow(diff)}{abs(diff):,.0f}口"
            return s

        if len(oi):
            days = sorted(oi['dt'].unique(), reverse=True)
            cur_d, prev_d = days[0], (days[1] if len(days) > 1 else None)

            def net_of(day, code):
                s = oi[(oi['dt'] == day) & (oi['c'] == code)]['net']
                return float(s.iloc[0]) if len(s) else None

            pair = []
            for code, nm in (('TX03', '外資期貨未平倉'), ('TX02', '投信期貨未平倉')):
                cur = net_of(cur_d, code)
                if cur is None:
                    continue
                prev = net_of(prev_d, code) if prev_d is not None else None
                pair.append((cur, prev))
                rows.append(oi_fmt(nm, cur, prev))
            if len(pair) == 2:
                cur_sum = pair[0][0] + pair[1][0]
                prev_sum = (pair[0][1] + pair[1][1]
                            if pair[0][1] is not None and pair[1][1] is not None else None)
                rows.append(oi_fmt('法人淨部位', cur_sum, prev_sum))
            # 期貨表可能落後現貨一天，同卡混用兩個交易日必須標示
            if str(cur_d)[:10] != d:
                warns.append(f'期貨未平倉資料日 {str(cur_d)[:10]}（落後現貨 {d}）')
    except Exception as e:
        warns.append(f'期貨未平倉取數失敗: {e}')

    if not rows:
        for w in warns:
            print(f'ERROR {w}', file=sys.stderr)
        sys.exit(1)

    note = f'資料日 {d}，融資融券餘額與增減均為張數乘收盤價之市值口徑'
    if len(rows) < FULL_ROWS:
        note += f'；本日部分籌碼資料未更新（僅 {len(rows)} 格）'
    for w in warns:
        note += f'；{w}'

    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(f"## 大盤速覽\n（{note}）\n" + '\n'.join(rows) + '\n')

    print(f'OK {out_path} 資料日={d} 共 {len(rows)} 格')
    for w in warns:
        print(f'WARN {w}', file=sys.stderr)
    if len(rows) < FULL_ROWS or warns:
        sys.exit(2)


if __name__ == '__main__':
    main(sys.argv[1])
