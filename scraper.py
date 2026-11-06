import asyncio
import json
import os
import re
import statistics
from datetime import datetime, timedelta, timezone
import requests
from playwright.async_api import async_playwright

# 日本時間 (JST)
JST = timezone(timedelta(hours=9))

# 監視するBOXの設定
TARGETS = [
    {
        "id": "30th_celebration",
        "name": "MEGA 拡張パック「30th CELEBRATION」",
        "search_keyword": "30th CELEBRATION BOX",
        "must_words": ["30th", "CELEBRATION"], # タイトルに必須のワード（大文字小文字問わず）
        "extra_ng_words": ["フューチャリスティック", "FUTURISTIC", "カードセット", "御三家", "ファイル", "デッキ"],
        # ※スニダンや買取サイトの個別URLを固定したい場合はここに入れます（空欄なら自動検索）
        "snkrdunk_with_url": "",
        "snkrdunk_without_url": "",
        "min_valid_price": 4000,   # これ未満はパックや空箱とみなして除外
        "max_valid_price": 45000   # これ超過はカートンやセットとみなして除外
    },
    {
        "id": "mega_dream_ex",
        "name": "MEGA ハイクラスパック「MEGAドリームex」",
        "search_keyword": "MEGAドリームex BOX",
        "must_words": ["MEGAドリーム", "ドリームex"], # どちらかが入っていればOK
        "extra_ng_words": ["デッキ", "ファイル"],
        "snkrdunk_with_url": "",
        "snkrdunk_without_url": "",
        "min_valid_price": 4000,
        "max_valid_price": 45000
    }
]

# 共通NGワード（タイトルに含まれていたら無条件で除外）
COMMON_NG_WORDS = [
    "空箱", "空き箱", "箱のみ", "パックのみ", "バラ", "1p", "5p", "10p", "1パック",
    "カートン", "セット", "まとめ", "オリパ", "確定", "サーチ", "開封済",
    "SAR", "SR", "AR", "UR", "MA", "MUR", "FUR", "プロモ", "PSA", "シングル",
    "ピカチュウ", "ゲンガー", "リザードン", "ミュウ", "アクリル", "ケースのみ"
]

# シュリンクなし判定ワード
NO_SHRINK_WORDS = ["シュリンクなし", "シュリンク無し", "シュリなし", "シュリ無し", "ペリペリ"]
# シュリンクあり判定ワード
WITH_SHRINK_WORDS = ["シュリンク付き", "シュリンクつき", "シュリンク有", "シュリ付き", "未開封"]

DATA_FILE = "data.json"
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")
ALERT_THRESHOLD = 1000  # 過去2日比で±1000円以上動いたら通知


def extract_price(text):
    """文字列から数値を抽出"""
    if not text:
        return None
    nums = re.findall(r'[\d,]+', text)
    for n in nums:
        val = int(n.replace(',', ''))
        if 1000 <= val <= 500000:
            return val
    return None


def filter_mercari_title(title, target):
    """メルカリのタイトルから対象BOXかどうか＆シュリンク有無を厳密判定"""
    t_upper = title.upper()

    # 1. 必須ワードチェック（30th CELEBRATIONなら両方、MEGAドリームなら該当ワードが含まれるか）
    if target["id"] == "30th_celebration":
        if not ("30TH" in t_upper and "CELEBRATION" in t_upper):
            return None
    else:
        if not any(w.upper() in t_upper for w in target["must_words"]):
            return None

    # 2. 共通NGワード＆個別NGワードチェック
    for ng in COMMON_NG_WORDS + target["extra_ng_words"]:
        if ng.upper() in t_upper:
            return None

    # 3. 複数BOX売り（2BOX、3箱など）を除外
    if re.search(r'[2-9２-９]\s*(BOX|ボックス|箱)', t_upper):
        return None

    # 4. シュリンク有無の振り分け
    if any(w in title for w in NO_SHRINK_WORDS):
        return "without_shrink"
    if any(w in title for w in WITH_SHRINK_WORDS) or "BOX" in t_upper or "ボックス" in title:
        return "with_shrink"

    return None


async def scrape_mercari(page, target):
    """メルカリ（売り切れ・最新順）からシュリンク有/無の中央値を取得"""
    kw = target["search_keyword"]
    url = f"https://jp.mercari.com/search?keyword={kw}&status=sold_out&sort=created_time&order=desc"
    with_prices, without_prices = [], []

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(4000)

        items = await page.query_selector_all('li[data-testid="item-cell"], mer-item-thumbnail')
        for item in items[:40]:
            text = await item.inner_text()
            lines = [line.strip() for line in text.split('\n') if line.strip()]
            if not lines:
                continue
            title = " ".join(lines)
            price = extract_price(title)
            if not price or not (target["min_valid_price"] <= price <= target["max_valid_price"]):
                continue

            status = filter_mercari_title(title, target)
            if status == "with_shrink":
                with_prices.append(price)
            elif status == "without_shrink":
                without_prices.append(price)

        med_with = int(statistics.median(with_prices[:10])) if with_prices else None
        med_without = int(statistics.median(without_prices[:10])) if without_prices else None
        return med_with, med_without
    except Exception as e:
        print(f"Mercari error ({target['name']}): {e}")
        return None, None


async def scrape_snkrdunk(page, target):
    """スニダンからシュリンク有/無の最安値を取得"""
    kw = target["search_keyword"].replace(" BOX", "")
    search_url = f"https://snkrdunk.com/search/result?keywords={kw}"
    price_with, price_without = None, None

    try:
        await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)
        content = await page.inner_text("body")

        # 検索結果一覧から「シュリンクなし」表記の有無で価格を振り分け
        blocks = content.split('\n')
        for i, line in enumerate(blocks):
            if any(w.upper() in line.upper() for w in target["must_words"]):
                if any(ng in line for ng in target["extra_ng_words"] + ["パック", "カートン"]):
                    continue
                # 周辺行から価格を探す
                nearby = " ".join(blocks[max(0, i-2):min(len(blocks), i+5)])
                p = extract_price(nearby)
                if p and target["min_valid_price"] <= p <= target["max_valid_price"]:
                    if "シュリンクなし" in line or "シュリンク無し" in line:
                        if not price_without:
                            price_without = p
                    else:
                        if not price_with:
                            price_with = p
        return price_with, price_without
    except Exception as e:
        print(f"SNKRDUNK error ({target['name']}): {e}")
        return None, None


async def scrape_homura(page, target):
    """買取ホムラからシュリンク有/無の買取価格を取得"""
    kw = target["must_words"][0]
    url = f"https://kaitori-homura.com/?q={kw}"
    price_with, price_without = None, None

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)
        text = await page.inner_text("body")
        lines = [l.strip() for l in text.split('\n') if l.strip()]

        for i, line in enumerate(lines):
            if any(w.upper() in line.upper() for w in target["must_words"]):
                if any(ng in line for ng in target["extra_ng_words"] + ["カートン", "パック"]):
                    continue
                nearby = " ".join(lines[i:min(len(lines), i+6)])
                p = extract_price(nearby)
                if p and target["min_valid_price"] <= p <= target["max_valid_price"]:
                    if "シュリンクなし" in nearby or "シュリンク無し" in nearby:
                        if not price_without:
                            price_without = p
                    else:
                        if not price_with:
                            price_with = p
        return price_with, price_without
    except Exception as e:
        print(f"Homura error ({target['name']}): {e}")
        return None, None


async def scrape_souba_site(page, target):
    """ポケカ相場サイト（トレカの地図等）から買取平均相場を取得"""
    kw = target["search_keyword"]
    url = f"https://html.duckduckgo.com/html/?q=site:torechart.com+OR+site:pokeca-chart.com+{kw}+買取"
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)
        text = await page.inner_text("body")
        prices = [int(p.replace(',', '')) for p in re.findall(r'([\d,]{4,6})\s*円', text)]
        valid = [p for p in prices if target["min_valid_price"] <= p <= target["max_valid_price"]]
        return valid[0] if valid else None
    except Exception as e:
        print(f"Souba site error: {e}")
        return None


def check_and_notify(history, new_entry):
    """過去2日間の記録と比較して±1000円以上動いていたらDiscord通知"""
    if not DISCORD_WEBHOOK or len(history) < 1:
        return

    # 過去2日（最大4回分）のデータを抽出
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

            # 過去2日間の同じ項目の有効な価格を取得
            past_vals = [
                r["boxes"].get(box_id, {}).get(key)
                for r in recent_records
                if r["boxes"].get(box_id, {}).get(key) is not None
            ]
            if not past_vals:
                continue

            # 過去2日間の基準値（最も古い値、または平均）と比較
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
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
            locale="ja-JP"
        )
        page = await context.new_page()

        for target in TARGETS:
            print(f"Fetching {target['name']}...")
            m_with, m_without = await scrape_mercari(page, target)
            s_with, s_without = await scrape_snkrdunk(page, target)
            h_with, h_without = await scrape_homura(page, target)
            souba_avg = await scrape_souba_site(page, target)

            # 万が一今回取得できなかった項目は、グラフが途切れないよう前回の値を引き継ぐ
            prev_box = history[-1]["boxes"].get(target["id"], {}) if history else {}

            new_entry["boxes"][target["id"]] = {
                "name": target["name"],
                "mercari_with": m_with or prev_box.get("mercari_with"),
                "mercari_without": m_without or prev_box.get("mercari_without"),
                "snkrdunk_with": s_with or prev_box.get("snkrdunk_with"),
                "snkrdunk_without": s_without or prev_box.get("snkrdunk_without"),
                "homura_with": h_with or prev_box.get("homura_with"),
                "homura_without": h_without or prev_box.get("homura_without"),
                "souba_site": souba_avg or prev_box.get("souba_site")
            }

        await browser.close()

    # アラート判定＆Discord通知
    check_and_notify(history, new_entry)

    # 履歴に追加して保存（最大180回分＝約3ヶ月分保持）
    history.append(new_entry)
    history = history[-180:]
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    print("Done!")

if __name__ == "__main__":
    asyncio.run(main())
