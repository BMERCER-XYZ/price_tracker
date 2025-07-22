import requests
import json
import os

DATA_FILE = "data.json"
URLS_FILE = "urls.txt"
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

# Parse user-card assignments
user_cards = {}
card_names = {}

with open(URLS_FILE, "r") as f:
    for line in f:
        if line.strip():
            try:
                user, name, pid = map(str.strip, line.strip().split(",", 2))
                if user not in user_cards:
                    user_cards[user] = []
                user_cards[user].append(pid)
                card_names[pid] = name
            except ValueError:
                print(f"⚠️ Skipping malformed line: {line.strip()}")

# Load previous data
if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r") as f:
        old_data = json.load(f)
else:
    old_data = {}

new_data = {}
message_lines = []

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

for user, ids in user_cards.items():
    message_lines.append(f"### 📦 {user}'s Cards")
    for pid in ids:
        name = card_names.get(pid, f"Card {pid}")
        price = get_price(pid)
        new_data[pid] = price
        old_price = old_data.get(pid)

        if price is None:
            message_lines.append(f"- ❌ **{name}** (`{pid}`): No price found.")
        elif old_price is None:
            message_lines.append(f"- 🆕 **{name}**: ${price:.2f} (new)")
        elif price != old_price:
            change = price - old_price
            symbol = "🔺" if change > 0 else "🔻"
            message_lines.append(f"- {symbol} **{name}**: ${old_price:.2f} → ${price:.2f} ({change:+.2f})")
        else:
            message_lines.append(f"- ⏸️ **{name}**: ${price:.2f} (no change)")
    message_lines.append("")  # Add empty line between users

# Save updated prices
with open(DATA_FILE, "w") as f:
    json.dump(new_data, f, indent=2)

# Send Discord webhook
if DISCORD_WEBHOOK_URL:
    payload = {
        "content": f"🧾 **Pokémon Card Price Tracker Report**\n" + "\n".join(message_lines)
    }
    try:
        response = requests.post(DISCORD_WEBHOOK_URL, json=payload)
        response.raise_for_status()
        print("✅ Webhook sent successfully.")
    except Exception as e:
        print(f"❌ Webhook error: {e}")
else:
    print("❌ Webhook URL not found in environment variables.")
