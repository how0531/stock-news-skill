# build_material.py — 從 news_result.json 產生盤前摘要的編號材料檔
# 用法: python build_material.py <news_result.json> <material.md>
# 折衷策略：財經相關的則附前 200 字內文（模型才有細節可寫），雜訊只列標題省 token。
import json
import re
import sys

FIN_RE = re.compile(
    r'股|指數|營收|獲利|EPS|財報|法說|外資|投信|自營|融資|融券|期貨|債|匯|升息|降息|'
    r'關稅|油價|金價|黃金|銅價|航運|運價|半導體|晶片|記憶體|AI|電子|面板|PCB|ETF|'
    r'億|兆元|美元|漲|跌|買超|賣超|上市|上櫃|處置|重訊|產能|訂單|出口|通膨|CPI|非農|'
    r'Fed|聯準會|央行|台積|美股|道瓊|標普|那斯達克|費半|日經|陸股|港股|恒指')


BODY_CHARS = 200   # 與 prompt 文案「前200字」對齊，改這裡要一起改 prompt


def main(json_path, out_path):
    d = json.load(open(json_path, encoding='utf-8'))
    # news_result.json 是 --today 與 --keyword 共用檔，後者無 items 鍵。
    # 直接 d['items'] 會噴 KeyError，錯誤訊息看不出真正原因。
    items = d.get('items')
    if not items:
        sys.exit('news_result.json 無 items（可能被 keyword 模式覆寫），請重跑 news.py --today')
    lines = [f"# 盤前新聞材料 {d.get('date', '')}（共 {d.get('count', 0)} 則，"
             f"每則含編號/時間/來源/標題/內文摘要）", '']
    n = 0
    for x in items:
        n += 1
        t = str(x.get('time') or '')[5:16].replace('T', ' ')   # 'MM-DD HH:MM':盤前窗跨日要看得出哪一天
        src = x.get('source') or ''
        title = (x.get('title') or '').replace('[', '［').replace(']', '］')
        url = (x.get('url') or '').replace('(', '%28').replace(')', '%29')
        link = f'[{title}]({url})' if url else title
        lines.append(f'[#{n:03d}] {t} ({src}) {link}')
        # 【公告】是 Yahoo 產業 feed 的自動營收快訊，內文只是標題的複述，附了純浪費；
        # 標題本身已含營收與年增率，保留即可（真正重要的公司另有正式報導）
        if FIN_RE.search(title) and not title.startswith('【公告】'):
            body = re.sub(r'\s+', ' ', (x.get('body') or x.get('summary') or '')).strip()[:BODY_CHARS]
            # 內文的中括號要中和：一篇內文若含「[#012]」字樣，會讓渲染器把論述掛到別篇網址
            body = body.replace('[', '［').replace(']', '］')
            if body:
                lines.append(f'    內文: {body}')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    print(f'OK {out_path} ({n} 則)')


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
