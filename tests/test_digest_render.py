# test_digest_render.py — 盤前摘要 renderer 純函式回歸測試（不觸網、不碰 DB）
# 跑法: python tests/test_digest_render.py   （exit 0 = 全過）
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'scripts'))
import render_digest_html as R  # noqa: E402

FIX = pathlib.Path(__file__).parent / 'fixtures'
ok = fail = 0


def check(cond, msg):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print(f'  FAIL {msg}')


# ── 1. inline 渲染：標籤成對、連結不跨出粗體、內部標記不外洩 ──
R.NUM_URLS = {12: 'https://news.cnyes.com/news/id/1'}
R.VALID_URLS = {'https://news.cnyes.com/news/id/1'}

h = R.linked_inline('**聯亞連4漲停**。磷化銦放量 [#012]')
check(h.count('<b>') == h.count('</b>'), f'<b> 未成對: {h}')
check('</a></b>' not in h, f'</a> 落在 <b> 內（2.1 的具體形狀）: {h}')
check('[#' not in h, f'編號標記外洩: {h}')
check('href="https://news.cnyes.com/news/id/1"' in h, f'連結未回填: {h}')

# 白名單
check(R.split_link('文字 [#999]')[1] is None, '未知編號不該給 URL')
check(R.split_link('文字 [x](https://evil.example/a)')[1] is None, '白名單外的 URL 不該通過')
check(R.split_link('文字 [#012]')[0] == '文字', '標記移除後不該留尾空白')
# 編號變體
check(R.split_link('文字 [#012、#034]')[1] == 'https://news.cnyes.com/news/id/1', '多編號變體未匹配')
check('[#' not in R.split_link('文字 [# 012]')[0], '空白變體未匹配')

# 導言加粗不重複包裝
check('*' not in R.md_inline(R.bold_lead('**群聯**：營收年增45%')), '已帶 ** 時二次包裝')
check('<b>群聯</b>' in R.md_inline(R.bold_lead('群聯：營收年增45%')), '未加粗導言')

# 顏色語意：部位方向優先於箭頭
check(R._kpi_color('外資期貨未平倉', '淨空單87,911口 ▲1,472口') == R.DOWN, '淨空單被箭頭帶成紅色')
check(R._kpi_color('外資', '賣超407.2億元') == R.DOWN, '賣超應為綠')
check(R._kpi_color('融券(市值)', '餘額237億元 張數▼2,002張') == R.UP, '券減為回補應為紅')

# ── 2. markdown 契約 ──
md = (FIX / 'digest_sample.md').read_text('utf-8')
secs = dict(R.parse(md))

check('國內個股焦點' in secs, '個股區未解析')
tbl = secs['國內個股焦點']['subs'][0][1]['table']
check(['個股', '重點 [#編號]'] not in tbl, '表頭列未被丟棄')
check(all(len(r) == 2 for r in tbl), '表格未截成兩欄')
check(len(tbl) == 2, f'個股列數應為 2，實得 {len(tbl)}')
check(secs['國內重點產業訊息']['bullets'], '缺 ### 的產業內容不該消失')
check(any('續行關鍵字' in b for b in secs['國際重點新聞']['bullets']), '條列續行遺失')
check(R.parse('﻿# 標題\n\n## A\n- x')[0][0] == 'A', '行首 BOM 讓區塊解析失敗')

# ── 3. 空區塊要回空字串，讓 build() 的守門攔得到 ──
empty = {'bullets': [], 'subs': [], 'table': [], 'text': []}
check(R.render_industry(dict(empty)) == '', '空產業區未回空字串')
check(R.render_stocks(dict(empty)) == '', '空個股區未回空字串')
check(R.render_industry({**empty, 'bullets': ['- x']}) != '', '有頂層條列時不該回空')

print(f'test_digest_render: {ok} passed, {fail} failed')
sys.exit(1 if fail else 0)
