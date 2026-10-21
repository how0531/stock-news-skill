# send_teams.py — 把當日盤前重點以 Adaptive Card 推到 Teams（Power Automate webhook）
# 用法: python send_teams.py <digest.md> [webhook_url]
# webhook 未設定就直接跳過（exit 0），不擋管線：Teams 只是額外通道，信才是主通道。
import json
import os
import re
import sys
import urllib.request

WEBHOOK = os.environ.get('PREMARKET_TEAMS_WEBHOOK', '')


def parse(md):
    """回傳 {區塊標題: [條列, ...]}；只取需要的三塊，不重造完整解析器。"""
    secs, cur = {}, None
    for line in md.splitlines():
        if line.startswith('## '):
            cur = line[3:].strip()
            secs[cur] = []
        elif line.startswith('- ') and cur:
            secs[cur].append(line[2:].strip())
    return secs


def plain(t):
    """[#012] 內部標記與 markdown 連結都拿掉，Teams 沒有編號表可查"""
    t = re.sub(r'\s*\[#[^\]]{0,20}\]', '', t)
    return re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', t).strip()


def main(md_path, webhook):
    secs = parse(open(md_path, encoding='utf-8').read())
    date = re.search(r'(\d{4}-\d{2}-\d{2})', os.path.basename(md_path))
    date = date.group(1) if date else ''

    body = [{'type': 'TextBlock', 'text': f'台股盤前重點 {date}',
             'size': 'Large', 'weight': 'Bolder', 'wrap': True}]

    # 大盤速覽走 FactSet：Teams 對兩欄式事實列的排版最穩
    kpi = [plain(x) for x in secs.get('大盤速覽', [])]
    facts = []
    for k in kpi:
        if ':' in k or '：' in k:
            name, _, val = k.replace('：', ':').partition(':')
            facts.append({'title': name.strip(), 'value': val.strip()})
    if facts:
        body.append({'type': 'FactSet', 'facts': facts})

    for title in ('今日三件事', '今日操作提醒', '近期行事曆'):
        items = secs.get(title) or []
        if not items:
            continue
        body.append({'type': 'TextBlock', 'text': title, 'weight': 'Bolder',
                     'spacing': 'Medium', 'wrap': True})
        for it in items[:5]:
            body.append({'type': 'TextBlock', 'text': f'• {plain(it)}',
                         'wrap': True, 'spacing': 'Small'})

    body.append({'type': 'TextBlock', 'size': 'Small', 'isSubtle': True, 'wrap': True,
                 'spacing': 'Medium',
                 'text': '完整版含連結請見信箱。本資料為公開新聞自動彙整，僅供內部參考，不構成投資建議。'})

    card = {'type': 'message', 'attachments': [{
        'contentType': 'application/vnd.microsoft.card.adaptive',
        'content': {'type': 'AdaptiveCard', 'version': '1.4',
                    '$schema': 'http://adaptivecards.io/schemas/adaptive-card.json',
                    'body': body}}]}

    req = urllib.request.Request(
        webhook, data=json.dumps(card).encode('utf-8'),
        headers={'Content-Type': 'application/json'}, method='POST')
    with urllib.request.urlopen(req, timeout=30) as r:
        print(f'OK Teams 已推送 (HTTP {r.status}, {len(body)} 個區塊)')


if __name__ == '__main__':
    hook = sys.argv[2] if len(sys.argv) > 2 else WEBHOOK
    if not hook:
        print('SKIP 未設定 PREMARKET_TEAMS_WEBHOOK，略過 Teams 推送')
        sys.exit(0)
    main(sys.argv[1], hook)
