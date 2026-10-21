"""
build_stock_dict.py
-------------------
Build curated stock dictionaries for Finance-NEWS individual-stock
identification across TW / US / JP markets.

Outputs:
    data/stocks/tw_stocks.json
    data/stocks/us_stocks.json
    data/stocks/jp_stocks.json

Each entry shape:
    {
      "<ticker>": {
        "ticker": str,
        "name_zh": str,
        "name_en": str,
        "market": "TW" | "US" | "JP",
        "sector": str,
        "aliases": [str, ...]
      }
    }

Design notes
============
* We deliberately curate a high-quality subset (top market-cap / frequently
  reported names) instead of scraping the full universe. This file is the
  single source of truth - run the script to regenerate JSON.
* Aliases include Chinese name, short name, English name, ticker with and
  without market suffix, and well-known nicknames (e.g. "護國神山", "黃仁勳").
* TW tickers use ``NNNN.TW`` (TWSE) or ``NNNN.TWO`` (TPEx).
* JP tickers use ``NNNN.T``. For Toyota / Sony / Honda we map ADR aliases
  (TM-US / SONY-US / HMC-US) used by cnyes.
* US tickers may include ``{TICKER}-US`` aliases (cnyes convention).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Tuple

try:
    from .common import request_get
except ImportError:
    from common import request_get

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "stocks"

# 高歧義縮寫與單字元，一律不得作為 alias（黑名單只維護在這裡）
ALIAS_BLACKLIST = {
    "AI", "EV", "5G", "6G", "IC", "IT", "OS", "CEO", "TV", "VR", "AR",
    "PC", "GPU", "CPU", "HBM", "SSD",
}


def _entry(
    ticker: str,
    name_zh: str,
    name_en: str,
    market: str,
    sector: str,
    extra_aliases: List[str] | None = None,
) -> Tuple[str, dict]:
    """Build one entry plus an auto-generated alias set."""
    aliases: List[str] = []

    # core variants
    if name_zh:
        aliases.append(name_zh)
    if name_en:
        aliases.append(name_en)

    aliases.append(ticker)
    # also add ticker without suffix
    bare = ticker.split(".")[0]
    if bare and bare != ticker:
        aliases.append(bare)

    # US: add cnyes "-US" suffix form
    if market == "US":
        aliases.append(f"{ticker}-US")

    if extra_aliases:
        aliases.extend(extra_aliases)

    # dedupe preserving order
    seen, ordered = set(), []
    for a in aliases:
        a = a.strip()
        if a and a not in seen:
            seen.add(a)
            ordered.append(a)

    return ticker, {
        "ticker": ticker,
        "name_zh": name_zh,
        "name_en": name_en,
        "market": market,
        "sector": sector,
        "aliases": ordered,
    }


# ---------------------------------------------------------------------------
# TW STOCKS  (curated ~180 names: weights, AI / semi supply chain, ETFs)
# ---------------------------------------------------------------------------

TW_RAW: List[tuple] = [
    # ticker,    zh,        en,                     sector,   extra aliases
    ("2330.TW", "台積電", "TSMC",                   "半導體", ["台積", "TSM", "護國神山", "晶圓代工龍頭", "TSM-US"]),
    ("2317.TW", "鴻海",   "Hon Hai Precision",      "電子組裝", ["鴻海精密", "Foxconn", "富士康", "HNHPF"]),
    ("2454.TW", "聯發科", "MediaTek",               "半導體", ["聯發", "MTK"]),
    ("2308.TW", "台達電", "Delta Electronics",      "電子零組件", ["台達", "Delta"]),
    ("2382.TW", "廣達",   "Quanta Computer",        "電子組裝", ["Quanta", "AI伺服器"]),
    ("2891.TW", "中信金", "CTBC Financial",         "金融", ["中國信託", "CTBC"]),
    ("2882.TW", "國泰金", "Cathay Financial",       "金融", ["國泰金控", "Cathay"]),
    ("2881.TW", "富邦金", "Fubon Financial",        "金融", ["富邦金控", "Fubon"]),
    ("2412.TW", "中華電", "Chunghwa Telecom",       "電信", ["中華電信", "CHT"]),
    ("2303.TW", "聯電",   "UMC",                    "半導體", ["聯華電子", "UMC-US"]),
    ("3711.TW", "日月光投控", "ASE Technology",     "半導體封測", ["日月光", "ASE", "ASX-US"]),
    ("2002.TW", "中鋼",   "China Steel",            "鋼鐵", ["中國鋼鐵"]),
    ("1301.TW", "台塑",   "Formosa Plastics",       "塑化", ["台灣塑膠"]),
    ("1303.TW", "南亞",   "Nan Ya Plastics",        "塑化", ["南亞塑膠"]),
    ("1326.TW", "台化",   "Formosa Chemicals",      "塑化", ["台灣化纖"]),
    ("6505.TW", "台塑化", "Formosa Petrochemical",  "塑化", []),
    ("2886.TW", "兆豐金", "Mega Financial",         "金融", ["兆豐金控", "Mega"]),
    ("2884.TW", "玉山金", "E.Sun Financial",        "金融", ["玉山金控", "E.Sun"]),
    ("2885.TW", "元大金", "Yuanta Financial",       "金融", ["元大金控", "Yuanta"]),
    ("2887.TW", "台新金", "Taishin Financial",      "金融", ["台新金控"]),
    ("2890.TW", "永豐金", "SinoPac Financial",      "金融", ["永豐金控"]),
    ("2892.TW", "第一金", "First Financial",        "金融", ["第一金控"]),
    ("2880.TW", "華南金", "Hua Nan Financial",      "金融", ["華南金控"]),
    ("2883.TW", "開發金", "CDF Holding",            "金融", ["中華開發金控"]),
    ("2888.TW", "新光金", "Shin Kong Financial",    "金融", ["新光金控"]),
    ("2889.TW", "國票金", "Waterland Financial",    "金融", []),
    ("5880.TW", "合庫金", "Taiwan Cooperative",     "金融", ["合庫金控"]),
    ("2801.TW", "彰銀",   "Chang Hwa Bank",         "金融", ["彰化銀行"]),
    ("2823.TW", "中壽",   "China Life",             "金融", ["中國人壽"]),
    ("2834.TW", "臺企銀", "Taiwan Business Bank",   "金融", ["台企銀"]),
    ("3045.TW", "台灣大", "Taiwan Mobile",          "電信", ["台灣大哥大"]),
    ("4904.TW", "遠傳",   "Far EasTone",            "電信", ["遠傳電信"]),
    ("2357.TW", "華碩",   "ASUS",                   "電子組裝", ["華碩電腦"]),
    ("2353.TW", "宏碁",   "Acer",                   "電子組裝", []),
    ("2376.TW", "技嘉",   "Gigabyte",               "電子組裝", ["技嘉科技"]),
    ("3231.TW", "緯創",   "Wistron",                "電子組裝", ["AI伺服器"]),
    ("3017.TW", "奇鋐",   "Auras Technology",       "電子零組件", ["散熱"]),
    ("2377.TW", "微星",   "MSI",                    "電子組裝", ["微星科技"]),
    ("2356.TW", "英業達", "Inventec",               "電子組裝", []),
    ("4938.TW", "和碩",   "Pegatron",               "電子組裝", []),
    ("3034.TW", "聯詠",   "Novatek",                "半導體", ["聯詠科技", "IC設計"]),
    ("3008.TW", "大立光", "Largan Precision",       "光學", ["大立光電"]),
    ("2474.TW", "可成",   "Catcher Technology",     "電子零組件", []),
    ("2912.TW", "統一超", "President Chain Store",  "通路", ["7-Eleven", "統一超商"]),
    ("1216.TW", "統一",   "Uni-President",          "食品", ["統一企業"]),
    ("2207.TW", "和泰車", "Hotai Motor",            "汽車", ["和泰汽車", "Toyota台灣代理"]),
    ("1101.TW", "台泥",   "Taiwan Cement",          "水泥", ["台灣水泥"]),
    ("1102.TW", "亞泥",   "Asia Cement",            "水泥", ["亞洲水泥"]),
    ("2105.TW", "正新",   "Cheng Shin Rubber",      "橡膠", ["正新橡膠"]),
    ("2227.TW", "裕日車", "Yulon Nissan",           "汽車", []),
    ("2201.TW", "裕隆",   "Yulon Motor",            "汽車", ["裕隆汽車"]),
    ("2603.TW", "長榮",   "Evergreen Marine",       "航運", ["長榮海運"]),
    ("2609.TW", "陽明",   "Yang Ming",              "航運", ["陽明海運"]),
    ("2615.TW", "萬海",   "Wan Hai Lines",          "航運", ["萬海航運"]),
    ("2618.TW", "長榮航", "EVA Air",                "航運", ["長榮航空"]),
    ("2610.TW", "華航",   "China Airlines",         "航運", ["中華航空"]),
    ("3037.TW", "欣興",   "Unimicron",              "PCB", ["欣興電子", "ABF載板"]),
    ("3023.TW", "信邦",   "Sinbon Electronics",     "電子零組件", []),
    ("2049.TW", "上銀",   "Hiwin",                  "機械", ["上銀科技"]),
    ("1605.TW", "華新",   "Walsin Lihwa",           "電線電纜", []),
    ("2912.TWO", "統一超商", "President Chain Store", "通路", []),  # placeholder dup harmless
    ("2345.TW", "智邦",   "Accton Technology",      "網通", ["白牌交換器"]),
    ("3661.TW", "世芯-KY", "Alchip",                "半導體", ["世芯", "Alchip Technologies"]),
    ("6669.TW", "緯穎",   "Wiwynn",                 "電子組裝", ["AI伺服器"]),
    ("2059.TW", "川湖",   "King Slide",             "電子零組件", []),
    ("1590.TW", "亞德客-KY", "AirTAC",              "機械", ["亞德客"]),
    ("4763.TW", "材料-KY", "Material Industries",   "塑化", []),
    ("6415.TW", "矽力-KY", "Silergy",               "半導體", ["矽力杰"]),
    ("3653.TW", "健策",   "Chenming Electronic",    "電子零組件", []),
    ("6488.TW", "環球晶", "GlobalWafers",           "半導體", ["環球晶圓"]),
    ("8046.TW", "南電",   "Nan Ya PCB",             "PCB", ["南亞電路板", "ABF載板"]),
    ("3661.TWO", "世芯-KY", "Alchip",               "半導體", []),
    ("3443.TW", "創意",   "Global Unichip",         "半導體", ["創意電子", "GUC"]),
    ("2360.TW", "致茂",   "Chroma ATE",             "電子設備", []),
    ("2379.TW", "瑞昱",   "Realtek",                "半導體", ["瑞昱半導體"]),
    ("2408.TW", "南亞科", "Nanya Technology",       "半導體", ["DRAM"]),
    ("3530.TW", "晶相光", "Crystalwise Technology", "光學", []),
    ("3231.TWO", "緯創",  "Wistron",                "電子組裝", []),
    ("2327.TW", "國巨",   "Yageo",                  "電子零組件", ["國巨電子", "MLCC"]),
    ("2383.TW", "台光電", "Elite Material",         "PCB", ["EMC", "CCL"]),
    ("6271.TW", "同欣電", "Tong Hsing Electronic",  "半導體封測", []),
    ("3702.TW", "大聯大", "WPG Holdings",           "通路", ["半導體通路"]),
    ("5871.TW", "中租-KY", "Chailease",             "金融", ["中租控股"]),
    ("5269.TW", "祥碩",   "Asmedia",                "半導體", []),
    ("8454.TW", "富邦媒", "Fubon Media",            "通路", ["momo"]),
    ("2912.TWO2", "統一超商", "PCSC",               "通路", []),  # alias-only fallback (unused)
    ("2492.TW", "華新科", "Walsin Technology",      "電子零組件", ["MLCC"]),
    ("3673.TW", "TPK-KY", "TPK Holding",           "光學", ["宸鴻"]),
    ("2492.TWO", "華新科", "Walsin Technology",     "電子零組件", []),
    ("8299.TW", "群聯",   "Phison Electronics",     "半導體", ["群聯電子"]),
    ("3293.TW", "鈊象",   "International Games System", "遊戲", []),
    ("3105.TW", "穩懋",   "WIN Semiconductors",     "半導體", []),
    ("3019.TW", "亞光",   "Asia Optical",           "光學", []),
    ("2376.TWO", "技嘉",  "Gigabyte",               "電子組裝", []),
    ("6213.TW", "聯茂",   "Iteq",                   "PCB", []),
    ("2371.TW", "大同",   "Tatung",                 "電機", []),
    ("2347.TW", "聯強",   "Synnex Technology",      "通路", []),
    ("2603.TWO", "長榮",  "Evergreen Marine",       "航運", []),
    ("3035.TW", "智原",   "Faraday Technology",     "半導體", []),
    ("8210.TW", "勤誠",   "Chenbro Micom",          "電子組裝", []),
    ("3017.TWO", "奇鋐",  "Auras Technology",       "電子零組件", []),
    ("1504.TW", "東元",   "Teco Electric",          "電機", []),
    ("5347.TW", "世界",   "Vanguard International", "半導體", ["世界先進"]),
    ("8454.TWO", "富邦媒", "Fubon Media",           "通路", []),
    ("2615.TWO", "萬海",  "Wan Hai Lines",          "航運", []),
    ("6526.TW", "達發",   "Airoha Technology",      "半導體", []),
    ("2618.TWO", "長榮航","EVA Air",                "航運", []),
    ("2049.TWO", "上銀",  "Hiwin",                  "機械", []),
    ("2492.TW",  "華新科","Walsin Technology",      "電子零組件", []),
    ("6510.TW", "精測",   "Chunghwa Precision Test", "半導體", []),
    ("4919.TW", "新唐",   "Nuvoton Technology",     "半導體", []),
    ("2618.TW", "長榮航",  "EVA Air",               "航運", []),
    ("3293.TWO","鈊象",   "International Games System","遊戲", []),
    ("9904.TW", "寶成",   "Pou Chen",               "紡織", []),
    ("9910.TW", "豐泰",   "Feng Tay",               "紡織", []),
    ("1402.TW", "遠東新", "Far Eastern New Century","紡織", ["遠東新世紀"]),
    ("2912.TW", "統一超", "President Chain Store",  "通路", []),
    ("1722.TW", "台肥",   "Taiwan Fertilizer",      "化工", []),
    ("1717.TW", "長興",   "Eternal Materials",      "化工", []),
    ("1314.TW", "中石化", "China Petrochemical",    "塑化", []),
    ("1227.TW", "佳格",   "Standard Foods",         "食品", []),
    ("1210.TW", "大成",   "Great Wall Enterprise",  "食品", []),
    ("1101.TWO","台泥",   "Taiwan Cement",          "水泥", []),
    ("2059.TWO","川湖",   "King Slide",             "電子零組件", []),
    ("3045.TWO","台灣大", "Taiwan Mobile",          "電信", []),
    # ETFs
    ("0050.TW", "元大台灣50", "Yuanta Taiwan 50 ETF", "ETF", ["台灣50", "台50"]),
    ("0056.TW", "元大高股息", "Yuanta High Dividend ETF", "ETF", ["高股息ETF"]),
    ("00878.TW","國泰永續高股息", "Cathay ESG Sustainability High Dividend ETF", "ETF", ["國泰永續"]),
    ("00929.TW","復華台灣科技優息", "Fuh Hwa Taiwan Tech Dividend ETF", "ETF", []),
    ("00919.TW","群益台灣精選高息", "Capital Taiwan Select High Dividend ETF", "ETF", []),
    ("00940.TW","元大臺灣價值高息", "Yuanta Taiwan Value High Dividend ETF", "ETF", []),
    # Smaller but frequently-reported
    ("3289.TW", "宜特",   "iST",                    "半導體", []),
    ("4966.TW", "譜瑞-KY","Parade Technologies",   "半導體", ["譜瑞"]),
    ("5388.TW", "中磊",   "Sercomm",                "網通", []),
    ("4977.TW", "眾達-KY","Lightel",                "光通訊", []),
    ("2455.TW", "全新",   "Visual Photonics",       "半導體", []),
    ("3450.TW", "聯鈞",   "Luxnet",                 "光通訊", []),
    ("3406.TW", "玉晶光", "Genius Electronic Optical","光學", []),
    ("4961.TW", "天鈺",   "Fitipower",              "半導體", []),
    ("6770.TW", "力積電", "Powerchip Semiconductor","半導體", ["力晶積成"]),
    ("3576.TW", "聯合再生", "United Renewable Energy", "綠能", []),
    ("6116.TW", "彩晶",   "Hannstar Display",       "面板", []),
    ("2409.TW", "友達",   "AUO",                    "面板", ["友達光電", "AUO-US"]),
    ("3481.TW", "群創",   "Innolux",                "面板", ["群創光電"]),
    ("2449.TW", "京元電", "King Yuan Electronics",  "半導體封測", ["京元電子"]),
    ("6533.TW", "晶心科", "Andes Technology",       "半導體", []),
    ("8081.TW", "致新",   "Global Mixed Mode Technology", "半導體", []),
    ("5274.TW", "信驊",   "Aspeed Technology",      "半導體", ["伺服器BMC"]),
    ("2376.TW", "技嘉",   "Gigabyte",               "電子組裝", []),
    ("3653.TWO","健策",   "Chenming Electronic",    "電子零組件", []),
    ("6669.TWO","緯穎",   "Wiwynn",                 "電子組裝", []),
    ("6741.TW", "91APP-KY","91APP",                 "軟體", []),
    ("4174.TW", "浩鼎",   "OBI Pharma",             "生技", []),
    ("4123.TW", "晟德",   "Center Laboratories",    "生技", []),
    ("6446.TW", "藥華藥", "PharmaEssentia",         "生技", []),
    ("2727.TW", "王品",   "Wowprime",               "餐飲", []),
    ("2723.TW", "美食-KY","Gourmet Master",         "餐飲", ["85度C"]),
    ("3293.TW", "鈊象",   "International Games System","遊戲", []),
    ("3293.TWO","鈊象",   "International Games System","遊戲", []),
    ("5269.TWO","祥碩",   "Asmedia",                "半導體", []),
    ("3653.TW", "健策",   "Chenming Electronic",    "電子零組件", []),
    ("6669.TW", "緯穎",   "Wiwynn",                 "電子組裝", []),
    ("3037.TWO","欣興",   "Unimicron",              "PCB", []),
    ("3008.TWO","大立光", "Largan Precision",       "光學", []),
    ("2376.TW", "技嘉",   "Gigabyte",               "電子組裝", []),
    ("8454.TW", "富邦媒", "Fubon Media",            "通路", []),
    ("6669.TW", "緯穎",   "Wiwynn",                 "電子組裝", []),
    ("4904.TWO","遠傳",   "Far EasTone",            "電信", []),
    ("2412.TWO","中華電", "Chunghwa Telecom",       "電信", []),
    ("3711.TWO","日月光投控","ASE Technology",      "半導體封測", []),
    ("2454.TWO","聯發科", "MediaTek",               "半導體", []),
    ("2317.TWO","鴻海",   "Hon Hai Precision",      "電子組裝", []),
    ("2330.TWO","台積電", "TSMC",                   "半導體", []),
]


# ---------------------------------------------------------------------------
# US STOCKS  (Mag 7 + key semiconductors + frequently-reported names)
# ---------------------------------------------------------------------------

US_RAW: List[tuple] = [
    # ticker, zh, en, sector, extra aliases
    ("NVDA", "輝達",       "NVIDIA",                 "半導體",   ["黃仁勳", "Jensen Huang", "NVIDIA Corp"]),
    ("AAPL", "蘋果",       "Apple",                  "科技",     ["Apple Inc", "庫克", "Tim Cook"]),
    ("MSFT", "微軟",       "Microsoft",              "軟體",     ["Microsoft Corp", "納德拉"]),
    ("GOOGL","谷歌",       "Alphabet Class A",       "網路",     ["Google", "Alphabet", "GOOG"]),
    ("GOOG", "谷歌",       "Alphabet Class C",       "網路",     ["Google", "Alphabet"]),
    ("AMZN", "亞馬遜",     "Amazon",                 "電商",     ["Amazon.com", "貝佐斯"]),
    ("META", "Meta",       "Meta Platforms",         "網路",     ["臉書", "Facebook", "祖克柏", "Mark Zuckerberg"]),
    ("TSLA", "特斯拉",     "Tesla",                  "汽車",     ["馬斯克", "Elon Musk", "電動車"]),
    ("AVGO", "博通",       "Broadcom",               "半導體",   ["Broadcom Inc"]),
    ("AMD",  "超微",       "AMD",                    "半導體",   ["Advanced Micro Devices", "蘇姿丰", "Lisa Su"]),
    ("INTC", "英特爾",     "Intel",                  "半導體",   ["Intel Corp"]),
    ("QCOM", "高通",       "Qualcomm",               "半導體",   ["Qualcomm Inc"]),
    ("TXN",  "德州儀器",   "Texas Instruments",      "半導體",   ["TI"]),
    ("MU",   "美光",       "Micron Technology",      "半導體",   ["Micron", "DRAM"]),
    ("ASML", "艾司摩爾",   "ASML Holding",           "半導體設備",["ASML", "曝光機", "EUV"]),
    ("AMAT", "應用材料",   "Applied Materials",      "半導體設備",["Applied"]),
    ("LRCX", "科林研發",   "Lam Research",           "半導體設備",["Lam"]),
    ("KLAC", "科磊",       "KLA Corporation",        "半導體設備",["KLA"]),
    ("MRVL", "邁威爾",     "Marvell Technology",     "半導體",   ["Marvell"]),
    ("ARM",  "安謀",       "Arm Holdings",           "半導體",   ["Arm"]),
    ("NFLX", "網飛",       "Netflix",                "媒體",     ["Netflix Inc"]),
    ("DIS",  "迪士尼",     "Walt Disney",            "媒體",     ["Disney"]),
    ("CRM",  "賽富時",     "Salesforce",             "軟體",     ["Salesforce.com"]),
    ("ORCL", "甲骨文",     "Oracle",                 "軟體",     ["Oracle Corp"]),
    ("ADBE", "奧多比",     "Adobe",                  "軟體",     ["Adobe Inc"]),
    ("NOW",  "ServiceNow", "ServiceNow",             "軟體",     []),
    ("INTU", "Intuit",     "Intuit",                 "軟體",     []),
    ("PLTR", "Palantir",   "Palantir Technologies",  "軟體",     ["AI"]),
    ("SNOW", "雪花",       "Snowflake",              "軟體",     ["Snowflake Inc"]),
    ("UBER", "優步",       "Uber Technologies",      "網路",     ["Uber"]),
    ("ABNB", "Airbnb",     "Airbnb",                 "網路",     []),
    ("SHOP", "Shopify",    "Shopify",                "網路",     []),
    ("PYPL", "PayPal",     "PayPal",                 "金融科技", []),
    ("SQ",   "Block",      "Block",                  "金融科技", ["Square"]),
    ("COIN", "Coinbase",   "Coinbase Global",        "金融科技", ["加密貨幣"]),
    ("V",    "Visa",       "Visa",                   "金融",     []),
    ("MA",   "萬事達",     "Mastercard",             "金融",     ["Mastercard"]),
    ("JPM",  "摩根大通",   "JPMorgan Chase",         "金融",     ["JPMorgan", "小摩"]),
    ("BAC",  "美國銀行",   "Bank of America",        "金融",     ["BofA"]),
    ("WFC",  "富國銀行",   "Wells Fargo",            "金融",     []),
    ("GS",   "高盛",       "Goldman Sachs",          "金融",     ["Goldman"]),
    ("MS",   "摩根士丹利", "Morgan Stanley",         "金融",     ["大摩"]),
    ("C",    "花旗",       "Citigroup",              "金融",     ["Citi"]),
    ("BRK.B","波克夏",     "Berkshire Hathaway B",   "金融",     ["Berkshire", "巴菲特", "Buffett"]),
    ("BLK",  "貝萊德",     "BlackRock",              "金融",     []),
    ("BX",   "黑石",       "Blackstone",             "金融",     []),
    ("WMT",  "沃爾瑪",     "Walmart",                "通路",     []),
    ("COST", "好市多",     "Costco",                 "通路",     ["Costco Wholesale"]),
    ("HD",   "家得寶",     "Home Depot",             "通路",     []),
    ("LOW",  "勞氏",       "Lowe's",                 "通路",     []),
    ("TGT",  "塔吉特",     "Target",                 "通路",     []),
    ("NKE",  "耐吉",       "Nike",                   "服飾",     ["Nike", "耐克"]),
    ("LULU", "Lululemon",  "Lululemon Athletica",    "服飾",     []),
    ("SBUX", "星巴克",     "Starbucks",              "餐飲",     []),
    ("MCD",  "麥當勞",     "McDonald's",             "餐飲",     []),
    ("KO",   "可口可樂",   "Coca-Cola",              "食品",     []),
    ("PEP",  "百事",       "PepsiCo",                "食品",     ["Pepsi"]),
    ("PG",   "寶僑",       "Procter & Gamble",       "消費品",   ["P&G"]),
    ("UNH",  "聯合健康",   "UnitedHealth Group",     "醫療",     ["UnitedHealth"]),
    ("JNJ",  "嬌生",       "Johnson & Johnson",      "醫療",     ["J&J"]),
    ("LLY",  "禮來",       "Eli Lilly",              "製藥",     ["Lilly"]),
    ("PFE",  "輝瑞",       "Pfizer",                 "製藥",     []),
    ("MRK",  "默克",       "Merck",                  "製藥",     []),
    ("ABBV", "艾伯維",     "AbbVie",                 "製藥",     []),
    ("NVO",  "諾和諾德",   "Novo Nordisk",           "製藥",     ["減肥藥"]),
    ("TMO",  "賽默飛",     "Thermo Fisher Scientific","醫療",    []),
    ("ABT",  "亞培",       "Abbott Laboratories",    "醫療",     []),
    ("XOM",  "埃克森美孚", "Exxon Mobil",            "能源",     ["ExxonMobil"]),
    ("CVX",  "雪佛龍",     "Chevron",                "能源",     []),
    ("BA",   "波音",       "Boeing",                 "航太",     []),
    ("CAT",  "開拓重工",   "Caterpillar",            "機械",     []),
    ("GE",   "奇異",       "GE Aerospace",           "工業",     ["GE", "通用電氣"]),
    ("HON",  "霍尼威爾",   "Honeywell",              "工業",     []),
    ("DE",   "迪爾",       "Deere",                  "機械",     ["John Deere"]),
    ("F",    "福特",       "Ford Motor",             "汽車",     ["Ford"]),
    ("GM",   "通用汽車",   "General Motors",         "汽車",     ["GM"]),
    ("RIVN", "Rivian",     "Rivian Automotive",      "汽車",     ["電動車"]),
    ("LCID", "Lucid",      "Lucid Group",            "汽車",     ["電動車"]),
    ("T",    "AT&T",       "AT&T",                  "電信",      []),
    ("VZ",   "威訊",       "Verizon",                "電信",     []),
    ("TMUS", "T-Mobile",   "T-Mobile US",            "電信",     []),
    ("CSCO", "思科",       "Cisco Systems",          "網通",     ["Cisco"]),
    ("IBM",  "IBM",        "IBM",                    "科技",     ["國際商業機器"]),
    ("HPQ",  "惠普",       "HP Inc",                 "科技",     ["HP"]),
    ("DELL", "戴爾",       "Dell Technologies",      "科技",     ["Dell"]),
    ("HPE",  "慧與",       "Hewlett Packard Enterprise","科技",  ["HPE"]),
    ("SMCI", "美超微",     "Super Micro Computer",   "電子組裝", ["Supermicro", "AI伺服器"]),
    ("ANET", "Arista",     "Arista Networks",        "網通",     []),
    ("PANW", "Palo Alto",  "Palo Alto Networks",     "資安",     []),
    ("CRWD", "CrowdStrike","CrowdStrike",            "資安",     []),
    ("ZS",   "Zscaler",    "Zscaler",                "資安",     []),
    ("NET",  "Cloudflare", "Cloudflare",             "軟體",     []),
    ("DDOG", "Datadog",    "Datadog",                "軟體",     []),
    ("MDB",  "MongoDB",    "MongoDB",                "軟體",     []),
    ("ROKU", "Roku",       "Roku",                   "媒體",     []),
    ("SPOT", "Spotify",    "Spotify",                "媒體",     []),
    ("PINS", "Pinterest",  "Pinterest",              "網路",     []),
    ("SNAP", "Snap",       "Snap",                   "網路",     ["Snapchat"]),
    ("X",    "X",          "X (Twitter)",            "網路",     ["Twitter"]),
    ("BABA", "阿里巴巴",   "Alibaba",                "電商",     ["Alibaba Group"]),
    ("JD",   "京東",       "JD.com",                 "電商",     []),
    ("PDD",  "拼多多",     "PDD Holdings",           "電商",     ["Temu"]),
    ("BIDU", "百度",       "Baidu",                  "網路",     []),
    ("NIO",  "蔚來",       "NIO",                    "汽車",     ["蔚來汽車"]),
    ("XPEV", "小鵬",       "XPeng",                  "汽車",     ["小鵬汽車"]),
    ("LI",   "理想",       "Li Auto",                "汽車",     ["理想汽車"]),
    ("TSM",  "台積電ADR",  "TSMC ADR",               "半導體",   ["台積電", "TSMC", "TSM"]),
    ("UMC",  "聯電ADR",    "UMC ADR",                "半導體",   ["聯電"]),
    ("ASX",  "日月光ADR",  "ASE ADR",                "半導體封測",["日月光"]),
    ("HIMX", "奇景光電",   "Himax Technologies",     "半導體",   []),
    ("OXY",  "西方石油",   "Occidental Petroleum",   "能源",     []),
    ("SLB",  "斯倫貝謝",   "SLB",                    "能源",     ["Schlumberger"]),
    ("FCX",  "自由港",     "Freeport-McMoRan",       "礦業",     []),
    ("NEM",  "紐蒙特",     "Newmont",                "礦業",     []),
    ("GLD",  "黃金ETF",    "SPDR Gold Shares",       "ETF",     []),
    ("SPY",  "標普500 ETF","SPDR S&P 500 ETF",       "ETF",     ["S&P 500"]),
    ("QQQ",  "納指ETF",    "Invesco QQQ Trust",      "ETF",     ["Nasdaq 100"]),
    ("DIA",  "道指ETF",    "SPDR Dow Jones ETF",     "ETF",     []),
    ("VTI",  "全市場ETF",  "Vanguard Total Stock",   "ETF",     []),
    ("ARKK", "ARK創新ETF", "ARK Innovation ETF",     "ETF",     ["木頭姐"]),
    ("SMH",  "半導體ETF",  "VanEck Semiconductor ETF","ETF",    []),
    ("SOXX", "iShares半導體","iShares Semiconductor","ETF",     []),
    ("TQQQ", "3倍那指ETF", "ProShares UltraPro QQQ", "ETF",     []),
    ("ENPH", "Enphase",    "Enphase Energy",         "綠能",     []),
    ("FSLR", "First Solar","First Solar",            "綠能",     []),
    ("PLUG", "Plug Power", "Plug Power",             "綠能",     ["氫能"]),
    ("RIOT", "Riot",       "Riot Platforms",         "加密貨幣", []),
    ("MARA", "Marathon",   "Marathon Digital",       "加密貨幣", []),
    ("MSTR", "MicroStrategy","MicroStrategy",        "軟體",     ["比特幣"]),
    ("GME",  "GameStop",   "GameStop",               "通路",     ["迷因股"]),
    ("AMC",  "AMC",        "AMC Entertainment",      "媒體",     ["迷因股"]),
    ("BB",   "黑莓",       "BlackBerry",             "軟體",     []),
    ("U",    "Unity",      "Unity Software",         "軟體",     []),
    ("ZM",   "Zoom",       "Zoom Video",             "軟體",     []),
    ("DOCU", "DocuSign",   "DocuSign",               "軟體",     []),
    ("OKTA", "Okta",       "Okta",                   "資安",     []),
    ("FTNT", "Fortinet",   "Fortinet",               "資安",     []),
    ("ON",   "安森美",     "ON Semiconductor",       "半導體",   []),
    ("MCHP", "微芯",       "Microchip Technology",   "半導體",   []),
    ("ADI",  "亞德諾",     "Analog Devices",         "半導體",   []),
    ("SWKS", "Skyworks",   "Skyworks Solutions",     "半導體",   []),
    ("MPWR", "Monolithic", "Monolithic Power",       "半導體",   []),
    ("WDC",  "威騰",       "Western Digital",        "半導體",   []),
    ("STX",  "希捷",       "Seagate Technology",     "半導體",   []),
]


# ---------------------------------------------------------------------------
# JP STOCKS  (Nikkei 225 representative names)
# ---------------------------------------------------------------------------

JP_RAW: List[tuple] = [
    # ticker, zh, en, sector, extras
    ("7203.T", "豐田汽車",   "Toyota Motor",         "汽車",   ["豐田", "Toyota", "TM-US"]),
    ("6758.T", "索尼",       "Sony Group",           "電子",   ["Sony", "SONY-US"]),
    ("9984.T", "軟銀集團",   "SoftBank Group",       "投資",   ["SoftBank", "孫正義", "Masayoshi Son"]),
    ("6861.T", "基恩斯",     "Keyence",              "電子設備",["Keyence"]),
    ("8035.T", "東京威力科創","Tokyo Electron",      "半導體設備",["TEL", "Tokyo Electron"]),
    ("8306.T", "三菱日聯",   "Mitsubishi UFJ",       "金融",   ["MUFG"]),
    ("9432.T", "NTT",        "Nippon Telegraph",     "電信",   ["日本電信電話"]),
    ("9433.T", "KDDI",       "KDDI",                 "電信",   []),
    ("9434.T", "軟銀",       "SoftBank Corp",        "電信",   ["SoftBank Corp"]),
    ("7974.T", "任天堂",     "Nintendo",             "遊戲",   ["Nintendo"]),
    ("6098.T", "Recruit",    "Recruit Holdings",     "服務",   ["瑞可利"]),
    ("8316.T", "三井住友",   "Sumitomo Mitsui",      "金融",   ["SMFG"]),
    ("8411.T", "瑞穗",       "Mizuho Financial",     "金融",   ["Mizuho"]),
    ("4063.T", "信越化學",   "Shin-Etsu Chemical",   "化工",   ["Shin-Etsu", "矽晶圓"]),
    ("6594.T", "日本電產",   "Nidec",                "電機",   ["Nidec"]),
    ("6501.T", "日立",       "Hitachi",              "電機",   ["Hitachi"]),
    ("6502.T", "東芝",       "Toshiba",              "電機",   ["Toshiba"]),
    ("6503.T", "三菱電機",   "Mitsubishi Electric",  "電機",   []),
    ("6752.T", "松下",       "Panasonic Holdings",   "電子",   ["Panasonic", "國際牌"]),
    ("6701.T", "NEC",        "NEC",                  "電子",   ["日本電氣"]),
    ("6702.T", "富士通",     "Fujitsu",              "電子",   ["Fujitsu"]),
    ("7267.T", "本田",       "Honda Motor",          "汽車",   ["Honda", "本田技研", "HMC-US"]),
    ("7201.T", "日產",       "Nissan Motor",         "汽車",   ["Nissan", "NSANY-US"]),
    ("7269.T", "鈴木",       "Suzuki Motor",         "汽車",   ["Suzuki"]),
    ("7270.T", "速霸陸",     "Subaru",               "汽車",   ["Subaru"]),
    ("7261.T", "馬自達",     "Mazda Motor",          "汽車",   ["Mazda"]),
    ("4502.T", "武田",       "Takeda Pharmaceutical","製藥",   ["Takeda", "TAK-US"]),
    ("4503.T", "安斯泰來",   "Astellas Pharma",      "製藥",   ["Astellas"]),
    ("4519.T", "中外製藥",   "Chugai Pharmaceutical","製藥",   ["Chugai"]),
    ("8001.T", "伊藤忠商事", "Itochu",               "綜合商社",["Itochu"]),
    ("8031.T", "三井物產",   "Mitsui & Co.",         "綜合商社",["Mitsui"]),
    ("8053.T", "住友商事",   "Sumitomo Corp",        "綜合商社",[]),
    ("8058.T", "三菱商事",   "Mitsubishi Corp",      "綜合商社",["Mitsubishi"]),
    ("8002.T", "丸紅",       "Marubeni",             "綜合商社",["Marubeni"]),
    ("9983.T", "迅銷",       "Fast Retailing",       "服飾",   ["Uniqlo", "優衣庫"]),
    ("4901.T", "富士軟片",   "Fujifilm Holdings",    "化工",   ["Fujifilm"]),
    ("7751.T", "佳能",       "Canon",                "光學",   ["Canon"]),
    ("4543.T", "泰爾茂",     "Terumo",               "醫療",   ["Terumo"]),
    ("6981.T", "村田製作所", "Murata Manufacturing", "電子零組件",["Murata", "MLCC"]),
    ("6954.T", "發那科",     "Fanuc",                "機械",   ["Fanuc"]),
    ("6367.T", "大金工業",   "Daikin Industries",    "機械",   ["Daikin", "大金"]),
    ("8766.T", "東京海上",   "Tokio Marine",         "金融",   ["Tokio Marine"]),
    ("9020.T", "JR東日本",   "East Japan Railway",   "運輸",   ["JR East"]),
    ("9022.T", "JR東海",     "Central Japan Railway","運輸",   ["JR Central"]),
    ("3382.T", "7&i控股",    "Seven & i Holdings",   "通路",   ["7-Eleven Japan"]),
    ("4661.T", "東方樂園",   "Oriental Land",        "娛樂",   ["東京迪士尼"]),
    ("4324.T", "電通",       "Dentsu Group",         "廣告",   ["Dentsu"]),
    ("2914.T", "JT",         "Japan Tobacco",        "菸草",   ["日本菸草"]),
    ("4523.T", "衛采",       "Eisai",                "製藥",   ["Eisai"]),
    ("6273.T", "SMC",        "SMC Corporation",      "機械",   []),
    ("7741.T", "豪雅",       "Hoya",                 "光學",   ["Hoya"]),
    ("6920.T", "雷射科技",   "Lasertec",             "半導體設備",["Lasertec"]),
    ("6857.T", "愛德萬",     "Advantest",            "半導體設備",["Advantest"]),
    ("6146.T", "迪思科",     "Disco Corporation",    "半導體設備",["Disco"]),
    ("4568.T", "第一三共",   "Daiichi Sankyo",       "製藥",   ["Daiichi Sankyo"]),
    ("9101.T", "日本郵船",   "Nippon Yusen",         "航運",   ["NYK"]),
    ("9104.T", "商船三井",   "Mitsui O.S.K. Lines",  "航運",   ["MOL"]),
    ("9107.T", "川崎汽船",   "Kawasaki Kisen",       "航運",   ["K Line"]),
]


def _build(rows: List[tuple], market: str) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for row in rows:
        ticker, name_zh, name_en, sector, extras = row
        if ticker in out:
            # merge extra aliases for duplicate rows
            out[ticker]["aliases"] = list(dict.fromkeys(out[ticker]["aliases"] + extras))
            continue
        k, v = _entry(ticker, name_zh, name_en, market, sector, extras)
        out[k] = v
    return out


# ---------------------------------------------------------------------------
# Full TW universe via TWSE / TPEx OpenAPI（補足非權值股的盤中比對覆蓋率）
# ---------------------------------------------------------------------------

TW_UNIVERSE_APIS = [
    # (OpenAPI 端點, ticker 後綴)
    ("https://openapi.twse.com.tw/v1/opendata/t187ap03_L", ".TW"),    # 上市公司基本資料
    ("https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O", ".TWO"),  # 上櫃公司基本資料
]

_UNIVERSE_HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def _row_field(row: dict, *keywords: str) -> str:
    """OpenAPI 中文欄位名偶有空白/版本差異，用關鍵字模糊取值。"""
    for k, v in row.items():
        if all(kw in k for kw in keywords):
            return str(v).strip()
    return ""


def _clean_aliases(aliases: List[str]) -> List[str]:
    """套用黑名單與長度限制（單字元一律剔除），保序去重。"""
    seen, out = set(), []
    for a in aliases:
        a = a.strip()
        if len(a) < 2 or a.upper() in ALIAS_BLACKLIST or a in seen:
            continue
        seen.add(a)
        out.append(a)
    return out


def fetch_tw_universe() -> Dict[str, dict]:
    """抓上市+上櫃全市場公司清單（約 1,800 檔），alias 為簡稱與代號變體。

    sector 留空（OpenAPI 產業別為代碼），人工策展清單的 sector / 綽號
    會在 merge 階段疊加覆蓋。
    """
    out: Dict[str, dict] = {}
    for url, suffix in TW_UNIVERSE_APIS:
        rows = request_get(url, headers=_UNIVERSE_HEADERS, timeout=30).json()
        for row in rows:
            # TWSE 欄位是中文,TPEx 是英文(SecuritiesCompanyCode / CompanyAbbreviation / CompanyName);
            # 簡稱的「*」標記(如 國巨*)新聞不會寫,去掉才比得到
            code = _row_field(row, "公司代號") or str(row.get("SecuritiesCompanyCode", "")).strip()
            name = (_row_field(row, "公司簡稱")
                    or str(row.get("CompanyAbbreviation", "")).strip()).replace("*", "")
            full = _row_field(row, "公司名稱") or str(row.get("CompanyName", "")).strip()
            if not code.isdigit() or not name:
                continue
            ticker = f"{code}{suffix}"
            out[ticker] = {
                "ticker": ticker,
                "name_zh": name,
                "name_en": _row_field(row, "英文簡稱"),
                "market": "TW",
                "sector": "",
                "aliases": _clean_aliases([name, full, code, ticker]),
            }
    return out


def _merge_curated(universe: Dict[str, dict], curated: Dict[str, dict]) -> Dict[str, dict]:
    """全市場為底，人工策展疊加：sector / name_en / 綽號 alias 以策展為準。"""
    merged = dict(universe)
    for ticker, cur in curated.items():
        if ticker in merged:
            base = merged[ticker]
            base["sector"] = cur["sector"] or base["sector"]
            base["name_en"] = cur["name_en"] or base["name_en"]
            base["aliases"] = _clean_aliases(base["aliases"] + cur["aliases"])
        else:
            merged[ticker] = cur
    return merged


def write_tw_names() -> None:
    """只寫全市場「代號 → 簡稱」到 data/stocks/tw_names.json,給沒有 Metabase 的代號查詢補股名;
    不動 tw_stocks.json(盤中監看的別名比對維持策展清單)。"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    names = {t.split(".")[0]: v["name_zh"] for t, v in fetch_tw_universe().items()}
    (OUT_DIR / "tw_names.json").write_text(
        json.dumps(names, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(f"[OK] tw_names.json: {len(names)} entries")


def main(full_tw: bool = False) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    tw = _build(TW_RAW, "TW")
    if full_tw:
        print("[tw] 抓取 TWSE/TPEx 全市場清單...")
        tw = _merge_curated(fetch_tw_universe(), tw)

    datasets = {
        "tw_stocks.json": tw,
        "us_stocks.json": _build(US_RAW, "US"),
        "jp_stocks.json": _build(JP_RAW, "JP"),
    }

    for filename, data in datasets.items():
        path = OUT_DIR / filename
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        avg_aliases = (
            sum(len(v["aliases"]) for v in data.values()) / len(data)
            if data else 0.0
        )
        print(f"[OK] {filename}: {len(data)} entries, avg {avg_aliases:.1f} aliases")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="重生 TW/US/JP 個股字典")
    ap.add_argument("--full-tw", action="store_true",
                    help="台股改用 TWSE/TPEx OpenAPI 全市場清單（需網路），"
                         "人工策展的 sector/綽號疊加其上")
    ap.add_argument("--names", action="store_true",
                    help="只更新全市場代號對簡稱 data/stocks/tw_names.json（需網路），不動 tw_stocks.json")
    a = ap.parse_args()
    if a.names:
        write_tw_names()
    else:
        main(a.full_tw)
