# -*- coding: utf-8 -*-
"""
news_sentiment.py
-----------------
規則層的台股新聞利多/利空 + 事件分類器。

對外公開介面：
    classify(title: str, body: str = "") -> dict

回傳：
    {
      "sentiment":  "bullish" | "bearish" | "neutral",
      "confidence": float,          # 0~1
      "events":     list[str],
      "rationale":  str,
    }

設計原則：
- 純標準庫、純函數、可重入、無副作用。
- 標題權重 2、內文權重 1（標題已被人精煉）。
- 此模組會被 news_core.query_news() 在 keyword 模式最後一步呼叫，
  classify() 簽名是契約，不要再改。
"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple


# --------------------------------------------------------------------------- #
# 1. 詞庫
# --------------------------------------------------------------------------- #

# 利多詞（正向）
BULLISH_WORDS: List[str] = [
    # 營收 / 獲利方向
    "攀升", "看漲", "強勁", "超預期", "優於預期", "優於市場預期", "優於財測",
    "上修", "上調", "創新高", "創高", "創歷史新高", "再創高", "改寫新高",
    "報喜", "爆發", "看好", "轉佳", "走強", "回溫", "回升", "翻多", "翻紅",
    "回神", "回穩", "築底反彈", "觸底反彈", "落底回升", "止穩", "止跌回升",
    # 訂單 / 產能 / 出貨
    "訂單滿手", "訂單湧入", "訂單能見度高", "急單", "拉貨", "急單湧入",
    "出貨暢旺", "出貨強勁", "出貨放量", "接單暢旺", "接單滿載", "滿載",
    "產能滿載", "擴產", "擴廠", "新增訂單", "大單", "大單挹注", "標案",
    "得標", "斬獲訂單", "拿下訂單", "供不應求",
    # 投顧 / 法人語言
    "利多", "加碼", "調升", "調升目標價", "目標價上修", "升評", "調升評等",
    "買進", "買超", "推薦", "認養", "連買", "連續買超", "土洋對作偏多",
    "中信買超", "外資買超", "投信買超", "投信連買", "法人加碼", "首次評等",
    # 量價走勢
    "突破", "放量大漲", "續強", "亮燈", "亮燈漲停", "漲停", "飆漲", "強漲",
    "大漲", "勁揚", "走揚", "攻頂", "創波段新高", "多頭", "領漲", "噴出",
    # 業績 / 基本面
    "年增", "月增", "季增", "獲利成長", "獲利大增", "獲利倍增", "獲利躍進",
    "EPS創高", "賺贏", "賺逾", "轉盈", "轉機", "由虧轉盈", "扭虧為盈",
    "毛利率提升", "毛利率攀升", "毛利率上揚", "營收創高", "營收創新高",
    "營收亮眼", "業績亮眼", "獲利亮眼", "題材發酵", "利多齊發", "業績噴發",
    # 公司行動 / 籌碼
    "庫藏股", "回購庫藏股", "實施庫藏股", "現金股利優於", "高殖利率",
    "標到", "中選", "簽約", "簽訂大單", "結盟", "策略聯盟", "入股",
    "購併", "併購", "收購", "勝訴", "獲准",
]

# 利空詞（負向）
BEARISH_WORDS: List[str] = [
    # 警訊 / 預警
    "預警", "警示", "示警", "警訊", "獲利預警", "財測下修", "營運示警",
    # 業績方向
    "不如預期", "不如市場預期", "遜於預期", "低於預期", "低於財測", "下修",
    "下調", "衰退", "減少", "下滑", "走弱", "走疲", "疲弱", "疲軟",
    "縮水", "縮減", "回落", "下探", "探底", "下挫", "急凍", "急轉直下",
    # 訂單 / 產能 / 出貨
    "砍單", "被砍單", "遭砍單", "抽單", "取消訂單", "訂單流失", "停產",
    "減產", "停工", "停擺", "出貨延誤", "出貨遞延", "出貨下修", "出貨衰退",
    "產能不足", "稼動率下滑", "庫存壓力", "庫存過高", "高庫存", "去化",
    "賣壓沉重", "賣壓湧現", "賣壓出籠",
    # 投顧 / 法人語言
    "利空", "減碼", "調降", "調降目標價", "目標價下修", "下修目標價",
    "降評", "調降評等", "賣出", "看淡", "看空", "出脫", "賣超", "連賣",
    "連續賣超", "外資賣超", "外資調節", "投信賣超", "法人調節", "法人棄守",
    # 量價走勢
    "跳水", "跌停", "崩跌", "慘跌", "重挫", "暴跌", "破底", "摜破", "跌破",
    "急殺", "殺盤", "失守", "下殺", "回檔", "領跌", "弱勢", "破底翻空",
    # 業績 / 基本面
    "虧損", "鉅額虧損", "認列損失", "提列損失", "踩雷", "營收衰退",
    "獲利衰退", "由盈轉虧", "轉虧", "毛利率下滑", "毛利率下降",
    "毛利率走低", "毛利率衰退", "獲利縮水", "獲利下滑", "財報不如預期",
    # 財務 / 重大事故
    "違約", "違約交割", "跳票", "下市", "停止交易", "打入全額交割",
    "財務危機", "財務吃緊", "周轉不靈", "聲請重整", "重整", "破產",
    "詐欺", "假帳", "掏空", "起訴", "搜索", "調查", "裁罰", "停業",
    "敗訴", "判賠", "求償", "遭罰", "重罰",
]

# 事件詞庫：以 "事件標籤" -> [關鍵字...] 表達
EVENT_LEXICON: Dict[str, List[str]] = {
    "法說":     ["法說會", "法說", "業績發表會", "業績說明會"],
    "財報":     ["財報", "季報", "年報", "財測", "財務報表", "EPS", "每股盈餘"],
    "營收":     ["月營收", "營收快報", "單月營收", "累計營收", "營收創"],
    "購併":     ["購併", "併購", "收購", "合併", "公開收購", "換股"],
    "警示":     ["警示", "示警", "警訊", "預警"],
    "獲利預警": ["獲利預警", "財測下修", "下修財測", "下修展望", "下修財測目標"],
    "產能":     ["擴產", "擴廠", "減產", "停產", "停工", "產能不足", "產能滿載", "新建廠", "稼動率"],
    "訂單":     ["訂單滿手", "訂單湧入", "新增訂單", "急單", "大單", "砍單", "抽單", "取消訂單", "得標", "標案", "接單"],
    "訴訟":     ["訴訟", "官司", "提告", "敗訴", "勝訴", "判賠", "和解", "起訴", "判決"],
    "股利":     ["股利", "配息", "配股", "除權", "除息", "現金股利", "股票股利", "殖利率"],
    "增資":     ["現金增資", "現增", "私募", "增資", "可轉債發行", "海外存託憑證", "GDR"],
    "減資":     ["減資", "減資彌補虧損", "減資退還股款"],
    "公開收購": ["公開收購"],
    "庫藏股":   ["庫藏股", "買回庫藏股", "實施庫藏股"],
    "漲停":     ["漲停", "亮燈漲停", "鎖死漲停"],
    "跌停":     ["跌停", "鎖死跌停"],
    "踩雷":     ["踩雷", "認列損失", "提列損失"],
    "法人動向": ["外資買超", "外資賣超", "投信買超", "投信賣超", "外資調節", "投信連買", "三大法人"],
    "財務危機": ["違約交割", "跳票", "下市", "停止交易", "全額交割", "聲請重整", "破產", "周轉不靈"],
    "重大訊息": ["掏空", "假帳", "搜索", "裁罰", "停業", "調查"],
}


# --------------------------------------------------------------------------- #
# 1b. 上下文規則用詞庫
# --------------------------------------------------------------------------- #

# 反轉慣用語：字面方向與實際情緒相反 / 是固定意涵的片語。
#   值為情緒方向："bullish" / "bearish"。
# 這些片語在一般詞掃描「之前」就先抽出計分，且會把它本身從文字遮蔽
# （換成佔位符），避免被 BULLISH/BEARISH 的子字串（如「利空」「利多」）重複命中。
REVERSAL_PHRASES: Dict[str, str] = {
    # 字面有「利空」但其實偏多
    "利空出盡": "bullish",
    "利空鈍化": "bullish",
    "利空淡化": "bullish",
    "利空消化": "bullish",
    "利空已反映": "bullish",
    "靴子落地": "bullish",
    # 字面有「利多」但其實偏空
    "利多出盡": "bearish",
    "利多不漲": "bearish",
    "利多已反映": "bearish",
    "見光死": "bearish",
}

# 否定詞：出現在「命中詞前方小窗口」內，會翻轉該詞情緒（或抵銷）。
NEGATION_WORDS: List[str] = [
    "未", "沒", "沒有", "不", "無", "免", "難以", "尚未", "並未", "未能",
    "未見", "不再", "不會", "毫無", "缺乏", "未如", "未達", "非",
]

# 否定詞前方窗口大小（字數）。命中詞起點往前看這麼多字。
NEGATION_WINDOW = 6

# 子句邊界（標點/空白）：否定窗口掃描遇到就截斷，避免跨子句/跨轉折誤判。
_CLAUSE_BREAK = re.compile(r"[，。；、！？!?;,\s]")

# 已內含否定/方向語意的片語：即使前方有否定詞，也「不」再翻轉，
# 避免「不如預期」「未如預期」這類本身就是利空詞的片語被二次否定翻成利多。
NEGATION_IMMUNE: set = {
    "不如預期", "不如市場預期", "低於預期", "低於財測", "遜於預期",
    "產能不足", "周轉不靈", "財報不如預期",
}

# 轉折詞：其後子句是新聞重點，命中詞落在轉折之後給予額外加權。
PIVOT_WORDS: List[str] = ["但", "卻", "然而", "不過", "惟", "可惜", "只是", "唯"]

# 轉折後子句的命中詞，分數乘上此倍率（取整數加權）。
PIVOT_BOOST = 2

# 主體誤判提示語：像「客戶砍單」「遭…砍單」，砍單動作主詞是客戶/他方，
# 對被報導公司而言是利空。這裡列出「會強化利空判定」的搭配，
# 主要用途是 rationale 註記，避免「接單/下單」這類字被誤當利多。
# key 為片語，value 為對被報導主體的情緒。
SUBJECT_HINTS: Dict[str, str] = {
    "客戶砍單": "bearish",
    "遭砍單": "bearish",
    "被砍單": "bearish",
    "客戶抽單": "bearish",
    "遭抽單": "bearish",
    "客戶縮減": "bearish",
    "客戶下修": "bearish",
}


# --------------------------------------------------------------------------- #
# 2. 核心計分
# --------------------------------------------------------------------------- #

TITLE_WEIGHT = 2
BODY_WEIGHT = 1


def _scan(text: str, vocab: List[str]) -> List[str]:
    """回傳 text 中命中 vocab 的詞清單（保留重複次序，方便加總）。

    保留此函式給事件掃描等不需位置資訊的場合使用。
    """
    if not text:
        return []
    hits: List[str] = []
    for w in vocab:
        if not w:
            continue
        # 中文不分詞，直接子字串比對即可；用 re 可一次數出多次出現
        cnt = len(re.findall(re.escape(w), text))
        if cnt > 0:
            hits.extend([w] * cnt)
    return hits


def _scan_with_pos(text: str, vocab: List[str]) -> List[Tuple[str, int]]:
    """回傳 [(命中詞, 起始索引), ...]，含重複命中，依出現位置排序。

    用於需要上下文（否定窗口、轉折位置）的計分。為避免短詞吃掉長詞造成
    重複計分（例如「目標價下修」同時命中「下修」），命中後將該區段
    遮蔽為等長佔位符再繼續掃下一個詞。先掃較長的詞，確保長詞優先。
    """
    if not text:
        return []
    work = list(text)  # 可變，命中後遮蔽
    found: List[Tuple[str, int]] = []
    for w in sorted([v for v in vocab if v], key=len, reverse=True):
        start = 0
        wl = len(w)
        while True:
            idx = "".join(work).find(w, start)
            if idx < 0:
                break
            found.append((w, idx))
            for i in range(idx, idx + wl):
                work[i] = "\x00"  # 遮蔽，避免被其他詞重複命中
            start = idx + wl
    found.sort(key=lambda x: x[1])
    return found


def _scan_events(text: str) -> List[str]:
    """掃 EVENT_LEXICON，回傳命中的事件標籤（已去重，保留首次出現順序）。"""
    if not text:
        return []
    found: List[str] = []
    for label, kws in EVENT_LEXICON.items():
        for kw in kws:
            if kw and kw in text:
                if label not in found:
                    found.append(label)
                break
    return found


def _is_negated(text: str, pos: int, word: str) -> bool:
    """命中詞起點 pos 前方 NEGATION_WINDOW 字內是否有否定詞。

    若該命中詞本身屬於 NEGATION_IMMUNE（已內含否定/方向語意），不視為被否定，
    避免「不如預期」「未如預期」被二次否定翻成正向。
    """
    if word in NEGATION_IMMUNE:
        return False
    win_start = max(0, pos - NEGATION_WINDOW)
    window = text[win_start:pos]
    # 子句邊界：只看「最後一個標點 / 轉折詞之後」到命中詞之間的範圍，
    # 避免「並未擴產，但訂單滿手」的「訂單滿手」被前一子句的「未」誤否定。
    cut = 0
    for m in _CLAUSE_BREAK.finditer(window):
        cut = m.end()
    for p in PIVOT_WORDS:
        i = window.rfind(p)
        if i >= 0:
            cut = max(cut, i + len(p))
    window = window[cut:]
    return any(neg in window for neg in NEGATION_WORDS)


def _pivot_start(text: str) -> int:
    """回傳第一個轉折詞之後的索引；沒有轉折詞則回傳一個大數（代表無轉折）。"""
    best = len(text) + 1
    for p in PIVOT_WORDS:
        idx = text.find(p)
        if 0 <= idx < best:
            best = idx + len(p)
    return best


def _score_text(text: str, vocab: List[str], weight: int) -> Tuple[int, int, List[str], List[str]]:
    """對單一段文字（標題或內文）計分。

    回傳 (本方得分, 翻轉到對方得分, 本方命中詞, 被否定翻轉的命中詞)。
    - 否定翻轉：命中詞前方窗口有否定詞 → 該詞分數記到「對方」，note 也歸對方。
    - 轉折加權：命中詞落在第一個轉折詞之後 → 分數乘 PIVOT_BOOST。
    """
    if not text:
        return 0, 0, [], []
    pivot = _pivot_start(text)
    own = 0
    flipped = 0
    own_notes: List[str] = []
    flip_notes: List[str] = []
    for word, pos in _scan_with_pos(text, vocab):
        w = weight
        boosted = pos >= pivot  # 轉折後子句是重點，加權
        if boosted:
            w *= PIVOT_BOOST
        if _is_negated(text, pos, word):
            flipped += w
            flip_notes.append(f"!{word}" + ("^" if boosted else ""))
        else:
            own += w
            own_notes.append(word + ("^" if boosted else ""))
    return own, flipped, own_notes, flip_notes


def _score_side(title: str, body: str, vocab: List[str]) -> Tuple[int, int, List[str], List[str]]:
    """合併標題（權重 2）與內文（權重 1）的計分。

    回傳 (本方總分, 翻轉到對方總分, 本方命中詞, 被否定翻轉命中詞)。
    """
    t_own, t_flip, t_own_n, t_flip_n = _score_text(title, vocab, TITLE_WEIGHT)
    b_own, b_flip, b_own_n, b_flip_n = _score_text(body, vocab, BODY_WEIGHT)
    own = t_own + b_own
    flipped = t_flip + b_flip

    def _dedup(seq):
        seen = set()
        return [w for w in seq if not (w in seen or seen.add(w))]

    return own, flipped, _dedup(t_own_n + b_own_n), _dedup(t_flip_n + b_flip_n)


def _apply_reversals(title: str, body: str) -> Tuple[int, int, List[str], str, str]:
    """先抽出反轉慣用語計分，並把命中片語從文字中遮蔽（換等長佔位符）。

    回傳 (反轉帶來的利多分, 反轉帶來的利空分, 命中片語描述, 遮蔽後標題, 遮蔽後內文)。
    片語在標題用 TITLE_WEIGHT、內文用 BODY_WEIGHT 計分。
    遮蔽是為了避免「利空出盡」之後又被「利空」這個子字串重複算成利空。
    """
    pos_add = 0
    neg_add = 0
    notes: List[str] = []
    for seg, weight in ((title, TITLE_WEIGHT), (body, BODY_WEIGHT)):
        for phrase, side in REVERSAL_PHRASES.items():
            if phrase in seg:
                cnt = seg.count(phrase)
                if side == "bullish":
                    pos_add += weight * cnt
                else:
                    neg_add += weight * cnt
                arrow = "→多" if side == "bullish" else "→空"
                notes.append(f"{phrase}{arrow}")
    # 遮蔽（標題、內文都做）
    masked_title = title
    masked_body = body
    for phrase in REVERSAL_PHRASES:
        masked_title = masked_title.replace(phrase, "\x00" * len(phrase))
        masked_body = masked_body.replace(phrase, "\x00" * len(phrase))
    # 去重 notes
    seen = set()
    uniq = [n for n in notes if not (n in seen or seen.add(n))]
    return pos_add, neg_add, uniq, masked_title, masked_body


def _apply_subject_hints(title: str, body: str) -> Tuple[int, List[str]]:
    """主體誤判提示：偵測「客戶砍單 / 遭砍單」等對被報導公司是利空的搭配。

    回傳 (額外利空分, 註記)。只加分不遮蔽（砍單本身仍會被利空詞掃到，
    這裡的加分是強化主詞為他方時的利空訊號，並在 rationale 留痕）。
    """
    SUBJECT_CAP = TITLE_WEIGHT          # 主體提示單則最多加這麼多分（防灌爆門檻）
    neg_add = 0
    notes: List[str] = []
    for seg, weight in ((title, TITLE_WEIGHT), (body, BODY_WEIGHT)):
        for phrase, side in SUBJECT_HINTS.items():
            start = 0
            while True:
                idx = seg.find(phrase, start)
                if idx < 0:
                    break
                start = idx + len(phrase)
                # 命中片語前方有否定詞（如「未遭客戶砍單」）→ 不加利空分
                if _is_negated(seg, idx, phrase):
                    notes.append(f"主體:{phrase}(否定略)")
                    continue
                if side == "bearish":
                    neg_add += weight
                notes.append(f"主體:{phrase}")
    neg_add = min(neg_add, SUBJECT_CAP)   # 單則上限
    seen = set()
    uniq = [n for n in notes if not (n in seen or seen.add(n))]
    return neg_add, uniq


# --------------------------------------------------------------------------- #
# 3. 對外 API
# --------------------------------------------------------------------------- #

def classify(title: str, body: str = "") -> dict:
    """
    依規則層判斷新聞的利多/利空與事件分類。

    Args:
        title: 新聞標題（必填）
        body:  新聞內文（可空）

    Returns:
        {
          "sentiment":  "bullish" | "bearish" | "neutral",
          "confidence": float,            # 0~1
          "events":     list[str],        # 例：["產能", "警示"]
          "rationale":  str,              # 命中關鍵字摘要（debug 用）
        }
    """
    title = title or ""
    body = body or ""

    # 事件：用原文掃（含反轉片語裡的字也算事件，例如「利多出盡」不影響事件）
    events_title = _scan_events(title)
    events_body = _scan_events(body)
    events: List[str] = list(events_title)
    for e in events_body:
        if e not in events:
            events.append(e)

    # 步驟 1：先抽出反轉慣用語（利空出盡→多、利多出盡→空），並遮蔽避免重複計分
    rev_pos, rev_neg, rev_notes, m_title, m_body = _apply_reversals(title, body)

    # 步驟 2：在「遮蔽後」的文字上做一般詞掃描（含否定翻轉、轉折加權）
    pos_own, pos_flip, pos_own_notes, pos_flip_notes = _score_side(
        m_title, m_body, BULLISH_WORDS)
    neg_own, neg_flip, neg_own_notes, neg_flip_notes = _score_side(
        m_title, m_body, BEARISH_WORDS)

    # 步驟 3：主體誤判提示（客戶砍單等 → 強化利空）
    subj_neg, subj_notes = _apply_subject_hints(m_title, m_body)

    # 匯總：本方得分 + 反轉貢獻 + 對方被否定翻過來的分 + 主體提示
    #   利多被否定 → 計入利空；利空被否定 → 計入利多。
    pos = pos_own + rev_pos + neg_flip
    neg = neg_own + rev_neg + pos_flip + subj_neg

    # 判斷情緒：要拉開 1.3 倍才算明顯偏一邊，否則 neutral
    if pos == 0 and neg == 0:
        sentiment = "neutral"
    elif pos > neg * 1.3:
        sentiment = "bullish"
    elif neg > pos * 1.3:
        sentiment = "bearish"
    else:
        sentiment = "neutral"

    # 信心：差距相對於總量的比例；+1 避免除以 0、避免兩邊都 0 時噴 NaN
    confidence = abs(pos - neg) / (pos + neg + 1)
    # 夾到 0~1
    if confidence < 0:
        confidence = 0.0
    elif confidence > 1:
        confidence = 1.0

    # 每一方列出「本方命中詞 + 從對方否定翻過來的詞」，讓分數有跡可循
    pos_src = pos_own_notes + [n.lstrip("!") + "(否定翻多)" for n in neg_flip_notes]
    neg_src = neg_own_notes + [n.lstrip("!") + "(否定翻空)" for n in pos_flip_notes]
    extra = rev_notes + subj_notes
    rationale = (
        f"pos={pos} {pos_src} | neg={neg} {neg_src} | events={events}"
        + (f" | ctx={extra}" if extra else "")
    )

    return {
        "sentiment": sentiment,
        "confidence": round(confidence, 3),
        "events": events,
        "rationale": rationale,
    }


# --------------------------------------------------------------------------- #
# 4. 自我測試
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    # (標題, 期望 sentiment[, 內文])
    cases = [
        # --- 基本利多 / 利空 / 中性 ---
        ("群創12月營收創新高 法人看好Q1",                    "bullish"),
        ("希捷示警:AI 產能跟不上,建廠緩不濟急",             "bearish"),
        ("聯電法說會召開 第四季展望持平",                    "neutral"),
        ("鴻海11月營收年增15% 訂單滿手",                     "bullish"),
        ("緯創股利政策維持去年水準",                          "neutral"),
        ("華邦電踩雷恆大 提列損失15億",                       "bearish"),
        ("聯發科宣布購併矽智財公司XX",                        "bullish"),
        # --- 主體區分：客戶砍單對被報導公司是利空（不可因「單」誤判利多）---
        ("台積電遭客戶砍單 出貨大幅下修",                    "bearish"),
        ("面板廠驚傳遭陸系客戶抽單 Q2恐轉虧",                "bearish"),
        # --- 反轉慣用語：利空出盡偏多、利多出盡偏空 ---
        ("台積電利空出盡 觸底反彈站回均線",                  "bullish"),
        ("除息行情上演利多出盡 開高走低翻黑",                "bearish"),
        ("半導體庫存利空鈍化 外資回頭買超",                  "bullish"),
        # --- 否定翻轉：否定詞在命中詞前方窗口 ---
        ("面板報價未見回升 廠商營運仍承壓",                  "bearish"),
        ("營收尚未轉佳 法人保守看待",                        "bearish"),
        ("旺季效應不如預期 出貨動能轉弱",                    "bearish"),
        # --- 轉折處理：但/卻之後是重點 ---
        ("營收創高，但毛利率大幅下滑 獲利衰退",              "bearish"),
        ("上半年表現平平，下半年訂單湧入 接單暢旺",          "bullish"),
        # --- 各類事件 ---
        ("XX生技訴訟敗訴 判賠12億元",                        "bearish"),
        ("某金控宣布實施庫藏股 護盤護價",                    "bullish"),
        ("某營建股辦理現金增資 每股70元",                    "neutral"),
        ("外資連三日賣超台積電 調節逾兩萬張",                "bearish"),
        ("投信認養中小型股 連續買超帶量攻漲停",              "bullish"),
        # --- 財務危機事件 ---
        ("某公司票據跳票 恐打入全額交割股",                  "bearish"),
        ("某電子廠調升全年財測目標 上修EPS預估",            "bullish"),
        # --- 內文輔助（標題中性，內文偏多）---
        ("某半導體廠召開法人說明會",                          "bullish",
         "公司表示在手訂單能見度高，產能滿載，毛利率提升，全年營收可望創高。"),
        # --- 修復回歸：否定窗口跨子句不誤判（Bug 1）、subject 尊重否定（Bug 2）---
        ("公司並未擴產，但訂單滿手 出貨暢旺",                  "bullish"),
        ("台積電未遭客戶砍單 營運穩健報喜",                    "bullish"),
    ]

    print(f"字典規模：利多 {len(BULLISH_WORDS)} 詞 / 利空 {len(BEARISH_WORDS)} 詞 / "
          f"事件 {len(EVENT_LEXICON)} 類 / 反轉語 {len(REVERSAL_PHRASES)} / "
          f"否定詞 {len(NEGATION_WORDS)} / 轉折詞 {len(PIVOT_WORDS)}")
    print("-" * 78)

    miss = 0
    for case in cases:
        title, expect = case[0], case[1]
        body = case[2] if len(case) > 2 else ""
        r = classify(title, body)
        ok = "OK " if r["sentiment"] == expect else "MISS"
        if r["sentiment"] != expect:
            miss += 1
        print(f"[{ok}] {title}")
        print(f"       -> {r['sentiment']} (conf={r['confidence']})  events={r['events']}")
        print(f"          expect={expect}  | {r['rationale']}")
        print()

    print("-" * 78)
    print(f"總結：{len(cases) - miss}/{len(cases)} 與預期一致，{miss} 個誤判。")
