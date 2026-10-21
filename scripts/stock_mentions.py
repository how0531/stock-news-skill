# -*- coding: utf-8 -*-
"""
全市場股名反查: 一則新聞的標題與內文點名了哪些上市櫃個股,點名在標題還是只在內文。
只用 data/stocks/tw_names.json(代號到簡稱)與 tw_stocks.json(策展別名),
不依賴 news_core,不連網。

  build_lexicon(code_names, curated)  建字典 {"names": {代號: 股名}, "terms": {詞: 代號}, "first": {首字: [詞…]}}
  load_lexicon()                      讀兩個 JSON 建字典,模組層快取
  find_mentions(title, body, stock_codes, lex)  回傳 {代號: "title" 或 "body"}
"""
import json
import pathlib
import re

_DATA = pathlib.Path(__file__).resolve().parent.parent / "data" / "stocks"

# 是產業或題材的別名,不代表點名某一檔(股票本身仍可靠代號命中)
THEME_ALIASES = frozenset({
    "AI伺服器", "ABF載板", "MLCC", "DRAM", "散熱", "IC設計", "EMC", "CCL", "半導體通路",
    "白牌交換器", "伺服器BMC", "高股息ETF", "台灣50", "台50", "晶圓代工龍頭", "Toyota台灣代理",
    "Delta", "Mega", "Cathay", "Quanta", "MSI",
})

# 股名同時是日常用語,出現在新聞裡多半不是在講這檔股票(股票本身仍可靠代號命中)
COMMON_WORD_NAMES = frozenset((
    "大量 新產 數字 中華 聯合 世界 新興 全新 新建 全台 統一 南亞 華電 至上 卓越 業強 大成 "
    "及成 力士 三星 精確 時報 全國 資通 力新 南港 承啟 泰山 地球 典範 根基 互動 宏觀 巨大 "
    "全家 光譜 帝寶 首利 合一 力成 達新 達能 中台 國統 大華 大亞 合機 中工 星通 立德 利機 "
    "華廣 高技 東森 高力 佳能 大樹 氣立 元晶 華城 大台北 光明 幸福 國產 安心 冠軍 傳奇 正文 "
    "有益 易發 綠電 精華 精英 進階 台南 建國 華夏 華東 無敵 樂意 得力 慶生 惠普 康普 昇陽 "
    "海光 花王 亞航 大塚 強生 恆大 新華 中航 中電 中天 中視 遠見 浪凡 台灣大 中石化 新零售 雲嘉南"
).split())

# 代號: 4 到 6 碼數字,前後不能黏著英數或小數點等,也不能是「2027年」「5000點」這類數量
_CODE_RE = re.compile(r"(?<![0-9A-Za-z./$])(\d{4,6})(?![0-9A-Za-z.%點元億萬張])(?!\s*[年月日])")
_URL_RE = re.compile(r"https?://\S+")

_LEXICON = None


def _term_ok(term):
    """可當比對詞的條件: 至少 2 字,不是純數字或 ticker(交給代號比對),不是主題詞或常用詞。"""
    return (len(term) >= 2 and not term.isdigit() and "." not in term
            and term not in THEME_ALIASES and term not in COMMON_WORD_NAMES)


def build_lexicon(code_names, curated):
    names = dict(code_names)
    bare_aliases = {}                      # 裸代號 -> 別名聯集(.TW/.TWO/.TWO2 合併)
    for key, info in curated.items():
        code = key.split(".")[0]
        zh = info.get("name_zh") or ""
        if zh:
            names.setdefault(code, zh)
        # name_zh 也當別名(與正式簡稱相同的會在下面因已是詞而略過)
        bare_aliases.setdefault(code, []).extend([zh, *(info.get("aliases") or [])])

    terms = {}
    for code, name in names.items():       # 正式簡稱優先
        name = name.strip()
        if _term_ok(name):
            terms.setdefault(name, code)
    owners = {}                            # 別名 -> 擁有它的代號集合
    for code, aliases in bare_aliases.items():
        for a in aliases:
            owners.setdefault(a.strip(), set()).add(code)
    for alias, codes in owners.items():
        # 別名是他檔正式簡稱就丟別名;同一別名在兩檔以上全部丟
        if len(codes) == 1 and alias not in terms and _term_ok(alias):
            terms[alias] = next(iter(codes))

    first = {}
    for term in terms:
        first.setdefault(term[0], []).append(term)
    for group in first.values():
        group.sort(key=len, reverse=True)  # 同首字的詞,長的在前(最長匹配)
    return {"names": names, "terms": terms, "first": first}


def load_lexicon():
    global _LEXICON
    if _LEXICON is None:
        code_names = json.loads((_DATA / "tw_names.json").read_text(encoding="utf-8"))
        curated = json.loads((_DATA / "tw_stocks.json").read_text(encoding="utf-8"))
        _LEXICON = build_lexicon(code_names, curated)
    return _LEXICON


def _is_alnum(ch):
    return ch.isascii() and ch.isalnum()


def _edge_ok(text, i, j, term):
    """詞首是英數時前一字不能是英數,詞尾是英數時後一字不能是英數(區分大小寫)。"""
    if _is_alnum(term[0]) and i > 0 and _is_alnum(text[i - 1]):
        return False
    if _is_alnum(term[-1]) and j < len(text) and _is_alnum(text[j]):
        return False
    return True


def _scan(text, lex):
    """首字索引掃描最長匹配,命中就吃掉那一段,短名不再重複命中。"""
    found, i, n = set(), 0, len(text)
    while i < n:
        for term in lex["first"].get(text[i], ()):
            j = i + len(term)
            if text.startswith(term, i) and _edge_ok(text, i, j, term):
                found.add(lex["terms"][term])
                i = j
                break
        else:
            i += 1
    return found


def _hits(text, lex):
    text = _URL_RE.sub(" ", text or "")
    found = _scan(text, lex)
    found.update(c for c in _CODE_RE.findall(text) if c in lex["names"])
    return found


def find_mentions(title, body, stock_codes, lex):
    """回傳 {代號: "title" 或 "body"}。標題點名算 title,只在內文或只在出版商代號算 body。"""
    in_title = _hits(title, lex)
    in_body = _hits(body, lex)
    in_body.update(c for c in (stock_codes or ()) if c in lex["names"])
    out = {c: "title" for c in sorted(in_title)}
    out.update({c: "body" for c in sorted(in_body - in_title)})
    return out
