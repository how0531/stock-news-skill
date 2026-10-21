# render_digest_html.py — 盤前摘要 markdown → Outlook 相容 HTML（盤前終端 v3）
# 用法: python render_digest_html.py <digest.md> <out.html> [raw_news.md]
# raw_news.md 提供連結白名單：摘要裡的 [原文](URL) 必須逐字存在於原料，否則視為
# 幻覺連結整條移除（寧可沒連結，不給錯連結）。
# Word 引擎不支援圓角/陰影/flex/webfont，元件感全靠 table + bgcolor + border；
# Barlow 需收件端已安裝，未安裝時退 Segoe UI。
import html
import re
import sys

# ── 設計 token（v3 配色）─────────────────────────────────────
PAGE, CARD, ZEBRA = '#F4F5F7', '#FFFFFE', '#F8F9FB'
HEAD_BG, GOLD = '#0E2038', '#D9A741'
CARD_BD, SEC_BG, LINE = '#E2E5EA', '#F3F5F8', '#E6E9EE'
INK, BODY, SUB, WEAK = '#171B21', '#333A44', '#4E5A68', '#7E8794'
UP, UP_BG = '#D32F2F', '#FBEAEA'          # 台股慣例：漲=紅
DOWN, DOWN_BG = '#1B8A57', '#E7F4EE'      # 跌=綠
NEU, NEU_BG = '#35598A', '#EAF1F9'
WARN, WARN_BG, WARN_BD = '#B45309', '#FEF6E7', '#F0DCB4'

# 內文：微軟正黑體
FONT = ("font-family:'Microsoft JhengHei','PingFang TC','Heiti TC','Noto Sans TC',"
        "'Segoe UI',Arial,sans-serif;mso-fareast-font-family:'Microsoft JhengHei';")
# 大標題：微軟雅黑粗體（fallback 正黑）
HFONT = ("font-family:'Microsoft YaHei','Microsoft JhengHei','PingFang TC',"
         "'Segoe UI',Arial,sans-serif;mso-fareast-font-family:'Microsoft YaHei';"
         "font-weight:700;")
# 數字：Barlow（收件端未安裝時退 Segoe UI；中文字退正黑不掉回系統預設）
NUM = ("font-family:'Barlow','Segoe UI','Microsoft JhengHei','PingFang TC',Arial,sans-serif;"
       "mso-fareast-font-family:'Microsoft JhengHei';")
TBL = 'border-collapse:collapse;mso-table-lspace:0pt;mso-table-rspace:0pt;'

VALID_URLS = None  # build() 時載入原料連結白名單
NUM_URLS = {}      # [#NNN] 編號 → 原料 URL 對照表

MAIL_W = 600                 # 信件容器寬（Word 引擎沒有 max-width，只能寫死）
CARD_INNER = MAIL_W - 32     # 扣掉左右 padding 後的可用寬

# 免責與顏色圖例：降級路徑（python-markdown 簡版）也要附，故抽成共用常數。
# 期貨與融券刻意依「部位方向」上色而非漲跌，圖例必須講清楚否則讀者會照字面讀反。
DISCLAIMER = ('本資料為公開新聞自動彙整，僅供內部參考，非本公司研究報告，不構成投資建議，請勿轉發客戶。'
              '紅字為漲（買超），綠字為跌（賣超）；期貨未平倉與融券依部位方向上色，綠為空方。')


def lh(px):
    # mso-line-height-rule 必須宣告在 line-height 之前才會被 Word 引擎採用
    return f'mso-line-height-rule:exactly;line-height:{px}px;'


def esc(t):
    return html.escape(t, quote=False)


def split_link(t):
    """取第一條可信 URL 並把 [#NNN] / [x](url) 標記從文字移除。
    編號制優先（[#012] 查 NUM_URLS 表，天然通過白名單）；直寫 URL 為舊格式相容。"""
    found = []
    # 涵蓋 [#012]、[#012,#034]、[#012、#034]、[# 012] 等變體；漏配的會原樣印進信裡
    t = re.sub(r'\s*\[#\s*\d{1,5}(?:\s*[,、，/]\s*#?\s*\d{1,5})*\s*\]',
               lambda m: (found.extend(NUM_URLS.get(int(x))
                                       for x in re.findall(r'\d{1,5}', m.group(0))), '')[1], t)
    t = re.sub(r'\s*\[[^\]]*\]\((https?://[^\s)]+)\)',
               lambda m: (found.append(m.group(1)), '')[1], t).strip()
    url = next((u for u in found
                if u and (VALID_URLS is None or u in VALID_URLS)), None)
    return t, url


def md_inline(t):
    """跳脫 + **粗體** + ▲▼ 釘字型（不處理連結，連結走 linked_inline）。
    內文不做關鍵字上色：紅綠只保留給 KPI 與個股漲跌欄這兩個強結構位置，
    散文上色會讓顏色從訊號退化成裝飾（漲停曾用紅字，使用者 2026-08-10 要求移除）。"""
    t = esc(t)
    t = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', t)
    t = re.sub(r'([▲▼])', rf'<span style="{FONT}">\1</span>', t)
    return t


def linked_inline(t, color=None, underline=True):
    """整則渲染：有 URL 時把粗體導言（無導言則整句）做成超連結，不另附「原文」尾巴"""
    t2, url = split_link(t)
    h = md_inline(t2)
    if url:
        href = html.escape(url, quote=True)
        deco = 'underline' if underline else 'none'
        a_style = f'color:{color or INK};text-decoration:{deco};'
        if '<b>' in h:
            # 用 regex 配對整組 <b>…</b>，避免 replace 各自找第一個而錯開配對
            h = re.sub(r'<b>(.*?)</b>',
                       lambda m: f'<a href="{href}" style="{a_style}"><b>{m.group(1)}</b></a>',
                       h, count=1)
        else:
            h = f'<a href="{href}" style="{a_style}">{h}</a>'
    return h


def bold_lead(text):
    """把「導言：內容」的導言加粗；已自帶 ** 就不重複包裝（否則會變 ****x****）"""
    return text if text.lstrip().startswith('**') else re.sub(r'^([^：:]+)([：:])', r'**\1**\2', text)


def gap(px=10):
    return (f'<tr><td height="{px}" style="height:{px}px;font-size:1px;'
            f'{lh(px)}">&nbsp;</td></tr>')


def card(inner, bg=CARD, border=CARD_BD):
    return (f'<tr><td style="padding:0;">'
            f'<table width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="{bg}" '
            f'style="{TBL}background-color:{bg};border:1px solid {border};">'
            f'{inner}</table></td></tr>')


def sec_header(title, meta=''):
    meta_td = (f'<td align="right" valign="bottom" style="{NUM}font-size:11px;'
               f'color:{WEAK};{lh(16)}">{esc(meta)}</td>') if meta else ''
    return (f'<tr><td style="padding:12px 16px 6px 16px;">'
            f'<table width="100%" cellpadding="0" cellspacing="0" border="0" style="{TBL}">'
            f'<tr><td width="4" bgcolor="{HEAD_BG}" style="width:4px;background-color:{HEAD_BG};'
            f'font-size:1px;{lh(14)}">&nbsp;</td>'
            f'<td width="10" style="width:10px;font-size:1px;">&nbsp;</td>'
            f'<td style="{HFONT}font-size:14px;color:{INK};{lh(20)}">{esc(title)}</td>'
            f'{meta_td}</tr></table></td></tr>')


def bullet_rows(items, size=13, line=20):
    rows = []
    for it in items:
        rows.append(
            f'<tr><td style="padding:4px 16px;">'
            f'<table width="100%" cellpadding="0" cellspacing="0" border="0" style="{TBL}">'
            f'<tr><td width="14" valign="top" style="width:14px;{FONT}font-size:{size}px;'
            f'color:{NEU};{lh(line)}">&#12539;</td>'
            f'<td valign="top" style="{FONT}font-size:{size}px;color:{BODY};{lh(line)}">'
            f'{linked_inline(it)}</td></tr></table></td></tr>')
    return ''.join(rows) + f'<tr><td height="10" style="height:10px;font-size:1px;{lh(10)}">&nbsp;</td></tr>'


# ── markdown 解析 ────────────────────────────────────────────
def parse(md):
    sections, cur, sub = [], None, None
    last_bullets = None   # 續行要接回的清單
    for raw in md.splitlines():
        line = raw.rstrip().lstrip('﻿')  # BOM 可能落在檔中任一行首（Out-File append 所致）
        if line.startswith('## '):
            cur = (line[3:].strip(), {'bullets': [], 'subs': [], 'table': [], 'text': []})
            sections.append(cur)
            sub, last_bullets = None, None
        elif line.startswith('### ') and cur:
            sub = (line[4:].strip(), {'bullets': [], 'table': []})
            cur[1]['subs'].append(sub)
            last_bullets = None
        elif line.startswith('- ') and cur:
            tgt = (sub[1] if sub else cur[1])['bullets']
            tgt.append(line[2:].strip())
            last_bullets = tgt
        elif line.startswith('|') and cur:
            cells = [c.strip() for c in line.strip('|').split('|')]
            tbl = (sub[1] if sub else cur[1])['table']
            if set(cells[0]) <= set('-: ') and cells[0]:
                # 分隔列：它前一列是表頭，丟掉（不比對任何字面，prompt 改欄名也不會漏）
                if tbl:
                    tbl.pop()
            elif len(cells) >= 2:
                tbl.append(cells[:2])
            last_bullets = None
        elif line and cur and not line.startswith('#'):
            if last_bullets:
                last_bullets[-1] += ' ' + line.strip()   # 條列換行續寫，接回前一則
            else:
                cur[1]['text'].append(line)
    return sections


# ── 各區塊 render ────────────────────────────────────────────
def _kpi_color(label, value):
    """依欄位語意上色：多方紅、空方綠。
    部位方向（淨多空／買賣超）優先於增減箭頭，否則「淨空單▲」會被箭頭帶成紅色。
    融券方向與字面相反：券增＝空方力道增（綠），券減＝回補（紅）。"""
    if not value:
        return WEAK
    if '淨多單' in value or '買超' in value or re.match(r'^\+', value.strip()):
        return UP
    if '淨空單' in value or '賣超' in value or re.match(r'^-', value.strip()):
        return DOWN
    if '融券' in label:
        return DOWN if '▲' in value else (UP if '▼' in value else INK)
    if '▲' in value:
        return UP
    if '▼' in value:
        return DOWN
    return INK


def _oi_value(v):
    """『淨空單1,234口』→ -1234；『淨多單567口』→ +567；解析不了回 None"""
    m = re.search(r'淨(多|空)單\s*([\d,]+)\s*口', v or '')
    if not m:
        return None
    n = int(m.group(2).replace(',', ''))
    return n if m.group(1) == '多' else -n


def render_kpi(sec):
    """3×3 儀表格：加權/櫃買 | 外資/投信/自營商 | 融資/融券/法人淨部位"""
    vals = {}
    for b in sec['bullets']:
        m = re.split(r'[:：]', b, 1)
        if len(m) != 2:
            continue
        label, value = m[0].strip(), split_link(m[1].strip())[0]
        for key in ('法人淨部位', '外資期貨', '投信期貨', '加權', '櫃買', '外資',
                    '投信', '自營', '融資', '融券', '成交', '資料日'):
            if label.startswith(key):
                vals.setdefault(key, value)
                break
    # 法人淨部位優先用 kpi_fetch 算好的（含前日增減）；沒有才在此加總當備援
    if not vals.get('法人淨部位'):
        a, b2 = _oi_value(vals.get('外資期貨')), _oi_value(vals.get('投信期貨'))
        if a is not None and b2 is not None:
            net = a + b2
            vals['法人淨部位'] = f'淨{"多" if net >= 0 else "空"}單{abs(net):,}口'
    if not vals:
        return ''
    # kpi_fetch 已把口徑與資料日寫進區塊註解列，直接沿用避免兩處各寫一份而失聯
    meta = ' '.join(sec['text']).strip().strip('（）()')
    note = '*法人淨部位＝外資期貨未平倉＋投信期貨未平倉' + (f'；{meta}' if meta else '')
    grid = [[('加權指數', '加權'), ('外資', '外資'), ('融資', '融資')],
            [('櫃買指數', '櫃買'), ('投信', '投信'), ('融券', '融券')],
            [('成交金額', '成交'), ('自營商', '自營'), ('法人淨部位*', '法人淨部位')]]
    # 第三欄（融資/融券/淨部位）整欄無值就收合成兩欄，開場卡片不留半版空格
    if not any(vals.get(k) for k in ('融資', '融券', '法人淨部位')):
        grid = [row[:2] for row in grid]
    w = 299 if len(grid[0]) == 2 else 199
    rows = []
    for ri, row in enumerate(grid):
        cells = []
        for ci, cell in enumerate(row):
            left_bd = f'border-left:1px solid {LINE};' if ci else ''
            top_bd = f'border-top:1px solid {LINE};' if ri else ''
            if cell is None:
                cells.append(f'<td width="{w}" style="width:{w}px;{left_bd}{top_bd}'
                             f'font-size:1px;">&nbsp;</td>')
                continue
            label, key = cell
            value = vals.get(key)
            if value:
                color = _kpi_color(label, value)
                vhtml = (f'<div style="{NUM}font-size:16px;font-weight:700;'
                         f'color:{color};{lh(23)}">{md_inline(value)}</div>')
            else:
                vhtml = (f'<div style="{FONT}font-size:11px;color:{WEAK};{lh(23)}">'
                         f'無資料</div>')
            cells.append(
                f'<td width="{w}" valign="top" style="width:{w}px;{left_bd}{top_bd}'
                f'padding:8px 12px 9px 12px;">'
                f'<div style="{FONT}font-size:11px;color:{WEAK};{lh(15)}">{esc(label)}</div>'
                f'{vhtml}</td>')
        rows.append(f'<tr>{"".join(cells)}</tr>')
    inner = (f'<tr><td style="padding:0;"><table width="100%" cellpadding="0" cellspacing="0" '
             f'border="0" style="{TBL}">{"".join(rows)}</table></td></tr>'
             f'<tr><td style="border-top:1px solid {LINE};padding:4px 12px 6px 12px;'
             f'{FONT}font-size:10px;color:{WEAK};{lh(14)}">'
             f'{esc(note)}</td></tr>')
    return card(inner)


def render_tldr(sec):
    rows = [sec_header('今日三件事', f'{len(sec["bullets"])} 則')]
    for i, b in enumerate(sec['bullets'], 1):
        text, url = split_link(b)
        m = re.match(r'\*\*(.+?)\*\*[:：]?\s*(.*)', text)
        head, tail = (m.group(1), m.group(2)) if m else (text, '')
        head_html = md_inline(head)
        if url:
            href = html.escape(url, quote=True)
            head_html = (f'<a href="{href}" style="color:{INK};text-decoration:underline;">'
                         f'{head_html}</a>')
        rows.append(
            f'<tr><td style="padding:7px 16px;">'
            f'<table width="100%" cellpadding="0" cellspacing="0" border="0" style="{TBL}">'
            f'<tr><td width="26" valign="top" style="width:26px;">'
            f'<table cellpadding="0" cellspacing="0" border="0" style="{TBL}">'
            f'<tr><td width="26" height="26" align="center" bgcolor="{HEAD_BG}" '
            f'style="width:26px;height:26px;background-color:{HEAD_BG};{NUM}'
            f'font-size:13px;font-weight:700;color:{GOLD};{lh(26)}">{i}</td></tr></table></td>'
            f'<td width="12" style="width:12px;font-size:1px;">&nbsp;</td>'
            f'<td valign="top">'
            f'<div style="{HFONT}font-size:15px;color:{INK};{lh(22)}">{head_html}</div>'
            + (f'<div style="{FONT}font-size:13px;color:{SUB};{lh(19)}">{md_inline(tail)}</div>' if tail else '')
            + '</td></tr></table></td></tr>')
    rows.append(f'<tr><td height="10" style="height:10px;font-size:1px;{lh(10)}">&nbsp;</td></tr>')
    return card(''.join(rows))


def render_notice(sec):
    text = ' '.join(sec['text']) or (sec['bullets'][0] if sec['bullets'] else '')
    if not text:
        return ''
    inner = (
        f'<tr><td style="padding:10px 16px;">'
        f'<table width="100%" cellpadding="0" cellspacing="0" border="0" style="{TBL}">'
        f'<tr><td width="72" valign="top" style="width:72px;">'
        f'<table cellpadding="0" cellspacing="0" border="0" style="{TBL}">'
        f'<tr><td bgcolor="{WARN}" align="center" style="background-color:{WARN};'
        f'padding:2px 8px;{HFONT}font-size:11px;color:#FFFFFF;{lh(16)}">操作提醒</td>'
        f'</tr></table></td>'
        f'<td width="10" style="width:10px;font-size:1px;">&nbsp;</td>'
        f'<td valign="top" style="{FONT}font-size:13px;font-weight:700;color:{WARN};{lh(19)}">'
        f'{linked_inline(text, color=WARN)}</td></tr></table></td></tr>')
    return card(inner, bg=WARN_BG, border=WARN_BD)


def render_stocks(sec, title='國內個股焦點'):
    # 整區空白時回空字串，讓 build() 的守門攔得到（否則只有標題列的空卡照樣過關）
    if not sec['subs'] and not sec['table'] and not sec['bullets']:
        return ''
    focus = other = None
    for name, data in sec['subs']:
        if '焦點' in name:
            focus = data
        else:
            other = data
    if focus is None and sec['table']:
        focus = sec
    focus_n = len(focus['table']) if focus else 0
    # 模型沒寫「其他」子區時，頂層 bullets 當速覽，不要整段丟棄
    other_items = ((other['bullets'] + [f'{n}：{d}' for n, d in other['table']])
                   if other else list(sec['bullets']))
    rows = [sec_header(title, f'{focus_n} 檔焦點・{len(other_items)} 檔速覽')]

    if focus and focus['table']:
        trs = [
            f'<tr><td width="96" bgcolor="{SEC_BG}" style="width:96px;background-color:{SEC_BG};'
            f'padding:5px 10px;{HFONT}font-size:11px;color:{SUB};{lh(16)}">個股</td>'
            f'<td bgcolor="{SEC_BG}" style="background-color:{SEC_BG};padding:5px 10px;{HFONT}'
            f'font-size:11px;color:{SUB};{lh(16)}">重點</td></tr>']
        for i, (name, detail) in enumerate(focus['table']):
            bg = ZEBRA if i % 2 else CARD
            dtext, durl = split_link(detail)
            name_html = esc(name)
            if durl:
                href = html.escape(durl, quote=True)
                name_html = (f'<a href="{href}" style="color:{INK};'
                             f'text-decoration:underline;">{name_html}</a>')
            trs.append(
                f'<tr><td width="96" valign="top" bgcolor="{bg}" style="width:96px;'
                f'background-color:{bg};padding:7px 10px;border-bottom:1px solid {LINE};'
                f'{HFONT}font-size:14px;color:{INK};{lh(20)}">{name_html}</td>'
                f'<td valign="top" bgcolor="{bg}" style="background-color:{bg};padding:7px 10px;'
                f'border-bottom:1px solid {LINE};{FONT}font-size:13px;color:{BODY};{lh(20)}">'
                f'{md_inline(dtext)}</td></tr>')
        rows.append(
            f'<tr><td style="padding:4px 16px 0 16px;">'
            f'<table width="100%" cellpadding="0" cellspacing="0" border="0" style="{TBL}">'
            + ''.join(trs) + '</table></td></tr>')

    if other_items:
        half = (len(other_items) + 1) // 2
        cols = [other_items[:half], other_items[half:]]
        col_tds = []
        for ci, col in enumerate(cols):
            lis = ''.join(
                f'<div style="{FONT}font-size:12px;color:{SUB};{lh(19)}">'
                f'{linked_inline(bold_lead(it), color=SUB)}</div>'
                for it in col)
            pad = 'padding:0 8px 0 0;' if ci == 0 else f'padding:0 0 0 10px;border-left:1px solid {LINE};'
            col_tds.append(f'<td width="283" valign="top" style="width:283px;{pad}">{lis}</td>')
        rows.append(
            f'<tr><td style="padding:10px 16px 12px 16px;">'
            f'<table width="100%" cellpadding="0" cellspacing="0" border="0" style="{TBL}">'
            f'<tr>{"".join(col_tds)}</tr></table></td></tr>')
    else:
        rows.append(f'<tr><td height="12" style="height:12px;font-size:1px;{lh(12)}">&nbsp;</td></tr>')
    return card(''.join(rows))


def render_industry(sec, title='國內重點產業訊息'):
    subs = [(n, d) for n, d in sec['subs'] if d['bullets']]
    if not subs:
        # 模型漏寫 ### 產業子標時，別把整區丟掉；真的沒內容才回空讓守門攔
        if not sec['bullets']:
            return ''
        return card(sec_header(title, f'{len(sec["bullets"])} 則') + bullet_rows(sec['bullets']))
    rows = [sec_header(title, f'{len(subs)} 個產業')]
    for si, (name, data) in enumerate(subs):
        inner = ''.join(
            f'<tr><td valign="top" style="padding:0 0 5px 0;{FONT}font-size:13px;'
            f'color:{BODY};{lh(20)}">{linked_inline(b)}</td></tr>'
            for b in data['bullets'])
        bd = f'border-top:1px solid {LINE};' if si else ''
        rows.append(
            f'<tr><td style="padding:0 16px;">'
            f'<table width="100%" cellpadding="0" cellspacing="0" border="0" style="{TBL}">'
            f'<tr><td colspan="3" style="{bd}font-size:1px;{lh(8)}height:8px;">&nbsp;</td></tr>'
            f'<tr><td width="100" valign="top" style="width:100px;">'
            f'<table cellpadding="0" cellspacing="0" border="0" style="{TBL}">'
            f'<tr><td bgcolor="{NEU}" align="center" style="background-color:{NEU};'
            f'padding:2px 7px;{HFONT}font-size:11px;color:#FFFFFF;{lh(16)};'
            f'white-space:nowrap;">{esc(name[:8])}</td></tr></table></td>'
            f'<td width="10" style="width:10px;font-size:1px;">&nbsp;</td>'
            f'<td valign="top"><table width="100%" cellpadding="0" cellspacing="0" border="0" '
            f'style="{TBL}">{inner}</table></td></tr>'
            f'<tr><td colspan="3" style="font-size:1px;{lh(4)}height:4px;">&nbsp;</td></tr>'
            f'</table></td></tr>')
    rows.append(f'<tr><td height="8" style="height:8px;font-size:1px;{lh(8)}">&nbsp;</td></tr>')
    return card(''.join(rows))


def render_generic(sec, title):
    items = sec['bullets'] or sec['text']
    if not items:
        return ''
    return card(sec_header(title, f'{len(items)} 則') + bullet_rows(items))


# ── 組裝 ─────────────────────────────────────────────────────
def build(md_path, out_path, raw_path=None):
    global VALID_URLS, NUM_URLS
    md = open(md_path, encoding='utf-8').read()
    if raw_path:
        try:
            raw = open(raw_path, encoding='utf-8').read()
            # 只收行首編號那條 URL，不要掃全檔（否則內文裡的 URL 也會混進白名單）
            VALID_URLS = set(re.findall(r'^\[#\d{1,5}\].*?\((https?://[^)\s]+)\)',
                                        raw, re.MULTILINE))
            for mm in re.finditer(r'^\[#(\d{1,5})\].*?\((https?://[^)\s]+)\)',
                                  raw, re.MULTILINE):
                NUM_URLS[int(mm.group(1))] = mm.group(2)
        except OSError as e:
            # fail-closed：有指定原料檔卻讀不到，白名單就形同失效，寧可不出信也不放行假連結
            print(f'ERROR 原料檔不可讀({e})，白名單無法建立', file=sys.stderr)
            raise SystemExit(2)
    sections = parse(md)

    m = re.search(r'#\s*盤前重點\s*([\d-]+)', md)
    date_str = m.group(1) if m else ''

    # 精確表全等比對，不用中文子字串模糊判斷（prompt 改標題會靜默掉進 render_generic）
    ROUTE = {
        '大盤速覽': ('kpi', render_kpi),
        '今日三件事': ('tldr', render_tldr),
        '今日操作提醒': ('notice', render_notice),
        '國內重點產業訊息': ('industry', render_industry),
        '國內個股焦點': ('stocks', render_stocks),
    }
    tldr_leads = []
    body_parts = []
    for title, sec in sections:
        route = ROUTE.get(title)
        if route is None:
            body_parts.append(('generic', render_generic(sec, title)))
            continue
        kind, fn = route
        if kind == 'tldr':
            for b in sec['bullets']:
                mm = re.match(r'\*\*(.+?)\*\*', b)
                if mm:
                    tldr_leads.append(mm.group(1))
        body_parts.append((kind, fn(sec) if kind in ('kpi', 'tldr', 'notice') else fn(sec, title)))

    missing = [t for t in ('今日三件事', '國內重點產業訊息', '國內個股焦點')
               if t not in [s[0] for s in sections]]
    if missing:
        print(f'WARN 缺少預期區塊 {missing}（模型可能改了標題）', file=sys.stderr)

    if not any(k in ('tldr', 'industry', 'stocks') for k, h in body_parts if h):
        raise SystemExit('結構解析失敗：缺少必要區塊，走降級路徑')

    preheader = esc('；'.join(tldr_leads[:3]))
    body = ''.join(h + gap(10) for _, h in body_parts if h)

    header_card = (
        f'<tr><td bgcolor="{HEAD_BG}" style="background-color:{HEAD_BG};'
        f'border-bottom:3px solid {GOLD};padding:16px 18px 13px 18px;">'
        f'<table width="100%" cellpadding="0" cellspacing="0" border="0" style="{TBL}"><tr>'
        f'<td><div style="{HFONT}font-size:19px;color:#FFFFFF;{lh(26)}">台股盤前重點</div>'
        f'<div style="{FONT}font-size:11px;color:#8FA3BF;{lh(16)}">07:40 自動彙整全市場新聞</div></td>'
        f'<td align="right" valign="top"><div style="{NUM}font-size:13px;font-weight:700;'
        f'color:{GOLD};{lh(26)}">{esc(date_str)}</div></td>'
        f'</tr></table></td></tr>')

    html_doc = f'''<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:v="urn:schemas-microsoft-com:vml"
      xmlns:o="urn:schemas-microsoft-com:office:office">
<head>
<meta http-equiv="Content-Type" content="text/html; charset=utf-8" />
<title>台股盤前重點</title>
<meta name="x-apple-disable-message-reformatting" />
<meta name="format-detection" content="telephone=no,date=no,address=no,email=no" />
<!--[if mso]>
<xml><o:OfficeDocumentSettings>
  <o:AllowPNG/><o:PixelsPerInch>96</o:PixelsPerInch>
</o:OfficeDocumentSettings></xml>
<![endif]-->
</head>
<body style="margin:0;padding:0;background-color:{PAGE};">
<!--[if !mso]><!-->
<div style="display:none;mso-hide:all;max-height:0;max-width:0;opacity:0;overflow:hidden;font-size:1px;line-height:1px;color:{PAGE};">{preheader}{'&zwnj;&nbsp;' * 30}</div>
<!--<![endif]-->
<table width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="{PAGE}"
       style="{TBL}background-color:{PAGE};">
<tr><td align="left" style="padding:14px;">
<table width="600" cellpadding="0" cellspacing="0" border="0" style="{TBL}width:600px;">
{card(header_card, bg=HEAD_BG, border=HEAD_BG)}
{gap(10)}
{body}
<tr><td style="padding:2px 4px 10px 4px;{FONT}font-size:11px;color:{WEAK};{lh(16)}">
{DISCLAIMER}</td></tr>
</table>
</td></tr>
</table>
</body>
</html>'''
    # 佈局表標 presentation，螢幕閱讀器不逐格朗讀
    html_doc = html_doc.replace('<table ', '<table role="presentation" ')
    # 安全網：任何 regex 沒吃掉的內部標記都不該印給讀者
    leftover = re.findall(r'\[#[^\]]{0,20}\]', html_doc)
    if leftover:
        print(f'WARN 殘留編號標記 {leftover[:5]}', file=sys.stderr)
        html_doc = re.sub(r'\s*\[#[^\]]{0,20}\]', '', html_doc)
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(html_doc)
    linked = html_doc.count('<a href=')
    print(f'OK {out_path} ({len(html_doc)} chars, 白名單 {len(VALID_URLS) if VALID_URLS else 0} 條, '
          f'編號表 {len(NUM_URLS)} 條, 成品連結 {linked} 個)')


if __name__ == '__main__':
    build(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
