import asyncio
import json
import os
import re
import statistics
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
import requests
from playwright.async_api import async_playwright

JST = timezone(timedelta(hours=9))

TARGETS = [
    {
        "id": "30th_celebration",
        "name": "MEGA 拡張パック「30th CELEBRATION」",
        "skip_mercari": True,
        "strict_box_type": True,
        "kw_general": ["30th CELEBRATION BOX", "30周年 拡張パック BOX"],
        "kw_without": ["30th CELEBRATION シュリンクなし", "30周年 拡張パック シュリンクなし"],
        "must_words": ["30TH", "30周年", "CELEBRATION"],
        "extra_ng_words": [
            "フューチャリスティック", "FUTURISTIC", "カードセット", "9種", "９種", "御三家", "ファイル", "デッキ", "エネルギー",
            "エーフィ", "ブラッキー", "プレミアム", "コレクションファイル",
            "25TH", "25周年", "20TH", "20周年", "ゴールデン", "GOLDEN", "アニバーサリー", "アビスアイ", "ストームエメラルダ"
        ],
        "snkrdunk_with_url": "https://snkrdunk.com/apparels/881421",
        "snkrdunk_without_url": "https://snkrdunk.com/apparels/881427",
        "homura_with_url": "https://kaitori-homura.com/products/7237",
        "homura_without_url": "https://kaitori-homura.com/products/7238",
        "min_valid_price": 12000,
        "max_valid_price": 35000  # 高騰時にも対応できるよう上限を広く確保
    },
    {
        "id": "storm_emeralda",
        "name": "MEGA 拡張パック「ストームエメラルダ」",
        "strict_box_type": True,
        "kw_general": "ストームエメラルダ BOX",
        "kw_without": "ストームエメラルダ BOX シュリンクなし",
        "must_words": ["ストームエメラルダ", "エメラルダ"],
        "extra_ng_words": ["レックウザ", "ライコウ", "カイオーガ", "グラードン", "ヒガナ", "30TH", "アビスアイ", "ムニキスゼロ", "メガドリーム"],
        "snkrdunk_with_url": "https://snkrdunk.com/apparels/846048",
        "snkrdunk_without_url": "https://snkrdunk.com/apparels/846050",
        "homura_with_url": "https://kaitori-homura.com/products/6933",
        "homura_without_url": "https://kaitori-homura.com/products/6934",
        "min_valid_price": 5000,
        "max_valid_price": 22000
    },
    {
        "id": "abyss_eye",
        "name": "MEGA 拡張パック「アビスアイ」",
        "strict_box_type": True,
        "kw_general": "アビスアイ BOX",
        "kw_without": "アビスアイ BOX シュリンクなし",
        "must_words": ["アビスアイ"],
        "extra_ng_words": ["ダークライ", "ゼラオラ", "シャンデラ", "カスミ", "グラジオ", "ムク", "30TH", "ストームエメラルダ", "ムニキスゼロ", "メガドリーム"],
        "snkrdunk_with_url": "https://snkrdunk.com/apparels/806644",
        "snkrdunk_without_url": "https://snkrdunk.com/apparels/806646",
        "homura_with_url": "https://kaitori-homura.com/products/6733",
        "homura_without_url": "https://kaitori-homura.com/products/6734",
        "min_valid_price": 4500,
        "max_valid_price": 20000
    },
    {
        "id": "munikis_zero",
        "name": "MEGA 拡張パック「ムニキスゼロ」",
        "strict_box_type": True,
        "kw_general": "ムニキスゼロ BOX",
        "kw_without": "ムニキスゼロ BOX シュリンクなし",
        "must_words": ["ムニキスゼロ"],
        "extra_ng_words": ["30TH", "ストームエメラルダ", "アビスアイ", "メガドリーム", "インフェルノ"],
        "snkrdunk_with_url": "https://snkrdunk.com/apparels/743533",
        "snkrdunk_without_url": "https://snkrdunk.com/apparels/743535",
        "homura_with_url": "https://kaitori-homura.com/products/5443",
        "homura_without_url": "https://kaitori-homura.com/products/5444",
        "min_valid_price": 4500,
        "max_valid_price": 20000
    },
    {
        "id": "mega_dream_ex",
        "name": "MEGA ハイクラスパック「MEGAドリームex」",
        "strict_box_type": True,
        "kw_general": "MEGAドリームex BOX",
        "kw_without": "MEGAドリームex BOX シュリンクなし",
        "must_words": ["MEGAドリーム", "メガドリーム", "ドリームEX"],
        "extra_ng_words": ["デッキ", "ファイル", "アビスアイ", "ストームエメラルダ", "ムニキスゼロ", "テラスタル", "バトルパートナーズ", "151", "30TH"],
        "snkrdunk_with_url": "https://snkrdunk.com/apparels/721913",
        "snkrdunk_without_url": "https://snkrdunk.com/apparels/721915",
        "homura_with_url": "https://kaitori-homura.com/products/3465",
        "homura_without_url": "https://kaitori-homura.com/products/3383",
        "min_valid_price": 6000,
        "max_valid_price": 25000
    },
    {
        "id": "sp_box_tohoku",
        "name": "スペシャルBOX ポケモンセンタートウホク",
        "kw_general": "スペシャルBOX トウホク",
        "kw_without": "",
        "must_words": ["トウホク", "東北"],
        "extra_ng_words": [
            "ヒロシマ", "フクオカ", "広島", "福岡", "プロモなし", "プロモ抜き", "サプライのみ",
            "デッキシールド", "スリーブ", "デッキケース", "ダメカン", "ストレージ", "ファイル"
        ],
        "snkrdunk_with_url": "https://snkrdunk.com/apparels/618442",
        "snkrdunk_without_url": "",
        "homura_with_url": "https://kaitori-homura.com/products/3326",
        "homura_without_url": "",
        "min_valid_price": 8500,
        "max_valid_price": 25000
    },
    {
        "id": "sp_box_hiroshima",
        "name": "スペシャルBOX ポケモンセンターヒロシマ",
        "kw_general": "スペシャルBOX ヒロシマ",
        "kw_without": "",
        "must_words": ["ヒロシマ", "広島"],
        "extra_ng_words": [
            "トウホク", "フクオカ", "東北", "福岡", "プロモなし", "プロモ抜き", "サプライのみ",
            "デッキシールド", "スリーブ", "デッキケース", "ダメカン", "ストレージ", "ファイル"
        ],
        "snkrdunk_with_url": "https://snkrdunk.com/apparels/618443",
        "snkrdunk_without_url": "",
        "homura_with_url": "https://kaitori-homura.com/products/3324",
        "homura_without_url": "",
        "min_valid_price": 8500,
        "max_valid_price": 25000
    },
    {
        "id": "sp_box_fukuoka",
        "name": "スペシャルBOX ポケモンセンターフクオカ",
        "kw_general": "スペシャルBOX フクオカ",
        "kw_without": "",
        "must_words": ["フクオカ", "福岡"],
        "extra_ng_words": [
            "トウホク", "ヒロシマ", "東北", "広島", "プロモなし", "プロモ抜き", "サプライのみ",
            "デッキシールド", "スリーブ", "デッキケース", "ダメカン", "ストレージ", "ファイル"
        ],
        "snkrdunk_with_url": "https://snkrdunk.com/apparels/618444",
        "snkrdunk_without_url": "",
        "homura_with_url": "https://kaitori-homura.com/products/3325",
        "homura_without_url": "",
        "min_valid_price": 8500,
        "max_valid_price": 25000
    },
    {
        "id": "30th_card_set_9",
        "name": "30th CELEBRATION カードセット 9種セット",
        "skip_mercari": True,
        "allow_set_word": True,
        "ignore_shrink_and_box_count": True,
        "kw_general": ["30th カードセット 9種 未開封", "30th 9種 輸送箱未開封"],
        "kw_without": "",
        "must_words": ["9種", "９種", "コンプ", "全種"],
        "require_unopened": True,
        "extra_ng_words": [
            "フューチャリスティック", "FUTURISTIC", "デッキ", "エーフィ", "ブラッキー",
            "1種", "2種", "3種", "単品", "バラ", "拡張パック"
        ],
        "snkrdunk_with_url": "",
        "snkrdunk_without_url": "",
        "homura_with_url": "https://kaitori-homura.com/products/7780",
        "homura_without_url": "",
        "min_valid_price": 11000,
        "max_valid_price": 30000
    }
]

COMMON_NG_WORDS = [
    "空箱", "空き箱", "箱のみ", "パックのみ", "バラ", "1P", "5P", "10P", "1パック", "10パック", "15パック", "30パック",
    "パック分", "1BOX分", "封入率", "カートン", "まとめ", "オリパ", "確定", "サーチ", "開封済", "おまけ",
    "SAR", "SR", "AR", "UR", "MA", "MUR", "FUR", "プロモ", "PSA", "シングル",
    "ピカチュウ", "ゲンガー", "リザードン", "ミュウ", "ルギア", "カイリュー", "アクリル", "ケースのみ"
]

NO_SHRINK_WORDS = ["シュリンクなし", "シュリンク無し", "シュリなし", "シュリ無し", "ペリペリ", "シュリンク無", "シュリ無"]
FALSE_NO_SHRINK_WORDS = ["シュリンクなしでは", "シュリンク無しでは", "シュリンク付き", "シュリンクあり", "シュリンク有"]

RETAIL_PRICES = (2090, 5400, 5500, 6000, 7200, 10800)

DATA_FILE = "data.json"
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")
ALERT_THRESHOLD = 1000


def get_usd_jpy_rate():
    try:
        res = requests.get("https://open.er-api.com/v6/latest/USD", timeout=10).json()
        return float(res["rates"]["JPY"])
    except Exception:
        return 157.0


def safe_median(prices):
    """件数が少ない時（9件以下）はそのまま中央値をとり、10件以上ある時だけ最大・最小の1件ずつを除外する"""
    if not prices:
        return None
    s = sorted(prices[:15])
    if len(s) >= 10:
        s = s[1:-1]
    return int(statistics.median(s))


def classify_item_text(title, target):
    t_upper = title.upper()
    if not any(w.upper() in t_upper for w in target["must_words"]):
        return None
    if target.get("require_unopened") and not any(w in t_upper for w in ["未開封", "未使用", "新品"]):
        return None
    for ng in COMMON_NG_WORDS + target["extra_ng_words"]:
        if ng.upper() in t_upper:
            return None
    if re.search(r'(?<!\d)[2-9２-９]\s*(BOX|ボックス|箱|個|点|セット)', t_upper):
        return None
    if re.search(r'[×✕xX]\s*[2-9２-９]', t_upper):
        return None
    if not target.get("allow_set_word"):
        if "セット" in t_upper and not any(ok in t_upper for ok in ["ローダー", "ケース"]):
            return None

    if any(w in title for w in NO_SHRINK_WORDS):
        if any(fw in title for fw in FALSE_NO_SHRINK_WORDS):
            return "with_shrink"
        return "without_shrink"
    return "with_shrink"


def filter_without_shrink_outliers(without_prices, with_median):
    """シュリンク無のリストに紛れ込んだ「シュリンク有と同額以上のデータ（表記トリックや2箱セット）」を除外"""
    if not without_prices:
        return []
    if with_median:
        max_allowed = min(int(with_median * 0.96), with_median - 200)
        return [p for p in without_prices if p <= max_allowed]
    return without_prices


def extract_mercari_price_jpy(raw_text, usd_rate, target):
    jpy_matches = re.findall(r'(?:[¥￥]|JPY_RAW:)\s*([\d,]{4,7})|([\d,]{4,7})\s*円', raw_text)
    for m in jpy_matches:
        val = int((m[0] or m[1]).replace(',', ''))
        if target["min_valid_price"] <= val <= target["max_valid_price"]:
            return val

    usd_matches = re.findall(r'US\$\s*([\d,]+\.\d+|[\d,]+)', raw_text)
    for m in usd_matches:
        usd_val = float(m.replace(',', ''))
        jpy_val = int(round((usd_val * usd_rate) / 100.0) * 100)
        if target["min_valid_price"] <= jpy_val <= target["max_valid_price"]:
            return jpy_val

    return None


async def fetch_mercari_items_from_url(page, keyword):
    kw = quote(keyword)
    url = f"https://jp.mercari.com/search?keyword={kw}&status=sold_out&sort=created_time&order=desc"
    await page.goto(url, wait_until="domcontentloaded", timeout=40000)
    await page.wait_for_timeout(4000)

    for _ in range(4):
        await page.evaluate("window.scrollBy(0, 1400)")
        await page.wait_for_timeout(1200)

    items_data = await page.evaluate("""() => {
        const results = [];
        const links = document.querySelectorAll('a[href*="/item/m"]');
        links.forEach(a => {
            let text = [a.getAttribute('aria-label') || '', a.innerText || ''].join(' ');
            const imgs = a.querySelectorAll('img');
            imgs.forEach(img => { text += ' ' + (img.getAttribute('alt') || ''); });
            const thumb = a.querySelector('mer-item-thumbnail');
            if (thumb) {
                const p = thumb.getAttribute('price');
                if (p) text += ' JPY_RAW:' + p;
                text += ' ' + (thumb.getAttribute('item-name') || '');
                if (thumb.shadowRoot) {
                    text += ' ' + (thumb.shadowRoot.innerHTML || '');
                }
            }
            text = text.replace(/のサムネイル/g, '').replace(/\\s+/g, ' ').trim();
            results.push(text);
        });
        return results;
    }""")
    return items_data


async def scrape_mercari_box(page, target, usd_rate):
    if not target["kw_general"] or target.get("skip_mercari"):
        return None, 0, None, 0

    with_prices, without_prices = [], []
    seen_texts = set()

    gen_kws = target["kw_general"] if isinstance(target["kw_general"], list) else [target["kw_general"]]
    wo_kws = target["kw_without"] if isinstance(target["kw_without"], list) else ([target["kw_without"]] if target["kw_without"] else [])

    try:
        for kw in gen_kws:
            items = await fetch_mercari_items_from_url(page, kw)
            for raw_text in items:
                if raw_text in seen_texts:
                    continue
                seen_texts.add(raw_text)
                price = extract_mercari_price_jpy(raw_text, usd_rate, target)
                if not price:
                    continue
                status = classify_item_text(raw_text, target)
                if status == "with_shrink":
                    with_prices.append(price)
                elif status == "without_shrink" and wo_kws:
                    without_prices.append(price)

        if wo_kws and len(without_prices) < 5:
            for kw in wo_kws:
                wo_items = await fetch_mercari_items_from_url(page, kw)
                for raw_text in wo_items:
                    if raw_text in seen_texts:
                        continue
                    seen_texts.add(raw_text)
                    price = extract_mercari_price_jpy(raw_text, usd_rate, target)
                    if not price:
                        continue
                    if classify_item_text(raw_text, target) == "without_shrink":
                        without_prices.append(price)

        med_w = safe_median(with_prices)
        clean_wo = filter_without_shrink_outliers(without_prices, med_w)
        med_wo = safe_median(clean_wo)
        return med_w, len(with_prices), med_wo, len(clean_wo)
    except Exception as e:
        print(f"  [Mercari Error] {e}")
        return None, 0, None, 0


async def fetch_yahoo_items_from_url(page, keyword):
    kw = quote(keyword)
    url = f"https://paypayfleamarket.yahoo.co.jp/search/{kw}?open=1"
    await page.goto(url, wait_until="domcontentloaded", timeout=40000)
    await page.wait_for_timeout(3500)

    for _ in range(3):
        await page.evaluate("window.scrollBy(0, 1400)")
        await page.wait_for_timeout(1000)

    items_data = await page.evaluate("""() => {
        const results = [];
        const links = document.querySelectorAll('a[href*="/item/"]');
        links.forEach(a => {
            const href = a.href || a.getAttribute('href') || '';
            let text = [a.getAttribute('aria-label') || '', a.innerText || ''].join(' ');
            const imgs = a.querySelectorAll('img');
            imgs.forEach(img => { text += ' ' + (img.getAttribute('alt') || ''); });
            text = text.replace(/\\s+/g, ' ').trim();
            if (text && href) results.push({ text, href });
        });
        return results;
    }""")
    return items_data


def extract_yahoo_price_jpy(raw_text, target):
    matches = re.findall(r'([\d,]{4,7})\s*円|[¥￥]\s*([\d,]{4,7})', raw_text)
    for m in matches:
        val = int((m[0] or m[1]).replace(',', ''))
        if target["min_valid_price"] <= val <= target["max_valid_price"]:
            return val
    return None


async def inspect_yahoo_item_detail(page, item_url, initial_status, target):
    try:
        await page.goto(item_url, wait_until="domcontentloaded", timeout=25000)
        await page.wait_for_timeout(1200)
        body_text = await page.inner_text("body")

        if not target.get("ignore_shrink_and_box_count"):
            m_box = re.search(r'ボックス数\s*([0-9０-９]+)\s*個', body_text)
            if m_box:
                num_str = m_box.group(1).translate(str.maketrans('０１２３４５６７８９', '0123456789'))
                if int(num_str) >= 2:
                    return None, f"ボックス数:{num_str}個"

        m_type = re.search(r'種別\s*(シングルカード|パック|ボックス|まとめ売り|周辺グッズ)', body_text)
        if m_type:
            item_type = m_type.group(1)
            if target.get("strict_box_type") and item_type != "ボックス":
                return None, f"種別:{item_type}"
            elif not target.get("strict_box_type") and item_type in ("シングルカード", "パック"):
                return None, f"種別:{item_type}"

        desc_check = body_text[:1500]
        if any(bad in desc_check for bad in ["プロモなし", "プロモ抜き", "空箱", "空き箱", "パックのみ", "1BOX分", "封入率一致"]):
            return None, "説明文NGワード"

        if not target.get("ignore_shrink_and_box_count"):
            m_shrink = re.search(r'シュリンク\s*(あり|なし|有|無)', body_text)
            if m_shrink:
                sh_val = m_shrink.group(1)
                if sh_val in ("なし", "無"):
                    return "without_shrink", "詳細:シュリンクなし"
                elif sh_val in ("あり", "有") and initial_status != "without_shrink":
                    return "with_shrink", "詳細:シュリンクあり"

        return initial_status, "OK"
    except Exception:
        return initial_status, "TimeoutFallback"


async def scrape_yahoo_box(page, target):
    if not target["kw_general"]:
        return None, 0, None, 0

    candidates = []
    seen_urls = set()

    gen_kws = target["kw_general"] if isinstance(target["kw_general"], list) else [target["kw_general"]]
    wo_kws = target["kw_without"] if isinstance(target["kw_without"], list) else ([target["kw_without"]] if target["kw_without"] else [])

    try:
        for kw in gen_kws:
            items = await fetch_yahoo_items_from_url(page, kw)
            for item in items:
                href = item["href"].split("?")[0]
                if href in seen_urls:
                    continue
                seen_urls.add(href)
                price = extract_yahoo_price_jpy(item["text"], target)
                if not price:
                    continue
                status = classify_item_text(item["text"], target)
                if status:
                    candidates.append({"url": href, "price": price, "status": status})

        wo_cand_count = sum(1 for c in candidates if c["status"] == "without_shrink")
        if wo_kws and wo_cand_count < 6:
            for kw in wo_kws:
                wo_items = await fetch_yahoo_items_from_url(page, kw)
                for item in wo_items:
                    href = item["href"].split("?")[0]
                    if href in seen_urls:
                        continue
                    seen_urls.add(href)
                    price = extract_yahoo_price_jpy(item["text"], target)
                    if not price:
                        continue
                    status = classify_item_text(item["text"], target)
                    if status:
                        candidates.append({"url": href, "price": price, "status": status})

        with_cands = [c for c in candidates if c["status"] == "with_shrink"][:12]
        without_cands = [c for c in candidates if c["status"] == "without_shrink"][:10]
        inspect_list = with_cands + (without_cands if wo_kws else [])

        with_prices, without_prices = [], []
        rejected_reasons = []

        for cand in inspect_list:
            final_status, reason = await inspect_yahoo_item_detail(page, cand["url"], cand["status"], target)
            if final_status == "with_shrink":
                with_prices.append(cand["price"])
            elif final_status == "without_shrink" and wo_kws:
                without_prices.append(cand["price"])
            else:
                rejected_reasons.append(f"{cand['price']}円({reason})")

        if rejected_reasons:
            print(f"    [Yahoo Detail 除外] {', '.join(rejected_reasons[:6])}")

        med_w = safe_median(with_prices)
        clean_wo = filter_without_shrink_outliers(without_prices, med_w)
        med_wo = safe_median(clean_wo)
        return med_w, len(with_prices), med_wo, len(clean_wo)
    except Exception as e:
        print(f"  [Yahoo Error] {e}")
        return None, 0, None, 0


async def scrape_snkrdunk_single(page, url, target, max_cap=None):
    """スニダンの画面構造（1個タイル、または売買履歴の1個）をピンポイントで狙い撃ちする"""
    if not url:
        return None
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=40000)
        await page.wait_for_timeout(3500)
        content = await page.inner_text("body")
        upper_bound = min(target["max_valid_price"], max_cap) if max_cap else target["max_valid_price"]

        # 1. 最優先：個数選択タイルの「1個(99+) ¥9,150〜」をピンポイント抽出（11個などに反応しないよう (?<!\d) を付与）
        m_tile = re.search(r'(?<!\d)1個\s*(?:\([0-9+]+\))?\s*[¥￥]\s*([\d,]{4,6})\s*[~〜]', content)
        if m_tile:
            val = int(m_tile.group(1).replace(',', ''))
            if target["min_valid_price"] <= val <= upper_bound:
                return val

        # 2. 次点：「1個」が「出品待ち」だった場合、下部の売買履歴「〇分前 1個 新品S ¥9,150」の直近3件の中央値を採用
        hist_matches = re.findall(r'(?:分前|時間前|日前)\s+1個\s+\S+\s+[¥￥]\s*([\d,]{4,6})', content)
        hist_vals = [
            int(m.replace(',', '')) for m in hist_matches
            if target["min_valid_price"] <= int(m.replace(',', '')) <= upper_bound
        ]
        if hist_vals:
            return int(statistics.median(hist_vals[:3]))

        # 3. 最終フォールバック：「2個」という文字が登場する前のエリア（メイン最安値表示）からのみ抽出
        before_two_box = re.split(r'(?<!\d)2個\s*\(', content)[0]
        for m in re.findall(r'[¥￥]\s*([\d,]{4,6})\s*[~〜]', before_two_box):
            val = int(m.replace(',', ''))
            if val not in RETAIL_PRICES and target["min_valid_price"] <= val <= upper_bound:
                return val

        return None
    except Exception as e:
        print(f"  [SNKRDUNK Error] {url}: {e}")
        return None


async def scrape_homura_single(page, url, target):
    if not url:
        return None
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=40000)
        await page.wait_for_timeout(3000)

        primary_text = await page.evaluate("""() => {
            const el = document.querySelector('main, article, .product-detail, [class*="product"]');
            return el ? el.innerText : '';
        }""")
        
        if primary_text:
            m = re.search(r'買取(?:価格|金額)[^0-9]{0,20}([\d,]{4,6})', primary_text)
            if m:
                val = int(m.group(1).replace(',', ''))
                if target["min_valid_price"] <= val <= target["max_valid_price"]:
                    return val

            for m2 in re.findall(r'([\d,]{4,6})\s*円', primary_text[:800]):
                val = int(m2.replace(',', ''))
                if target["min_valid_price"] <= val <= target["max_valid_price"]:
                    return val

        content = await page.inner_text("body")
        m_fallback = re.search(r'買取(?:価格|金額)[^0-9]{0,20}([\d,]{4,6})', content)
        if m_fallback:
            val = int(m_fallback.group(1).replace(',', ''))
            if target["min_valid_price"] <= val <= target["max_valid_price"]:
                return val

        return None
    except Exception as e:
        print(f"  [Homura Error] {url}: {e}")
        return None


def apply_spike_guard(new_val, prev_val, label=""):
    """前回比で+50%超（2個セット誤爆等）または-35%超の異常ジャンプのみをブロック"""
    if new_val is None:
        return prev_val
    if prev_val is None:
        return new_val
    ratio = new_val / prev_val
    if ratio > 1.50 or ratio < 0.65:
        print(f"    [外れ値ガード発動] {label}: 前回{prev_val}円 → 今回{new_val}円 (変動が大きすぎるため前回値を維持)")
        return prev_val
    return new_val


def sanitize_past_history(history):
    """過去のdata.jsonに混入した外れ値（ストームエメラルダ無15949円や無＞有の逆転データ）を自動修復"""
    for record in history:
        boxes = record.get("boxes", {})
        b30 = boxes.get("30th_celebration")
        if b30:
            b30["mercari_with"] = None
            b30["mercari_without"] = None

        for bid, bdata in boxes.items():
            for prefix in ("mercari", "yahoo", "snkrdunk"):
                w_val = bdata.get(f"{prefix}_with")
                wo_val = bdata.get(f"{prefix}_without")
                if w_val and wo_val and wo_val >= w_val:
                    bdata[f"{prefix}_without"] = int(round((w_val * 0.82) / 100.0) * 100)


def check_and_notify(history, new_entry):
    if not DISCORD_WEBHOOK or len(history) < 1:
        return
    recent_records = history[-4:]
    alerts = []

    for box_id, box_data in new_entry["boxes"].items():
        box_name = box_data["name"]
        metrics = [
            ("メルカリ(有)", "mercari_with"),
            ("メルカリ(無)", "mercari_without"),
            ("Yahoo!フリマ(有)", "yahoo_with"),
            ("Yahoo!フリマ(無)", "yahoo_without"),
            ("スニダン(有)", "snkrdunk_with"),
            ("スニダン(無)", "snkrdunk_without"),
            ("買取ホムラ(有)", "homura_with"),
            ("買取ホムラ(無)", "homura_without"),
        ]
        for label, key in metrics:
            curr_val = box_data.get(key)
            if not curr_val:
                continue
            past_vals = [
                r["boxes"].get(box_id, {}).get(key)
                for r in recent_records
                if r["boxes"].get(box_id, {}).get(key) is not None
            ]
            if not past_vals:
                continue
            base_val = past_vals[0]
            diff = curr_val - base_val
            if abs(diff) >= ALERT_THRESHOLD:
                sign = "+" if diff > 0 else ""
                alerts.append(f"・**{box_name}** [{label}]\n  {base_val:,}円 → **{curr_val:,}円** ({sign}{diff:,}円)")

    if alerts:
        msg = "🚨 **【ポケカBOX 相場変動アラート（過去2日比 ±1,000円以上）】**\n\n" + "\n".join(alerts)
        try:
            requests.post(DISCORD_WEBHOOK, json={"content": msg}, timeout=10)
        except Exception as e:
            print(f"Discord notify error: {e}")


async def main():
    now_str = datetime.now(JST).strftime("%Y-%m-%d %H:%M")
    usd_rate = get_usd_jpy_rate()

    history = []
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            history = []

    sanitize_past_history(history)

    new_entry = {"timestamp": now_str, "boxes": {}}

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            locale="ja-JP",
            timezone_id="Asia/Tokyo"
        )
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page = await context.new_page()

        for target in TARGETS:
            print(f"=== Fetching {target['name']} ===")
            m_with, cnt_w, m_without, cnt_wo = await scrape_mercari_box(page, target, usd_rate)
            print(f"  [Mercari Result] 有: {m_with} ({cnt_w}件) / 無: {m_without} ({cnt_wo}件)")

            y_with, y_cnt_w, y_without, y_cnt_wo = await scrape_yahoo_box(page, target)
            print(f"  [Yahoo Result]   有: {y_with} ({y_cnt_w}件) / 無: {y_without} ({y_cnt_wo}件)")

            s_with = await scrape_snkrdunk_single(page, target["snkrdunk_with_url"], target)
            s_wo_cap = int(s_with * 0.96) if s_with else None
            s_without = await scrape_snkrdunk_single(page, target["snkrdunk_without_url"], target, max_cap=s_wo_cap)
            print(f"  [SNKRDUNK Result] 有: {s_with} / 無: {s_without}")

            h_with = await scrape_homura_single(page, target["homura_with_url"], target)
            h_without = await scrape_homura_single(page, target["homura_without_url"], target)
            print(f"  [Homura Result]  有: {h_with} / 無: {h_without}")

            prev_box = history[-1]["boxes"].get(target["id"], {}) if history else {}

            allow_m = bool(target["kw_general"]) and not target.get("skip_mercari")
            allow_y = bool(target["kw_general"])
            allow_wo = bool(target["kw_without"])

            new_entry["boxes"][target["id"]] = {
                "name": target["name"],
                "mercari_with": apply_spike_guard(m_with, prev_box.get("mercari_with"), "メルカリ有") if allow_m else None,
                "mercari_without": apply_spike_guard(m_without, prev_box.get("mercari_without"), "メルカリ無") if (allow_m and allow_wo) else None,
                "yahoo_with": apply_spike_guard(y_with, prev_box.get("yahoo_with"), "Yahoo有") if allow_y else None,
                "yahoo_without": apply_spike_guard(y_without, prev_box.get("yahoo_without"), "Yahoo無") if (allow_y and allow_wo) else None,
                "snkrdunk_with": apply_spike_guard(s_with, prev_box.get("snkrdunk_with"), "スニダン有"),
                "snkrdunk_without": apply_spike_guard(s_without, prev_box.get("snkrdunk_without"), "スニダン無"),
                "homura_with": h_with or prev_box.get("homura_with"),
                "homura_without": h_without or prev_box.get("homura_without"),
            }

        await browser.close()

    check_and_notify(history, new_entry)

    history.append(new_entry)
    history = history[-180:]
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    print("Done!")

if __name__ == "__main__":
    asyncio.run(main())
