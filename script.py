import requests
import json
import os
from datetime import datetime
import pytz

# === Constants ===
DATA_FILE = "data.json"
URLS_FILE = "urls.txt"
LAST_RUN_FILE = "last_run.txt"
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

# === Timezone ===
tz_adelaide = pytz.timezone("Australia/Adelaide")
now = datetime.now(tz_adelaide)

# === Read the last successful run time ===
if os.path.exists(LAST_RUN_FILE):
    with open(LAST_RUN_FILE, "r") as f:
        last_run_raw = f.read().strip()
    try:
        last_run_dt = datetime.fromisoformat(last_run_raw).astimezone(tz_adelaide)
        delta = now - last_run_dt
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        minutes = remainder // 60

        if hours >= 1:
            ago_str = f"{hours} hour{'s' if hours != 1 else ''}"
            if minutes:
                ago_str += f", {minutes} minute{'s' if minutes != 1 else ''}"
        else:
            ago_str = f"{minutes} minute{'s' if minutes != 1 else ''}"

        formatted_last_run = last_run_dt.strftime("%d %B @ %I:%M %p")
        last_run_time_str = f"{formatted_last_run} ({ago_str} ago)"

    except Exception as e:
        print(f"⚠️ Error parsing last run time: {e}")
        last_run_time_str = "Unknown"
else:
    last_run_time_str = "Unknown"

# === Read product IDs from urls.txt ===
# Format: UserName,Card Name,ProductID
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
else:
    old_data = {}

new_data = {}
message_lines = []

# === Fetch price from TCGPlayer API ===
def get_price(product_id):
    url = f"https://mpapi.tcgplayer.com/v2/product/{product_id}/pricepoints"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        prices = response.json()

        for entry in prices:
            if entry.get("printingType") == "Foil" and entry.get("marketPrice"):
                return entry["marketPrice"]
            elif entry.get("printingType") == "Normal" and entry.get("marketPrice"):
                return entry["marketPrice"]
        return None
    except Exception as e:
        print(f"❌ Failed to get price for {product_id}: {e}")
        return None

# === Fetch prices and build new_data ===
for user, ids in user_cards.items():
    for pid in ids:
        if pid not in new_data:
            new_data[pid] = get_price(pid)

# === Generate report ===
# === Save updated data ===
with open(DATA_FILE, "w") as f:
    json.dump(new_data, f, indent=2)

# === Save current run time in ISO format ===
with open(LAST_RUN_FILE, "w") as f:
    f.write(now.isoformat())

# === Send an individual embed per user ===
# === Build embeds per user ===
embeds = []

for idx, (user, ids) in enumerate(user_cards.items()):
    sorted_ids = sorted(ids, key=lambda pid: new_data.get(pid) or 0, reverse=True)

    field_lines = []
    total_value = 0.0
    old_total_value = 0.0

    for pid in sorted_ids:
        name = card_names.get(pid, f"Card {pid}")
        price = new_data.get(pid)
        old_price = old_data.get(pid)

        if price is not None:
            total_value += price
        if old_price is not None:
            old_total_value += old_price

        if price is None:
            line = f"❌ **{name}** (`{pid}`): No price found."
        elif old_price is None:
            line = f"🆕 **{name}**: ${price:.2f} (new)"
        elif price != old_price:
            change = price - old_price
            symbol = "📈" if change > 0 else "📉"
            line = f"{symbol} **{name}**: ${old_price:.2f} → ${price:.2f} ({change:+.2f})"
        else:
            line = f"⏸️ **{name}**: ${price:.2f} (no change)"
        field_lines.append(line)

    month_change = total_value - old_total_value if old_total_value else 0.0
    change_symbol = "📈" if month_change > 0 else "📉" if month_change < 0 else "⏸️"

    embed = {
        "title": f"{user}'s Card Summary",
        "color": 0x00ffcc,
        "fields": [
            {
                "name": "Total Value",
                "value": f"${total_value:.2f}",
                "inline": True
            },
            {
                "name": "Month-to-Date Change",
                "value": f"{change_symbol} {month_change:+.2f}",
                "inline": True
            },
            {
                "name": "Card Details",
                "value": "\n".join(field_lines) or "No cards found.",
                "inline": False
            }
        ]
    }

    # Only add the footer to the last embed
    if idx == len(user_cards) - 1:
        embed["footer"] = {"text": f"Last run: {last_run_time_str}"}

    embeds.append(embed)

# === Send to Discord ===
payload = {
    "content": "🧾 **Pokémon Card Price Tracker Report**",
    "embeds": embeds
}

response = requests.post(DISCORD_WEBHOOK_URL, json=payload)
