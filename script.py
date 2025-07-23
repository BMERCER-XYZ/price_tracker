import requests
import json
import os
from datetime import datetime
import pytz  # Required for timezone support

# === Constants ===
DATA_FILE = "data.json"          # Stores previous product prices
URLS_FILE = "urls.txt"           # Contains list of cards to track (user, name, product ID)
LAST_RUN_FILE = "last_run.txt"   # Stores last successful run time
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")  # Webhook URL from GitHub secret

# === Get current time in Adelaide timezone ===
tz_adelaide = pytz.timezone("Australia/Adelaide")
now = datetime.now(tz_adelaide)
formatted_time = now.strftime("%A, %d %B %Y at %-I:%M %p %Z")

# Read the last successful run time
if os.path.exists(LAST_RUN_FILE):
    with open(LAST_RUN_FILE, "r") as f:
        last_run_str = f.read().strip()
    try:
        # Parse the saved last run time into a datetime object
        last_run_dt = datetime.strptime(last_run_str, "%A, %d %B %Y at %I:%M %p %Z")
        last_run_dt = tz_adelaide.localize(last_run_dt.replace(tzinfo=None))  # Ensure timezone is correct

        # Calculate time since last run
        delta = now - last_run_dt
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        minutes = remainder // 60

        # Create a friendly duration string
        if hours >= 1:
            ago_str = f"{hours} hour{'s' if hours != 1 else ''} ago"
            if minutes:
                ago_str += f", {minutes} minute{'s' if minutes != 1 else ''}"
        else:
            ago_str = f"{minutes} minute{'s' if minutes != 1 else ''} ago"

        last_run_time_str = f"{last_run_str} ({ago_str})"

    except Exception as e:
        print(f"⚠️ Error parsing last run time: {e}")
        last_run_time_str = last_run_str  # Fall back to raw string
else:
    last_run_time_str = "Unknown"

# === Read URLs file and organize data by user ===
# Expected format per line: UserName,Card Name,ProductID
user_cards = {}     # Dictionary to group card IDs by user
card_names = {}     # Dictionary to map product ID -> card name

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

# === Load previous price data ===
if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r") as f:
        old_data = json.load(f)
else:
    old_data = {}

new_data = {}         # Will hold updated prices
message_lines = []    # Lines of text to send in the Discord webhook

# === Function to fetch price data from TCGPlayer API ===
def get_price(product_id):
    url = f"https://mpapi.tcgplayer.com/v2/product/{product_id}/pricepoints"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        prices = response.json()

        # Look for Foil price first, fallback to Normal
        for entry in prices:
            if entry.get("printingType") == "Foil" and entry.get("marketPrice"):
                return entry["marketPrice"]
            elif entry.get("printingType") == "Normal" and entry.get("marketPrice"):
                return entry["marketPrice"]
        return None  # No valid price found
    except Exception as e:
        print(f"❌ Failed to get price for {product_id}: {e}")
        return None

# === Generate price comparison report for each user ===
for user, ids in user_cards.items():
    message_lines.append(f"### :point_down: {user}'s Cards")
    for pid in ids:
        name = card_names.get(pid, f"Card {pid}")
        price = get_price(pid)  # New price
        new_data[pid] = price   # Save new price
        old_price = old_data.get(pid)  # Previous price

        # Decide message based on comparison
        if price is None:
            message_lines.append(f"- ❌ **{name}** (`{pid}`): No price found.")
        elif old_price is None:
            message_lines.append(f"- 🆕 **{name}**: ${price:.2f} (new)")
        elif price != old_price:
            change = price - old_price
            symbol = ":chart_with_upwards_trend:" if change > 0 else ":chart_with_downwards_trend:"
            message_lines.append(f"- {symbol} **{name}**: ${old_price:.2f} → ${price:.2f} ({change:+.2f})")
        else:
            message_lines.append(f"- ⏸️ **{name}**: ${price:.2f} (no change)")
    message_lines.append("")  # Spacer between users

# === Save updated price data to file ===
with open(DATA_FILE, "w") as f:
    json.dump(new_data, f, indent=2)

# === Save current timestamp as last successful run ===
with open(LAST_RUN_FILE, "w") as f:
    f.write(formatted_time)

# === Add timestamp info to end of report ===
message_lines.append(f"_Last successful run: {last_run_time_str}_")

# === Send report via Discord Webhook ===
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
