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
        "kw_with": "30th CELEBRATION BOX シュリンク付き",
        "kw_without": "30th CELEBRATION BOX シュリンクなし",
        "must_words": ["30TH", "30周年", "CELEBRATION"],
        "extra_ng_words": [
            "フューチャリスティック", "FUTURISTIC", "カードセット", "御三家", "ファイル", "デッキ", "エネルギー",
            "25TH", "25周年", "20TH", "20周年", "ゴールデン", "GOLDEN", "アニバーサリー", "アビスアイ"
        ],
        "snkrdunk_with_url": "https://snkrdunk.com/apparels/881421",
        "snkrdunk_without_url": "https://snkrdunk.com/apparels/881427",
        "homura_with_url": "https://kaitori-homura.com/products/7237",
        "homura_without_url": "https://kaitori-homura.com/products/7238",
        "min_valid_price": 10000,
        "max_valid_price": 35000
    },
    {
        "id": "mega_dream_ex",
        "name": "MEGA ハイクラスパック「MEGAドリームex」",
        "kw_with": "MEGAドリームex BOX シュリンク付き",
        "kw_without": "MEGAドリームex BOX シュリンクなし",
        "must_words": ["MEGAドリーム", "メガドリーム", "ドリームEX"],
        "extra_ng_words": ["デッキ", "ファイル", "アビスアイ", "テラスタル", "バトルパートナーズ", "151", "30TH"],
        "snkrdunk_with_url": "https://snkrdunk.com/apparels/721913",
        "snkrdunk_without_url": "https://snkrdunk.com/apparels/721915",
        "homura_with_url": "https://kaitori-homura.com/products/3465",
        "homura_without_url": "https://kaitori-homura.com/products/3383",
        "min_valid_price": 6000,
        "max_valid_price": 25000
    }
]

COMMON_NG_WORDS = [
    "空箱", "空き箱", "箱のみ", "パックのみ", "バラ", "1P", "5P", "10P", "1パック", "10パック",
    "カートン", "セット", "まとめ", "オリパ", "確定", "サーチ", "開封済",
    "SAR", "SR", "AR", "UR", "MA", "MUR", "FUR", "プロモ", "PSA", "シングル",
    "ピカチュウ", "ゲンガー", "リザードン", "ミュウ", "ルギア", "カイリュー", "アクリル", "ケースのみ"
]

NO_SHRINK_WORDS = ["シュリンクなし", "シュリンク無し", "シュリなし", "シュリ無し", "ペリペリ", "シュリンク無"]
WITH_SHRINK_WORDS = ["シュリンク付き", "シュリンクつき", "シュリンク有", "シュリ付き", "未開封"]

DATA_FILE = "data.json"
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")
ALERT_THRESHOLD = 1000


def get_usd_jpy_rate():
    try:
        res = requests.get("https://open.er-api.com/v6/latest/USD", timeout=10).json()
        return float(res["rates"]["JPY"])
    except Exception:
        return 157.0


def is_valid_mercari_item(title, target, expect_shrink):
    t_upper = title.upper()

    # 1. 必須ワードチェック
    if not any(w.upper() in t_upper for w in target["must_words"]):
        return False

    # 2. NGワードチェック
    for ng in COMMON_NG_WORDS + target["extra_ng_words"]:
        if ng.upper() in t_upper:
            return False

    # 3. 複数BOX売り（2BOX、3箱、2個セットなど）を除外（「30th」の数字は除外しないよう厳密化）
    if re.search(r'(?<!\d)[2-9２-９]\s*(BOX|ボックス|箱|個|点)', t_upper):
        return False

    has_no_shrink_word = any(w in title for w in NO_SHRINK_WORDS)

    if expect_shrink:
        if has_no_shrink_word:
            return False
        return True
    else:
        return has_no_shrink_word


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


async def scrape_mercari_single_mode(page, keyword, target, usd_rate, expect_shrink):
    kw = quote(keyword)
    url = f"https://jp.mercari.com/search?keyword={kw}&status=sold_out&sort=created_time&order=desc"
    prices = []
    mode_label = "有" if expect_shrink else "無"

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=40000)
        await page.wait_for_timeout(5000)
        await page.evaluate("window.scrollBy(0, 1500)")
        await page.wait_for_timeout(2500)

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
                // サムネイル等の重複ワードを削って綺麗にする
                text = text.replace(/のサムネイル/g, '').replace(/\\s+/g, ' ').trim();
                results.push(text);
            });
            return results;
        }""")

        for raw_text in items_data[:45]:
            price = extract_mercari_price_jpy(raw_text, usd_rate, target)
            if not price:
                continue
            if is_valid_mercari_item(raw_text, target, expect_shrink):
                prices.append(price)

        # もし0件だった場合、何が画面に出ていたのか先頭2件をログに出力して原因を見える化する
        if not prices and items_data:
            print(f"    [Debug Mercari({mode_label}) 0件] 画面の先頭商品: {items_data[0][:90]} / {items_data[1][:90] if len(items_data)>1 else ''}")

        med = int(statistics.median(prices[:10])) if prices else None
        return med, len(prices)
    except Exception as e:
        print(f"  [Mercari Error] {e}")
        return None, 0


async def scrape_snkrdunk_single(page, url, target):
    if not url:
        return None
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=40000)
        await page.wait_for_timeout(4000)
        content = await page.inner_text("body")
        matches = re.findall(r'[¥￥]\s*([\d,]{4,6})\s*[~〜]', content)
        if not matches:
            matches = re.findall(r'[¥￥]\s*([\d,]{4,6})', content)
        for m in matches:
            val = int(m.replace(',', ''))
            if val in (5500, 7200):
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
        await page.wait_for_timeout(3500)
        content = await page.inner_text("body")
        m = re.search(r'買取(?:価格|金額)[^0-9]{0,20}([\d,]{4,6})', content)
        if m:
            val = int(m.group(1).replace(',', ''))
            if target["min_valid_price"] <= val <= target["max_valid_price"]:
                return val

        for m2 in re.findall(r'([\d,]{4,6})\s*円', content[:1500]):
            val = int(m2.replace(',', ''))
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
            ("メルカリ(シュリ有)", "mercari_with"),
            ("メルカリ(シュリ無)", "mercari_without"),
            ("スニダン(シュリ有)", "snkrdunk_with"),
            ("スニダン(シュリ無)", "snkrdunk_without"),
            ("買取ホムラ(シュリ有)", "homura_with"),
            ("買取ホムラ(シュリ無)", "homura_without"),
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
            m_with, cnt_w = await scrape_mercari_single_mode(page, target["kw_with"], target, usd_rate, True)
            m_without, cnt_wo = await scrape_mercari_single_mode(page, target["kw_without"], target, usd_rate, False)
            print(f"  [Mercari Result] 有: {m_with} ({cnt_w}件) / 無: {m_without} ({cnt_wo}件)")

            s_with = await scrape_snkrdunk_single(page, target["snkrdunk_with_url"], target)
            s_without = await scrape_snkrdunk_single(page, target["snkrdunk_without_url"], target)
            print(f"  [SNKRDUNK Result] 有: {s_with} / 無: {s_without}")

            h_with = await scrape_homura_single(page, target["homura_with_url"], target)
            h_without = await scrape_homura_single(page, target["homura_without_url"], target)
            print(f"  [Homura Result] 有: {h_with} / 無: {h_without}")

            prev_box = history[-1]["boxes"].get(target["id"], {}) if history else {}

            new_entry["boxes"][target["id"]] = {
                "name": target["name"],
                "mercari_with": m_with or prev_box.get("mercari_with"),
                "mercari_without": m_without or prev_box.get("mercari_without"),
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
