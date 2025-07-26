import requests
import json
import os
from datetime import datetime, timedelta
import pytz

# === Constants ===
DATA_FILE = "data.json"
URLS_FILE = "urls.txt"
LAST_RUN_FILE = "last_run.txt"
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

# === Timezone ===
tz_adelaide = pytz.timezone("Australia/Adelaide")
now = datetime.now(tz_adelaide)
today_str = now.strftime("%Y-%m-%d")

# === Read the last successful run time ===
if os.path.exists(LAST_RUN_FILE):
    with open(LAST_RUN_FILE, "r") as f:
        last_run_raw = f.read().strip()
    try:
        last_run_dt = datetime.fromisoformat(last_run_raw).astimezone(tz_adelaide)
        delta = now - last_run_dt
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        minutes = remainder // 60
        ago_str = f"{hours} hour{'s' if hours != 1 else ''}" if hours else f"{minutes} minute{'s' if minutes != 1 else ''}"
        formatted_last_run = last_run_dt.strftime("%d %B @ %I:%M %p")
        last_run_time_str = f"{formatted_last_run} ({ago_str} ago)"
    except Exception as e:
        print(f"⚠️ Error parsing last run time: {e}")
        last_run_time_str = "Unknown"
else:
    last_run_time_str = "Unknown"

# === Read product IDs from urls.txt ===
user_cards = {}
card_names = {}

with open(URLS_FILE, "r") as f:
    for line in f:
        if line.strip():
            try:
                user, name, pid = map(str.strip, line.strip().split(",", 2))
                user_cards.setdefault(user, []).append(pid)
                card_names[pid] = name
            except ValueError:
                print(f"⚠️ Skipping malformed line: {line.strip()}")

# === Load previous price data ===
if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r") as f:
        old_data = json.load(f)
        # Upgrade old format if needed
        for pid, value in list(old_data.items()):
            if isinstance(value, float):  # Old format: just price
                old_data[pid] = {
                    "price": value,
                    "history": []
                }
else:
    old_data = {}

new_data = {}

# === Fetch price from TCGPlayer API ===
def get_price(product_id):
    url = f"https://mpapi.tcgplayer.com/v2/product/{product_id}/pricepoints"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        prices = response.json()

        # Prioritize Foil prices if available, else Normal
        for entry in prices:
            if entry.get("printingType") == "Foil" and entry.get("marketPrice"):
                return entry["marketPrice"]
        for entry in prices:
            if entry.get("printingType") == "Normal" and entry.get("marketPrice"):
                return entry["marketPrice"]
        return None
    except Exception as e:
        print(f"❌ Failed to get price for {product_id}: {e}")
        return None

# === Update price history ===
def update_price_history(pid, market_price):
    history = old_data.get(pid, {}).get("history", [])
    if not any(entry["date"] == today_str for entry in history):
        history.append({"date": today_str, "market": market_price})
    return history

# === Calculate change from a specific period ===
def calculate_performance(history, target_date):
    baseline = None
    for entry in reversed(history):
        entry_date = datetime.strptime(entry["date"], "%Y-%m-%d").date()
        if entry_date <= target_date:
            baseline = entry["market"]
            break
    latest = history[-1]["market"] if history else None
    if baseline is None or latest is None:
        return None
    return round(latest - baseline, 2)

# === Fetch current prices and update new_data with history ===
for user, ids in user_cards.items():
    for pid in ids:
        price = get_price(pid)
        if price is not None:
            new_data.setdefault(pid, {})["price"] = price
            new_data[pid]["history"] = update_price_history(pid, price)

# === Save updated data ===
with open(DATA_FILE, "w") as f:
    json.dump(new_data, f, indent=2)

# === Save current run time ===
with open(LAST_RUN_FILE, "w") as f:
    f.write(now.isoformat())

# === Build Discord Embeds ===
embeds = []

for idx, (user, ids) in enumerate(user_cards.items()):
    sorted_ids = sorted(ids, key=lambda pid: new_data.get(pid, {}).get("price") or 0, reverse=True)

    field_lines = []
    total_value = 0.0
    old_total_value = 0.0

    # Calculate total old and new value for performance metrics
    for pid in sorted_ids:
        price = new_data.get(pid, {}).get("price")
        old_price = old_data.get(pid, {}).get("price")
        if price is not None:
            total_value += price
        if old_price is not None:
            old_total_value += old_price

    # Calculate total performance for WTD, MTD, YTD, ALL
    today = now.date()
    start_of_week = today - timedelta(days=today.weekday())
    start_of_month = today.replace(day=1)
    start_of_year = today.replace(month=1, day=1)

    def get_total_baseline(target_date):
        baseline_sum = 0.0
        for pid in sorted_ids:
            history = new_data.get(pid, {}).get("history", [])
            baseline = None
            for entry in reversed(history):
                entry_date = datetime.strptime(entry["date"], "%Y-%m-%d").date()
                if entry_date <= target_date:
                    baseline = entry["market"]
                    break
            if baseline is not None:
                baseline_sum += baseline
        return baseline_sum

    baseline_week = get_total_baseline(start_of_week)
    baseline_month = get_total_baseline(start_of_month)
    baseline_year = get_total_baseline(start_of_year)
    baseline_all = get_total_baseline(datetime.strptime(min((entry["date"] for pid in sorted_ids for entry in new_data.get(pid, {}).get("history", [{"date": today_str}]))), "%Y-%m-%d").date())

    total_wtd = total_value - baseline_week
    total_mtd = total_value - baseline_month
    total_ytd = total_value - baseline_year
    total_all = total_value - baseline_all

    def emoji_for_change(change):
        if change > 0:
            return "📈"
        elif change < 0:
            return "📉"
        else:
            return "⏸️"

    total_perf_str = (
        f"{emoji_for_change(total_wtd)} WTD {total_wtd:+.2f} | "
        f"{emoji_for_change(total_mtd)} MTD {total_mtd:+.2f} | "
        f"{emoji_for_change(total_ytd)} YTD {total_ytd:+.2f} | "
        f"{emoji_for_change(total_all)} ALL {total_all:+.2f}"
    )

    # Build field lines for each card WITHOUT performance stats
    for pid in sorted_ids:
        name = card_names.get(pid, f"Card {pid}")
        price = new_data.get(pid, {}).get("price")
        old_price = old_data.get(pid, {}).get("price")

        if price is None:
            line = f"❌ **{name}** (`{pid}`): No price found."
        elif old_price is None:
            line = f"🆕 **{name}**: ${price:.2f} (new)"
        else:
            change = price - old_price
            symbol = "📈" if change > 0 else "📉" if change < 0 else "⏸️"
            line = f"{symbol} **{name}**: ${price:.2f} ({change:+.2f})"

        field_lines.append(line)

    embed = {
        "title": f"{user}'s Card Summary",
        "color": 0x00ffcc,
        "fields": [
            {
                "name": "Total Value & Performance",
                "value": f"${total_value:.2f} | {total_perf_str}",
                "inline": False
            },
            {
                "name": "Card Details",
                "value": "\n".join(field_lines) or "No cards found.",
                "inline": False
            }
        ]
    }

    if idx == len(user_cards) - 1:
        embed["footer"] = {"text": f"Last run: {last_run_time_str}"}

    embeds.append(embed)

# === Send to Discord ===
payload = {
    "content": "🧾 **Pokémon Card Price Tracker Report**",
    "embeds": embeds
}

response = requests.post(DISCORD_WEBHOOK_URL, json=payload)

if response.status_code != 204:
    print(f"❌ Failed to send Discord webhook: {response.status_code} {response.text}")
