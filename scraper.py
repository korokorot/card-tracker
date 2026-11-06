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
        "search_keyword": "30th CELEBRATION BOX",
        "must_words": ["30th", "CELEBRATION"],
        "extra_ng_words": ["フューチャリスティック", "FUTURISTIC", "カードセット", "御三家", "ファイル", "デッキ"],
        "min_valid_price": 4000,
        "max_valid_price": 45000
    },
    {
        "id": "mega_dream_ex",
        "name": "MEGA ハイクラスパック「MEGAドリームex」",
        "search_keyword": "MEGAドリームex BOX",
        "must_words": ["MEGAドリーム", "ドリームex"],
        "extra_ng_words": ["デッキ", "ファイル"],
        "min_valid_price": 4000,
        "max_valid_price": 45000
    }
]

COMMON_NG_WORDS = [
    "空箱", "空き箱", "箱のみ", "パックのみ", "バラ", "1p", "5p", "10p", "1パック",
    "カートン", "セット", "まとめ", "オリパ", "確定", "サーチ", "開封済",
    "SAR", "SR", "AR", "UR", "MA", "MUR", "FUR", "プロモ", "PSA", "シングル",
    "ピカチュウ", "ゲンガー", "リザードン", "ミュウ", "アクリル", "ケースのみ"
]

NO_SHRINK_WORDS = ["シュリンクなし", "シュリンク無し", "シュリなし", "シュリ無し", "ペリペリ"]
WITH_SHRINK_WORDS = ["シュリンク付き", "シュリンクつき", "シュリンク有", "シュリ付き", "未開封"]

DATA_FILE = "data.json"
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")
ALERT_THRESHOLD = 1000


def extract_price(text):
    if not text:
        return None
    # ¥記号や円がついている数字を優先抽出
    matches = re.findall(r'[¥￥]\s*([\d,]{4,7})|([\d,]{4,7})\s*円', text)
    for m in matches:
        num_str = m[0] or m[1]
        val = int(num_str.replace(',', ''))
        if 3000 <= val <= 100000:
            return val
    # なければ通常の数値
    nums = re.findall(r'[\d,]{4,7}', text)
    for n in nums:
        val = int(n.replace(',', ''))
        if 3000 <= val <= 100000:
            return val
    return None


def filter_mercari_title(title, target):
    t_upper = title.upper()
    if target["id"] == "30th_celebration":
        if not ("30TH" in t_upper and "CELEBRATION" in t_upper):
            return None
    else:
        if not any(w.upper() in t_upper for w in target["must_words"]):
            return None

    for ng in COMMON_NG_WORDS + target["extra_ng_words"]:
        if ng.upper() in t_upper:
            return None

    if re.search(r'[2-9２-９]\s*(BOX|ボックス|箱)', t_upper):
        return None

    if any(w in title for w in NO_SHRINK_WORDS):
        return "without_shrink"
    if any(w in title for w in WITH_SHRINK_WORDS) or "BOX" in t_upper or "ボックス" in title:
        return "with_shrink"
    return None


async def scrape_mercari(page, target):
    kw = quote(target["search_keyword"])
    url = f"https://jp.mercari.com/search?keyword={kw}&status=sold_out&sort=created_time&order=desc"
    with_prices, without_prices = [], []

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=40000)
        await page.wait_for_timeout(6000)
        await page.evaluate("window.scrollBy(0, 1200)")
        await page.wait_for_timeout(3000)

        page_title = await page.title()
        # 商品リンク（/item/m...）をすべて取得し、aria-labelや内部テキストから判定
        links = await page.query_selector_all('a[href*="/item/m"]')
        print(f"  [Mercari] Title: {page_title} | Found links: {len(links)}")

        for link in links[:45]:
            aria = await link.get_attribute("aria-label") or ""
            inner = await link.inner_text() or ""
            full_text = f"{aria} {inner}".replace('\n', ' ')

            price = extract_price(full_text)
            if not price or not (target["min_valid_price"] <= price <= target["max_valid_price"]):
                continue

            status = filter_mercari_title(full_text, target)
            if status == "with_shrink":
                with_prices.append(price)
            elif status == "without_shrink":
                without_prices.append(price)

        med_with = int(statistics.median(with_prices[:10])) if with_prices else None
        med_without = int(statistics.median(without_prices[:10])) if without_prices else None
        print(f"  [Mercari Result] 有: {med_with} ({len(with_prices)}件) / 無: {med_without} ({len(without_prices)}件)")
        return med_with, med_without
    except Exception as e:
        print(f"  [Mercari Error] {e}")
        return None, None


async def scrape_snkrdunk(page, target):
    kw = quote(target["search_keyword"].replace(" BOX", ""))
    search_url = f"https://snkrdunk.com/search/result?keywords={kw}"
    price_with, price_without = None, None

    try:
        await page.goto(search_url, wait_until="domcontentloaded", timeout=40000)
        await page.wait_for_timeout(5000)
        await page.evaluate("window.scrollBy(0, 800)")
        await page.wait_for_timeout(2000)

        page_title = await page.title()
        content = await page.inner_text("body")
        print(f"  [SNKRDUNK] Title: {page_title} | Text len: {len(content)}")

        blocks = [b.strip() for b in content.split('\n') if b.strip()]
        for i, line in enumerate(blocks):
            if any(w.upper() in line.upper() for w in target["must_words"]):
                if any(ng in line for ng in target["extra_ng_words"] + ["パック", "カートン", "シングル"]):
                    continue
                nearby = " ".join(blocks[max(0, i-2):min(len(blocks), i+6)])
                p = extract_price(nearby)
                if p and target["min_valid_price"] <= p <= target["max_valid_price"]:
                    if "シュリンクなし" in line or "シュリンク無し" in line:
                        if not price_without:
                            price_without = p
                    else:
                        if not price_with:
                            price_with = p
        print(f"  [SNKRDUNK Result] 有: {price_with} / 無: {price_without}")
        return price_with, price_without
    except Exception as e:
        print(f"  [SNKRDUNK Error] {e}")
        return None, None


async def scrape_homura(page, target):
    kw = quote(target["must_words"][0])
    url = f"https://kaitori-homura.com/products?q%5Bname_cont%5D={kw}"
    price_with, price_without = None, None

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=40000)
        await page.wait_for_timeout(4000)
        content = await page.inner_text("body")

        # もし検索URLで見つからなければトップページから探す
        if not any(w.upper() in content.upper() for w in target["must_words"]):
            await page.goto("https://kaitori-homura.com/", wait_until="domcontentloaded", timeout=40000)
            await page.wait_for_timeout(4000)
            content = await page.inner_text("body")

        page_title = await page.title()
        print(f"  [Homura] Title: {page_title} | Text len: {len(content)}")

        lines = [l.strip() for l in content.split('\n') if l.strip()]
        for i, line in enumerate(lines):
            if any(w.upper() in line.upper() for w in target["must_words"]):
                if any(ng in line for ng in target["extra_ng_words"] + ["カートン", "パック"]):
                    continue
                nearby = " ".join(lines[i:min(len(lines), i+6)])
                p = extract_price(nearby)
                if p and target["min_valid_price"] <= p <= target["max_valid_price"]:
                    if "シュリンクなし" in nearby or "シュリンク無し" in nearby or "シュリなし" in nearby:
                        if not price_without:
                            price_without = p
                    else:
                        if not price_with:
                            price_with = p
        print(f"  [Homura Result] 有: {price_with} / 無: {price_without}")
        return price_with, price_without
    except Exception as e:
        print(f"  [Homura Error] {e}")
        return None, None


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
    history = []
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            history = []

    new_entry = {"timestamp": now_str, "boxes": {}}

    async with async_playwright() as p:
        # 自動化検知を回避するオプション付きで起動
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
        # webdriverフラグを隠す
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page = await context.new_page()

        for target in TARGETS:
            print(f"=== Fetching {target['name']} ===")
            m_with, m_without = await scrape_mercari(page, target)
            s_with, s_without = await scrape_snkrdunk(page, target)
            h_with, h_without = await scrape_homura(page, target)

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
