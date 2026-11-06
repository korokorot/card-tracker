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
        "skip_mercari": True,  # 出品制限により異常値(1件等)になるためメルカリは除外し、Yahoo!フリマ等で取得
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
        "max_valid_price": 24500  # 26,000円等の抱き合わせ・異常値を弾くため上限を適正化
    },
    {
        "id": "storm_emeralda",
        "name": "MEGA 拡張パック「ストームエメラルダ」",
        "kw_general": "ストームエメラルダ BOX",
        "kw_without": "ストームエメラルダ BOX シュリンクなし",
        "must_words": ["ストームエメラルダ", "エメラルダ"],
        "extra_ng_words": ["レックウザ", "ライコウ", "カイオーガ", "グラードン", "ヒガナ", "30TH", "アビスアイ", "ムニキスゼロ", "メガドリーム"],
        "snkrdunk_with_url": "https://snkrdunk.com/apparels/846048",
        "snkrdunk_without_url": "https://snkrdunk.com/apparels/846050",
        "homura_with_url": "https://kaitori-homura.com/products/6933",
        "homura_without_url": "https://kaitori-homura.com/products/6934",
        "min_valid_price": 5000,
        "max_valid_price": 20000
    },
    {
        "id": "abyss_eye",
        "name": "MEGA 拡張パック「アビスアイ」",
        "kw_general": "アビスアイ BOX",
        "kw_without": "アビスアイ BOX シュリンクなし",
        "must_words": ["アビスアイ"],
        "extra_ng_words": ["ダークライ", "ゼラオラ", "シャンデラ", "カスミ", "グラジオ", "ムク", "30TH", "ストームエメラルダ", "ムニキスゼロ", "メガドリーム"],
        "snkrdunk_with_url": "https://snkrdunk.com/apparels/806644",
        "snkrdunk_without_url": "https://snkrdunk.com/apparels/806646",
        "homura_with_url": "https://kaitori-homura.com/products/6733",
        "homura_without_url": "https://kaitori-homura.com/products/6734",
        "min_valid_price": 4500,
        "max_valid_price": 18000
    },
    {
        "id": "munikis_zero",
        "name": "MEGA 拡張パック「ムニキスゼロ」",
        "kw_general": "ムニキスゼロ BOX",
        "kw_without": "ムニキスゼロ BOX シュリンクなし",
        "must_words": ["ムニキスゼロ"],
        "extra_ng_words": ["30TH", "ストームエメラルダ", "アビスアイ", "メガドリーム", "インフェルノ"],
        "snkrdunk_with_url": "https://snkrdunk.com/apparels/743533",
        "snkrdunk_without_url": "https://snkrdunk.com/apparels/743535",
        "homura_with_url": "https://kaitori-homura.com/products/5443",
        "homura_without_url": "https://kaitori-homura.com/products/5444",
        "min_valid_price": 4500,
        "max_valid_price": 18000
    },
    {
        "id": "mega_dream_ex",
        "name": "MEGA ハイクラスパック「MEGAドリームex」",
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
        "kw_general": "",
        "kw_without": "",
        "must_words": [],
        "extra_ng_words": [],
        "snkrdunk_with_url": "",
        "snkrdunk_without_url": "",
        "homura_with_url": "https://kaitori-homura.com/products/7780",
        "homura_without_url": "",
        "min_valid_price": 9000,
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


def classify_item_text(title, target):
    """タイトルから 'with_shrink' / 'without_shrink' / None を判定（メルカリ・Yahoo共通）"""
    t_upper = title.upper()
    if not any(w.upper() in t_upper for w in target["must_words"]):
        return None
    for ng in COMMON_NG_WORDS + target["extra_ng_words"]:
        if ng.upper() in t_upper:
            return None
    # 2BOX、２箱、×2、x3 などの複数個出品を除外
    if re.search(r'(?<!\d)[2-9２-９]\s*(BOX|ボックス|箱|個|点|セット)', t_upper):
        return None
    if re.search(r'[×✕xX]\s*[2-9２-９]', t_upper):
        return None
    if "セット" in t_upper and not any(ok in t_upper for ok in ["ローダー", "ケース"]):
        return None
    if any(w in title for w in NO_SHRINK_WORDS):
        return "without_shrink"
    return "with_shrink"


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

        if wo_kws and len(without_prices) < 3:
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

        med_w = int(statistics.median(with_prices[:15])) if with_prices else None
        med_wo = int(statistics.median(without_prices[:15])) if without_prices else None
        return med_w, len(with_prices), med_wo, len(without_prices)
    except Exception as e:
        print(f"  [Mercari Error] {e}")
        return None, 0, None, 0


# === Yahoo!フリマ（旧PayPayフリマ）のスクレイピング処理 ===
async def fetch_yahoo_items_from_url(page, keyword):
    kw = quote(keyword)
    # open=1 で「売り切れ」のみを検索
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
            let text = [a.getAttribute('aria-label') || '', a.innerText || ''].join(' ');
            const imgs = a.querySelectorAll('img');
            imgs.forEach(img => { text += ' ' + (img.getAttribute('alt') || ''); });
            text = text.replace(/\\s+/g, ' ').trim();
            if (text) results.push(text);
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


async def scrape_yahoo_box(page, target):
    if not target["kw_general"]:
        return None, 0, None, 0

    with_prices, without_prices = [], []
    seen_texts = set()

    gen_kws = target["kw_general"] if isinstance(target["kw_general"], list) else [target["kw_general"]]
    wo_kws = target["kw_without"] if isinstance(target["kw_without"], list) else ([target["kw_without"]] if target["kw_without"] else [])

    try:
        for kw in gen_kws:
            items = await fetch_yahoo_items_from_url(page, kw)
            for raw_text in items:
                if raw_text in seen_texts:
                    continue
                seen_texts.add(raw_text)
                price = extract_yahoo_price_jpy(raw_text, target)
                if not price:
                    continue
                status = classify_item_text(raw_text, target)
                if status == "with_shrink":
                    with_prices.append(price)
                elif status == "without_shrink" and wo_kws:
                    without_prices.append(price)

        if wo_kws and len(without_prices) < 3:
            for kw in wo_kws:
                wo_items = await fetch_yahoo_items_from_url(page, kw)
                for raw_text in wo_items:
                    if raw_text in seen_texts:
                        continue
                    seen_texts.add(raw_text)
                    price = extract_yahoo_price_jpy(raw_text, target)
                    if not price:
                        continue
                    if classify_item_text(raw_text, target) == "without_shrink":
                        without_prices.append(price)

        med_w = int(statistics.median(with_prices[:15])) if with_prices else None
        med_wo = int(statistics.median(without_prices[:15])) if without_prices else None
        return med_w, len(with_prices), med_wo, len(without_prices)
    except Exception as e:
        print(f"  [Yahoo Error] {e}")
        return None, 0, None, 0


async def scrape_snkrdunk_single(page, url, target):
    if not url:
        return None
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=40000)
        await page.wait_for_timeout(3500)
        content = await page.inner_text("body")
        matches = re.findall(r'[¥￥]\s*([\d,]{4,6})\s*[~〜]', content)
        if not matches:
            matches = re.findall(r'[¥￥]\s*([\d,]{4,6})', content)
        for m in matches:
            val = int(m.replace(',', ''))
            if val in RETAIL_PRICES:
                continue
            if target["min_valid_price"] <= val <= target["max_valid_price"]:
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
            s_without = await scrape_snkrdunk_single(page, target["snkrdunk_without_url"], target)
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
                "mercari_with": (m_with or prev_box.get("mercari_with")) if allow_m else None,
                "mercari_without": (m_without or prev_box.get("mercari_without")) if (allow_m and allow_wo) else None,
                "yahoo_with": (y_with or prev_box.get("yahoo_with")) if allow_y else None,
                "yahoo_without": (y_without or prev_box.get("yahoo_without")) if (allow_y and allow_wo) else None,
                "snkrdunk_with": s_with or prev_box.get("snkrdunk_with"),
                "snkrdunk_without": s_without or prev_box.get("snkrdunk_without"),
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
