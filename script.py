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
for user, ids in user_cards.items():
    sorted_ids = sorted(
        ids,
        key=lambda pid: new_data.get(pid) if new_data.get(pid) is not None else 0,
        reverse=True
    )

    message_lines.append(f"### :point_down: {user}'s Cards")
    for pid in sorted_ids:
        name = card_names.get(pid, f"Card {pid}")
        price = new_data.get(pid)
        old_price = old_data.get(pid)

        if price is None:
            message_lines.append(f"\> ❌ **{name}** (`{pid}`): No price found.")
        elif old_price is None:
            message_lines.append(f"\> 🆕 **{name}**: ${price:.2f} (new)")
        elif price != old_price:
            change = price - old_price
            symbol = ":chart_with_upwards_trend:" if change > 0 else ":chart_with_downwards_trend:"
            message_lines.append(f"\> {symbol} **{name}**: ${old_price:.2f} → ${price:.2f} ({change:+.2f})")
        else:
            message_lines.append(f"\> **{name}**: ${price:.2f} (no change)")
    message_lines.append("")


# === Save updated data ===
with open(DATA_FILE, "w") as f:
    json.dump(new_data, f, indent=2)

# === Save current run time in ISO format ===
with open(LAST_RUN_FILE, "w") as f:
    f.write(now.isoformat())

# === Add footer ===
message_lines.append(f"`Last run: {last_run_time_str}`")

embed = {
    "title": "🧾 Pokémon Card Price Tracker Report",
    "color": 0x00ffcc,  # Teal
    "fields": [],
    "footer": {"text": f"Last run: {last_run_time_str}"}
}

for user, ids in user_cards.items():
    sorted_ids = sorted(ids, key=lambda pid: new_data.get(pid) or 0, reverse=True)

    field_lines = []
    for pid in sorted_ids:
        name = card_names.get(pid, f"Card {pid}")
        price = new_data.get(pid)
        old_price = old_data.get(pid)

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

    embed["fields"].append({
        "name": f"{user}'s Cards",
        "value": "\n".join(field_lines) or "No cards found.",
        "inline": False
    })

# === Send Embed to Discord ===
payload = {
    "embeds": [embed]
}
response = requests.post(DISCORD_WEBHOOK_URL, json=payload)

